"""B3：时区 + 昼夜交叉校验（EXIF 拍摄时间 vs 候选时区 vs 场景光照描述）。

仅在有 EXIF 时间且场景包含明确昼夜描述时生效；证据不足则跳过。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..schemas import Candidate, SceneAnalysis
from ..tools import timezone as tzmod

NIGHT_HOURS = (22, 23, 0, 1, 2, 3, 4)
DAY_HOURS = (9, 10, 11, 12, 13, 14, 15, 16, 17)
NIGHT_WORDS = ("夜晚", "夜间", "夜景", "黑夜", "night", "evening", "dusk", "dark")
DAY_WORDS = ("晴", "白天", "日照", "阳光", "sunny", "daylight", "morning", "afternoon", "noon")


def parse_captured(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.fromisoformat(str(raw)[:19].replace(":", "-", 2))
        except ValueError:
            return None


def _scene_period(scene: SceneAnalysis) -> str | None:
    text = " ".join(scene.weather + scene.unique_features + [scene.summary or ""]).lower()
    if any(w in text for w in NIGHT_WORDS):
        return "night"
    if any(w in text for w in DAY_WORDS):
        return "day"
    return None


def apply_sun_check(candidates: list[Candidate], scene: SceneAnalysis,
                    captured_at: str | None) -> None:
    """对每个候选：本地时间与场景昼夜描述比对，矛盾降权、一致升权。"""
    dt = parse_captured(captured_at)
    if dt is None:
        return
    period = _scene_period(scene)
    if period is None:
        return
    for c in candidates:
        tz_name = tzmod.timezone_at(c.lat, c.lon)
        if tz_name is None:
            continue
        try:
            local = dt.astimezone(timezone.utc).astimezone(
                __import__("zoneinfo").ZoneInfo(tz_name))
        except Exception:
            continue
        hour = local.hour
        if period == "night" and hour in DAY_HOURS:
            c.score *= 0.8
            c.evidence.append(f"☀️ 昼夜矛盾：照片为夜晚场景，但该候选地本地时间为 {hour}:00 白天")
        elif period == "day" and hour in NIGHT_HOURS:
            c.score *= 0.8
            c.evidence.append(f"🌙 昼夜矛盾：照片为白天场景，但该候选地本地时间为 {hour}:00 深夜")
        elif (period == "day" and hour in DAY_HOURS) or (period == "night" and hour in NIGHT_HOURS):
            c.score = min(0.99, c.score * 1.05)
            c.evidence.append(f"🕐 昼夜一致：本地时间 {hour}:00 与场景吻合")
