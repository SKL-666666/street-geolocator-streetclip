"""Geo-KB 引擎单元测试。"""
from __future__ import annotations

from app.geokb import engine
from app.geokb.countries import CITY_ALIASES, COUNTRY_ALIASES, LANG_ALIASES
from app.schemas import CityHypothesis, CountryHypothesis, SceneAnalysis


def _scene(**kw) -> SceneAnalysis:
    defaults = dict(
        is_street_view=True, scene_type="street", driving_side="unknown",
        languages=[], visible_text=[], traffic_signs=[], unique_features=[],
        country_hypotheses=[], city_hypotheses=[],
    )
    defaults.update(kw)
    return SceneAnalysis(**defaults)


class TestAliases:
    def test_chinese_lang_alias(self):
        assert LANG_ALIASES["西里尔字母"] == "Cyrillic"
        assert LANG_ALIASES["中文"] == "Chinese"

    def test_country_alias(self):
        assert COUNTRY_ALIASES["乌克兰"] == "Ukraine"
        assert COUNTRY_ALIASES["英国"] == "United Kingdom"
        assert CITY_ALIASES["基辅"] == "Kyiv"


class TestCrossFilter:
    def setup_method(self):
        engine.reset_cache()

    def test_driving_side_plus_language(self):
        scene = _scene(driving_side="left", languages=["English"])
        result = engine.cross_filter(scene, {})
        by_name = {r.country: r for r in result.countries}
        # 左舵+英语 → UK/Ireland 等应获得支持线索且 kb_score > 0
        assert "United Kingdom" in by_name
        assert by_name["United Kingdom"].kb_score > 0
        assert any("驾驶侧" in c for c in by_name["United Kingdom"].supporting_clues)
        # 未在 LLM 假设中的右舵国家不进入矩阵（避免满屏噪声）
        assert "Germany" not in by_name

    def test_driving_contradiction_for_llm_country(self):
        # LLM 猜了德国，但线索是左舵 → 德国应带矛盾标记且 kb_score=0
        scene = _scene(driving_side="left")
        result = engine.cross_filter(scene, {"Germany": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert "Germany" in by_name
        assert by_name["Germany"].kb_score == 0
        assert any("矛盾" in c for c in by_name["Germany"].contradicting_clues)
        # 融合分被压到 0.6*0.5=0.3（无 KB 支持）
        assert by_name["Germany"].final_score == 0.3

    def test_language_and_suffix(self):
        scene = _scene(languages=["Ukrainian", "Cyrillic"], visible_text=["вул. Шевченка"])
        result = engine.cross_filter(scene, {})
        by_name = {r.country: r for r in result.countries}
        ukraine = by_name.get("Ukraine")
        assert ukraine is not None
        assert any("语言" in c for c in ukraine.supporting_clues)
        assert any("街道后缀" in c for c in ukraine.supporting_clues)
        # 乌克兰应排在最前
        assert result.countries[0].country == "Ukraine"

    def test_sign_keyword_with_llm_mention(self):
        scene = _scene(traffic_signs=["yellow diamond warning sign"])
        result = engine.cross_filter(scene, {"United States": 0.4})
        by_name = {r.country: r for r in result.countries}
        assert "United States" in by_name
        assert any("路牌" in c for c in by_name["United States"].supporting_clues)

    def test_weak_kb_only_noise_dropped(self):
        # 仅单一弱维度（只有驾驶侧）且 LLM 未提及 → 不进矩阵（防噪声）
        scene = _scene(driving_side="right")
        result = engine.cross_filter(scene, {})
        assert len(result.countries) == 0

    def test_llm_merge(self):
        scene = _scene(
            driving_side="right",
            country_hypotheses=[
                CountryHypothesis(country="Italy", confidence=0.6, reasoning="x"),
                CountryHypothesis(country="Mars", confidence=0.9, reasoning="x"),  # 幻觉国家
            ],
        )
        result = engine.cross_filter(scene, {"Italy": 0.6, "Mars": 0.9})
        by_name = {r.country: r for r in result.countries}
        # Mars 不在知识库：unverified + kb=0，final 低于 Italy
        assert by_name["Mars"].unverified is True
        assert by_name["Mars"].kb_score == 0
        assert by_name["Italy"].final_score > by_name["Mars"].final_score

    def test_chinese_country_names(self):
        # GLM 输出中文国家名也能正确匹配知识库
        scene = _scene(
            driving_side="right", languages=["Ukrainian", "Cyrillic"],
            country_hypotheses=[CountryHypothesis(country="乌克兰", confidence=0.7, reasoning="r")],
        )
        result = engine.cross_filter(scene, {"乌克兰": 0.7})
        by_name = {r.country: r for r in result.countries}
        # 规范化为英文名
        assert "Ukraine" in by_name
        assert by_name["Ukraine"].unverified is False
        assert by_name["Ukraine"].llm_confidence == 0.7
        # 回写 scene 时中文假设获得融合分
        engine.merge_into_scene(result, scene)
        assert scene.country_hypotheses[0].country == "乌克兰"
        assert scene.country_hypotheses[0].confidence > 0.7

    def test_merge_into_scene(self):
        scene = _scene(
            driving_side="left", languages=["English"],
            country_hypotheses=[
                CountryHypothesis(country="United Kingdom", confidence=0.2, reasoning="r"),
            ],
        )
        result = engine.cross_filter(scene, {"United Kingdom": 0.2})
        engine.merge_into_scene(result, scene)
        # 融合后置信度提升（KB 支持）
        assert scene.country_hypotheses[0].confidence > 0.2


class TestPoleMeta:
    """电线杆特征库（pole_meta.py）匹配测试。"""

    def setup_method(self):
        engine.reset_cache()

    def test_greek_harp_top_unique(self):
        # 竖琴形金属框架=希腊独有；pole 线索是佐证（仅对 LLM 提及的国家抬分，不单独进矩阵）
        scene = _scene(pole="木质深棕色电线杆较高，杆顶是竖琴形金属框架，五个垂直绝缘子，希腊式小灯")
        result = engine.cross_filter(scene, {"Greece": 0.5, "Italy": 0.4})
        by_name = {r.country: r for r in result.countries}
        assert "Greece" in by_name
        assert any("电线杆特征" in c for c in by_name["Greece"].supporting_clues)
        assert any("独有" in c for c in by_name["Greece"].supporting_clues)
        # 希腊获得 pole 支持后应高于无 pole 支持的意大利
        assert by_name["Greece"].final_score > by_name["Italy"].final_score

    def test_inverted_triangle_shared_weak(self):
        # 倒三角是共享样式：LLM 提及的多国都获得弱支持（不锁定单一国家）
        scene = _scene(pole="杆顶为倒三角形，无其他特征")
        hyps = {c: 0.5 for c in ("Albania", "Czechia", "Slovakia", "Romania", "Serbia", "Germany")}
        result = engine.cross_filter(scene, hyps)
        by_name = {r.country: r for r in result.countries}
        for c in hyps:
            assert c in by_name, f"{c} 应获得倒三角弱支持"
            assert any("电线杆特征" in x for x in by_name[c].supporting_clues)

    def test_poland_vs_romania_hungary_holes(self):
        # 波兰孔洞不延伸到底部 → 只有波兰命中；罗马尼亚/匈牙利的关键词不同
        scene = _scene(pole="混凝土电线杆上有孔洞，孔洞不延伸到底部")
        result = engine.cross_filter(scene, {"Poland": 0.5, "Romania": 0.4, "Hungary": 0.4})
        by_name = {r.country: r for r in result.countries}
        assert any("电线杆特征" in c for c in by_name["Poland"].supporting_clues)
        assert not any("电线杆特征" in c for c in by_name["Romania"].supporting_clues)
        assert not any("电线杆特征" in c for c in by_name["Hungary"].supporting_clues)

    def test_tasmania_possum_guard_australia(self):
        # 塔斯马尼亚橄榄绿防鼠护套（文档：识别塔斯马尼亚最重要 meta 之一）
        scene = _scene(pole="电线杆上有橄榄绿防鼠护套，木质电线杆")
        result = engine.cross_filter(scene, {"Australia": 0.6})
        by_name = {r.country: r for r in result.countries}
        assert any("橄榄绿防鼠护套" in c for c in by_name["Australia"].supporting_clues)

    def test_japan_screw_ridges(self):
        scene = _scene(pole="圆形混凝土电线杆，表面螺丝状凸起，反光带不接触地面")
        result = engine.cross_filter(scene, {"Japan": 0.7})
        by_name = {r.country: r for r in result.countries}
        assert any("螺丝状凸起" in c for c in by_name["Japan"].supporting_clues)

    def test_empty_pole_no_clues(self):
        scene = _scene(pole="", driving_side="right", languages=["German"])
        result = engine.cross_filter(scene, {"Germany": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert not any("电线杆特征" in c for c in by_name["Germany"].supporting_clues)


class TestCountryDetails:
    """国家细节线索库（country_details.py）+ 相机特征扩展（camera_gen.py）。"""

    def setup_method(self):
        engine.reset_cache()

    def test_russian_letter_yy(self):
        # 西里尔 Ы → 俄语 → 俄罗斯（文字特征维度）
        scene = _scene(visible_text=["улица Мытищи 15"], languages=["Russian", "Cyrillic"])
        result = engine.cross_filter(scene, {"Russia": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert any("文字特征" in c for c in by_name["Russia"].supporting_clues)

    def test_smallcam_multi_country(self):
        scene = _scene(image_quality="4代小相机，大圆形打码前方有突起")
        result = engine.cross_filter(scene, {"France": 0.4, "Canada": 0.3})
        by_name = {r.country: r for r in result.countries}
        for c in ("France", "Canada"):
            assert any("smallcam" in x for x in by_name[c].supporting_clues)

    def test_lowcam_japan(self):
        scene = _scene(image_quality="低相机，打码模糊更大，路显得更宽")
        result = engine.cross_filter(scene, {"Japan": 0.6})
        by_name = {r.country: r for r in result.countries}
        assert any("lowcam" in x for x in by_name["Japan"].supporting_clues)

    def test_antenna_car_russia(self):
        scene = _scene(image_quality="normal", unique_features=["黑色街景车带长天线"])
        result = engine.cross_filter(scene, {"Russia": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert any("长天线" in x for x in by_name["Russia"].supporting_clues)

    def test_fortlev_brazil(self):
        scene = _scene(unique_features=["屋顶蓝色FORTLEV水箱"], architecture=["橙瓦屋顶"])
        result = engine.cross_filter(scene, {"Brazil": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert any("FORTLEV" in c for c in by_name["Brazil"].supporting_clues)

    def test_speed_limit_us(self):
        scene = _scene(visible_text=["SPEED LIMIT 55"])
        result = engine.cross_filter(scene, {"United States": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert any("SPEED LIMIT" in c for c in by_name["United States"].supporting_clues)

    def test_einbahn_germany(self):
        scene = _scene(visible_text=["Einbahnstraße"], traffic_signs=["单向交通标志"])
        result = engine.cross_filter(scene, {"Germany": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert any("Einbahn" in c for c in by_name["Germany"].supporting_clues)

    def test_eucalyptus_australia(self):
        scene = _scene(vegetation=["桉树"], terrain=["平原"])
        result = engine.cross_filter(scene, {"Australia": 0.5})
        by_name = {r.country: r for r in result.countries}
        assert any("桉树" in c for c in by_name["Australia"].supporting_clues)

    def test_black_white_plate_indonesia_malaysia(self):
        scene = _scene(unique_features=["黑底白字车牌"])
        result = engine.cross_filter(scene, {"Indonesia": 0.4, "Malaysia": 0.4})
        by_name = {r.country: r for r in result.countries}
        for c in ("Indonesia", "Malaysia"):
            assert any("黑底白字车牌" in x for x in by_name[c].supporting_clues)

    def test_no_detail_no_clue(self):
        scene = _scene(visible_text=["hello"], unique_features=["普通路标"])
        result = engine.cross_filter(scene, {"Germany": 0.4})
        by_name = {r.country: r for r in result.countries}
        assert not any("国家细节" in c for c in by_name["Germany"].supporting_clues)


class TestRescue:
    """知识库"救回"：强线索命中但 LLM 未提及 → 补低置信城市假设。"""

    def test_rescue_pole_unique_greece(self):
        from app.geokb.rescue import rescue_countries
        scene = _scene(pole="木质杆顶是竖琴形金属框架")
        assert "Greece" in rescue_countries(scene)

    def test_rescue_detail_single_brazil(self):
        from app.geokb.rescue import rescue_countries
        scene = _scene(unique_features=["屋顶蓝色FORTLEV水箱"])
        assert "Brazil" in rescue_countries(scene)

    def test_rescue_skips_known_country(self):
        from app.geokb.rescue import rescue_countries
        scene = _scene(pole="竖琴形杆顶",
                       country_hypotheses=[CountryHypothesis(country="Greece", confidence=0.5)])
        assert "Greece" not in rescue_countries(scene)

    def test_rescue_skips_multi_country_detail(self):
        # "双黄线" 指向 4 国 → 不救回（防噪声）
        from app.geokb.rescue import rescue_countries
        scene = _scene(unique_features=["双黄线"])
        assert rescue_countries(scene) == []

    def test_rescue_cn_scope_empty(self):
        from app.geokb.rescue import rescue_countries
        scene = _scene(pole="竖琴形杆顶")
        assert rescue_countries(scene, scope="cn") == []

    def test_apply_rescue_injects_city(self):
        from app.geokb.rescue import apply_rescue
        scene = _scene(pole="木质杆顶是竖琴形金属框架")
        added = apply_rescue(scene)
        assert added >= 1
        assert any(h.country == "Greece" for h in scene.city_hypotheses)
        # 二次调用不重复注入
        assert apply_rescue(scene) == 0


class TestWorldCityProfiles:
    """世界城市特征档案（Top300，LLM 生成）。"""

    def test_data_loaded(self):
        from app.geokb.world_cities import WORLD_CITY_PROFILES
        assert len(WORLD_CITY_PROFILES) >= 200
        assert all(c.get("keywords") for c in WORLD_CITY_PROFILES)

    def test_paris_eiffel_match(self):
        from app.geokb.world_city_engine import match_world_cities
        scene = _scene(architecture=["埃菲尔铁塔"], summary="塞纳河畔")
        hits = match_world_cities(scene)
        assert hits and hits[0].city == "Paris"
        assert hits[0].country == "France"
        assert hits[0].confidence <= 0.5

    def test_single_keyword_no_match(self):
        from app.geokb.world_city_engine import match_world_cities
        scene = _scene(unique_features=["黄色出租车"])  # 纽约特征之一，单词不注入
        assert match_world_cities(scene) == []

    def test_merge_dedup_existing(self):
        from app.geokb.world_city_engine import merge_world_hypotheses
        scene = _scene(architecture=["埃菲尔铁塔", "凯旋门", "卢浮宫"],
                       city_hypotheses=[CityHypothesis(city="Paris", country="France",
                                                       confidence=0.5, reasoning="llm")])
        merge_world_hypotheses(scene)
        paris = [h for h in scene.city_hypotheses if h.city == "Paris"]
        assert len(paris) == 1
        assert paris[0].confidence > 0.5  # 佐证加权
