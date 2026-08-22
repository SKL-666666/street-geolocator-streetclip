"""Pydantic 数据模型：任务、分析结果、API 请求/响应。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------- LLM 线索分析 ----------

class CountryHypothesis(BaseModel):
    country: str
    country_zh: str = ""            # 中文名（后端映射填充）
    reasoning: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class CityHypothesis(BaseModel):
    city: str
    country: str = ""
    country_zh: str = ""            # 国家中文名
    lat: Optional[float] = None     # LLM 估算经纬度（未收录城市用）
    lon: Optional[float] = None
    reasoning: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class SceneAnalysis(BaseModel):
    """Prompt A 的结构化输出。"""
    is_street_view: bool = True
    scene_type: str = "street"          # street / indoor / closeup / sky / unknown
    visible_text: list[str] = []
    languages: list[str] = []
    scripts: list[str] = []              # 文字体系：Latin/Cyrillic/Greek/Arabic/Hebrew/Chinese/Hangul/Thai
    traffic_signs: list[str] = []
    architecture: list[str] = []
    vegetation: list[str] = []
    terrain: list[str] = []
    weather: list[str] = []
    soil: list[str] = []                 # 土壤颜色（红土/黑土/黄土/砂土等）
    sun_shadow: str = ""                 # 太阳位置与阴影方向（推断南北半球，如"阴影朝北"）
    image_quality: str = ""              # 画质/街景相机特征（Gen4 鲜明光团/Gen2 大范围打码圆/印度相机低画质核爆太阳/正常）
    pole: str = ""                       # 电线杆特征描述（材质/杆顶形状/绝缘子排列/贴纸涂漆，见铁律6h；无电线杆为空）
    driving_side: str = "unknown"       # left / right / unknown
    tokens: dict = Field(default_factory=lambda: {"prompt": 0, "completion": 0, "calls": 0})  # LLM token 消耗统计
    unique_features: list[str] = []
    country_hypotheses: list[CountryHypothesis] = []
    city_hypotheses: list[CityHypothesis] = []
    overall_confidence: float = 0.0
    summary: str = ""
    raw_output: str = ""


# ---------- GPS / 候选点 ----------

class GPSCoord(BaseModel):
    lat: float
    lon: float
    altitude_m: Optional[float] = None
    source: str = "exif"                # exif / llm / retrieval
    captured_at: Optional[str] = None


class Candidate(BaseModel):
    rank: int
    lat: float
    lon: float
    distance_m: Optional[float] = None
    score: float = 0.0                  # 0~1 相似度/置信度
    source: str = "llm"                 # llm / retrieval / streetview / geocode / prior / country / exif
    city: str = ""                      # 城市名（国家级兜底=首都）
    city_zh: str = ""                   # 城市中文名
    country: str = ""                   # 国家名（英文规范名）
    country_zh: str = ""                # 国家中文名
    accuracy_hint: str = ""             # 准确度提示（国家级/城市级/精确）
    evidence: list[str] = []
    thumbnail_url: str = ""
    image_url: str = ""


# ---------- 地理事实知识库（方案 B）----------

class KBEvidence(BaseModel):
    """单个国家的事实核查结果（证据矩阵的一行）。"""
    country: str
    country_zh: str = ""            # 中文名（前端展示用）
    llm_confidence: float = 0.0         # LLM 假设置信度（无则 0）
    kb_score: float = 0.0               # 知识库交叉筛选得分（0~1）
    final_score: float = 0.0            # 融合后得分（0~1）
    unverified: bool = False            # 不在知识库中，LLM 声称无法核实（降信）
    supporting_clues: list[str] = []
    contradicting_clues: list[str] = []


class GeoKBResult(BaseModel):
    countries: list[KBEvidence] = []
    method: str = "cross-filter"        # 线索交叉筛选


# ---------- Agentic 工具查证（方案 D）----------

class ToolFact(BaseModel):
    tool: str                           # geocode / wiki / timezone / streetview
    query: str
    summary: str = ""
    results: list[dict[str, Any]] = []
    ok: bool = True


# ---------- 任务 ----------

class TaskStatus(str):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TaskResult(BaseModel):
    """单图分析的完整结果。"""
    task_id: str
    status: str = TaskStatus.PENDING
    progress: int = 0                   # 0~100
    stage: str = "queued"               # exif / scene / geokb / tools / streetview / done / failed
    message: str = ""
    error: Optional[str] = None

    filename: str = ""
    has_image: bool = False             # 是否保存了原图（失败/降级后可一键重试）
    gps: Optional[GPSCoord] = None      # EXIF 直读（快路径）
    scene: Optional[SceneAnalysis] = None
    geo_kb: Optional[GeoKBResult] = None   # 方案 B：事实核查证据矩阵
    facts: list[ToolFact] = []             # 方案 D：外部工具查证记录
    candidates: list[Candidate] = []
    confidence_level: str = "unknown"   # none / country / city / street / exact
    mode: str = "balanced"              # fast / balanced / deep
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    elapsed_ms: int = 0
    meta: dict[str, Any] = {}


class AnalyzeResponse(BaseModel):
    task_id: str


class TaskQueryResponse(BaseModel):
    task: TaskResult


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    mapillary: bool
    needs_setup: bool = False
    warming_up: bool = False       # 本地模型预热中（期间禁止上传）
    warmup_elapsed: float = 0.0    # 预热已耗时（秒）
