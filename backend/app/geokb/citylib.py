"""城市工具库：坐标查询 / 中文名 / 最近城市（A2/A3/A5 的统一入口）。

城市表 7100 城（Natural Earth 10m 居民点，按人口排序，覆盖世界所有主要城市）。
为性能，构建一次 fold 索引（重音折叠 → 城市名）。
"""
from __future__ import annotations

import math
import unicodedata

from .cities import CITY_COORDS, CITY_ZH
from .countries import CITY_ALIASES


# ---- 中国主要城市：中文名 → 精确坐标（城市级，误差 ±0.05° 内）----
# 解决城市表两个缺陷：① 表内英文键缺失（沈阳/乌鲁木齐/江苏苏州等）；
# ② 中文同名歧义（"苏州"若走英文键会命中安徽宿州 Suzhou）。
# 中文城市名直查此表优先于任何表/别名逻辑，保证"仅中国大陆"模式城市坐标准确。
_CN_ZH_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
    "成都": (30.5728, 104.0668), "重庆": (29.5630, 106.5516),
    "西安": (34.3416, 108.9398), "杭州": (30.2741, 120.1551),
    "武汉": (30.5928, 114.3055), "南京": (32.0603, 118.7969),
    "天津": (39.3434, 117.3616), "苏州": (31.2989, 120.5853),
    "郑州": (34.7466, 113.6254), "长沙": (28.2282, 112.9388),
    "东莞": (23.0207, 113.7518), "沈阳": (41.8057, 123.4315),
    "青岛": (36.0671, 120.3826), "合肥": (31.8206, 117.2272),
    "佛山": (23.0218, 113.1219), "济南": (36.6512, 117.1201),
    "大连": (38.9140, 121.6147), "福州": (26.0745, 119.2965),
    "昆明": (24.8801, 102.8329), "哈尔滨": (45.8038, 126.5349),
    "长春": (43.8171, 125.3235), "无锡": (31.4912, 120.3119),
    "南昌": (28.6820, 115.8579), "贵阳": (26.6470, 106.6302),
    "南宁": (22.8170, 108.3665), "太原": (37.8706, 112.5489),
    "石家庄": (38.0428, 114.5149), "乌鲁木齐": (43.8256, 87.6168),
    "兰州": (36.0611, 103.8343), "海口": (20.0444, 110.1999),
    "三亚": (18.2528, 109.5119), "厦门": (24.4798, 118.0894),
    "宁波": (29.8683, 121.5440), "温州": (27.9938, 120.6994),
    "烟台": (37.4638, 121.4479), "潍坊": (36.7069, 119.1618),
    "洛阳": (34.6197, 112.4540), "徐州": (34.2044, 117.2857),
    "唐山": (39.6305, 118.1802), "保定": (38.8740, 115.4646),
    "珠海": (22.2707, 113.5767), "汕头": (23.3535, 116.6820),
    "柳州": (24.3264, 109.4150), "桂林": (25.2742, 110.2896),
    "绍兴": (30.0303, 120.5802), "嘉兴": (30.7522, 120.7560),
    "台州": (28.6564, 121.4209), "金华": (29.0784, 119.6473),
    "南通": (31.9802, 120.8943), "常州": (31.8107, 119.9741),
    "扬州": (32.3947, 119.4129), "镇江": (32.1878, 119.4258),
    "泰州": (32.4555, 119.9261), "盐城": (33.3477, 120.1636),
    "连云港": (34.6000, 119.2216), "淮安": (33.6102, 119.0156),
    "邯郸": (36.6256, 114.5391), "邢台": (37.0706, 114.5044),
    "沧州": (38.3039, 116.8388), "廊坊": (39.5378, 116.6840),
    "张家口": (40.7676, 114.8862), "承德": (40.9515, 117.9635),
    "大同": (40.0768, 113.3001), "包头": (40.6574, 109.8403),
    "鄂尔多斯": (39.6088, 109.7813), "呼和浩特": (40.8424, 111.7490),
    "银川": (38.4872, 106.2309), "西宁": (36.6171, 101.7782),
    "拉萨": (29.6520, 91.1721), "鞍山": (41.1076, 122.9935),
    "大庆": (46.5891, 125.1039), "齐齐哈尔": (47.3543, 123.9182),
    "芜湖": (31.3525, 118.4331), "蚌埠": (32.9151, 117.3892),
    "安庆": (30.5240, 117.0636), "黄山": (29.7147, 118.3377),
    "九江": (29.7051, 116.0015), "赣州": (25.8311, 114.9351),
    "宜昌": (30.6920, 111.2865), "襄阳": (32.0090, 112.1224),
    "荆州": (30.3260, 112.2415), "常德": (29.0317, 111.6985),
    "岳阳": (29.3570, 113.1287), "湘潭": (27.8297, 112.9442),
    "株洲": (27.8274, 113.1339), "衡阳": (26.8939, 112.5718),
    "张家界": (29.1174, 110.4792), "惠州": (23.1115, 114.4162),
    "江门": (22.5787, 113.0817), "肇庆": (23.0472, 112.4606),
    "湛江": (21.2707, 110.3594), "中山": (22.5170, 113.3928),
    "潮州": (23.6567, 116.6228), "揭阳": (23.5498, 116.3728),
    "绵阳": (31.4675, 104.6796), "宜宾": (28.7519, 104.6417),
    "泸州": (28.8717, 105.4428), "南充": (30.8373, 106.1107),
    "达州": (31.2095, 107.4680), "乐山": (29.5521, 103.7657),
    "攀枝花": (26.5823, 101.7186), "宿州": (33.6381, 116.9769),
    "六安": (31.7357, 116.5219), "阜阳": (32.8897, 115.8141),
    "滁州": (32.3019, 118.3160), "铜陵": (30.9456, 117.8116),
    "新乡": (35.3030, 113.9268), "安阳": (36.1034, 114.3529),
    "开封": (34.7971, 114.3074), "焦作": (35.2159, 113.2418),
    "平顶山": (33.7458, 113.1926), "南阳": (32.9908, 112.5283),
    "信阳": (32.1469, 114.0919), "商丘": (34.4143, 115.6564),
    "周口": (33.6261, 114.6969), "驻马店": (33.0114, 114.0223),
    "许昌": (34.0357, 113.8520), "漯河": (33.5815, 114.0165),
    "三门峡": (34.7729, 111.2003), "濮阳": (35.7618, 115.0292),
    "济宁": (35.4146, 116.5871), "临沂": (35.1040, 118.3564),
    "菏泽": (35.2336, 115.4810), "聊城": (36.4569, 115.9855),
    "德州": (37.4358, 116.3594), "滨州": (37.3835, 117.9707),
    "东营": (37.4346, 118.6747), "日照": (35.4165, 119.5272),
    "威海": (37.5131, 122.1204), "泰安": (36.2003, 117.0876),
    "淄博": (36.8131, 118.0548), "枣庄": (34.8107, 117.3238),
    "漳州": (24.5134, 117.6474), "泉州": (24.8741, 118.6757),
    "莆田": (25.4540, 119.0078), "三明": (26.2638, 117.6392),
    "南平": (26.6417, 118.1779), "宁德": (26.6657, 119.5476),
    "梧州": (23.4770, 111.2790), "北海": (21.4812, 109.1202),
    "贵港": (23.1115, 109.5980), "玉林": (22.6540, 110.1810),
    "大理": (25.6065, 100.2676), "丽江": (26.8550, 100.2296),
    "曲靖": (25.4897, 103.7964), "玉溪": (24.3550, 102.5430),
    "昭通": (27.3380, 103.7171), "保山": (25.1120, 99.1617),
    "遵义": (27.7257, 106.9272), "六盘水": (26.5924, 104.8304),
    "安顺": (26.2455, 105.9475), "毕节": (27.2830, 105.2915),
    "铜仁": (27.7183, 109.1926), "恩施": (30.2722, 109.4882),
    "十堰": (32.6294, 110.7979), "孝感": (30.9178, 113.9165),
    "黄冈": (30.4460, 114.8723), "咸宁": (29.8414, 114.3226),
    "荆门": (31.0354, 112.1993), "黄石": (30.1995, 115.0389),
    "鄂州": (30.3909, 114.8936), "随州": (31.6901, 113.3826),
    "汉中": (33.0676, 107.0237), "宝鸡": (34.3621, 107.2370),
    "咸阳": (34.3295, 108.7089), "渭南": (34.4994, 109.5098),
    "延安": (36.5853, 109.4898), "榆林": (38.2854, 109.7349),
    "安康": (32.6847, 109.0293), "商洛": (33.8702, 109.9403),
    "天水": (34.5809, 105.7249), "酒泉": (39.7324, 98.4944),
    "张掖": (38.9259, 100.4498), "武威": (37.9282, 102.6380),
    "平凉": (35.5428, 106.6652), "庆阳": (35.7091, 107.6440),
    "喀什": (39.4704, 75.9898), "伊宁": (43.9129, 81.2777),
    "库尔勒": (41.7246, 86.1731), "克拉玛依": (45.5799, 84.8892),
    "哈密": (42.8188, 93.5152), "吐鲁番": (42.9513, 89.1892),
    "石河子": (44.3059, 86.0802), "昌吉": (44.0142, 87.3054),
    "儋州": (19.5209, 109.5808), "琼海": (19.2580, 110.4666),
    "万宁": (18.7962, 110.3893), "五指山": (18.7751, 109.5170),
    "文昌": (19.5434, 110.7538), "东方": (19.0960, 108.6535),
    "定安": (19.6811, 110.3592), "屯昌": (19.3518, 110.1035),
    "澄迈": (19.7385, 110.0072), "陵水": (18.5060, 110.0375),
    "保亭": (18.6392, 109.7024), "琼中": (19.0333, 109.8399),
    "百色": (23.9027, 106.6184), "河池": (24.6926, 108.0854),
    "钦州": (21.9797, 108.6541), "防城港": (21.6869, 108.3538),
    "梧州": (23.4770, 111.2790), "贺州": (24.4038, 111.5664),
    "来宾": (23.7516, 109.2212), "崇左": (22.4040, 107.3647),
}


