"""谷歌街景相机代数 → 国家/地区覆盖（GeoGuessr 高判别力线索）。

依据 GeoGuessr 社区总结（2025 街景覆盖与代数）：
- Gen4（最新，色彩鲜明、太阳为光团非圆盘）：主要在北美洲、西欧、大洋洲、东南亚，且覆盖持续扩展
- Gen3（最广）：几乎覆盖所有谷歌街景国家（弱约束，不用于过滤）
- Gen2（模糊、大范围打码圆）：北美/澳大利亚为主；南非是非洲唯一实际有 Gen2 的国家；
  巴西/智利/捷克等仅理论存在
- Gen1（极模糊，已被新街景替换，极其少见）：北美/澳大利亚；墨西哥/新西兰/日本/法国/意大利理论上
- 印度相机（official ari/shitcam：低画质、色彩奇异、太阳过曝核爆状、街景车打码巨大）：
  印度、孟加拉、斯里兰卡、柬埔寨、尼日利亚、美国、芬兰、厄瓜多尔等
- 港澳台特殊：香港=百度+腾讯+谷歌、澳门=百度+腾讯、台湾=谷歌

使用方式：LLM 识别出明显相机特征（打码/光团/核爆太阳/模糊圆）时，引擎据此
对候选国家加权/降权；普通画质（手机街拍等非街景车照片）不启用此维度。
国家名与 countries.py（180 国）对齐。
"""
from __future__ import annotations

# {代数: [国家规范名]} —— 按用户提供资料整理的覆盖区（Gen4/Gen2 为主要约束）
GEN_COUNTRIES: dict[str, list[str]] = {
    # Gen4 覆盖区：北美洲 / 西欧 / 大洋洲 / 东南亚（覆盖持续扩展，作"优先考虑"弱加权）
    "gen4": [
        # 北美洲
        "United States", "Canada",
        # 西欧
        "United Kingdom", "Ireland", "France", "Germany", "Austria", "Switzerland",
        "Netherlands", "Belgium", "Luxembourg", "Spain", "Portugal", "Italy",
        "Denmark", "Sweden", "Norway", "Finland", "Iceland",
        # 大洋洲
        "Australia", "New Zealand",
        # 东南亚
        "Thailand", "Vietnam", "Indonesia", "Philippines", "Malaysia", "Singapore",
        # 中东/东亚部分（用户未列，保守不加）
    ],
    # Gen2：北美/澳大利亚为主；南非是非洲唯一实际有 Gen2 的国家
    "gen2": [
        "United States", "Canada", "Australia",
        "South Africa",      # 非洲唯一
        # 理论存在：Brazil / Chile / Czechia 等（弱，不加）
    ],
    # Gen1：极罕见，已被新街景替换
    "gen1": [
        "United States", "Canada", "Australia",
        # 理论上：Mexico / New Zealand / Japan / France / Italy（弱）
    ],
    # 印度相机（official ari）：低画质、巨大打码、核爆太阳
    "indian": [
        "India", "Bangladesh", "Sri Lanka", "Cambodia", "Nigeria",
        "United States", "Finland", "Ecuador",
        # Sao Tome and Principe 不在 180 国库（跳过）
    ],
    # 4代"小相机"（smallcam，安装更低、大圆形打码前有突起、打码可透明）：
    # 印度 4 代全部、法国 4 代、加拿大/美国部分 4 代、阿根廷/巴西/秘鲁 4 代
    "smallcam": [
        "India", "France", "Canada", "United States",
        "Argentina", "Brazil", "Peru",
    ],
    # "低相机"（全境低机位、打码模糊更大、路显更宽）：日本全境、瑞士（全码）、
    # 列支敦士登全 4 代低相机、斯里兰卡 4 代低相机
    "lowcam": [
        "Japan", "Switzerland", "Liechtenstein", "Sri Lanka",
    ],
    # 俄罗斯三代街景车：黑色/白色、带长天线（打码全车者为短天线）
    "antenna_car": [
        "Russia",
    ],
}

# 特征关键词 → 代数（engine 从 scene 文本推断）
GEN_KEYWORDS: dict[str, list[str]] = {
    "indian": ["印度相机", "巨大打码", "核爆", "过曝", "低画质", "色彩奇异", "ari", "shitcam", "棕色调"],
    "gen2": ["gen2", "gen 2", "大范围打码", "打码圆", "模糊圆", "二代相机", "彩色变色"],
    "gen4": ["gen4", "gen 4", "光团", "色彩鲜明", "四代相机", "鲜艳", "太阳光团"],
    "gen1": ["gen1", "gen 1", "极模糊", "一代相机", "第一代"],
    "smallcam": ["小相机", "大圆形打码", "大圆打码", "前方突起", "打码前突起"],
    "lowcam": ["低相机", "低机位", "打码模糊更大", "路显更宽"],
    "antenna_car": ["长天线街景车", "带天线街景车", "长天线"],
}
