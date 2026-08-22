"""图像预处理 + LLM 场景分析（线索提取）。"""
from __future__ import annotations

import asyncio
import io

from PIL import Image, ImageOps

from ..config import settings
from ..llm.base import LLMProvider
from ..llm.parsing import extract_json
from ..llm.prompts import repair_prompt
from ..schemas import CityHypothesis, CountryHypothesis, SceneAnalysis


class SceneTimeoutError(Exception):
    """主模型与快速模型均超时：调用方应降级（保留先验/检索结果），而非判失败。"""


def _safe_latlon(value) -> float | None:
    """经纬度安全解析：仅接受合法范围数值。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if -180.0 <= v <= 180.0 else None


def _union(iterables) -> list[str]:
    """去重保序合并字符串列表。"""
    out: list[str] = []
    seen: set[str] = set()
    for seq in iterables:
        for item in seq:
            key = str(item).strip().lower()
            if item and key not in seen:
                seen.add(key)
                out.append(str(item))
    return out


def _pick_most_confident(values) -> str:
    """取非 unknown 的第一个值。"""
    for v in values:
        if v and v != "unknown":
            return v
    return "unknown"


def _merge_hypotheses(items, key_fn, conf_fn, build_fn):
    """按 key 取置信度最高的假设。"""
    best: dict = {}
    for item in items:
        k = key_fn(item)
        if not k:
            continue
        conf = conf_fn(item)
        if k not in best or conf > best[k][0]:
            best[k] = (conf, item)
    return [build_fn(k, c, it) for k, (c, it) in best.items()]


class SceneAnalyzer:
    """把一张图交给多模态 LLM，产出结构化线索 JSON。

    两级模型策略：主模型超时（llm_primary_timeout_sec）→ 自动降级到
    快速模型（llm_fallback_model），硬性保证单图耗时上限。
    """

    def __init__(self, provider: LLMProvider, retries: int | None = None,
                 fallback_provider: LLMProvider | None = None,
                 image_side: int | None = None,
                 primary_timeout: float | None = None,
                 fallback_timeout: float | None = None,
                 fallback_enabled: bool = True,
                 samples: int = 1):
        self.provider = provider
        self.retries = settings.llm_retries if retries is None else retries
        self.fallback_provider = fallback_provider
        self.image_side = image_side or settings.max_image_side
        self.primary_timeout = primary_timeout or settings.llm_primary_timeout_sec
        self.fallback_timeout = (fallback_timeout if fallback_timeout is not None
                                 else settings.llm_fallback_timeout_sec)
        self.fallback_enabled = fallback_enabled
        self.samples = samples
        self.used_fallback = False

    async def analyze(self, image_bytes: bytes, mime: str = "image/jpeg",
                      scope: str = "world") -> SceneAnalysis:
        # 采样策略：单采样（双采样开关已移除；local 模式不走此分析器）
        samples = self.samples
        if samples <= 1:
            scene = await self._analyze_once(image_bytes, mime, scope)
        else:
            # A6：双次采样（并行执行，耗时≈单次；抗单次提取波动）
            results = await asyncio.gather(
                *[self._analyze_once(image_bytes, mime, scope)
                  for _ in range(samples)],
                return_exceptions=True)
            scenes = [r for r in results if isinstance(r, SceneAnalysis)]
            if not scenes:
                err = next((r for r in results if isinstance(r, Exception)), None)
                # 全部失败：超时/繁忙/审核拦截向上传递，触发降级
                from ..llm.base import BalanceError, ContentFilterError, OverloadError
                if all(isinstance(r, (SceneTimeoutError, ContentFilterError, OverloadError))
                       for r in results):
                    raise type(err)(str(err)) from None
                raise ValueError(f"多次采样全部失败：{err}") from err
            scene = self._merge_scenes(scenes)
        # 强制城市级：城市假设为空时按 top 国家补 2-3 个大城市（不只会蒙首都）
        self._ensure_city_hypotheses(scene, scope)
        return scene

    @staticmethod
    def _scene_confident(scene: SceneAnalysis) -> bool:
        """结论是否充分（无需补采样）：有明确城市假设（置信度 ≥0.5）且国家假设存在。"""
        if not scene.city_hypotheses:
            return False
        if scene.city_hypotheses[0].confidence < 0.5:
            return False
        return bool(scene.country_hypotheses)

    async def _analyze_once(self, image_bytes: bytes, mime: str = "image/jpeg",
                            scope: str = "world") -> SceneAnalysis:
        from ..llm.base import BalanceError, OverloadError

        payload, mime = self._prepare(image_bytes, mime)
        tokens = {"prompt": 0, "completion": 0, "calls": 0}
        try:
            text = await asyncio.wait_for(
                self._ask_with_retry(payload, mime, scope, tokens=tokens), timeout=self.primary_timeout)
        except (asyncio.TimeoutError, OverloadError) as e:
            # 余额不足：重试/降级模型无意义，直接向上传播（orchestrator 明确提示充值）
            if isinstance(e, BalanceError):
                raise
            # 超时或平台繁忙/限流：都尝试快速模型兜底（同样失败则抛 SceneTimeoutError 降级）
            text = await self._fallback(payload, mime, scope, cause=e, tokens=tokens)
        data = extract_json(text)
        scene = self._to_schema(data, text)
        scene.tokens = tokens
        if self.used_fallback:
            scene.summary = (scene.summary or "") + "（快速模式）"
        self._inject_text_clues(scene, scope)
        return scene

    @staticmethod
    def _ensure_city_hypotheses(scene: SceneAnalysis, scope: str = "world") -> None:
        """强制城市级兜底：城市假设为空且国家假设非空时，补该国的 2-3 个大城市。

        城市表按人口生成，取该国人口前 3（不只会蒙首都）。
        除中国大陆模式跳过中国城市；仅中国大陆模式只补中国城市。
        """
        if scene.city_hypotheses or not scene.country_hypotheses:
            return
        from ..geokb.cities import CITY_COORDS
        from ..geokb.countries import COUNTRY_ALIASES

        country = COUNTRY_ALIASES.get(scene.country_hypotheses[0].country,
                                      scene.country_hypotheses[0].country)
        if scope == "no-cn" and country == "China":
            return
        if scope == "cn" and country != "China":
            return
        from ..geokb.citylib import city_zh
        from ..schemas import CityHypothesis

        # CITY_COORDS 按人口降序生成，直接取前 3
        for name, (_lat, _lon, c) in CITY_COORDS.items():
            if c != country or len(scene.city_hypotheses) >= 3:
                continue
            zh = city_zh(name)
            scene.city_hypotheses.append(CityHypothesis(
                city=name, country=c, country_zh=zh,
                reasoning="城市级兜底：国家确定后按人口选取的主要城市", confidence=0.25))
        scene.city_hypotheses.sort(key=lambda h: h.confidence, reverse=True)

    @staticmethod
    def _inject_text_clues(scene: SceneAnalysis, scope: str = "world") -> None:
        """文字地名直出：visible_text 中匹配城市/国家名，直接强化假设。

        城市名（600 城表）→ 城市假设；国家名（中英文）→ 国家假设加权。
        除中国大陆模式：跳过中国（大陆）城市与国家。
        仅中国大陆模式：只保留中国（大陆）城市与国家的匹配。
        """
        from ..geokb.cities import CITY_COORDS
        from ..geokb.citylib import _fold, city_zh, folded_city_index
        from ..geokb.countries import COUNTRY_ALIASES, COUNTRY_META, country_zh

        if not scene.visible_text:
            return
        text_blob = " ".join(scene.visible_text)
        low = text_blob.lower()

        # 0) 中文城市名直配：visible_text 中的中文城市名（如"成都""西安"）直接命中
        #    （英文 fold 索引对中文无效；中文名走 CITY_ZH/补全表/精确坐标表）
        from ..geokb.citylib import _fold, _norm, city_coords, city_zh, zh_city_names
        from ..geokb.countries import country_zh as _country_zh
        from ..schemas import CityHypothesis as _CityHypothesis

        for text in scene.visible_text:
            if not any("\u4e00" <= ch <= "\u9fff" for ch in text):
                continue
            for zh in zh_city_names():
                if not zh or zh not in text:
                    continue
                hit = city_coords(zh)
                if hit is None:
                    continue
                country = hit[2]
                if scope == "no-cn" and country == "China":
                    continue
                if scope == "cn" and country != "China":
                    continue
                en = _norm(zh)
                if any(_fold(h.city) == _fold(en) for h in scene.city_hypotheses):
                    continue
                scene.city_hypotheses.append(_CityHypothesis(
                    city=en, country=country, country_zh=_country_zh(country),
                    reasoning="可见文字直接包含该城市名（中文匹配）", confidence=0.6))

        # 1) 城市匹配（预折叠索引，覆盖 7100 城；匹配到的名字反向取规范名）
        city_by_fold = {}
        for fname, (clat, clon, country) in folded_city_index().items():
            city_by_fold[fname] = (clat, clon, country)
        for fname, (clat, clon, country) in city_by_fold.items():
            if fname and fname in low:
                if scope == "no-cn" and country == "China":
                    continue
                if scope == "cn" and country != "China":
                    continue
                from ..geokb.citylib import _norm
                cname = _norm(fname)
                zh = country_zh(country)
                hit = next((h for h in scene.city_hypotheses if _fold(h.city) == fname), None)
                if hit:
                    hit.confidence = min(0.9, max(hit.confidence, 0.6))
                else:
                    from ..schemas import CityHypothesis
                    scene.city_hypotheses.append(CityHypothesis(
                        city=cname, country=country, country_zh=zh,
                        reasoning="可见文字直接包含该城市名", confidence=0.6))
        # 2) 国家匹配（规范英文名 + 别名 + 中文名）
        for cname in COUNTRY_META:
            if scope == "cn" and cname != "China":
                continue
            aliases = [cname.lower(), (COUNTRY_ALIASES.get(cname) or "").lower(),
                       country_zh(cname).lower()]
            if any(a and a in low for a in aliases):
                if scope == "no-cn" and cname == "China":
                    continue
                hit = next((h for h in scene.country_hypotheses
                            if h.country.lower() == cname.lower()), None)
                if hit:
                    hit.confidence = min(0.95, hit.confidence + 0.08)
                else:
                    from ..schemas import CountryHypothesis
                    scene.country_hypotheses.append(CountryHypothesis(
                        country=cname, country_zh=country_zh(cname),
                        reasoning="可见文字直接包含该国名", confidence=0.35))
        scene.country_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        scene.city_hypotheses.sort(key=lambda h: h.confidence, reverse=True)

    @staticmethod
    def _merge_scenes(scenes: list[SceneAnalysis]) -> SceneAnalysis:
        """合并多次采样：集合字段取并集，假设按置信度取最大。"""
        base = scenes[0]
        merged = SceneAnalysis(
            is_street_view=all(s.is_street_view for s in scenes),
            scene_type=base.scene_type,
            visible_text=_union(s.visible_text for s in scenes),
            languages=_union(s.languages for s in scenes),
            scripts=_union(s.scripts for s in scenes),
            traffic_signs=_union(s.traffic_signs for s in scenes),
            architecture=_union(s.architecture for s in scenes),
            vegetation=_union(s.vegetation for s in scenes),
            terrain=_union(s.terrain for s in scenes),
            weather=_union(s.weather for s in scenes),
            soil=_union(s.soil for s in scenes),
            sun_shadow=_pick_most_confident(s.sun_shadow for s in scenes),
            image_quality=_pick_most_confident(s.image_quality for s in scenes),
            pole=_pick_most_confident(s.pole for s in scenes),
            driving_side=_pick_most_confident(s.driving_side for s in scenes),
            unique_features=_union(s.unique_features for s in scenes),
            overall_confidence=max(s.overall_confidence for s in scenes),
            summary=scenes[0].summary or scenes[-1].summary or "",
            raw_output="\n".join(s.raw_output for s in scenes),
            tokens={
                "prompt": sum(s.tokens.get("prompt", 0) for s in scenes),
                "completion": sum(s.tokens.get("completion", 0) for s in scenes),
                "calls": sum(s.tokens.get("calls", 0) for s in scenes),
            },
        )
        # 国家/城市假设：按名称取最大置信度
        merged.country_hypotheses = _merge_hypotheses(
            [h for s in scenes for h in s.country_hypotheses],
            lambda h: h.country, lambda h: h.confidence,
            lambda name, conf, best: CountryHypothesis(
                country=name, country_zh=best.country_zh, reasoning=best.reasoning,
                confidence=conf))
        merged.city_hypotheses = _merge_hypotheses(
            [h for s in scenes for h in s.city_hypotheses],
            lambda h: h.city, lambda h: h.confidence,
            lambda name, conf, best: CityHypothesis(
                city=name, country=best.country, country_zh=best.country_zh,
                lat=best.lat, lon=best.lon,
                reasoning=best.reasoning, confidence=conf))
        merged.country_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        merged.city_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return merged

    async def _fallback(self, payload: bytes, mime: str,
                        scope: str = "world",
                        cause: Exception | None = None,
                        tokens: dict | None = None) -> str:
        """主模型超时/繁忙 → 快速模型兜底；快速模型也不可用 → SceneTimeoutError（降级不失败）。"""
        from ..llm.base import OverloadError

        if not self.fallback_enabled:
            raise SceneTimeoutError("主模型不可用（模式配置未启用降级模型）")
        if self.fallback_provider is None:
            if not settings.llm_fallback_model:
                raise SceneTimeoutError("主模型不可用且未配置降级模型")
            from ..llm.factory import create_provider
            self.fallback_provider = create_provider(model=settings.llm_fallback_model)
        try:
            text = await asyncio.wait_for(
                self._ask_with_retry(payload, mime, scope,
                                     provider=self.fallback_provider, tokens=tokens),
                timeout=self.fallback_timeout)
        except asyncio.TimeoutError:
            raise SceneTimeoutError("主模型与快速模型均超时") from None
        except OverloadError:
            raise SceneTimeoutError("主模型与快速模型均繁忙/限流（平台瞬态故障）") from None
        self.used_fallback = True
        return text

    # ---- 内部 ----

    async def _ask_with_retry(self, payload: bytes, mime: str,
                              scope: str = "world",
                              provider: LLMProvider | None = None,
                              tokens: dict | None = None) -> str:
        from ..llm.prompts import build_clue_prompt

        provider = provider or self.provider
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            # 中国/全球提示词按 scope 分离（build_clue_prompt 内含范围指令与对应少样本）
            prompt = (build_clue_prompt(scope) if attempt == 0 else repair_prompt(last_text))
            result = await provider.analyze_image(payload, prompt, mime=mime)
            last_text = result.content
            usage = getattr(result, "usage", None)
            if tokens is not None and usage:
                tokens["prompt"] += int(usage.get("prompt_tokens", 0) or 0)
                tokens["completion"] += int(usage.get("completion_tokens", 0) or 0)
                tokens["calls"] += 1
            try:
                extract_json(last_text)
                return last_text
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise ValueError(f"模型输出无法解析为 JSON（重试 {self.retries} 次后放弃）：{last_err}")

    def _prepare(self, image_bytes: bytes, mime: str) -> tuple[bytes, str]:
        """压缩超大图 + 轻度对比度/锐化增强（提升 OCR 与细节线索识别）。"""
        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            raise ValueError(f"无法解析图片：{e}") from e

        img = ImageOps.exif_transpose(img)
        if max(img.size) > self.image_side:
            img.thumbnail((self.image_side, self.image_side), Image.LANCZOS)

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if img.mode == "L":
            img = img.convert("RGB")

        # 轻度增强（数值保守，避免失真）：对比度 +8%，锐化 +15%
        try:
            from PIL import ImageEnhance
            img = ImageEnhance.Contrast(img).enhance(1.08)
            img = ImageEnhance.Sharpness(img).enhance(1.15)
        except Exception:
            pass

        buf = io.BytesIO()
        if mime == "image/png":
            img.save(buf, format="PNG")
            return buf.getvalue(), "image/png"
        img.save(buf, format="JPEG", quality=settings.jpeg_quality)
        return buf.getvalue(), "image/jpeg"

    @staticmethod
    def _to_schema(data: dict, raw: str) -> SceneAnalysis:
        from ..geokb.countries import country_zh

        def _countries(raw_list) -> list[CountryHypothesis]:
            out = []
            for item in raw_list or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("country", ""))
                out.append(CountryHypothesis(
                    country=name,
                    country_zh=country_zh(name),
                    reasoning=str(item.get("reasoning", "")),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                ))
            return out

        def _cities(raw_list) -> list[CityHypothesis]:
            out = []
            for item in raw_list or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("city", ""))
                cname = str(item.get("country", ""))
                out.append(CityHypothesis(
                    city=name,
                    country=cname,
                    country_zh=country_zh(cname),
                    lat=_safe_latlon(item.get("lat")),
                    lon=_safe_latlon(item.get("lon")),
                    reasoning=str(item.get("reasoning", "")),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                ))
            return out

        def _strings(key: str) -> list[str]:
            val = data.get(key)
            if isinstance(val, list):
                return [str(x) for x in val if x]
            if isinstance(val, str) and val:
                return [val]
            return []

        return SceneAnalysis(
            is_street_view=bool(data.get("is_street_view", True)),
            scene_type=str(data.get("scene_type", "unknown")),
            visible_text=_strings("visible_text"),
            languages=_strings("languages"),
            scripts=_strings("scripts"),
            traffic_signs=_strings("traffic_signs"),
            architecture=_strings("architecture"),
            vegetation=_strings("vegetation"),
            terrain=_strings("terrain"),
            weather=_strings("weather"),
            soil=_strings("soil"),
            sun_shadow=str(data.get("sun_shadow", "")),
            image_quality=str(data.get("image_quality", "")),
            pole=str(data.get("pole", "")),
            driving_side=str(data.get("driving_side", "unknown")),
            unique_features=_strings("unique_features"),
            country_hypotheses=_countries(data.get("country_hypotheses")),
            city_hypotheses=_cities(data.get("city_hypotheses")),
            overall_confidence=float(data.get("overall_confidence", 0.0) or 0.0),
            summary=str(data.get("summary", "")),
            raw_output=raw,
        )