# ---- 表内中国主要城市：英文键 → 中文名（显示 + 中文文本反向匹配）----
# 与 _CN_ZH_COORDS 互补：此表负责 CITY_COORDS 已有英文键的中文名补全。
_CN_ZH_EXTRA: dict[str, str] = {
    "Nanjing": "南京", "Shenyang": "沈阳", "Dalian": "大连",
    "Harbin": "哈尔滨", "Changchun": "长春", "Jinan": "济南",
    "Qingdao": "青岛", "Xiamen": "厦门", "Fuzhou": "福州",
    "Kunming": "昆明", "Guiyang": "贵阳", "Lanzhou": "兰州",
    "Lhasa": "拉萨", "Haikou": "海口", "Sanya": "三亚",
    "Tangshan": "唐山", "Baoding": "保定", "Jiaxing": "嘉兴",
    "Wenzhou": "温州", "Luoyang": "洛阳", "Xuzhou": "徐州",
    "Yantai": "烟台", "Weihai": "威海", "Nantong": "南通",
    "Changzhou": "常州", "Wuxi": "无锡", "Hefei": "合肥",
    "Nanchang": "南昌", "Zhengzhou": "郑州", "Shijiazhuang": "石家庄",
    "Taiyuan": "太原", "Hohhot": "呼和浩特", "Yinchuan": "银川",
    "Xining": "西宁", "Nanning": "南宁", "Urumqi": "乌鲁木齐",
    "Guiyang": "贵阳", "Jilin": "吉林", "Anshan": "鞍山",
    "Fushun": "抚顺", "Daqing": "大庆", "Qiqihar": "齐齐哈尔",
    "Wuhu": "芜湖", "Bengbu": "蚌埠", "Anqing": "安庆",
    "Huangshan": "黄山", "Jiujiang": "九江", "Ganzhou": "赣州",
    "Yichang": "宜昌", "Xiangyang": "襄阳", "Jingzhou": "荆州",
    "Changde": "常德", "Yueyang": "岳阳", "Xiangtan": "湘潭",
    "Zhuzhou": "株洲", "Hengyang": "衡阳", "Zhangjiajie": "张家界",
    "Huizhou": "惠州", "Jiangmen": "江门", "Zhaoqing": "肇庆",
    "Zhanjiang": "湛江", "Zhongshan": "中山", "Chaozhou": "潮州",
    "Jieyang": "揭阳", "Mianyang": "绵阳", "Yibin": "宜宾",
    "Luzhou": "泸州", "Nanchong": "南充", "Dazhou": "达州",
    "Leshan": "乐山", "Panzhihua": "攀枝花", "Xinxiang": "新乡",
    "Anyang": "安阳", "Kaifeng": "开封", "Jiaozuo": "焦作",
    "Pingdingshan": "平顶山", "Nanyang": "南阳", "Xinyang": "信阳",
    "Shangqiu": "商丘", "Zhoukou": "周口", "Zhumadian": "驻马店",
    "Xuchang": "许昌", "Luohe": "漯河", "Sanmenxia": "三门峡",
    "Puyang": "濮阳", "Jining": "济宁", "Linyi": "临沂",
    "Heze": "菏泽", "Liaocheng": "聊城", "Dezhou": "德州",
    "Binzhou": "滨州", "Dongying": "东营", "Rizhao": "日照",
    "Tai'an": "泰安", "Zibo": "淄博", "Zaozhuang": "枣庄",
    "Zhangzhou": "漳州", "Quanzhou": "泉州", "Putian": "莆田",
    "Sanming": "三明", "Nanping": "南平", "Ningde": "宁德",
    "Wuzhou": "梧州", "Beihai": "北海", "Guigang": "贵港",
    "Yulin": "玉林", "Dali": "大理", "Lijiang": "丽江",
    "Qujing": "曲靖", "Yuxi": "玉溪", "Zhaotong": "昭通",
    "Baoshan": "保山", "Zunyi": "遵义", "Liupanshui": "六盘水",
    "Anshun": "安顺", "Bijie": "毕节", "Tongren": "铜仁",
    "Enshi": "恩施", "Shiyan": "十堰", "Xiaogan": "孝感",
    "Huanggang": "黄冈", "Xianning": "咸宁", "Jingmen": "荆门",
    "Huangshi": "黄石", "Ezhou": "鄂州", "Suizhou": "随州",
    "Hanzhong": "汉中", "Baoji": "宝鸡", "Xianyang": "咸阳",
    "Weinan": "渭南", "Yanan": "延安", "Yulin": "榆林",
    "Ankang": "安康", "Shangluo": "商洛", "Tianshui": "天水",
    "Jiuquan": "酒泉", "Zhangye": "张掖", "Wuwei": "武威",
    "Pingliang": "平凉", "Qingyang": "庆阳", "Kashgar": "喀什",
    "Yining": "伊宁", "Korla": "库尔勒", "Karamay": "克拉玛依",
    "Hami": "哈密", "Turpan": "吐鲁番", "Shihezi": "石河子",
    "Changji": "昌吉", "Danjiangkou": "丹江口", "Linfen": "临汾",
    "Yuncheng": "运城", "Yangquan": "阳泉", "Changzhi": "长治",
    "Jincheng": "晋城", "Shuozhou": "朔州", "Jinzhong": "晋中",
    "Xinzhou": "忻州", "Lvliang": "吕梁", "Chifeng": "赤峰",
    "Tongliao": "通辽", "Hulunbuir": "呼伦贝尔", "Bayannur": "巴彦淖尔",
    "Ulanqab": "乌兰察布", "Tonghua": "通化", "Baicheng": "白城",
    "Songyuan": "松原", "Baishan": "白山", "Liaoyuan": "辽源",
    "Siping": "四平", "Liaoyang": "辽阳", "Panjin": "盘锦",
    "Tieling": "铁岭", "Chaoyang": "朝阳", "Huludao": "葫芦岛",
    "Jinzhou": "锦州", "Yingkou": "营口", "Fuxin": "阜新",
    "Benxi": "本溪", "Dandong": "丹东", "Jiamusi": "佳木斯",
    "Mudanjiang": "牡丹江", "Qitaihe": "七台河", "Hegang": "鹤岗",
    "Shuangyashan": "双鸭山", "Yichun": "伊春", "Jixi": "鸡西",
    "Suihua": "绥化", "Heihe": "黑河", "Daxing'anling": "大兴安岭",
    "Huai'an": "淮安", "Suqian": "宿迁", "Lianyungang": "连云港",
    "Zhenjiang": "镇江", "Taizhou": "泰州", "Yangzhou": "扬州",
    "Xuzhou": "徐州", "Lianyungang": "连云港", "Yancheng": "盐城",
    # ---- 世界主要城市中文名补全（LLM 常输出中文名，供反向匹配；键=城市表英文键）----
    "Belém": "贝伦", "São Paulo": "圣保罗", "Rio de Janeiro": "里约热内卢",
    "Brasília": "巴西利亚", "Salvador": "萨尔瓦多", "Recife": "累西腓",
    "Buenos Aires": "布宜诺斯艾利斯", "Santiago": "圣地亚哥", "Lima": "利马",
    "Bogotá": "波哥大", "Caracas": "加拉加斯", "Montevideo": "蒙得维的亚",
    "Quito": "基多", "La Paz": "拉巴斯", "Asunción": "亚松森",
    "Mexico City": "墨西哥城", "Guadalajara": "瓜达拉哈拉", "Monterrey": "蒙特雷",
    "Panama City": "巴拿马城", "Havana": "哈瓦那", "Santo Domingo": "圣多明各",
    "Guatemala City": "危地马拉城", "San José": "圣何塞", "Managua": "马那瓜",
    "San Salvador": "圣萨尔瓦多", "Tegucigalpa": "特古西加尔巴",
    "Casablanca": "卡萨布兰卡", "Algiers": "阿尔及尔", "Cairo": "开罗",
    "Johannesburg": "约翰内斯堡", "Cape Town": "开普敦", "Nairobi": "内罗毕",
    "Lagos": "拉各斯", "Accra": "阿克拉", "Kinshasa": "金沙萨",
    "Addis Ababa": "亚的斯亚贝巴", "Tunis": "突尼斯", "Dakar": "达喀尔",
    "Istanbul": "伊斯坦布尔", "Ankara": "安卡拉", "Izmir": "伊兹密尔",
    "Athens": "雅典", "Thessaloniki": "塞萨洛尼基", "Lisbon": "里斯本",
    "Porto": "波尔图", "Warsaw": "华沙", "Kraków": "克拉科夫",
    "Prague": "布拉格", "Budapest": "布达佩斯", "Bucharest": "布加勒斯特",
    "Sofia": "索非亚", "Belgrade": "贝尔格莱德", "Zagreb": "萨格勒布",
    "Stockholm": "斯德哥尔摩", "Oslo": "奥斯陆", "Copenhagen": "哥本哈根",
    "Helsinki": "赫尔辛基", "Dublin": "都柏林", "Brussels": "布鲁塞尔",
    "Amsterdam": "阿姆斯特丹", "Rotterdam": "鹿特丹", "Zurich": "苏黎世",
    "Geneva": "日内瓦", "Milan": "米兰", "Naples": "那不勒斯", "Turin": "都灵",
    "Munich": "慕尼黑", "Hamburg": "汉堡", "Frankfurt": "法兰克福",
    "Cologne": "科隆", "Stuttgart": "斯图加特", "Kyiv": "基辅",
    "Minsk": "明斯克", "Tashkent": "塔什干", "Almaty": "阿拉木图",
    "Bangkok": "曼谷", "Ho Chi Minh City": "胡志明市", "Hanoi": "河内",
    "Phnom Penh": "金边", "Vientiane": "万象", "Yangon": "仰光",
    "Dhaka": "达卡", "Karachi": "卡拉奇", "Lahore": "拉合尔",
    "Tehran": "德黑兰", "Baghdad": "巴格达", "Riyadh": "利雅得",
    "Dubai": "迪拜", "Abu Dhabi": "阿布扎比", "Tel Aviv": "特拉维夫",
    "Jerusalem": "耶路撒冷", "Amman": "安曼", "Beirut": "贝鲁特",
    "Muscat": "马斯喀特", "Doha": "多哈", "Kuwait City": "科威特城",
    "Manila": "马尼拉", "Jakarta": "雅加达", "Kuala Lumpur": "吉隆坡",
    "Sydney": "悉尼", "Melbourne": "墨尔本", "Brisbane": "布里斯班",
    "Perth": "珀斯", "Adelaide": "阿德莱德", "Auckland": "奥克兰",
    "Wellington": "惠灵顿", "Christchurch": "基督城", "Toronto": "多伦多",
    "Vancouver": "温哥华", "Montreal": "蒙特利尔", "Calgary": "卡尔加里",
    "Chicago": "芝加哥", "Los Angeles": "洛杉矶", "San Francisco": "旧金山",
    "Seattle": "西雅图", "Boston": "波士顿", "Miami": "迈阿密",
    "Houston": "休斯顿", "Dallas": "达拉斯", "Denver": "丹佛",
    "Phoenix": "凤凰城", "Washington": "华盛顿", "Atlanta": "亚特兰大",
    "New Orleans": "新奥尔良", "Philadelphia": "费城", "Detroit": "底特律",
    "Oklahoma City": "俄克拉荷马城", "Portland": "波特兰",
    # ---- 第二批：南亚/东南亚/中东/非洲/北欧/东欧/拉美/大洋洲常见城市 ----
    "Mumbai": "孟买", "Delhi": "德里", "Bangalore": "班加罗尔", "Hyderabad": "海得拉巴",
    "Chennai": "金奈", "Kolkata": "加尔各答", "Ahmedabad": "艾哈迈达巴德", "Pune": "浦那",
    "Jaipur": "斋浦尔", "Lucknow": "勒克瑙", "Kanpur": "坎普尔", "Goa": "果阿",
    "Kathmandu": "加德满都", "Colombo": "科伦坡", "Chittagong": "吉大港",
    "Siem Reap": "暹粒", "Da Nang": "岘港", "Nha Trang": "芽庄", "Hue": "顺化",
    "Can Tho": "芹苴", "Chiang Mai": "清迈", "Chiang Rai": "清莱", "Phuket": "普吉",
    "Pattaya": "芭堤雅", "Khon Kaen": "孔敬", "Yogyakarta": "日惹", "Surabaya": "泗水",
    "Bandung": "万隆", "Medan": "棉兰", "Makassar": "望加锡", "Denpasar": "登巴萨",
    "Palembang": "巨港", "Semarang": "三宝垄", "Cebu": "宿务", "Davao": "达沃",
    "Iloilo": "伊洛伊洛", "Seoul": "首尔", "Busan": "釜山", "Incheon": "仁川",
    "Daegu": "大邱", "Daejeon": "大田", "Gwangju": "光州", "Ulsan": "蔚山",
    "Jeju": "济州", "Yokohama": "横滨", "Osaka": "大阪", "Nagoya": "名古屋",
    "Sapporo": "札幌", "Fukuoka": "福冈", "Kobe": "神户", "Kyoto": "京都",
    "Hiroshima": "广岛", "Sendai": "仙台", "Kagoshima": "鹿儿岛", "Naha": "那霸",
    "Kabul": "喀布尔", "Herat": "赫拉特", "Kandahar": "坎大哈", "Tbilisi": "第比利斯",
    "Yerevan": "埃里温", "Baku": "巴库", "Ashgabat": "阿什哈巴德", "Dushanbe": "杜尚别",
    "Bishkek": "比什凯克", "Ulaanbaatar": "乌兰巴托", "Pyongyang": "平壤",
    "Basra": "巴士拉", "Mosul": "摩苏尔", "Erbil": "埃尔比勒", "Aleppo": "阿勒颇",
    "Damascus": "大马士革", "Sana'a": "萨那", "Aden": "亚丁", "Tripoli": "的黎波里",
    "Benghazi": "班加西", "Khartoum": "喀土穆", "Omdurman": "恩图曼", "Djibouti": "吉布提",
    "Mogadishu": "摩加迪沙", "Asmara": "阿斯马拉", "Kampala": "坎帕拉", "Kigali": "基加利",
    "Bujumbura": "布琼布拉", "Dar es Salaam": "达累斯萨拉姆", "Dodoma": "多多马",
    "Zanzibar": "桑给巴尔", "Lusaka": "卢萨卡", "Harare": "哈拉雷", "Maputo": "马普托",
    "Windhoek": "温得和克", "Gaborone": "哈博罗内", "Antananarivo": "塔那那利佛",
    "Port Louis": "路易港", "Abidjan": "阿比让", "Ouagadougou": "瓦加杜古", "Bamako": "巴马科",
    "Conakry": "科纳克里", "Freetown": "弗里敦", "Monrovia": "蒙罗维亚", "Niamey": "尼亚美",
    "N'Djamena": "恩贾梅纳", "Yaoundé": "雅温得", "Douala": "杜阿拉", "Libreville": "利伯维尔",
    "Brazzaville": "布拉柴维尔", "Pointe-Noire": "黑角", "Luanda": "罗安达", "Kigali": "基加利",
    "Vilnius": "维尔纽斯", "Riga": "里加", "Tallinn": "塔林", "Kaunas": "考纳斯",
    "Gdansk": "格但斯克", "Wroclaw": "弗罗茨瓦夫", "Poznan": "波兹南", "Lodz": "罗兹",
    "Bratislava": "布拉迪斯拉发", "Ljubljana": "卢布尔雅那", "Sarajevo": "萨拉热窝",
    "Skopje": "斯科普里", "Tirana": "地拉那", "Podgorica": "波德戈里察", "Pristina": "普里什蒂纳",
    "Chisinau": "基希讷乌", "Lviv": "利沃夫", "Odessa": "敖德萨", "Kharkiv": "哈尔科夫",
    "Dnipro": "第聂伯罗", "Donetsk": "顿涅茨克", "Zaporizhzhia": "扎波罗热", "Kazan": "喀山",
    "Novosibirsk": "新西伯利亚", "Yekaterinburg": "叶卡捷琳堡", "Vladivostok": "符拉迪沃斯托克",
    "Irkutsk": "伊尔库茨克", "Sochi": "索契", "Volgograd": "伏尔加格勒", "Samara": "萨马拉",
    "Omsk": "鄂木斯克", "Chelyabinsk": "车里雅宾斯克", "Perm": "彼尔姆", "Ufa": "乌法",
    "Bergen": "卑尔根", "Gothenburg": "哥德堡", "Malmö": "马尔默", "Aarhus": "奥胡斯",
    "Odense": "欧登塞", "Tampere": "坦佩雷", "Turku": "图尔库", "Oulu": "奥卢",
    "Reykjavik": "雷克雅未克", "Edinburgh": "爱丁堡", "Glasgow": "格拉斯哥",
    "Manchester": "曼彻斯特", "Birmingham": "伯明翰", "Liverpool": "利物浦",
    "Leeds": "利兹", "Sheffield": "谢菲尔德", "Bristol": "布里斯托尔", "Cardiff": "加的夫",
    "Belfast": "贝尔法斯特", "Cork": "科克", "Galway": "戈尔韦", "Limerick": "利默里克",
    "Nice": "尼斯", "Lyon": "里昂", "Marseille": "马赛", "Toulouse": "图卢兹",
    "Bordeaux": "波尔多", "Lille": "里尔", "Strasbourg": "斯特拉斯堡", "Nantes": "南特",
    "Rennes": "雷恩", "Montpellier": "蒙彼利埃", "Bilbao": "毕尔巴鄂", "Seville": "塞维利亚",
    "Valencia": "巴伦西亚", "Granada": "格拉纳达", "Malaga": "马拉加", "Zaragoza": "萨拉戈萨",
    "Palma": "帕尔马", "Alicante": "阿利坎特", "Palermo": "巴勒莫", "Catania": "卡塔尼亚",
    "Venice": "威尼斯", "Florence": "佛罗伦萨", "Bologna": "博洛尼亚", "Genoa": "热那亚",
    "Verona": "维罗纳", "Padua": "帕多瓦", "Bari": "巴里", "Cagliari": "卡利亚里",
    "Prague": "布拉格", "Brno": "布尔诺", "Ostrava": "俄斯特拉发", "Košice": "科希策",
    "Graz": "格拉茨", "Linz": "林茨", "Salzburg": "萨尔茨堡", "Innsbruck": "因斯布鲁克",
    "Antwerp": "安特卫普", "Ghent": "根特", "Bruges": "布鲁日", "Liège": "列日",
    "The Hague": "海牙", "Utrecht": "乌得勒支", "Eindhoven": "埃因霍温", "Groningen": "格罗宁根",
    "Fez": "非斯", "Marrakesh": "马拉喀什", "Tangier": "丹吉尔", "Agadir": "阿加迪尔",
    "Alexandria": "亚历山大", "Giza": "吉萨", "Luxor": "卢克索", "Aswan": "阿斯旺",
    "Asunción": "亚松森", "Córdoba": "科尔多瓦", "Rosario": "罗萨里奥", "Mendoza": "门多萨",
    "Valparaíso": "瓦尔帕莱索", "Concepción": "康塞普西翁", "Antofagasta": "安托法加斯塔",
    "Arequipa": "阿雷基帕", "Cusco": "库斯科", "Trujillo": "特鲁希略", "Guayaquil": "瓜亚基尔",
    "Medellín": "麦德林", "Cali": "卡利", "Barranquilla": "巴兰基亚", "Cartagena": "卡塔赫纳",
    "Maracaibo": "马拉开波", "Valencia": "巴伦西亚", "Bucaramanga": "布卡拉曼加",
    "Porto Alegre": "阿雷格里港", "Curitiba": "库里蒂巴", "Fortaleza": "福塔莱萨",
    "Manaus": "马瑙斯", "Belém": "贝伦", "Salvador": "萨尔瓦多", "Natal": "纳塔尔",
    "Maceió": "马塞约", "Florianópolis": "弗洛里亚诺波利斯", "Goiânia": "戈亚尼亚",
    "Brasília": "巴西利亚", "Belize City": "伯利兹城", "San Pedro Sula": "圣佩德罗苏拉",
    "Roatán": "罗阿坦", "Puerto Vallarta": "巴亚尔塔港", "Cancún": "坎昆", "Oaxaca": "瓦哈卡",
    "Puebla": "普埃布拉", "Tijuana": "蒂华纳", "Mérida": "梅里达", "Guadalajara": "瓜达拉哈拉",
}


