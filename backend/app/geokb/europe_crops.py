"""欧洲作物分布 + WRB 土壤类型（GeoGuessr 乡村/田野场景辅助线索）。

依据 GeoGuessr 社区"欧洲地理总论"整理：
- 作物 → 种植国家（英国/挪威为主，茶/甘蔗特殊）
- 作物形态 → 识别关键词（scene 农田/植被文本匹配）
- WRB 土壤类型 → 关键词 + 区域国家（黑土→欧亚草原等）

使用注意（来源作者原话）：官方街景模糊难判断；图寻街景视角固定不适合植物识别；
有人文地点优先用人文知识。因此本维度仅作**乡村/田野场景的弱辅助线索**。

国家名与 countries.py（180 国）对齐。
"""
from __future__ import annotations

# 作物 → 种植国家（用户资料；英国/挪威东南部最盛）
CROP_COUNTRIES: dict[str, list[str]] = {
    "小麦": ["United Kingdom", "Norway"],
    "大麦": ["United Kingdom", "Norway"],
    "玉米": ["United Kingdom", "Norway"],
    "土豆": ["United Kingdom", "Norway", "Ireland", "France", "Germany", "Poland", "Belarus"],
    "甜菜": ["United Kingdom", "Norway", "France", "Germany", "Poland", "Ukraine", "Russia"],
    "大豆": ["United Kingdom", "Italy", "Serbia", "Croatia"],
    "向日葵": ["United Kingdom", "Ukraine", "Russia", "Romania", "Bulgaria", "Hungary"],
    "高粱": ["Spain", "Portugal", "Italy"],
    "甘蔗": ["Spain", "Portugal"],
    "棉花": ["Greece", "Spain", "Turkey"],
    "茶": ["Belgium", "France", "Germany", "Italy", "Montenegro", "Portugal",
           "Spain", "Sweden", "Switzerland", "Ukraine", "United Kingdom", "Ireland"],
    "水稻": ["Italy", "Spain", "Portugal", "Greece"],
}

# 作物形态 → 识别关键词（scene 植被/农田文本匹配；中文为主）
CROP_KEYWORDS: dict[str, list[str]] = {
    "小麦": ["麦田", "金色麦浪", "麦穗", "细茎长穗", "短芒", "wheat"],
    "大麦": ["大麦", "barley", "麦田"],
    "玉米": ["玉米", "玉米田", "corn", "maize"],
    "土豆": ["土豆", "马铃薯", "低矮卵形叶", "白花", "蓝紫花", "potato"],
    "甜菜": ["甜菜", "皱缩光泽叶", "叶脉突出", "sugar beet", "beet"],
    "大豆": ["大豆", "近圆豆科叶", "soybean", "soy"],
    "向日葵": ["向日葵", "sunflower", "黄色大花盘"],
    "高粱": ["高粱", "火红", "sorghum", "穗红"],
    "甘蔗": ["甘蔗", "sugarcane", "蔗田"],
    "棉花": ["棉花", "cotton", "阔卵三裂叶"],
    "茶": ["茶园", "茶叶", "革质叶", "tea plantation", "tea"],
    "水稻": ["水稻", "稻田", "paddy", "rice field"],
}

# WRB 土壤类型 → 关键词 + 区域国家（选判别力强的；弱辅助）
SOIL_TYPES: dict[str, dict] = {
    "Chernozem": {"kw": ["黑土", "黑钙土"], "countries": ["Ukraine", "Russia", "Hungary", "Romania", "Bulgaria", "Serbia", "Moldova"]},
    "Podzol": {"kw": ["灰化土", "针叶林土壤", "酸性沙壤"], "countries": ["Norway", "Sweden", "Finland", "Russia", "Canada"]},
    "Luvisol": {"kw": ["肥沃黏土", "温带农业土"], "countries": ["France", "Germany", "United Kingdom", "Poland", "Denmark"]},
    "Calcisol": {"kw": ["钙质土", "石灰性土"], "countries": ["Spain", "Greece", "Turkey", "Iran", "Tunisia"]},
    "Andosol": {"kw": ["火山土", "火山灰土"], "countries": ["Iceland", "Italy", "Japan", "Indonesia", "Ecuador", "Costa Rica"]},
    "Arenosol": {"kw": ["砂土", "沙质土"], "countries": ["Saudi Arabia", "Namibia", "Australia", "Morocco", "Egypt"]},
    "Kastanozem": {"kw": ["栗钙土"], "countries": ["Russia", "Kazakhstan", "Mongolia", "Turkey"]},
    "Histosol": {"kw": ["泥炭土", "沼泽土"], "countries": ["Ireland", "Finland", "Sweden", "Russia", "Indonesia"]},
    "Vertisol": {"kw": ["膨胀黏土", "龟裂土"], "countries": ["India", "Australia", "Sudan", "Ethiopia"]},
    "Fluvisol": {"kw": ["冲积土", "河漫滩土"], "countries": ["Egypt", "Bangladesh", "Netherlands", "China", "India"]},
    "Gleysol": {"kw": ["潜育土", "地下水土"], "countries": ["Netherlands", "Russia", "Poland"]},
    "Cryosol": {"kw": ["冻土"], "countries": ["Russia", "Canada", "Greenland"]},
}
