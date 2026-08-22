"""从模型输出中稳健地提取 JSON（各家模型输出格式五花八门）。"""
from __future__ import annotations

import json
import re
from typing import Any


class JSONParseError(ValueError):
    pass


def _strip_comments(text: str) -> str:
    """剥离字符串字面量之外的 // 与 # 行注释（容忍模型输出的注释）。"""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    quote = ""
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_json(text: str) -> dict[str, Any]:
    """尝试多种方式从模型文本中提取 JSON 对象。"""
    if not text or not text.strip():
        raise JSONParseError("模型输出为空")

    t = text.strip()

    # 1) 去掉 markdown 代码围栏
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\s*```$", "", t, flags=re.MULTILINE)

    # 2) 直接解析
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 3) 截取第一个 { 到最后一个 }（容忍前后废话/注释行）
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        candidate = t[start : end + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 4) 剥离注释（含行内）、容忍尾逗号后再试一次
    cleaned = _strip_comments(t)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    raise JSONParseError(f"无法从模型输出中提取 JSON：{text[:200]}…")
