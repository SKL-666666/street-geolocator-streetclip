"""单元测试：JSON 解析鲁棒性 + EXIF GPS 提取 + 降级链。"""
from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image
from PIL.ExifTags import IFD

from app.llm.base import BalanceError, ContentFilterError, OverloadError
from app.llm.openai_compat import (
    _is_balance_error,
    _is_content_filter_error,
    _is_overload_error,
)
from app.llm.parsing import JSONParseError, extract_json
from app.llm.prompts import (
    CN_FEWSHOT_EXAMPLES,
    GLOBAL_FEWSHOT_EXAMPLES,
    build_clue_prompt,
)
from app.geokb.citylib import city_coords, zh_city_names
from app.geokb.cn_engine import match_cn_cities, match_cn_regions, merge_cn_hypotheses
from app.geokb.engine import cross_filter
from app.pipeline.exif import extract_gps
from app.pipeline.orchestrator import (
    _fallback_candidate,
    _filter_mainland,
    _keep_mainland_only,
    _keep_only_china,
)
from app.pipeline.scene import SceneAnalyzer, SceneTimeoutError
from app.schemas import Candidate, CityHypothesis, GeoKBResult, KBEvidence, SceneAnalysis


class TestExtractJson:
    def test_plain(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_surrounding_text(self):
        assert extract_json('好的，分析如下：\n{"a": 1}\n希望有帮助') == {"a": 1}

    def test_comments_and_trailing_comma(self):
        text = '{\n  "a": 1, // 注释\n  "b": [1, 2,],\n}'
        assert extract_json(text) == {"a": 1, "b": [1, 2]}

    def test_garbage_raises(self):
        with pytest.raises(JSONParseError):
            extract_json("这不是 JSON，完全没有大括号")


def _make_gps_image() -> bytes:
    img = Image.new("RGB", (64, 48), (10, 20, 30))
    exif = Image.Exif()
    exif[IFD.GPSInfo] = {
        1: "N",
        2: (51.0, 30.0, 12.345),
        3: "E",
        4: (0.0, 7.0, 0.0),
    }
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


class TestExifGPS:
    def test_extract(self):
        gps = extract_gps(_make_gps_image())
        assert gps is not None
        assert abs(gps.lat - 51.5034292) < 1e-6
        assert abs(gps.lon - 0.1166667) < 1e-6

    def test_no_gps(self):
        img = Image.new("RGB", (64, 48), (10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        assert extract_gps(buf.getvalue()) is None

    def test_garbage_bytes(self):
        assert extract_gps(b"not an image at all") is None


# ---------- 降级链（平台繁忙/限流/审核拦截 → 降级而非失败）----------

def _tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (80, 90, 100)).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeProvider:
    """按需抛错的假 LLM 供应商（支持链式异常）。"""

    name = "fake"
    model = "fake"

    def __init__(self, error: Exception | None = None, text: str = ""):
        self.error = error
        self.text = text

    async def analyze_image(self, image_bytes, prompt, mime="image/jpeg"):
        if self.error is not None:
            raise self.error
        return type("R", (), {"content": self.text})()


class TestErrorRecognition:
    def test_content_filter_1301(self):
        class E(Exception):
            body = '{"error": {"code": "1301", "message": "内容涉及敏感信息"}}'

        assert _is_content_filter_error(E("1301"))
        assert not _is_overload_error(E("1301"))

    def test_overload_1305(self):
        class E(Exception):
            body = '{"error": {"code": "1305", "message": "用户请求并发数超限"}}'

        assert _is_overload_error(E("1305"))
        assert not _is_content_filter_error(E("1305"))

    def test_overload_429_class(self):
        class RateLimitError(Exception):
            pass

        assert _is_overload_error(RateLimitError("429 too many requests"))

    def test_balance_1113(self):
        class E(Exception):
            body = '{"error": {"code": "1113", "message": "余额不足或无可用资源包,请充值。"}}'

        assert _is_balance_error(E("1113"))
        assert not _is_overload_error(E("1113"))


class TestSceneDegrade:
    def test_overload_without_fallback_degrades(self):
        """主模型抛 OverloadError 且模式未启用降级模型 → SceneTimeoutError（不判失败）。"""
        provider = _FakeProvider(error=OverloadError())
        analyzer = SceneAnalyzer(provider, fallback_enabled=False,
                                 primary_timeout=5.0, samples=1)
        with pytest.raises(SceneTimeoutError):
            asyncio.run(analyzer.analyze(_tiny_jpeg()))

    def test_content_filter_propagates(self):
        """内容审核拦截 → ContentFilterError 向上传递（orchestrator 降级）。"""
        provider = _FakeProvider(error=ContentFilterError())
        analyzer = SceneAnalyzer(provider, fallback_enabled=False,
                                 primary_timeout=5.0, samples=1)
        with pytest.raises(ContentFilterError):
            asyncio.run(analyzer.analyze(_tiny_jpeg()))

    def test_unparseable_output_raises_valueerror(self):
        """模型输出无法解析 → ValueError（orchestrator 降级）。"""
        provider = _FakeProvider(text="这不是 JSON")
        analyzer = SceneAnalyzer(provider, fallback_enabled=False,
                                 retries=0, primary_timeout=5.0, samples=1)
        with pytest.raises(ValueError):
            asyncio.run(analyzer.analyze(_tiny_jpeg()))


class TestFilterMainland:
    """no-cn 范围过滤：国家名优先，bbox 仅兜底（防误杀东南亚候选）。"""

    @staticmethod
    def _cand(lat, lon, country="", country_zh=""):
        return Candidate(rank=1, lat=lat, lon=lon, source="llm",
                         country=country, country_zh=country_zh,
                         city="X", city_zh="X")

    def test_thailand_north_kept(self):
        """泰国北部（清迈 18.778,98.986）：旧 bbox 误删，国家名必须保留。"""
        cands = [self._cand(18.778, 98.986, "Thailand", "泰国")]
        _filter_mainland(cands)
        assert len(cands) == 1

    def test_thailand_chinese_name_kept(self):
        cands = [self._cand(18.778, 98.986, "泰国", "泰国")]
        _filter_mainland(cands)
        assert len(cands) == 1

    def test_laos_north_kept(self):
        """老挝北部同样在旧 bbox 内，国家名保留。"""
        cands = [self._cand(20.96, 102.61, "Laos", "老挝")]
        _filter_mainland(cands)
        assert len(cands) == 1

    def test_china_removed(self):
        cands = [self._cand(39.9042, 116.4074, "China", "中国")]
        _filter_mainland(cands)
        assert len(cands) == 0

    def test_china_chinese_name_removed(self):
        cands = [self._cand(31.2304, 121.4737, "中国", "中国")]
        _filter_mainland(cands)
        assert len(cands) == 0

    def test_no_country_in_bbox_removed(self):
        """无国家名 + 坐标在 bbox 内 → 兜底删除。"""
        cands = [self._cand(35.0, 105.0)]
        _filter_mainland(cands)
        assert len(cands) == 0

    def test_no_country_taiwan_kept(self):
        """无国家名 + 台湾岛坐标（排除框内）→ 保留。"""
        cands = [self._cand(25.03, 121.5654)]
        _filter_mainland(cands)
        assert len(cands) == 1

    def test_no_country_thailand_kept_outside_bbox_lat(self):
        """无国家名 + 泰国中部（lat 13.7 < 18）→ 不在 bbox，保留。"""
        cands = [self._cand(13.7, 100.5)]
        _filter_mainland(cands)
        assert len(cands) == 1


class TestChineseCityResolution:
    """中国城市中文名解析：精确坐标表（解决表缺失与同名歧义）。"""

    def test_suzhou_is_jiangsu(self):
        """"苏州"必须解析到江苏苏州，而不是安徽宿州 Suzhou。"""
        hit = city_coords("苏州")
        assert hit is not None
        assert abs(hit[0] - 31.30) < 0.1   # 江苏苏州纬度
        assert abs(hit[1] - 120.59) < 0.1

    def test_suzhou_anhui(self):
        """"宿州"解析到安徽宿州。"""
        hit = city_coords("宿州")
        assert hit is not None
        assert abs(hit[0] - 33.64) < 0.1

    def test_cities_missing_from_table(self):
        """表内英文键缺失的中国城市（沈阳/乌鲁木齐）也能解析。"""
        assert city_coords("沈阳") is not None
        assert city_coords("乌鲁木齐") is not None

    def test_zh_names_coverage(self):
        """中文城市名索引覆盖主要城市（供 visible_text 子串匹配）。"""
        names = set(zh_city_names())
        for zh in ("成都", "西安", "杭州", "武汉", "南京", "保定", "洛阳", "大理", "丽江"):
            assert zh in names, f"缺少中文名 {zh}"

    def test_visible_text_zh_match(self):
        """中文招牌文本 → 城市假设（_inject_text_clues 中文直配）。"""
        from app.pipeline.scene import SceneAnalyzer
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["成都火锅 总店", "春熙路 66 号"])
        SceneAnalyzer._inject_text_clues(scene)
        cities = [h.city for h in scene.city_hypotheses]
        assert "Chengdu" in cities or "成都" in cities


class TestPromptSeparation:
    """中国与全球提示词/知识库严格分离。"""

    def test_cn_prompt_uses_cn_fewshot_only(self):
        """cn 提示词必须含中国少样本（火锅/骑楼），绝不含全球少样本（Rua do Carmo/波兰）。"""
        cn = build_clue_prompt("cn")
        assert "老灶火锅" in cn and "阿嫲腸粉" in cn       # 中国少样本
        assert "Rua do Carmo" not in cn                     # 全球少样本必须剔除
        assert "Bialystok" not in cn
        assert "仅限中国大陆" in cn                          # 范围指令

    def test_world_prompt_uses_global_fewshot(self):
        """world 提示词含全球少样本，绝不含中国少样本。"""
        w = build_clue_prompt("world")
        assert "Rua do Carmo" in w
        assert "老灶火锅" not in w and "阿嫲腸粉" not in w
        assert "仅限中国大陆" not in w

    def test_no_cn_prompt_has_exclusion(self):
        n = build_clue_prompt("no-cn")
        assert "排除中国大陆" in n
        assert "Rua do Carmo" in n
        assert "老灶火锅" not in n

    def test_fewshot_constants_are_disjoint(self):
        """两个少样本常量互不包含（防误用）。"""
        assert "Rua do Carmo" not in CN_FEWSHOT_EXAMPLES
        assert "火锅" not in GLOBAL_FEWSHOT_EXAMPLES

    def test_global_fewshot_has_difficult_cases(self):
        """全球少样本含难图示例（无文字乡村/雪地/沙漠），教模型无文字时锁区域。"""
        w = build_clue_prompt("world")
        assert "针叶林与桦木" in w        # 无文字乡村
        assert "积雪覆盖的郊区街道" in w  # 雪地
        assert "干旱荒漠公路" in w        # 沙漠
        assert "无文字" in w

    def test_cn_fewshot_has_north_case(self):
        """中国少样本含东北示例（厚墙住宅/少空调/橙线），教省份级线索。"""
        cn = build_clue_prompt("cn")
        assert "厚墙多层住宅" in cn and "橙线标线" in cn
        assert "Changchun" in cn


class TestCnCityProfiles:
    """中国城市特征档案（独立知识库）。"""

    def test_hotpot_basin_matches_chongqing(self):
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              terrain=["盆地"], unique_features=["火锅店招牌", "坡道街道"],
                              summary="火锅与坡道指向山城")
        hits = match_cn_cities(scene)
        assert hits, "应命中档案城市"
        assert hits[0].city == "Chongqing" or hits[0].city == "Chengdu"
        assert hits[0].country == "China"
        assert hits[0].lat is not None

    def test_qi_lou_matches_guangzhou(self):
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              architecture=["骑楼连廊"], visible_text=["阿嫲肠粉"],
                              summary="骑楼街景")
        cities = [h.city for h in match_cn_cities(scene)]
        assert "Guangzhou" in cities or "Shantou" in cities

    def test_single_keyword_does_not_match(self):
        """单关键词命中不注入（防巧合误判）。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["烤鸭店"])
        assert match_cn_cities(scene, min_hits=2) == []

    def test_merge_dedup_and_rank(self):
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              terrain=["盆地"], unique_features=["火锅", "坡道", "吊脚楼"],
                              summary="山城")
        merge_cn_hypotheses(scene)
        names = [h.city for h in scene.city_hypotheses]
        # 去重：同一城市不重复
        assert len(names) == len(set(names))
        # 排序：置信度降序
        confs = [h.confidence for h in scene.city_hypotheses]
        assert confs == sorted(confs, reverse=True)


class TestCnRegions:
    """中国省级/区域线索（cn_regions.py）：车牌/区号/植被/建筑/地名后缀/雪景。"""

    def test_plate_province_strong(self):
        # 粤A → 广东（铁证级 0.55），注入广东代表城市
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["粤A·12345", "某商铺招牌"])
        hits = match_cn_regions(scene)
        assert hits, "应命中车牌省份"
        assert hits[0].confidence == 0.55
        names = [h.city for h in hits]
        assert "广州" in names or "潮州" in names

    def test_area_code_3_city(self):
        # 010 → 北京（0.5）
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["010-66668888"])
        hits = match_cn_regions(scene)
        assert any(h.city == "北京" and h.confidence == 0.5 for h in hits)

    def test_area_code_4_region_weak(self):
        # 0755（深圳区号，四位）→ 仅定中南大区，弱置信，注入武汉/长沙
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["0755-88886666"])
        hits = match_cn_regions(scene)
        assert hits, "四位区号应命中大区"
        assert max(h.confidence for h in hits) <= 0.4
        assert any(h.city in ("武汉", "长沙") for h in hits)

    def test_yaodong_architecture(self):
        # 窑洞 → 陕西/甘肃/宁夏/西北
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              architecture=["黄土窑洞"], terrain=["黄土高原"])
        hits = match_cn_regions(scene)
        names = [h.city for h in hits]
        assert "西安" in names or "兰州" in names

    def test_dongzong_vegetation_yunnan(self):
        # 董棕 → 云南
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              vegetation=["董棕", "热带阔叶"])
        hits = match_cn_regions(scene)
        assert any(h.city == "昆明" for h in hits)

    def test_place_suffix_kuang_shandong(self):
        # 地名后缀"夼" → 胶东（山东）
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["西河夼村"])
        hits = match_cn_regions(scene)
        assert any(h.city in ("济南", "青岛") for h in hits)

    def test_snow_cities(self):
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              weather=["积雪"], summary="路面有积雪")
        hits = match_cn_regions(scene)
        assert hits and max(h.confidence for h in hits) <= 0.3
        assert "蚌埠" in [h.city for h in hits]

    def test_merge_boosts_existing_same_city(self):
        # 已有英文"Guangzhou"假设 + 粤牌线索 → 同城去重并加权
        scene = SceneAnalysis(
            is_street_view=True, scene_type="street",
            city_hypotheses=[CityHypothesis(city="Guangzhou", country="China",
                                            confidence=0.4, reasoning="llm")],
            visible_text=["粤B·88888"],
        )
        merge_cn_hypotheses(scene)
        gz = next(h for h in scene.city_hypotheses if h.city.lower() == "guangzhou")
        assert gz.confidence > 0.4, "同城线索应加权"
        assert len(scene.city_hypotheses) == 1, "中文/英文同城应去重"

    def test_no_region_hits_no_inject(self):
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["hello world"], vegetation=["普通行道树"])
        assert match_cn_regions(scene) == []


class TestCameraGen:
    """谷歌街景相机代数 → 覆盖区国家（GeoGuessr 印证线索）。"""

    def test_indian_camera_reinforces_india(self):
        """印度相机特征 → 印证印度（LLM 假设 + 相机线索都指向时升权）。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              image_quality="印度相机：低画质、巨大打码、太阳核爆状",
                              unique_features=["巨大打码"], summary="低画质街景")
        kb = cross_filter(scene, {"India": 0.3})
        row = next((r for r in kb.countries if r.country == "India"), None)
        assert row is not None
        assert any("相机代数" in c for c in row.supporting_clues)

    def test_gen2_reinforces_south_africa(self):
        """Gen2 大范围打码圆 → 印证南非（非洲唯一 Gen2）。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              image_quality="Gen2：模糊、街景车打码为完美圆、天空彩色变色")
        kb = cross_filter(scene, {"South Africa": 0.3})
        row = next((r for r in kb.countries if r.country == "South Africa"), None)
        assert row is not None
        assert any("相机代数" in c for c in row.supporting_clues)

    def test_normal_quality_no_constraint(self):
        """普通画质（手机街拍）不触发相机代数过滤。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              image_quality="normal", unique_features=["柏油路面"])
        kb = cross_filter(scene, {})
        assert not any(any("相机代数" in c for c in r.supporting_clues)
                       for r in kb.countries)


