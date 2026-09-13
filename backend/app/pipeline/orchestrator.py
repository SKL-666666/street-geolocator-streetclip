"""单图分析管线编排：任务队列 + 各阶段执行 + 降级链。

阶段：queued → exif → scene → streetview → done/failed
降级链：
  - EXIF 有 GPS → 直接完成（快路径，零 LLM 成本）
  - 无 GPS → LLM 线索提取（场景判别 + 国家/城市假设）
  - 有 MAPILLARY_TOKEN → 按城市假设做街景回查（骨架，Phase 2 完善）
  - LLM 不可用 → 任务失败并给出明确错误
"""
from __future__ import annotations

import asyncio
import io
import time
import uuid
from typing import Optional

from ..config import get_analyze_mode, settings
from ..geokb.engine import cross_filter, merge_into_scene
from ..llm.base import BalanceError, ContentFilterError, LLMProvider, OverloadError
from ..llm.factory import create_provider
from ..schemas import Candidate, SceneAnalysis, TaskResult, TaskStatus, ToolFact
from ..storage import TaskStore
from .exif import extract_captured, extract_gps, extract_camera
from .scene import SceneAnalyzer, SceneTimeoutError
from .suncheck import apply_sun_check
from .tools_pass import candidates_from_geocode, run_fact_check, run_tools_pass
from .verify import run_verify



def _fallback_candidate(scope: str = "world") -> list[Candidate]:
    """终极兜底：LLM 超时且本地先验不可用时输出固定示意点，保证结果永不为空。

    全世界/除大陆用东京（知名城市，双范围通用）；仅中国大陆用北京。
    提示语明确标注"无实际依据"，避免误导。
    """
    if scope == "cn":
        return [Candidate(
            rank=1, lat=39.9042, lon=116.4074, score=0.01, source="fallback",
            country="China", country_zh="中国",
            city="Beijing", city_zh="北京",
            accuracy_hint="⚠ 未能提取任何地理线索，默认示意点（无实际依据）",
            evidence=["定位失败：LLM 超时且本地先验不可用，显示默认示意点（北京）"],
        )]
    return [Candidate(
        rank=1, lat=35.6762, lon=139.6503, score=0.01, source="fallback",
        country="Japan", country_zh="日本",
        city="Tokyo", city_zh="东京",
        accuracy_hint="⚠ 未能提取任何地理线索，默认示意点（无实际依据）",
        evidence=["定位失败：LLM 超时且本地先验不可用，显示默认示意点（东京）"],
    )]


def _exclude_china(geo_kb) -> None:
    """除中国大陆模式：把证据矩阵中的中国（大陆）清零。"""
    from ..geokb.countries import COUNTRY_ALIASES

    for row in geo_kb.countries:
        if COUNTRY_ALIASES.get(row.country, row.country) == "China":
            row.kb_score = 0.0
            row.final_score = 0.0
            row.contradicting_clues.append("范围排除：任务指定排除中国大陆")


def _keep_only_china(geo_kb) -> None:
    """仅中国大陆模式：只保留中国的证据行，其余清零（对称逻辑）。"""
    from ..geokb.countries import COUNTRY_ALIASES

    for row in geo_kb.countries:
        if COUNTRY_ALIASES.get(row.country, row.country) != "China":
            row.kb_score = 0.0
            row.final_score = 0.0
            row.contradicting_clues.append("范围排除：任务指定仅中国大陆")


def _is_mainland_candidate(c: Candidate) -> bool:
    """候选是否属于中国（大陆）：国家名优先，无国家名时用矩形兜底。

    国家名判定绝不用坐标矩形（矩形与东南亚/南亚邻国有重叠，会误杀）。
    """
    from ..geokb.countries import COUNTRY_ALIASES, is_mainland_china

    name = COUNTRY_ALIASES.get(c.country or "", c.country or "")
    if name:
        return name == "China"
    return is_mainland_china(c.lat, c.lon)


def _filter_mainland(candidates: list[Candidate]) -> None:
    """除中国大陆模式：剔除中国（大陆）候选（就地过滤）。"""
    candidates[:] = [c for c in candidates if not _is_mainland_candidate(c)]


def _keep_mainland_only(candidates: list[Candidate]) -> None:
    """仅中国大陆模式：只保留中国（大陆）候选（就地过滤）。"""
    candidates[:] = [c for c in candidates if _is_mainland_candidate(c)]



def _first_city_of_country(country: str):
    """国家规范名 → 该国表内人口第一城市（600 城表按人口生成）。"""
    from ..geokb.cities import CITY_COORDS

    for name, v in CITY_COORDS.items():
        if v[2] == country:
            return v
    return None