def _fold(name: str) -> str:
    """ASCII 折叠：去重音（Kraków→krakow, Málaga→malaga），用于模糊匹配。"""
    n = unicodedata.normalize("NFD", name)
    return "".join(c for c in n if not unicodedata.combining(c)).lower()


# ---- 模块级索引（一次性构建）----
_FOLD_TO_NAME: dict[str, str] | None = None
_FOLD_INDEX: dict[str, tuple[float, float, str]] | None = None
_ZH_FOLD: dict[str, str] | None = None


def _build_indexes() -> None:
    global _FOLD_TO_NAME, _FOLD_INDEX, _ZH_FOLD
    if _FOLD_INDEX is not None:
        return
    _FOLD_TO_NAME = {}
    _FOLD_INDEX = {}
    for name, v in CITY_COORDS.items():
        f = _fold(name)
        _FOLD_TO_NAME.setdefault(f, name)
        _FOLD_INDEX.setdefault(f, v)
    _ZH_FOLD = {_fold(zh): en for en, zh in CITY_ZH.items()}
    # 中文名补全表并入（"保定"→Baoding 等，供中文文本反向匹配）
    _ZH_FOLD.update({_fold(zh): en for en, zh in _CN_ZH_EXTRA.items()})


def _norm(name: str) -> str:
    """城市名别名归一化：中文→英文（CITY_ALIASES 优先，CITY_ZH 反向兜底）。"""
    n = name.strip()
    alias = CITY_ALIASES.get(n)
    if alias:
        return alias
    _build_indexes()
    # CITY_ZH 反向：LLM 可能直接输出中文城市名（如"阿克拉"→Accra）
    f = _fold(n)
    en = _ZH_FOLD.get(f)
    if en:
        return en
    # 重音折叠匹配英文名（Lomé 输入 Lome）
    return _FOLD_TO_NAME.get(f, n)


