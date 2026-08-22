"""全局配置：环境变量 + .env 文件（支持 backend/.env 与仓库根 .env）。

打包版（PyInstaller）适配：
- 数据目录（data/）默认位于 exe 同目录（可写，存放任务库与用户 API Key 配置）
- 前端静态资源与只读数据（画廊/索引/权重）打进 _internal（只读）
- 用户通过设置页写入的 API Key 保存在 <data_dir>/llm_key.json，
  启动时优先于 .env / 环境变量（打包分发时每个人填自己的 Key）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
ROOT_DIR = BASE_DIR.parent


def _default_data_dir() -> Path:
    """运行数据目录：打包版用 exe 同目录/data（可写），开发版用 backend/data。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return BASE_DIR / "data"


def _default_frontend_dist() -> Path:
    """前端静态资源：打包版从 _internal/frontend_dist 读（只读），开发版用仓库 dist。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        base = Path(meipass) if meipass else Path(sys.executable).resolve().parent
        return base / "frontend_dist"
    return ROOT_DIR / "frontend" / "dist"


class Settings(BaseSettings):
    # 打包版（frozen）不读 .env：杜绝"分享时误带 .env 导致他人使用开发者 Key"。
    # 打包版只能通过设置页（llm_key.json）配置自己的 Key。
    model_config = SettingsConfigDict(
        env_file=() if getattr(sys, "frozen", False) else (".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 服务 ----
    app_name: str = "Street Geolocator"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ---- LLM 供应商 ----
    # 可选：mock | openai | anthropic | gemini
    # 其他 OpenAI 兼容服务（DeepSeek/通义/智谱/豆包/Moonshot 等）用 openai + 自定义 base_url
    # 默认 openai：未配置 Key 时进入"待配置"状态，由设置页引导填写（不再默认 mock）
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_base_url: str = ""          # openai 兼容服务的 base_url，如 https://api.deepseek.com/v1
    llm_model: str = ""             # 留空时用各供应商默认模型
    llm_timeout_sec: float = 90.0
    # 部分供应商不支持原生 json_schema 结构化输出（如 DeepSeek），
    # 统一走"提示词约束 + 健壮解析 + 失败重试"的通用路径
    llm_retries: int = 1
    # 推理模型（GLM-4.6 系）关闭思考链：速度优先（实测 40s → 数秒）
    llm_disable_thinking: bool = True
    # 两级模型策略：主模型超时则降级到快速模型（硬性耗时保证）
    llm_primary_timeout_sec: float = 12.0   # 主模型单次调用上限（放宽以扛住 GLM 波动）
    llm_fallback_model: str = "glm-4.6v-flashx"  # 降级模型（模式级 fallback_model 未启用时仅作默认）
    llm_fallback_timeout_sec: float = 6.0

    # 缓存 schema 版本：数据结构变更时 +1，旧缓存自动失效
    schema_version: int = 5

    # 默认分析模式（可被 API 的 mode 参数覆盖）：仅 local（本地+云端结合）
    analyze_mode: str = "local"

    # local 模式第二级引擎：clip（本地 CLIP-B/16，免费）/ llm（云端 LLM 猜城市名，要 token）
    local_city_engine: str = "clip"

    # KartaView 街景回查：已关闭（实测不影响定位正确率，仅展示缩略图，且荒野图无图可拉）
    streetview_enabled: bool = False

    # ---- 图像预处理 ----
    max_image_side: int = 1024      # 送 LLM 前最长边压缩（越小越快，实测 1024px 最优）
    jpeg_quality: int = 85

    # ---- 街景数据源 ----
    mapillary_token: str = ""       # 留空则跳过街景回查
    mapillary_radius_m: int = 60    # 候选点回查半径

    # ---- 增强方案开关 ----
    enable_geokb: bool = True       # 方案 B：地理事实库核查
    enable_tools: bool = True       # 方案 D：外部工具查证
    geocoding_base_url: str = "https://nominatim.openstreetmap.org"  # 可换国内可达实例
    wiki_base_url: str = ""         # 留空用 https://{lang}.wikipedia.org

    # ---- 方案 5：MixVPR 本地先验 ----
    enable_prior: bool = True       # 画廊/模型不可用时自动降级
    prior_min_score: float = 0.3    # 低于此相似度不采信（防跨城误判）

    # ---- 缓存（已移除命中机制，保留字段避免配置引用报错）----
    cache_enabled: bool = False     # 已禁用：每次上传都重新分析

    # ---- B 档：并发与缓存治理 ----
    max_concurrent_tasks: int = 3   # 多图批量：3 个并行分析（flashx 平台并发=3，单采样下 3 请求刚好）
    cache_max_tasks: int = 500      # B6：任务保留上限
    cache_ttl_days: int = 30        # B6：任务过期天数

    # ---- 存储 ----
    data_dir: Path = Field(default_factory=_default_data_dir)
    upload_dir: Optional[Path] = None      # 默认 data_dir/uploads（model_post_init 派生）
    tasks_db: Optional[Path] = None        # 默认 data_dir/tasks.json
    llm_key_file: Optional[Path] = None    # 默认 data_dir/llm_key.json（旧版单配置，自动迁移）
    llm_configs_file: Optional[Path] = None  # 默认 data_dir/llm_configs.json（多配置列表）
    max_upload_mb: int = 20

    # ---- 前端 ----
    frontend_dist: Path = Field(default_factory=_default_frontend_dist)

    # ---- 地图源（华为地图瓦片，可配置 key；无 key 前端回退高德）----
    map_tile_url: str = "https://mapapi.cloud.huawei.com/mapapi/tile/v1/?x={x}&y={y}&z={z}&lang=zh&size=1&scale=1&apikey={key}"
    map_api_key: str = ""           # 华为 AppGallery Connect 地图 Key

    # ---- CORS（开发模式前端 5173）----
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    def model_post_init(self, __context) -> None:
        """派生数据目录相关路径。

        注意：激活配置（llm_configs.json）的加载**不能**在这里做——
        本方法在 Settings() 构造期间执行，此时本模块尚未加载完成，
        任何 import config_store（其内部 import settings）都会失败。
        加载放在模块末尾 settings = Settings() 之后。
        """
        if self.upload_dir is None:
            self.upload_dir = self.data_dir / "uploads"
        if self.tasks_db is None:
            self.tasks_db = self.data_dir / "tasks.json"
        if self.llm_key_file is None:
            self.llm_key_file = self.data_dir / "llm_key.json"
        if self.llm_configs_file is None:
            self.llm_configs_file = self.data_dir / "llm_configs.json"


settings = Settings()

# ---- 激活配置加载（必须在 settings 构造完成之后：config_store 依赖 settings）----
try:
    from .llm.config_store import apply_active_to_settings, load_configs

    apply_active_to_settings(load_configs())  # 含旧版 llm_key.json 自动迁移
except Exception:  # noqa: BLE001 - 配置文件损坏不阻塞启动
    pass

# ---- 用户偏好恢复（城市引擎等，本机 prefs.json）----
try:
    import json
    _prefs_path = settings.data_dir / "prefs.json"
    if _prefs_path.exists():
        _prefs = json.loads(_prefs_path.read_text(encoding="utf-8"))
        _city = _prefs.get("local_city_engine", "clip")
        settings.local_city_engine = _city if _city in ("clip", "llm") else "clip"
except Exception:  # noqa: BLE001
    pass


# ---- 分析模式：只保留本地+云端结合（本地判国家 + 云端/本地定城市）----
# 已移除纯云端模式（fast/balanced/deep）与双采样开关（2026-08 需求简化）
ANALYZE_MODES: dict[str, dict] = {
    "local": {
        "label": "本地免费",
        "desc": "本地 StreetCLIP 判国家 + 城市判断引擎（本地 CLIP 或云端 LLM）",
        "image_side": 224,
        "model": "",
        "disable_thinking": False,
        "primary_timeout": 10.0,
        "fallback_timeout": 0.0,
        "fallback_model": "",
        "retries": 0,
        "enable_geokb": False,
        "enable_prior": False,
        "enable_tools": False,
        "enable_verify": False,
        "enable_retrieval": False,
        "samples": 1,
        "streetview_timeout": 0.0,
        "local": True,               # 本地模型通道：不走 LLM，零 API 成本
    },
}


def get_analyze_mode(name: str | None) -> dict:
    """按名称取模式配置（非法名回退默认 local）。"""
    key = (name or settings.analyze_mode).lower()
    return ANALYZE_MODES.get(key, ANALYZE_MODES["local"])
