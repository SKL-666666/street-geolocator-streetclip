"""用户反馈分析：扫描 feedback/ 目录 → 构建混淆矩阵 + 国家先验校正。"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path


def load_feedback(feedback_dir: Path) -> list[dict]:
    """加载所有反馈文件。"""
    results = []
    if not feedback_dir.exists():
        return results
    for f in feedback_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except Exception:
            continue
    return results


def build_confusion_matrix(feedbacks: list[dict]) -> dict:
    """构建预测→正确 的混淆统计。
    返回：{predicted: {correct: count, ...}, ...}
    """
    matrix = defaultdict(lambda: defaultdict(int))
    for fb in feedbacks:
        predicted = fb.get("predicted")
        correct = fb.get("correct_country") or fb.get("correct_lat")  # lat 表示用户选了坐标
        if predicted and correct and isinstance(correct, str):
            matrix[predicted][correct] += 1
    return dict(matrix)


def build_prior_correction(feedbacks: list[dict], min_samples: int = 2) -> dict:
    """从反馈数据构建先验校正值。
    返回：{predicted_country: correction_factor}，factor < 1 表示降权。
    """
    matrix = build_confusion_matrix(feedbacks)
    corrections = {}
    for predicted, corrects in matrix.items():
        total = sum(corrects.values())
        if total < min_samples:
            continue
        # 如果经常被误判（该国被预测 N 次但只有少数被确认正确），降权
        correct_count = corrects.get(predicted, 0)
        error_rate = 1.0 - (correct_count / total) if total > 0 else 0
        if error_rate > 0.5:  # 超过一半是错的 → 降权到 0.7
            corrections[predicted] = 0.7
        elif error_rate > 0.3:  # 超过30%是错的 → 降权到 0.85
            corrections[predicted] = 0.85
    return corrections


def get_feedback_stats(feedback_dir: Path) -> dict:
    """返回反馈统计摘要。"""
    feedbacks = load_feedback(feedback_dir)
    if not feedbacks:
        return {"total": 0, "message": "暂无用户反馈数据"}
    
    good = sum(1 for fb in feedbacks if fb.get("satisfaction", 0) >= 4)
    bad = len(feedbacks) - good
    corrections = sum(1 for fb in feedbacks 
                     if fb.get("correct_lat") or fb.get("correct_country"))
    matrix = build_confusion_matrix(feedbacks)
    top_confusions = []
    for pred, corrects in matrix.items():
        for corr, count in corrects.items():
            if corr != pred and count >= 2:
                top_confusions.append((pred, corr, count))
    top_confusions.sort(key=lambda x: -x[2])
    
    return {
        "total": len(feedbacks),
        "good": good,
        "bad": bad,
        "corrections": corrections,
        "confusion_pairs": top_confusions[:5],
        "prior_corrections": build_prior_correction(feedbacks),
    }