def city_coords(name: str) -> tuple[float, float, str] | None:
    """城市名 → (lat, lon, 国家名)；中文/别名/重音模糊匹配。

    中国城市中文名直查精确坐标表（_CN_ZH_COORDS）——解决城市表英文键缺失
    （沈阳/乌鲁木齐/江苏苏州）与中文同名歧义（"苏州"≠安徽宿州 Suzhou）。
    """
    n = name.strip()
    cn_hit = _CN_ZH_COORDS.get(n)
    if cn_hit:
        return (cn_hit[0], cn_hit[1], "China")
    en = _norm(n)
    hit = CITY_COORDS.get(en)
    if hit:
        return hit
    _build_indexes()
    return _FOLD_INDEX.get(_fold(en))


def city_zh(name: str) -> str:
    """城市名 → 中文名（找不到返回原名）。"""
    n = _norm(name)
    zh = CITY_ZH.get(n) or _CN_ZH_EXTRA.get(n)
    if zh:
        return zh
    _build_indexes()
    return _ZH_FOLD.get(_fold(n), name)


def zh_city_names() -> list[str]:
    """所有已知中文城市名（含补全表），供 visible_text 中文子串匹配。"""
    _build_indexes()
    names = set(CITY_ZH.values())
    names.update(_CN_ZH_EXTRA.values())
    names.update(_CN_ZH_COORDS.keys())
    return sorted(names)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest_city(lat: float, lon: float, max_km: float = 50.0) -> dict | None:
    """坐标 → 最近城市（A5：EXIF 快路径补城市名）。返回 None 表示附近无已知城市。"""
    _build_indexes()
    best_name: str | None = None
    best_d = float("inf")
    # bbox 预筛：约 ±1.2° 覆盖 100km，避免全表 haversine
    dlat, dlon = max_km / 111.0, max_km / (111.0 * max(0.5, math.cos(math.radians(lat))))
    for name, (clat, clon, country) in CITY_COORDS.items():
        if abs(clat - lat) > dlat or abs(clon - lon) > dlon:
            continue
        d = _haversine_km(lat, lon, clat, clon)
        if d < best_d:
            best_d = d
            best_name = name
    if best_name is None or best_d > max_km:
        return None
    _, _, country = CITY_COORDS[best_name]
    return {"name": best_name, "zh": city_zh(best_name),
            "distance_km": round(best_d, 1), "country": country}


def folded_city_index() -> dict[str, tuple[float, float, str]]:
    """预折叠城市索引（供 visible_text 匹配复用，避免重复 fold）。"""
    _build_indexes()
    return _FOLD_INDEX
