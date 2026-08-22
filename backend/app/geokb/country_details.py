"""国家细节线索库（依据 GeoGuessr"各大国第一步识别"教程整理，12 国高判别细节）。

结构与 countries.py 的关键词表一致，但用**中文关键词**（LLM 场景字段多为中文输出）：
{中文关键词: [国家规范名]}

覆盖维度：车牌样式、路桩、护栏/标线、交通标志、独有物件/连锁、语言文本铁证。
引擎（engine.py 步骤11）在 traffic_signs + unique_features + architecture + visible_text
合并文本中做子串匹配，命中即对该国家弱-中加权（权重 1.5，佐证级，不单点锁定）。

多国共享样式（如"双黄线"美加巴阿、"蓝底白箭头"法意西）按教程原意收录，
命中后由交叉验证决定权重。国家名与 countries.py（180 国）对齐。
"""
from __future__ import annotations

DETAIL_KEYWORDS: dict[str, list[str]] = {
    # ================= 印度 =================
    "白色长车牌": ["India"],
    "长车牌": ["India"],
    "黑白条纹路标杆": ["India", "Bangladesh", "Sri Lanka"],
    # ================= 印度尼西亚 =================
    "黑底白字车牌": ["Indonesia", "Malaysia"],
    "红白幅旗": ["Indonesia"],
    "幅旗": ["Indonesia"],
    "香烟广告": ["Indonesia"],
    "peringatan": ["Indonesia"],
    "摩托车前牌照": ["Indonesia"],
    "前牌照": ["Indonesia"],
    "Rp": ["Indonesia"],
    "印尼盾": ["Indonesia"],
    "黄色里程碑": ["Indonesia"],
    "英式路桩": ["Indonesia", "United Kingdom"],
    # ================= 日本 =================
    "绿字车牌": ["Japan"],
    "白色短车牌": ["Japan"],
    "轻型车黄牌": ["Japan"],
    "六边形路号": ["Japan"],
    "六边形盾徽": ["Japan"],
    "交通镜": ["Japan"],
    "挡土墙": ["Japan"],
    # ================= 法国 =================
    "长白牌": ["France"],
    "黄色道路编号牌": ["France"],
    "D开头路牌": ["France"],
    "蓝底白箭头": ["France", "Italy", "Spain"],
    "双白块虚线": ["France"],
    "长间隔虚线": ["France", "United Kingdom"],
    "五条纹人行横道": ["France", "Italy"],
    "扁平标志杆": ["France", "Portugal", "Spain", "Italy"],
    "蓝色门牌": ["France"],
    "奥地利国旗配色": ["France"],
    "标致": ["France"],
    "雷诺": ["France"],
    "雪铁龙": ["France"],
    # ================= 德国 =================
    "Einbahn": ["Germany"],
    "黄绿H": ["Germany"],
    "黄色邮箱": ["Germany"],
    "蓝色公里标": ["Germany"],
    "黑色牌背": ["Germany", "Italy", "Romania", "Albania"],
    "绿标贴纸": ["Germany"],
    "风力涡轮机": ["Germany"],
    # ================= 意大利 =================
    "短前牌": ["Italy"],
    "三角路桩": ["Italy", "Albania"],
    "双层护栏": ["Italy"],
    "红色反光板": ["Italy", "Australia"],
    "护栏末端外弯": ["Italy"],
    "黑底白箭头": ["Italy", "Spain", "Greece", "Albania"],
    "白底蓝边": ["Italy"],
    "passo carrabile": ["Italy"],
    # ================= 俄罗斯 =================
    "全白车牌": ["Russia"],
    "无蓝条车牌": ["Russia"],
    "黑顶红反光镜": ["Russia"],
    "宽阔路口": ["Russia"],
    "底部涂黑": ["Russia"],
    "三条斑马线": ["Russia", "Ukraine", "Lithuania", "Mongolia", "Kyrgyzstan"],
    "黄白条纹人行横道": ["Russia"],
    "黑白条纹护栏": ["Russia"],
    "混凝土公寓楼": ["Russia", "Ukraine", "Belarus"],
    "华丽窗框": ["Russia"],
    # ================= 加拿大 =================
    "菱形丁字路口": ["Canada"],
    "MAXIMUM": ["Canada"],
    "单黄线": ["Canada"],
    "加拿大邮政": ["Canada"],
    "红色邮政": ["Canada"],
    # ================= 美国 =================
    "SPEED LIMIT": ["United States"],
    "NO PASSING": ["United States"],
    "YIELD": ["United States"],
    "ONE WAY": ["United States"],
    "橙白光缆": ["United States"],
    "橙色路障桶": ["United States"],
    "隆起标线": ["United States"],
    "双黄线": ["United States", "Canada", "Brazil", "Argentina"],
    "移动房车": ["United States"],
    "浸信会教堂": ["United States"],
    "Taco Bell": ["United States"],
    "Wendy's": ["United States"],
    "Dunkin": ["United States"],
    "Exxon": ["United States"],
    "长鼻卡车": ["United States", "Canada"],
    # ================= 澳大利亚 =================
    "桉树": ["Australia"],
    "振动带": ["Australia", "New Zealand"],
    "白底红圈限速": ["Australia"],
    # ================= 阿根廷 =================
    "黑点车牌": ["Argentina"],
    "顶部蓝条": ["Argentina", "Brazil"],
    "白底红箭头": ["Argentina"],
    "黄红反光片": ["Argentina", "Uruguay"],
    "开阔荒凉": ["Argentina"],
    # ================= 巴西 =================
    "红色车牌": ["Brazil"],
    "黑底黄箭头": ["Brazil"],
    "蓝色路标": ["Brazil"],
    "白色路缘石": ["Brazil"],
    "透明卫星锅": ["Brazil"],
    "FORTLEV": ["Brazil"],
    "蓝色水箱": ["Brazil"],
    "橙色瓦片": ["Brazil", "Italy", "Spain", "Portugal"],
}
