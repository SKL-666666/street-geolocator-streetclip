"""街景地理位置分析工具 — FastAPI 入口。"""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import settings
from .pipeline.orchestrator import Orchestrator
from .storage import TaskStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("street-geolocator")

# 就绪状态：预热完成前为 False（期间拒绝上传分析；health 返回 warming_up）
APP_READY = False
# 预热耗时（秒），供前端提示"预热中"
WARMUP_ELAPSED = 0.0


def _ensure_frozen_data() -> None:
    """打包版首启：把 _internal 里的只读数据复制到 exe 同目录 data/（不存在时）。

    geokb.sqlite 不需要复制（首次加载时从内置种子自动重建）。
    """
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    src = Path(meipass)
    dst = settings.data_dir
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("prior_gallery", "index"):
        s = src / name
        d = dst / name
        if s.exists() and not d.exists():
            try:
                if s.is_dir():
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
                logger.info("已初始化数据目录：%s", name)
            except OSError as e:  # noqa: BLE001
                logger.warning("数据目录复制失败（%s）：%s", name, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global APP_READY, WARMUP_ELAPSED
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    _ensure_frozen_data()
    app.state.store = TaskStore(settings.tasks_db)
    app.state.orchestrator = Orchestrator(app.state.store)
    # 后台预热：本地模型加载（StreetCLIP ~15-25s，首次含权重读取）+ 工具网络探测（~3s）。
    # 预热完成前 APP_READY=False，analyze 接口拒绝上传（503），避免用户任务排队卡住。
    warmup = asyncio.create_task(_warmup())
    logger.info(
        "后端就绪 provider=%s model=%s mapillary=%s（预热中，期间禁止上传）",
        app.state.orchestrator.provider.name,
        app.state.orchestrator.provider.model,
        bool(settings.mapillary_token),
    )
    yield
    warmup.cancel()
    APP_READY = False
    logger.info("后端关闭")


async def _warmup() -> None:
    """预热本地模型与工具层连通性（全部静默失败，不影响启动）；完成后置 APP_READY=True。"""
    global APP_READY, WARMUP_ELAPSED
    import asyncio

    _t0 = time.monotonic()

    async def _local_model():
        # 本地免费模式（StreetCLIP）后台预加载：首次用户调用免等 ~20s
        try:
            from .geokb.local_engine import _load_engine
            await asyncio.to_thread(_load_engine)
            logger.info("本地模型已预加载")
        except Exception:
            pass  # 加载失败不阻塞启动；用户用时按需加载

    async def _tools_probe():
        try:
            from .tools import ToolNetworkError
            from .tools import geocode as geo
            results = await geo.geocode("London", timeout=3.0)
            # "London" 必然可解析；空结果说明服务异常/被墙 → 同样跳过
            if not results:
                raise ToolNetworkError("探测无结果")
        except ToolNetworkError:
            from .pipeline.tools_pass import mark_tools_broken
            mark_tools_broken()
            logger.info("工具层网络不可达，本会话自动跳过外部查证")
        except Exception:
            pass

    await asyncio.gather(_local_model(), _tools_probe(), return_exceptions=True)
    WARMUP_ELAPSED = round(time.monotonic() - _t0, 1)
    APP_READY = True
    logger.info("预热完成：本地模型就绪（耗时 %.1fs），开放上传", WARMUP_ELAPSED)


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# 托管前端构建产物（存在时）：生产模式一个服务搞定
dist: Path = settings.frontend_dist
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")


@app.get("/", include_in_schema=False)
async def root():
    return {"app": settings.app_name, "docs": "/docs", "api": "/api/health"}
