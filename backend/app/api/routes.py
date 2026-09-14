"""REST API：健康检查 / 上传分析 / 任务查询。"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.requests import Request
from fastapi.responses import JSONResponse

import json  # noqa: E402（导出用）

from ..config import ANALYZE_MODES, get_analyze_mode, settings
from ..pipeline.orchestrator import Orchestrator
from ..schemas import AnalyzeResponse, HealthResponse, TaskQueryResponse, TaskResult, TaskStatus
from ..storage import TaskStore

router = APIRouter(prefix="/api")


def _get_orchestrator(request) -> Orchestrator:
    return request.app.state.orchestrator


def _get_store(request) -> TaskStore:
    return request.app.state.store


@router.get("/health", response_model=HealthResponse)
async def health(request: Request):
    orch: Orchestrator = _get_orchestrator(request)
    desc = orch.provider.describe()
    from ..main import APP_READY, WARMUP_ELAPSED
    return HealthResponse(
        status="ok",
        provider=desc["name"],
        model=desc["model"],
        mapillary=bool(settings.mapillary_token),
        needs_setup=not bool(settings.llm_api_key),
        warming_up=not APP_READY,
        warmup_elapsed=round(WARMUP_ELAPSED, 1),
    )


@router.get("/config")
async def public_config(request: Request):
    """前端需要知道的公开配置（不含任何密钥）。"""
    desc = request.app.state.orchestrator.provider.describe()
    return {
        "provider": desc["name"],
        "model": desc["model"],
        "mapillary_enabled": bool(settings.mapillary_token),
        "max_upload_mb": settings.max_upload_mb,
        "modes": {k: {"label": v["label"], "desc": v["desc"]} for k, v in ANALYZE_MODES.items()},
        "default_mode": settings.analyze_mode,
        "local_city_engine": _load_prefs().get("local_city_engine", settings.local_city_engine),
        # 地图源：华为瓦片模板（key 已渲染，与各大地图 SDK 惯例一致，受域名白名单限制）
        "map_tile_url": settings.map_tile_url.replace("{key}", settings.map_api_key)
        if settings.map_api_key else "",
        "map_source": "huawei" if settings.map_api_key else "amap",
        # 未配置 LLM Key 时前端显示"设置页"
        "needs_setup": not bool(settings.llm_api_key),
        "setup_hint": "未配置 LLM API Key",
        # 本地模型预热中（前端禁用上传并提示）
        "warming_up": _warming_up(),
        "warmup_elapsed": _warmup_elapsed(),
    }


def _warming_up() -> bool:
    try:
        from ..main import APP_READY
        return not APP_READY
    except Exception:
        return False


def _warmup_elapsed() -> float:
    try:
        from ..main import WARMUP_ELAPSED
        return round(WARMUP_ELAPSED, 1)
    except Exception:
        return 0.0


def _prefs_path():
    return settings.data_dir / "prefs.json"


def _load_prefs() -> dict:
    """读取用户偏好（双采样开关等；文件缺失/损坏返回空）。"""
    try:
        import json
        return json.loads(_prefs_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


@router.post("/prefs")
async def save_prefs(request: Request, local_city_engine: str = Form("")):
    """保存用户偏好（本机持久化 + 立即生效）。"""
    prefs = _load_prefs()
    if local_city_engine in ("clip", "llm"):
        prefs["local_city_engine"] = local_city_engine
    try:
        _prefs_path().parent.mkdir(parents=True, exist_ok=True)
        import json
        _prefs_path().write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    city = prefs.get("local_city_engine", settings.local_city_engine)
    settings.local_city_engine = city if city in ("clip", "llm") else "clip"
    return {"ok": True, "local_city_engine": settings.local_city_engine}


@router.get("/llm-configs")
async def list_llm_configs(request: Request):
    """已保存的 LLM 配置列表（Key 脱敏展示）。"""
    from ..llm import config_store
    return {"configs": config_store.public_configs()}


@router.post("/llm-configs")
async def add_llm_config(request: Request,
                         api_key: str = Form(...),
                         base_url: str = Form(""),
                         model: str = Form(""),
                         name: str = Form("")):
    """添加新配置并立即激活（保存到本机，不落库）。

    重复配置（同 key+模型+地址）不新增，直接激活已有那条（duplicated=true）。
    """
    from ..llm import config_store

    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    configs, added = config_store.add_config(
        name=name.strip(), api_key=api_key,
        base_url=base_url.strip(), model=model.strip())
    _apply_llm_config(request)
    return {"configs": config_store.public_configs(configs), "duplicated": not added}


@router.post("/llm-configs/{config_id}/activate")
async def activate_llm_config(config_id: str, request: Request):
    """一键切换：激活指定配置并热加载。"""
    from ..llm import config_store

    configs = config_store.activate_config(config_id)
    if not any(c.get("id") == config_id for c in configs):
        raise HTTPException(status_code=404, detail="配置不存在")
    _apply_llm_config(request)
    return {"configs": config_store.public_configs(configs)}


@router.delete("/llm-configs/{config_id}")
async def delete_llm_config(config_id: str, request: Request):
    """删除配置；若删除的是激活项则自动激活剩余第一条。"""
    from ..llm import config_store

    before = config_store.load_configs()
    if not any(c.get("id") == config_id for c in before):
        raise HTTPException(status_code=404, detail="配置不存在")
    configs = config_store.delete_config(config_id)
    _apply_llm_config(request)
    return {"configs": config_store.public_configs(configs)}


def _apply_llm_config(request: Request) -> None:
    """把激活配置写入内存并热加载 provider（/api/config 的 needs_setup 立即更新）。"""
    from ..llm import config_store

    config_store.apply_active_to_settings()
    orch: Orchestrator = _get_orchestrator(request)
    orch.reload_provider()


@router.post("/setup")
async def setup_llm(request: Request,
                    api_key: str = Form(...),
                    base_url: str = Form(""),
                    model: str = Form("")):
    """兼容旧设置页：保存为"默认配置"并激活（同 /api/llm-configs）。"""
    from ..llm import config_store

    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    configs, _added = config_store.add_config(
        name="默认配置", api_key=api_key,
        base_url=base_url.strip(), model=model.strip())
    _apply_llm_config(request)
    orch: Orchestrator = _get_orchestrator(request)
    return {"ok": True, "provider": orch.provider.name, "model": orch.provider.model,
            "configs": config_store.public_configs(configs)}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request, file: UploadFile = File(...),
                  mode: str = Form("local"), scope: str = Form("world"),
                  ):

    orch: Orchestrator = _get_orchestrator(request)

    # 预热中：本地模型未就绪，拒绝上传（避免任务排队卡住）
    from ..main import APP_READY, WARMUP_ELAPSED
    if not APP_READY:
        raise HTTPException(
            status_code=503,
            detail=f"本地模型预热中（已耗时 {WARMUP_ELAPSED:.0f}s），请稍候再上传",
        )

    # 未配置 Key：仅"云端 LLM 定城市"需要；本地 CLIP 城市引擎（clip）纯本地可无 key
    if not settings.llm_api_key and settings.local_city_engine == "llm":
        raise HTTPException(status_code=503, detail="云端 LLM 定城市需要 API Key：请先在设置页填写，或切到「本地 CLIP-B/16」城市引擎")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb}MB 限制")

    valid_modes = set(ANALYZE_MODES.keys())
    mode = mode.lower() if mode.lower() in valid_modes else settings.analyze_mode
    scope = scope if scope in ("world", "no-cn", "cn") else "world"
    task_id = orch.submit(data, file.filename or "upload.jpg", mode=mode, scope=scope)
    return AnalyzeResponse(task_id=task_id)


@router.get("/tasks/{task_id}", response_model=TaskQueryResponse)
async def get_task(task_id: str, request: Request):
    store: TaskStore = _get_store(request)
    result: TaskResult | None = store.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return TaskQueryResponse(task=result)


@router.get("/tasks")
async def list_tasks(request: Request):
    store: TaskStore = _get_store(request)
    return {"tasks": [t.model_dump(mode="json") for t in store.list_recent(50)]}


@router.post("/tasks/{task_id}/feedback")
async def submit_feedback(task_id: str, request: Request,
                          satisfaction: str = Form(""),
                          correct_lat: str = Form(""),
                          correct_lon: str = Form("")):
    """用户反馈：满意度评分 + 可选正确标注"""
    store: TaskStore = _get_store(request)
    result: TaskResult | None = store.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    import json
    from pathlib import Path
    fb_dir = settings.data_dir / "feedback"
    fb_dir.mkdir(exist_ok=True)
    fb = {
        "task_id": task_id,
        "filename": result.filename,
        "satisfaction": int(satisfaction) if satisfaction.isdigit() else 0,  # 1-5 星
        "predicted": result.candidates[0].country if result.candidates else None,
        "correct_lat": float(correct_lat) if correct_lat else None,
        "correct_lon": float(correct_lon) if correct_lon else None,
        "scope": result.meta.get("scope"),
        "timestamp": time.time(),
    }
    fb_path = fb_dir / f"{task_id}.json"
    fb_path.write_text(json.dumps(fb, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "message": "反馈已保存", "path": str(fb_path)}


@router.post("/tasks/{task_id}/retry", response_model=AnalyzeResponse)
async def retry_task(task_id: str, request: Request,
                     mode: str = Form(""), scope: str = Form("")):
    """失败/降级任务一键重试：用保存的原图重新分析（无需重新上传）。

    mode/scope 不传时沿用原任务的设置。
    """
    orch: Orchestrator = _get_orchestrator(request)
    store: TaskStore = _get_store(request)
    old = store.get(task_id)
    if old is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    if not old.has_image:
        raise HTTPException(status_code=400, detail="该任务未保存原图，无法重试，请重新上传")
    data = _load_uploaded_image(task_id)
    if data is None:
        raise HTTPException(status_code=400, detail="原图文件已丢失，无法重试，请重新上传")
    new_mode = mode if mode.lower() in ANALYZE_MODES else old.mode
    new_scope = scope if scope in ("world", "no-cn") else old.meta.get("scope", "world")  # cn 已移除
    new_id = orch.submit(data, old.filename or "retry.jpg", mode=new_mode, scope=new_scope)
    return AnalyzeResponse(task_id=new_id)


def _load_uploaded_image(task_id: str) -> Optional[bytes]:
    """按任务 id 读取保存的原图字节（扩展名不固定，按前缀匹配）。"""
    for p in settings.upload_dir.glob(f"{task_id}.*"):
        try:
            return p.read_bytes()
        except OSError:
            return None
    return None


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    """B6：删除任务记录。"""
    store: TaskStore = _get_store(request)
    if not store.delete(task_id):
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return {"ok": True}


@router.get("/tasks/{task_id}/export")
async def export_task(task_id: str, request: Request, format: str = "geojson"):
    """B5：导出候选点为 GeoJSON / KML / CSV。"""
    store: TaskStore = _get_store(request)
    result = store.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    if format not in ("geojson", "kml", "csv"):
        raise HTTPException(status_code=400, detail="format 仅支持 geojson/kml/csv")
    return await _build_export(result, format)


async def _build_export(result: TaskResult, format: str):
    from fastapi.responses import PlainTextResponse

    cands = sorted(result.candidates, key=lambda c: -c.score)
    if format == "geojson":
        features = []
        for c in cands:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [c.lon, c.lat]},
                "properties": {
                    "rank": c.rank, "city": c.city_zh or c.city, "source": c.source,
                    "score": c.score, "accuracy_hint": c.accuracy_hint,
                    "evidence": c.evidence, "thumbnail": c.thumbnail_url,
                },
            })
        body = json.dumps({"type": "FeatureCollection", "features": features},
                          ensure_ascii=False, indent=1)
        media = "application/geo+json"
        fname = f"{task_name(result)}.geojson"
    elif format == "kml":
        placemarks = []
        for c in cands:
            placemarks.append(f"""  <Placemark>
    <name>{escape_xml(c.city_zh or c.city or '候选')}</name>
    <description>来源:{c.source} 得分:{c.score:.2f} {escape_xml(c.accuracy_hint or '')}</description>
    <Point><coordinates>{c.lon},{c.lat},0</coordinates></Point>
  </Placemark>""")
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n'
                "<Document>\n" + "\n".join(placemarks) + "\n</Document>\n</kml>")
        media = "application/vnd.google-earth.kml+xml"
        fname = f"{task_name(result)}.kml"
    else:  # csv
        import io as _io

        buf = _io.StringIO()
        buf.write("rank,city,source,score,lat,lon,accuracy_hint,evidence\n")
        for c in cands:
            ev = " | ".join(c.evidence).replace('"', "'")
            buf.write(f'{c.rank},"{c.city_zh or c.city}",{c.source},{c.score:.3f},'
                      f'{c.lat:.6f},{c.lon:.6f},"{c.accuracy_hint}","{ev}"\n')
        body = buf.getvalue()
        media = "text/csv; charset=utf-8"
        fname = f"{task_name(result)}.csv"
    return PlainTextResponse(body, media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


def task_name(result: TaskResult) -> str:
    return (result.filename or "result").rsplit(".", 1)[0] + f"_{result.task_id[:8]}"


def escape_xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


@router.get("/tasks/{task_id}/wait")
async def wait_task(task_id: str, request: Request, timeout: float = 60.0):
    """阻塞轮询直到任务结束（前端轮询更友好，此接口备用）。"""
    store: TaskStore = _get_store(request)
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = store.get(task_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
        if result.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED):
            return TaskQueryResponse(task=result)
        await asyncio.sleep(0.5)
    return JSONResponse({"task_id": task_id, "status": "timeout"}, status_code=202)
