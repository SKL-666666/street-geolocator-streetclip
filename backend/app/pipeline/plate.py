"""车牌样式识别：OCR 检测到的文本 → 车牌国家代码映射。"""
from __future__ import annotations

import re

# 车牌前缀/后缀 → 国家（欧洲车牌、亚洲车牌等）
PLATE_COUNTRY = {
    # 欧洲车牌后缀
    "F": "France", "D": "Germany", "I": "Italy", "E": "Spain", "A": "Austria",
    "CH": "Switzerland", "NL": "Netherlands", "B": "Belgium", "P": "Portugal",
    "GB": "United Kingdom", "S": "Sweden", "N": "Norway", "DK": "Denmark",
    "FIN": "Finland", "PL": "Poland", "CZ": "Czechia", "H": "Hungary",
    "RO": "Romania", "BG": "Bulgaria", "HR": "Croatia", "GR": "Greece",
    "TR": "Turkey", "UA": "Ukraine", "RUS": "Russia", "BY": "Belarus",
    "LT": "Lithuania", "LV": "Latvia", "EST": "Estonia", "SRB": "Serbia",
    # 亚洲
    "J": "Japan", "ROK": "South Korea", "IND": "India", "THA": "Thailand",
    "V": "Vietnam", "MAL": "Malaysia", "RI": "Indonesia",
    # 美洲
    "USA": "United States", "CDN": "Canada", "MEX": "Mexico", "BR": "Brazil",
    "RA": "Argentina", "RCH": "Chile", "CO": "Colombia", "PE": "Peru",
    # 非洲
    "ZAF": "South Africa", "KEN": "Kenya", "ET": "Ethiopia", "MA": "Morocco",
}

# 车牌颜色特征（需结合 OCR 置信度判断）
PLATE_STYLE_CLUES = {
    # 欧盟蓝色条（左侧蓝条 + 字母数字）
    "blue_stripe_eu": {"hint": "欧盟车牌", "countries": ["France", "Germany", "Italy", "Spain", "Austria", "Poland", "Czechia", "Hungary"]},
    # 黄色底（英国/荷兰/卢森堡）
    "yellow_plate": {"hint": "黄底车牌", "countries": ["United Kingdom", "Netherlands", "Luxembourg"]},
    # 白色底（美国/加拿大/日本）
    "white_plate": {"hint": "白底车牌", "countries": ["United States", "Canada", "Japan"]},
}


def detect_plate_country(ocr_texts: list[str]) -> dict:
    """从 OCR 文本中检测车牌国家代码。"""
    results = []
    for text in ocr_texts:
        # 清理文本（去除特殊字符）
        clean = re.sub(r'[^A-Za-z0-9]', '', text.upper())
        if len(clean) < 2:
            continue

        # 匹配已知车牌前缀/后缀
        for code, country in PLATE_COUNTRY.items():
            if clean.startswith(code) or clean.endswith(code):
                results.append({
                    "code": code,
                    "country": country,
                    "original": text,
                    "confidence": 0.7 if len(code) >= 3 else 0.5,  # 长代码更可信
                })

    if not results:
        return {"detected": False}

    # 返回最可信的结果
    best = max(results, key=lambda x: x["confidence"])
    return {
        "detected": True,
        "code": best["code"],
        "country": best["country"],
        "original": best["original"],
        "confidence": best["confidence"],
    }