class Orchestrator:
    def __init__(self, store: TaskStore, provider: Optional[LLMProvider] = None):
        self.store = store
        self.provider = provider or create_provider()
        # 按模式缓存的供应商与分析器（fast 用轻量模型、deep 开思考链；
        # 注意：balanced 也走懒创建，避免默认分析器吞掉模式配置）
        self._providers: dict[str, LLMProvider] = {}
        self._analyzers: dict[str, SceneAnalyzer] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._sem: Optional[asyncio.Semaphore] = None  # B4：并发上限（懒创建）

    def _analyzer_for(self, mode: str) -> SceneAnalyzer:
        """取模式对应的 SceneAnalyzer（懒创建：模型/图片尺寸/超时随模式变化）。"""
        mode_cfg = get_analyze_mode(mode)
        if mode not in self._analyzers:
            provider = create_provider(
                model=mode_cfg.get("model") or None,
                disable_thinking=mode_cfg.get("disable_thinking",
                                               settings.llm_disable_thinking))
            self._providers[mode] = provider
            analyzer = SceneAnalyzer(
                provider,
                retries=mode_cfg.get("retries", 1),
                fallback_provider=create_provider(model=mode_cfg.get("fallback_model") or None)
                if mode_cfg.get("fallback_model") else None,
                fallback_enabled=bool(mode_cfg.get("fallback_model")),
                image_side=mode_cfg.get("image_side", settings.max_image_side),
                primary_timeout=mode_cfg.get("primary_timeout", settings.llm_primary_timeout_sec),
                fallback_timeout=mode_cfg.get("fallback_timeout", settings.llm_fallback_timeout_sec),
                samples=mode_cfg.get("samples", 1),
            )
            self._analyzers[mode] = analyzer
        return self._analyzers[mode]

    def reload_provider(self) -> None:
        """配置变更后重建供应商与分析器缓存（/api/setup 保存 Key 后调用）。"""
        self.provider = create_provider()
        self._providers.clear()
        self._analyzers.clear()

    # ---------- 对外接口 ----------

    def submit(self, image_bytes: bytes, filename: str, mode: str = "local",
               scope: str = "world", enhance_ocr: bool = False,
               enhance_baidu: bool = False) -> str:
        mode = (mode or settings.analyze_mode).lower()
        scope = scope if scope in ("world", "no-cn", "cn") else "world"
        # 缓存机制已移除：每次上传都重新分析（保证结果新鲜）
        task_id = uuid.uuid4().hex[:12]
        result = TaskResult(task_id=task_id, filename=filename, stage="queued",
                            status=TaskStatus.PENDING, mode=mode,
                            meta={"scope": scope,
                                  "enhance_ocr": enhance_ocr,
                                  "enhance_baidu": enhance_baidu})
        # 保存原图（供失败/降级后一键重试；保存失败不阻塞分析）
        try:
            from pathlib import Path
            ext = Path(filename).suffix.lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
                ext = ".jpg"
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            (settings.upload_dir / f"{task_id}{ext}").write_bytes(image_bytes)
            result.has_image = True
        except Exception:  # noqa: BLE001
            result.has_image = False
        self.store.save(result)
        task = asyncio.create_task(self._run(task_id, image_bytes, mode, scope))
        self._tasks[task_id] = task
        return task_id

    def get(self, task_id: str) -> Optional[TaskResult]:
        return self.store.get(task_id)

    # ---------- 内部执行 ----------

    async def _run(self, task_id: str, image_bytes: bytes, mode: str = "balanced",
                   scope: str = "world") -> None:
        """B4：并发信号量包裹执行体。"""
        if self._sem is None:
            self._sem = asyncio.Semaphore(settings.max_concurrent_tasks)
        async with self._sem:
            await self._run_inner(task_id, image_bytes, mode, scope)

    async def _run_inner(self, task_id: str, image_bytes: bytes, mode: str = "balanced",
                         scope: str = "world") -> None:
        started = time.monotonic()
        mode_cfg = get_analyze_mode(mode)
        # 本地免费模式：不走 LLM（零 API 成本），直接本地模型分类
        if mode_cfg.get("local"):
            await self._run_local_inner(task_id, image_bytes, mode, scope)
            return
        analyzer = self._analyzer_for(mode)
        result = self.store.get(task_id)
        assert result is not None
        result.status = TaskStatus.RUNNING
        result.meta = {**result.meta, "scope": result.meta.get("scope", scope)}
        self._update(result, progress=5, stage="exif", message="读取 EXIF 元数据")

        try:
            # ① EXIF GPS 仅作参考展示，不再直接定位（用户要求移除快路径）：
            #    统一走完整 LLM 分析流程，EXIF 坐标不进入候选。
            gps = extract_gps(image_bytes)
            if gps:
                result.gps = gps
                note = f"EXIF GPS：{gps.lat:.5f}, {gps.lon:.5f}"
                try:
                    from ..geokb.citylib import nearest_city
                    near = nearest_city(gps.lat, gps.lon, max_km=80)
                    if near:
                        note += f"（最近城市：{near['zh']}，{near['distance_km']}km）"
                except Exception:
                    pass
                result.meta = {**result.meta, "exif_note": note}

            # ①b EXIF 相机信息（辅助线索：品牌→市场份额→国家概率）
            camera = extract_camera(image_bytes)
            if camera:
                result.meta = {**result.meta, "camera": camera}

            # ② LLM 线索提取（与 MixVPR 先验并行，省一次串行等待）
            # 提示词按 scope 分离（中国/全球），范围指令与少样本由 build_clue_prompt 组装
            self._update(result, progress=25, stage="scene", message="多模态 LLM 分析地理线索")
            scene_task = asyncio.create_task(
                analyzer.analyze(image_bytes, scope=scope))
            try:
                scene = await scene_task
            except SceneTimeoutError:
                # 双模型超时：不判失败，降级为"仅本地证据"继续（先验/检索仍可定位）
                from ..schemas import SceneAnalysis as _SA
                scene = _SA(
                    is_street_view=True, scene_type="street",
                    summary="LLM 分析超时，本次仅基于本地先验/检索定位")
                result.message = "LLM 超时，已降级为本地先验/检索定位"
                result.meta = {**result.meta, "degraded": True}  # 降级结果不入缓存
            except ContentFilterError:
                # 平台内容审核拦截：图片或生成内容被判敏感 → 优雅降级而非失败
                from ..schemas import SceneAnalysis as _SA
                scene = _SA(
                    is_street_view=True, scene_type="street",
                    summary="内容审核拦截：图片或生成内容被平台判定为敏感，仅基于本地先验/检索定位")
                result.message = "内容审核拦截（图片被平台判定为敏感），已降级为本地先验/检索定位"
                result.meta = {**result.meta, "degraded": True, "content_filtered": True}
            except BalanceError:
                # 账号余额不足/资源包耗尽（智谱 1113）：非瞬态，明确提示充值
                from ..schemas import SceneAnalysis as _SA
                scene = _SA(
                    is_street_view=True, scene_type="street",
                    summary="LLM 账号余额不足，本次仅基于本地先验/检索定位")
                result.message = "LLM 账号余额不足（请充值或更换 API Key），已降级为本地先验/检索定位"
                result.meta = {**result.meta, "degraded": True, "insufficient_balance": True}
            except OverloadError:
                # 平台繁忙/限流（1305/429/网络抖动）：瞬态故障 → 降级而非失败
                from ..schemas import SceneAnalysis as _SA
                scene = _SA(
                    is_street_view=True, scene_type="street",
                    summary="LLM 平台繁忙/限流，本次仅基于本地先验/检索定位")
                result.message = "LLM 平台繁忙/限流，已降级为本地先验/检索定位"
                result.meta = {**result.meta, "degraded": True, "overloaded": True}
            except ValueError as e:
                # 图片无法解析/模型输出无法解析：降级而非失败（无论如何必须输出结果）
                from ..schemas import SceneAnalysis as _SA
                scene = _SA(
                    is_street_view=True, scene_type="street",
                    summary=f"场景解析异常（{e}），本次仅基于本地先验/检索定位")
                result.message = f"场景解析异常，已降级为本地先验/检索定位（{e}）"
                result.meta = {**result.meta, "degraded": True}
            result.scene = scene
            # 成本感知：LLM token 消耗统计（prompt/completion/调用次数）
            result.meta = {**result.meta, "tokens": scene.tokens}
            self._update(result, progress=45, stage="scene", message="LLM 分析完成")

            if not scene.is_street_view:
                # 非街景图：若 LLM 仍给出国家/城市地理线索（如自然景观、航拍），
                # 照常走候选生成链做"近似定位"，绝不浪费线索；
                # 只有完全无线索时才提示"非街景，无法定位"。
                if not (scene.country_hypotheses or scene.city_hypotheses):
                    result.confidence_level = "none"
                    self._update(result, progress=100, stage="done",
                                 message=f"非街景图片（{scene.scene_type}），无地理线索，无法定位",
                                 status=TaskStatus.SUCCEEDED)
                    return
                result.message = f"非街景图片（{scene.scene_type}），按地理线索近似定位"

            # ③ 方案 B：Geo-KB 事实核查（确定性交叉筛选，零外部依赖）
            result.geo_kb = None
            if mode_cfg.get("enable_geokb", True):
                self._update(result, progress=55, stage="geokb", message="地理事实库交叉核查")
                llm_conf = {h.country: h.confidence for h in scene.country_hypotheses}
                result.geo_kb = cross_filter(scene, llm_conf)
                if scope == "no-cn":
                    _exclude_china(result.geo_kb)
                elif scope == "cn":
                    _keep_only_china(result.geo_kb)
                merge_into_scene(result.geo_kb, scene)
                # 仅中国大陆：中国城市特征档案匹配（独立知识库，与全球 Geo-KB 分离）
                from ..geokb.cn_engine import merge_cn_hypotheses
                merge_cn_hypotheses(scene)
                # 世界/除大陆：城市特征档案（Top300）+ 知识库强线索"救回"漏判国家
                if scope != "cn":
                    from ..geokb.rescue import apply_rescue
                    from ..geokb.world_city_engine import merge_world_hypotheses
                    merge_world_hypotheses(scene, scope)
                    apply_rescue(scene, scope)
                self._update(result, progress=65, stage="geokb", message="事实核查完成")



            # ⑤ 方案 D：Agentic 工具查证（按模式开关；LLM 降级时跳过，保速度）
            self._update(result, progress=70, stage="tools", message="外部工具查证（地理编码/百科）")
            result.facts = []
            if mode_cfg.get("enable_tools", False) and not result.meta.get("degraded"):
                result.facts = await run_tools_pass(scene)
            if any(f.ok for f in result.facts):
                await run_fact_check(self.provider, scene, result.facts)
            self._update(result, progress=80, stage="tools", message="查证完成")

            # ⑥ 置信度分级 + 候选点（先验坐标优先，地理编码次之，城市表兜底）
            result.confidence_level = self._level_from_scene(scene)
            result.candidates = (candidates_from_geocode(result.facts)
                                 or self._candidates_from_scene(scene))
            # 用户要求：任何级别都给城市级坐标点 → 国家级兜底 = 直接选首都城市
            if not result.candidates:
                result.candidates = self._country_capital_candidate(scene, scope)
            # LLM 超时/降级且无任何线索：不输出无依据示意点（用户要求），明确"无法定位"
            if not result.candidates and result.meta.get("degraded"):
                result.confidence_level = "none"
                result.candidates = []
                self._update(result, progress=100, stage="done",
                             message=(result.message or "LLM 分析超时/不可用，未生成定位结果（本次无法定位）"),
                             status=TaskStatus.SUCCEEDED)
                return
            # 兜底：仍无线索（极端情况）→ 固定示意点（历史行为，保持结果永不为空）
            if not result.candidates:
                result.candidates = _fallback_candidate(scope)
            self._annotate_candidates(result)
            # 范围过滤：除中国大陆 → 剔除大陆候选；仅中国大陆 → 只留大陆候选
            if scope == "no-cn":
                _filter_mainland(result.candidates)
            elif scope == "cn":
                _keep_mainland_only(result.candidates)
                if not result.candidates:
                    # 过滤后为空（如外国图片）→ 中国兜底示意点，结果永不为空
                    result.candidates = _fallback_candidate(scope)

            # ⑥b B1：街景索引检索（有索引的城市 → 街道级候选）
            if mode_cfg.get("enable_retrieval", False):
                rv = self._retrieval_pass(image_bytes, result.candidates)
                if rv:
                    result.candidates = rv + result.candidates
                    result.message = "命中街景索引检索"
                    self._annotate_candidates(result)

            # ⑥c B3：时区昼夜校验（EXIF 时间 vs 候选时区 vs 场景描述）
            captured = extract_captured(image_bytes)
            if captured:
                apply_sun_check(result.candidates, scene, captured)
                self._annotate_candidates(result)

            # ⑦ 街景回查：已关闭（不影响定位正确率；深度模式的 verify 复检已改为独立拉图，不依赖此阶段）
            sv_timeout = mode_cfg.get("streetview_timeout", 2.0)
            degraded = bool(result.meta.get("degraded"))
            if not degraded and settings.streetview_enabled:
                self._update(result, progress=88, stage="streetview", message="街景回查（KartaView）")
                try:
                    await asyncio.wait_for(self._streetview_pass(result, scene), timeout=sv_timeout)
                except asyncio.TimeoutError:
                    result.message = "街景回查超时，已跳过"
                self._annotate_candidates(result)  # 街景候选也补齐提示

            # ⑧ A1：LLM 复检闭环（查询图 + 候选街景拼图判定"是否同一地点"）
            if mode_cfg.get("enable_verify", False) and not degraded:
                # 时间预算守卫：管线已耗时超过预算则跳过复检（保证总时长）
                if time.monotonic() - started < mode_cfg.get("verify_budget_sec", 99):
                    verify_fact = await run_verify(
                        self._providers.get(mode, self.provider), image_bytes,
                        result.candidates, timeout=mode_cfg.get("verify_timeout", 6.0))
                    result.facts.append(verify_fact)
                    self._annotate_candidates(result)
                else:
                    result.facts.append(ToolFact(
                        tool="verify", query="街景复检",
                        summary="耗时超预算，已跳过复检（保证响应速度）", ok=False))

            # ⑧b B2：深度模式二轮精查（有候选被复检确认时，扩大半径再查再验）
            if mode_cfg.get("deep_round2", False) and self._has_confirmed(result):
                try:
                    await asyncio.wait_for(
                        self._streetview_pass(result, scene, radii=(300, 500)), timeout=5.0)
                    self._annotate_candidates(result)
                    fact2 = await run_verify(
                        self._providers.get(mode, self.provider), image_bytes,
                        result.candidates, timeout=10.0)
                    result.facts.append(fact2)
                    self._annotate_candidates(result)
                except Exception:  # noqa: BLE001
                    pass

            self._update(result, progress=100, stage="done",
                         message="分析完成", status=TaskStatus.SUCCEEDED)

        except Exception as e:  # noqa: BLE001
            result.error = f"{type(e).__name__}: {e}"
            self._update(result, stage="failed", message="分析失败", status=TaskStatus.FAILED)
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            result.updated_at = result.updated_at.now()
            self.store.save(result)
            self._tasks.pop(task_id, None)

    # ---------- 辅助 ----------

    async def _run_local_inner(self, task_id: str, image_bytes: bytes,
                               mode: str = "local", scope: str = "world") -> None:
        """本地免费模式：本地模型分类国家 TopK → 城市表主要城市候选（零 API 成本）。"""
        started = time.monotonic()
        result = self.store.get(task_id)
        assert result is not None
        result.status = TaskStatus.RUNNING
        self._update(result, progress=10, stage="scene",
                     message="本地模型分类（免费，不调用 LLM）")
        try:
            if scope == "cn":
                # 中国模式：跳过 StreetCLIP 国家，直接用城市模型推断中国城市
                from ..geokb.local_engine import classify_cities, model_name, _encode_image
                from ..geokb.citylib import city_coords, city_zh
                self._update(result, progress=40, stage="scene",
                             message="中国模式：直接推断城市（免费）")
                try:
                    img_feat = await asyncio.to_thread(_encode_image, image_bytes)
                    hits = await asyncio.to_thread(
                        classify_cities, image_bytes, "China", 3, None, img_feat)
                except Exception:
                    hits = []
                candidates = []
                for rank, h in enumerate(hits, 1):
                    candidates.append(Candidate(
                        rank=rank, lat=h["lat"], lon=h["lon"],
                        score=round(h["prob"], 3), source="local",
                        country="China", country_zh="中国",
                        city=h["label"], city_zh=city_zh(h["label"]),
                        accuracy_hint="城市级（中国模式：直接推断）",
                        evidence=[f"本地模型 {model_name()}：{h['label']}（{h['prob']:.1%}）"],
                    ))
                if not candidates:
                    candidates = _fallback_candidate("cn")
                result.candidates = candidates
                # OCR + Tavily 增强（cn 模式）
                if (result.meta or {}).get("enhance_ocr") and candidates:
                    try:
                        result.candidates = self._ocr_tavily_enhance(
                            image_bytes, result.candidates, result)
                    except Exception:
                        pass
                result.confidence_level = "city" if candidates[0].source == "local" else "none"
                result.scene = SceneAnalysis(
                    is_street_view=True, scene_type="street",
                    summary=f"中国模式 Top1：{candidates[0].city_zh}")
                self._update(result, progress=100, stage="done",
                             message=f"中国模式完成：{candidates[0].city_zh}",
                             status=TaskStatus.SUCCEEDED)
                return
            from ..geokb.local_engine import (
                classify_countries, classify_cities, classify_cities_llm_multi,
                model_name, _encode_image)
            from ..geokb.citylib import city_coords, city_zh
            from ..geokb.countries import COUNTRY_ALIASES, country_zh

            self._update(result, progress=40, stage="scene", message="本地模型推理中")
            # 第一级：本地 StreetCLIP 判国家 Top3
            top = await asyncio.to_thread(classify_countries, image_bytes, 3)
            # Top1/Top2 分差极小 → 标注"候选接近"（东欧互混等模糊场景更诚实）
            close = len(top) >= 2 and top[0]["prob"] - top[1]["prob"] < 0.02
            # 第二级引擎（config 切换）：
            #   llm（推荐）——Top3 国家 + 原图发给云端 LLM，一次定 3 城市（未必是首都），
            #     套用纯云端坐标逻辑落点（城市表优先 → LLM 估算坐标校正 → 兜底）；
            #   clip（免费）——本地 CLIP-B/16 只对 TOP1 猜城市，TOP2/3 用首都示意。
            city_engine = settings.local_city_engine
            candidates: list[Candidate] = []
            if city_engine == "llm" and top:
                # 云端 LLM：对 Top3 国家并行发单国调用，逐个定城市（未必是首都）
                labels = [t["label"] for t in top]
                city_rows = await classify_cities_llm_multi(image_bytes, labels)
                for rank, (t, row) in enumerate(zip(top, city_rows), 1):
                    label = t["label"]
                    country = COUNTRY_ALIASES.get(label, label)
                    if row and row.get("label"):
                        self._append_llm_city_candidate(candidates, rank, t, country, row)
                    else:
                        # LLM 说不出该国城市 → 首都示意兜底
                        self._append_capital_candidate(candidates, rank, t, country)
            elif top:
                # 本地 CLIP-B/16：只对 TOP1 猜城市，TOP2/3 首都
                t1 = top[0]
                hits: list[dict] = []
                try:
                    img_feat = await asyncio.to_thread(_encode_image, image_bytes)
                    hits = await asyncio.to_thread(
                        classify_cities, image_bytes, t1["label"], 1, None, img_feat)
                except Exception:  # noqa: BLE001
                    hits = []
                for rank, t in enumerate(top, 1):
                    label = t["label"]
                    country = COUNTRY_ALIASES.get(label, label)
                    if rank == 1 and hits:
                        h = hits[0]
                        candidates.append(Candidate(
                            rank=rank, lat=h["lat"], lon=h["lon"], score=round(t["prob"], 3),
                            source="local", country=country, country_zh=country_zh(country),
                            city=h["label"], city_zh=city_zh(h["label"]),
                            accuracy_hint=(
                                "城市级（本地两级：国家→城市；候选接近）" if close
                                else "城市级（本地两级：国家→城市）"),
                            evidence=[f"本地模型 {model_name()}：{label}（{t['prob']:.1%}）；"
                                      f"城市 {h['label']}"],
                        ))
                    else:
                        self._append_capital_candidate(candidates, rank, t, country)
            self._update(result, progress=70, stage="scene", message="生成候选位置")
            result.candidates = candidates

            # ---- OCR + Tavily 增强（用户勾选时触发）----
            meta = result.meta or {}
            if meta.get("enhance_ocr") and candidates:
                try:
                    result.candidates = self._ocr_tavily_enhance(
                        image_bytes, candidates, result)
                except Exception:
                    pass  # OCR/Tavily 失败不阻塞主流程

            # ---- 植被/气候分类（始终运行，轻量）----
            try:
                from .climate import classify_climate
                climate = classify_climate(image_bytes)
                if climate and climate.get("priors"):
                    result.facts.append(ToolFact(
                        tool="climate", query=climate["climate"],
                        summary=f"气候区: {climate['climate']}（置信度 {climate['confidence']:.1%}）",
                        ok=True))
                    for c, w in climate["priors"].items():
                        if any(cand.country == c for cand in candidates):
                            for cand in candidates:
                                if cand.country == c:
                                    cand.score = round(cand.score + w, 3)
                                    cand.evidence.append(f"气候区匹配：{climate['climate']}")
            except Exception:
                pass

            # ---- 车牌识别（始终运行，轻量）----
            try:
                from .plate import detect_plate_country
                from rapidocr_onnxruntime import RapidOCR
                ocr = RapidOCR()
                results, _ = ocr(Image.open(io.BytesIO(image_bytes)))
                if results:
                    texts = [r[1] for r in results if len(r[1]) >= 2]
                    plate = detect_plate_country(texts)
                    if plate.get("detected"):
                        result.facts.append(ToolFact(
                            tool="plate", query=plate["code"],
                            summary=f"车牌代码: {plate['code']}（{plate['country']}）",
                            ok=True))
                        # 车牌信号加权
                        for cand in candidates:
                            if cand.country == plate["country"]:
                                cand.score = round(cand.score + 0.1, 3)
                                cand.evidence.append(f"车牌代码 {plate['code']} → {plate['country']}")
            except Exception:
                pass

            top_name = candidates[0].city_zh if candidates else "无"
            result.scene = SceneAnalysis(
                is_street_view=True, scene_type="street",
                summary=f"本地模型（免费）Top1：{top_name}；Top3：{'、'.join(c.city_zh for c in candidates)}")
            result.confidence_level = "city" if candidates else "none"
            self._update(result, progress=100, stage="done",
                         message=f"本地模型完成：Top1={top_name}（免费，未调用 LLM）",
                         status=TaskStatus.SUCCEEDED)
        except Exception as e:  # noqa: BLE001
            result.error = f"{type(e).__name__}: {e}"
            self._update(result, stage="failed", message="本地模型分析失败", status=TaskStatus.FAILED)
        finally:
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            result.updated_at = result.updated_at.now()
            self.store.save(result)
            self._tasks.pop(task_id, None)

    @staticmethod
    def _retrieval_pass(image_bytes: bytes, candidates: list[Candidate]) -> list[Candidate]:
        """B1：对 top-1 候选城市做街景索引检索，产出街道级候选。"""
        from ..geokb.citylib import _norm, city_zh
        from ..retrieval.index import search_city

        top_city = next((c.city for c in candidates if c.city), None)
        if not top_city:
            return []
        en = _norm(top_city)
        hits = search_city(en, image_bytes, k=3)
        if not hits:
            return []
        zh = city_zh(en)
        out = []
        for h in hits:
            out.append(Candidate(
                rank=0, lat=h["lat"], lon=h["lon"],
                score=min(0.98, h["score"]), source="retrieval",
                city=en, city_zh=zh,
                accuracy_hint="街道级（街景索引检索）",
                evidence=[f"街景索引命中 {zh}（相似度 {h['score']:.2f}）"],
            ))
        return out

    @staticmethod
    def _ocr_tavily_enhance(image_bytes, candidates, result):
        """OCR + Tavily 增强：提取文字 → 搜索验证 → 加权融合到候选分数。"""
        import re, io
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            return candidates
        ocr = RapidOCR()
        img = Image.open(io.BytesIO(image_bytes))
        ocr_results, _ = ocr(img)
        if not ocr_results:
            result.facts.append(ToolFact(tool="ocr", query="", summary="无文字", ok=False))
            return candidates
        # 从 OCR 结果提取文字
        texts = [r[1] for r in ocr_results if len(r[1]) >= 2]
        if not texts:
            return candidates
        # 关键词：非数字、长度 >= 3
        keywords = [t for t in texts if len(t) >= 3 and not t.isdigit()][:2]
        result.facts.append(ToolFact(tool="ocr", query=str(keywords),
            summary=f"识别文字: {', '.join(texts[:5])}", ok=True))
        if not keywords:
            return candidates
        # Tavily 搜索
        import httpx as _httpx
        TAVILY_KEY = getattr(settings, "tavily_api_key", "") or "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"
        if not TAVILY_KEY:
            return candidates  # 未配置 Tavily Key，跳过
        try:
            with _httpx.Client(timeout=12) as c:
                r = c.post("https://api.tavily.com/search", json={
                    "query": " ".join(keywords), "search_depth": "basic",
                    "include_answer": True, "max_results": 2
                }, headers={"Authorization": f"Bearer {TAVILY_KEY}"})
            if r.status_code != 200:
                return candidates
            answer = r.json().get("answer", "")
            # 从 answer 第一句话提取国家
            CN_MAP = {"法国": "France", "意大利": "Italy", "奥地利": "Austria",
                      "德国": "Germany", "英国": "United Kingdom", "捷克": "Czechia",
                      "匈牙利": "Hungary", "波兰": "Poland", "乌克兰": "Ukraine",
                      "中国": "China", "蒙古": "Mongolia", "日本": "Japan",
                      "巴西": "Brazil", "玻利维亚": "Bolivia", "智利": "Chile",
                      "阿根廷": "Argentina", "秘鲁": "Peru", "美国": "United States",
                      "加拿大": "Canada", "俄罗斯": "Russia", "澳大利亚": "Australia",
                      "南非": "South Africa", "肯尼亚": "Kenya", "印度": "India"}
            first = re.split(r'[.。]', answer)[0]
            tav_country = None
            for cn, en in CN_MAP.items():
                if cn in first:
                    tav_country = en
                    break
            if not tav_country:
                # 英文匹配
                from ..geokb.countries import COUNTRY_ALIASES
                for c in COUNTRY_ALIASES.values():
                    if c.lower() in first.lower():
                        tav_country = c
                        break
            result.facts.append(ToolFact(tool="tavily", query=" ".join(keywords),
                summary=f"Tavily: {answer[:80]}... → {tav_country}",
                ok=tav_country is not None))
            if tav_country:
                # 在候选中找对应国家并加权
                for c in candidates:
                    if c.country == tav_country:
                        c.score = round(c.score * 1.15 + 0.03, 3)
                        c.evidence.append(f"OCR+Tavily 验证指向 {tav_country}")
        except Exception:
            pass
        return candidates
        return any("✅" in ev for c in result.candidates for ev in c.evidence)

    async def _streetview_pass(self, result: TaskResult, scene: SceneAnalysis,
                               radii: tuple[int, ...] | None = None) -> None:
        """候选点街景回查：KartaView（免 key，始终可用）+ Mapillary（有 token 时）。

        Phase 2 将在此接入 FAISS 索引检索；当前演示"候选点→真实街景影像"链路。
        """
        from ..streetview.kartaview import KartaViewClient
        from ..streetview.mapillary import MapillaryClient

        providers = [KartaViewClient(timeout=8)]
        if settings.mapillary_token:
            providers.append(MapillaryClient(settings.mapillary_token))

        # 速度优先：只回查 top-1 候选，半径两档（默认 60→200），每源最多 2 张
        candidates = result.candidates[:1]
        if not candidates:
            return
        radius_list = list(radii or (settings.mapillary_radius_m, 200))
        for cand in candidates:
            for provider in providers:
                images = []
                for radius in radius_list:
                    try:
                        images = await provider.nearby_with_thumbs(
                            cand.lat, cand.lon, radius_m=radius, limit=2)
                    except Exception as e:  # noqa: BLE001
                        result.message = f"街景回查失败（{e}），已降级为 LLM 假设"
                        break
                    if images:
                        break
                source = "kartaview" if isinstance(provider, KartaViewClient) else "streetview"
                for img in images[:2]:
                    result.candidates.append(Candidate(
                        rank=len(result.candidates) + 1,
                        lat=img.lat, lon=img.lon,
                        score=cand.score * 0.9,
                        source=source,
                        thumbnail_url=img.thumb_url,
                        evidence=[f"{source} {img.id}（{img.captured_at or '时间未知'}）"],
                    ))
                if images:
                    break  # 该源已有影像，不再试更大半径

    @staticmethod
    def _append_capital_candidate(candidates: list[Candidate], rank: int,
                                  t: dict, country: str) -> None:
        """首都示意候选（LLM 看不出该国城市 / 非 TOP1 时的兜底）。"""
        from ..geokb.countries import (
            country_centroid, country_capital_zh, country_zh)
        from ..geokb.local_engine import model_name

        center = country_centroid(country)
        if center is None:
            return
        cap_zh = country_capital_zh(country)
        cap_en = cap_zh or country
        from ..geokb.cities import CITY_COORDS
        for cn, v in CITY_COORDS.items():
            if v[2] == country and abs(v[0] - center[0]) < 0.5 and abs(v[1] - center[1]) < 0.5:
                cap_en = cn
                break
        candidates.append(Candidate(
            rank=rank, lat=center[0], lon=center[1], score=round(t["prob"], 3),
            source="local", country=country, country_zh=country_zh(country),
            city=cap_en, city_zh=cap_zh or country,
            accuracy_hint="国家级（本地模型，免费；首都示意）",
            evidence=[f"本地模型 {model_name()}：{t['label']}（{t['prob']:.1%}）；"
                      f"城市未识别，取首都 {cap_en}"],
        ))

    @staticmethod
    def _append_llm_city_candidate(candidates: list[Candidate], rank: int,
                                   t: dict, country: str, row: dict) -> None:
        """LLM 城市候选（套用纯云端坐标逻辑）：城市表优先 → LLM 估算坐标校正 → 首都兜底。"""
        from ..geokb.citylib import city_coords, city_zh, nearest_city
        from ..geokb.countries import country_zh

        city = str(row.get("label") or "").strip()
        lat = float(row.get("lat") or 0)
        lon = float(row.get("lon") or 0)
        if not city:
            Orchestrator._append_capital_candidate(candidates, rank, t, country)
            return
        # 1) 城市表优先（权威坐标）
        hit = city_coords(city)
        if hit:
            from ..geokb.citylib import _norm
            en_name = _norm(city)
            zh = city_zh(city)
            hint = "城市级（本地国家→云端 LLM 城市，城市表坐标）"
            ev = [f"云端 LLM 城市：{city}（城市表坐标 {hit[0]:.2f},{hit[1]:.2f}）"]
            if country and country != hit[2]:
                hint = "⚠ 同名城市歧义，坐标按城市表解析国家"
                ev.append(f"LLM 判断 {country}，城市表解析为 {hit[2]}（{zh}）")
            candidates.append(Candidate(
                rank=rank, lat=hit[0], lon=hit[1], score=round(t["prob"], 3),
                source="local", country=hit[2], country_zh=country_zh(hit[2]),
                city=en_name, city_zh=zh, accuracy_hint=hint, evidence=ev,
            ))
            return
        # 2) LLM 估算坐标（城市未收录时）：最近城市校正
        if lat or lon:
            near = nearest_city(lat, lon, max_km=80)
            fixed = city_coords(near["name"]) if near else None
            if fixed:
                candidates.append(Candidate(
                    rank=rank, lat=fixed[0], lon=fixed[1], score=round(t["prob"], 3),
                    source="local", country=fixed[2], country_zh=country_zh(fixed[2]),
                    city=near["name"], city_zh=near["zh"],
                    accuracy_hint="（坐标估算）",
                    evidence=[f"云端 LLM 城市：{city}（估算坐标校正为最近城市 {near['zh']}）"],
                ))
                return
            candidates.append(Candidate(
                rank=rank, lat=lat, lon=lon, score=round(t["prob"], 3),
                source="local", country=country, country_zh=country_zh(country),
                city=city, city_zh=city_zh(city),
                accuracy_hint="（坐标估算）",
                evidence=[f"云端 LLM 城市：{city}（LLM 估算坐标 {lat:.2f},{lon:.2f}）"],
            ))
            return
        # 3) 城市未收录且无坐标：首都兜底
        Orchestrator._append_capital_candidate(candidates, rank, t, country)

    @staticmethod
    def _country_capital_candidate(scene: SceneAnalysis, scope: str = "world") -> list[Candidate]:
        """国家级结论的兜底候选：89 国首都坐标优先，否则该国表内人口第一城。

        覆盖世界上所有国家（7100 城表按人口排序）。
        """
        from ..geokb.countries import (
            COUNTRY_ALIASES,
            country_capital_zh,
            country_centroid,
            country_zh,
        )

        hypos = scene.country_hypotheses
        if scope == "no-cn":
            # 除中国大陆模式：跳过中国（大陆）假设，取下一个国家
            hypos = [h for h in hypos if COUNTRY_ALIASES.get(h.country, h.country) != "China"]
        elif scope == "cn":
            # 仅中国大陆模式：只取中国假设
            hypos = [h for h in hypos if COUNTRY_ALIASES.get(h.country, h.country) == "China"]
        if not hypos:
            return []
        top = hypos[0]
        country = COUNTRY_ALIASES.get(top.country, top.country)
        center = country_centroid(country)          # 89 国首都坐标
        is_capital = True
        if center is None:
            center = _first_city_of_country(country)  # 其他国家的表内人口第一城
            is_capital = False
        if center is None:
            return []
        zh = country_zh(country)
        capital = country_capital_zh(country)
        city_label = capital or zh
        note = "首都" if is_capital else "人口最大城市"
        return [Candidate(
            rank=1, lat=center[0], lon=center[1],
            score=round(top.confidence, 3), source="country",
            country=country, country_zh=zh,
            city=city_label, city_zh=city_label,
            accuracy_hint=f"信息不足，准确度仅国家级（示意点为{zh}{note}）",
            evidence=[f"国家级结论（{zh}）：示意点取{note} {city_label}"],
        )]

    @staticmethod
    def _annotate_candidates(result: TaskResult) -> None:
        """为所有候选点补齐城市名/国家名与准确度提示（任何候选都必须是城市级点）。"""
        from ..geokb.citylib import city_coords
        from ..geokb.countries import country_zh

        hints = {
            "exif": "精确（EXIF GPS）",
            "geocode": "城市级（地理编码）",
            "llm": "城市级（LLM 假设）",
            "streetview": "街道级（真实街景影像）",
            "kartaview": "街道级（真实街景影像）",
            "country": "",
        }
        # A8：城市名继承 —— 无城市名的候选（如街景点）继承最高分候选的城市
        donor = next((c for c in result.candidates if c.city_zh), None)
        for c in result.candidates:
            if not c.accuracy_hint:
                c.accuracy_hint = hints.get(c.source, "城市级")
            if c.source == "country" and c.city:
                continue
            if not c.city_zh and donor is not None:
                c.city = c.city_zh = donor.city_zh
                c.evidence.append(f"位于 {donor.city_zh} 附近")
            if not c.city:
                c.city = c.city_zh or ""
            if not c.city_zh:
                c.city_zh = c.city
            # 国家名：从城市表解析
            if c.city and not c.country:
                hit = city_coords(c.city)
                if hit:
                    c.country = hit[2]
                    c.country_zh = country_zh(hit[2])

    @staticmethod
    def _level_from_scene(scene: SceneAnalysis) -> str:
        if scene.city_hypotheses and scene.city_hypotheses[0].confidence >= 0.5:
            return "city"
        if scene.country_hypotheses:
            return "country"
        return "none"

    @staticmethod
    def _candidates_from_scene(scene: SceneAnalysis) -> list[Candidate]:
        """把 LLM 假设转成候选点。

        坐标优先级：7100 城表/中国中文精确坐标表 > LLM 估算经纬度（未收录城市）
        > 国家主要城市（近似）。
        表坐标优先于 LLM 估算坐标：LLM 对中国城市坐标常有偏差（如"苏州"误指
        安徽宿州），城市表（含中文精确坐标特例）更权威。
        最终兜底：候选仍为空且存在国家假设 → 用顶层国家生成一条候选（地图必显示）。
        """
        from ..geokb.citylib import city_coords, city_zh
        from ..geokb.countries import COUNTRY_ALIASES, country_zh

        # 顶层国家假设（城市假设 country 缺失时回退用）
        top_country = ""
        if scene.country_hypotheses:
            top_country = COUNTRY_ALIASES.get(
                scene.country_hypotheses[0].country, scene.country_hypotheses[0].country)

        candidates: list[Candidate] = []
        rank = 0
        for h in scene.city_hypotheses[:5]:
            country = COUNTRY_ALIASES.get(h.country, h.country) or top_country
            # 1) 城市表（含中文精确坐标特例）——比 LLM 估算坐标更可靠；city 一律用英文表键，中文名作标注
            hit = city_coords(h.city)
            if hit:
                rank += 1
                from ..geokb.citylib import _norm
                en_name = _norm(h.city)          # 中文/别名 → 英文表键（Belém）
                zh = city_zh(h.city)             # 中文名（有映射则"贝伦"，无则同英文）
                hint = "城市级（LLM 假设，城市表坐标）"
                ev = [f"LLM 城市假设：{h.city}（城市表坐标 {hit[0]:.2f},{hit[1]:.2f}）"]
                # 同名城市歧义提示：LLM 判断的国家与城市表解析的国家不同（如 Suzhou→宿州/苏州）
                if country and country != hit[2]:
                    hint = "⚠ 同名城市歧义，坐标按城市表解析国家"
                    ev.append(f"LLM 判断 {country}，城市表解析为 {hit[2]}（{zh}）")
                candidates.append(Candidate(
                    rank=rank, lat=hit[0], lon=hit[1],
                    score=h.confidence, source="llm",
                    country=hit[2], country_zh=country_zh(hit[2]),
                    city=en_name, city_zh=zh,
                    accuracy_hint=hint,
                    evidence=ev,
                ))
                continue
            # 2) LLM 估算坐标（prompt 强制输出，已范围校验；仅城市未收录时使用）
            #    LLM 估算坐标常不准（可能落在别国）→ 用最近城市校正，保证 列表名/地图点/国家 一致
            if h.lat is not None and h.lon is not None and -90 <= h.lat <= 90 and -180 <= h.lon <= 180:
                from ..geokb.citylib import nearest_city, _fold
                near = nearest_city(h.lat, h.lon, max_km=80)
                fixed = city_coords(near["name"]) if near else None
                if fixed:
                    rank += 1
                    candidates.append(Candidate(
                        rank=rank, lat=fixed[0], lon=fixed[1],
                        score=h.confidence, source="llm",
                        country=fixed[2], country_zh=country_zh(fixed[2]),
                        city=near["name"], city_zh=near["zh"],
                        accuracy_hint="（坐标估算）",
                        evidence=[f"LLM 城市假设：{h.city}（估算坐标校正为最近城市 {near['zh']}）"],
                    ))
                    continue
                rank += 1
                candidates.append(Candidate(
                    rank=rank, lat=h.lat, lon=h.lon,
                    score=h.confidence, source="llm",
                    country=country, country_zh=country_zh(country),
                    city=h.city, city_zh=city_zh(h.city),
                    accuracy_hint="（坐标估算）",
                    evidence=[f"LLM 城市假设：{h.city}（LLM 估算坐标 {h.lat:.2f},{h.lon:.2f}）"],
                ))
                continue
            # 3) 城市未收录且无 LLM 坐标：用该国主要城市近似（列表名/地图点/坐标必须一致）
            approx = _first_city_of_country(country)
            if approx is None:
                continue
            rank += 1
            from ..geokb.cities import CITY_COORDS
            approx_name = next((n for n, v in CITY_COORDS.items() if v[2] == country), None)
            approx_zh = city_zh(approx_name) if approx_name else (approx_name or country)
            candidates.append(Candidate(
                rank=rank, lat=approx[0], lon=approx[1],
                score=h.confidence, source="llm",
                country=approx[2], country_zh=country_zh(approx[2]),
                city=approx_name or h.city, city_zh=approx_zh,
                accuracy_hint="（坐标估算）",
                evidence=[f"LLM 城市假设：{h.city}（未收录，坐标取 {approx_zh} 近似）"],
            ))

        # 最终兜底：城市假设全部落空（如城市与国家都未识别）→ 顶层国家主要城市
        if not candidates and top_country:
            from ..geokb.cities import CITY_COORDS
            approx = _first_city_of_country(top_country)
            approx_name = next((n for n, v in CITY_COORDS.items() if v[2] == top_country), None)
            if approx is not None and approx_name:
                top = scene.country_hypotheses[0]
                candidates.append(Candidate(
                    rank=1, lat=approx[0], lon=approx[1],
                    score=round(top.confidence, 3), source="llm",
                    country=top_country, country_zh=country_zh(top_country),
                    city=approx_name, city_zh=city_zh(approx_name),
                    accuracy_hint="⚠ 城市未识别，坐标为该国主要城市（近似）",
                    evidence=[f"国家级结论（{country_zh(top_country)}）：城市未识别，坐标取主要城市"],
                ))
        return candidates

    @staticmethod
    def _update(result: TaskResult, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(result, k, v)
        result.updated_at = result.updated_at.now()