class TestEuropeCrops:
    """欧洲作物/土壤类型（乡村田野场景弱辅助线索）。"""

    def test_sunflower_field_reinforces_uk(self):
        """向日葵田 → 英国（向日葵广泛种植）。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              vegetation=["向日葵田"], terrain=["平原农田"])
        kb = cross_filter(scene, {"United Kingdom": 0.3})
        row = next((r for r in kb.countries if r.country == "United Kingdom"), None)
        assert row is not None
        assert any("作物" in c for c in row.supporting_clues)

    def test_chernozem_reinforces_ukraine(self):
        """黑土 → 欧亚草原（乌克兰等）。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              soil=["黑土"], terrain=["草原平原"])
        kb = cross_filter(scene, {"Ukraine": 0.3})
        row = next((r for r in kb.countries if r.country == "Ukraine"), None)
        assert row is not None
        assert any("土壤类型" in c for c in row.supporting_clues)

    def test_tea_plantation_reinforces_china_or_europe(self):
        """茶园 → 茶种植区（欧洲 12 国）。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              vegetation=["茶园"], terrain=["丘陵"])
        kb = cross_filter(scene, {"France": 0.3})
        row = next((r for r in kb.countries if r.country == "France"), None)
        assert row is not None
        assert any("作物" in c for c in row.supporting_clues)


class TestLangScript:
    """语言文字指纹（特殊字母/组合 → 语言 → 国家）。"""

    def test_eszett_reinforces_germany(self):
        """ß → 德语 → 德国。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["Bahnhofstraße 12"])
        kb = cross_filter(scene, {"Germany": 0.3})
        row = next((r for r in kb.countries if r.country == "Germany"), None)
        assert row is not None
        assert any("文字特征" in c and "German" in c for c in row.supporting_clues)

    def test_n_tilde_reinforces_spain(self):
        """ñ → 西班牙语 → 西班牙。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["Calle Mayor 5, España"])
        kb = cross_filter(scene, {"Spain": 0.3})
        row = next((r for r in kb.countries if r.country == "Spain"), None)
        assert row is not None
        assert any("文字特征" in c and "Spanish" in c for c in row.supporting_clues)

    def test_icelandic_thorn(self):
        """þ/ð → 冰岛。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["Reykjavíkurgata", "þingvellir"])
        kb = cross_filter(scene, {"Iceland": 0.3})
        row = next((r for r in kb.countries if r.country == "Iceland"), None)
        assert row is not None

    def test_plain_latin_no_false_trigger(self):
        """普通英文招牌不误触发特殊语言。"""
        scene = SceneAnalysis(is_street_view=True, scene_type="street",
                              visible_text=["Main Street 42", "OPEN 24H"])
        kb = cross_filter(scene, {})
        assert not any(any("文字特征" in c for c in r.supporting_clues)
                       for r in kb.countries)


