"""Agentic 工具层（方案 D）：地理编码 / Wikipedia 查证 / 时区。

所有工具都是可选的、可插拔的：失败一律优雅降级（返回空结果），
绝不让外部服务故障拖垮整个分析管线。
"""
from __future__ import annotations


class ToolNetworkError(Exception):
    """网络级失败（连接/超时）：触发"网络已断"快速跳过，后续任务不再调用工具。"""