class TestKeepMainlandOnly:
    """仅中国大陆模式：只保留大陆候选（对称逻辑）。"""

    @staticmethod
    def _cand(lat, lon, country="", country_zh=""):
        return Candidate(rank=1, lat=lat, lon=lon, source="llm",
                         country=country, country_zh=country_zh,
                         city="X", city_zh="X")

    def test_china_kept(self):
        cands = [self._cand(39.9042, 116.4074, "China", "中国")]
        _keep_mainland_only(cands)
        assert len(cands) == 1

    def test_thailand_removed(self):
        """泰国北部（旧 bbox 误判区）→ 国家名判定删除。"""
        cands = [self._cand(18.778, 98.986, "Thailand", "泰国")]
        _keep_mainland_only(cands)
        assert len(cands) == 0

    def test_mixed(self):
        cands = [self._cand(39.9042, 116.4074, "China", "中国"),
                 self._cand(48.8566, 2.3522, "France", "法国")]
        _keep_mainland_only(cands)
        assert len(cands) == 1
        assert cands[0].country == "China"

    def test_no_country_in_bbox_kept(self):
        cands = [self._cand(35.0, 105.0)]
        _keep_mainland_only(cands)
        assert len(cands) == 1

    def test_no_country_abroad_removed(self):
        cands = [self._cand(52.23, 21.01)]
        _keep_mainland_only(cands)
        assert len(cands) == 0

    def test_fallback_candidate_cn_is_beijing(self):
        cands = _fallback_candidate("cn")
        assert len(cands) == 1
        assert cands[0].country == "China"
        assert cands[0].city_zh == "北京"
        assert abs(cands[0].lat - 39.9042) < 1e-3


class TestKeepOnlyChinaKB:
    """仅中国大陆模式：Geo-KB 证据矩阵只留中国行。"""

    def test_zeroes_foreign_rows(self):
        kb = GeoKBResult(countries=[
            KBEvidence(country="China", country_zh="中国", kb_score=0.7, final_score=0.8),
            KBEvidence(country="Thailand", country_zh="泰国", kb_score=0.6, final_score=0.7),
            KBEvidence(country="Japan", country_zh="日本", kb_score=0.5, final_score=0.6),
        ])
        _keep_only_china(kb)
        china = next(r for r in kb.countries if r.country == "China")
        assert china.final_score == 0.8  # 中国行不动
        for r in kb.countries:
            if r.country != "China":
                assert r.final_score == 0.0
                assert any("仅中国大陆" in c for c in r.contradicting_clues)
