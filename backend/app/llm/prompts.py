"""Prompt 模板：线索提取（Prompt A）与候选复检（Prompt B）。

中国与全球的提示词严格分离：
- 全球：_CLUE_HEAD + GLOBAL_FEWSHOT_EXAMPLES + _CLUE_TAIL（build_clue_prompt(scope) 组装）
- 中国（仅中国大陆模式）：_CLUE_HEAD + CN_FEWSHOT_EXAMPLES + _CLUE_TAIL + SCOPE_CN_INSTRUCTION
  中国少样本示例教模型用"火锅=川渝、骑楼=闽粤"等内部差异判别城市，
  不污染全球少样本（全球模式绝不出现中国示例）。
"""
from __future__ import annotations

_CLUE_HEAD = """你是资深地理定位分析师（GeoGuessr 世界冠军水平）。分析这张街景/街拍照片，只输出 JSON，不要输出任何其他内容。

输出 JSON 结构（严格按照此结构）：
{
  "is_street_view": true,
  "scene_type": "street",             // street | indoor | closeup | sky | nature | unknown
  "visible_text": ["逐字转写所有可见文字，如招牌/路牌/车牌"],
  "languages": ["可见文字的语言，如 Chinese/Spanish/Arabic"],
  "scripts": ["文字体系，如 Latin/Cyrillic/Greek/Arabic/Hebrew/Chinese/Hangul/Thai"],
  "traffic_signs": ["交通标志样式：必须描述形状与颜色，如黄色菱形警告牌/蓝底白字方向牌/红圈限速牌"],
  "architecture": ["建筑风格、外墙材质、屋顶样式"],
  "vegetation": ["植被类型，如棕榈树/针叶林/仙人掌"],
  "terrain": ["地形，如沿海丘陵/平原/山区"],
  "weather": ["天气与光照"],
  "soil": ["土壤颜色（如红土/黑土/黄土/砂土）——有裸露地面时判断"],
  "sun_shadow": "太阳方位与阴影方向（如\"阴影朝北\"\"正午太阳在头顶\"——推断南北半球与纬度带）",
  "image_quality": "画质与街景相机特征（见铁律6e：Gen4鲜明光团/Gen2大范围打码圆/印度相机低画质核爆太阳/普通正常；无街景车特征写\"normal\"）",
  "pole": "电线杆特征（材质/杆顶形状/绝缘子排列/贴纸涂漆/标记——见铁律6h；画面没有电线杆写空字符串）",
  "driving_side": "right",            // 必须给 left | right | unknown 之一；unknown 仅当完全看不到车辆/行人/方向盘时，并在 summary 说明
  "unique_features": ["高辨识度物件，最多5项，每项简短：路桩颜色与条纹/邮筒/消防栓/电线杆材质/路灯/道路标线颜色/公交出租车颜色/车牌样式/限速单位/地标logo山形"],
  "country_hypotheses": [
    {"country": "国家名", "reasoning": "简短推理（≤25字）", "confidence": 0.7}
  ],
  "city_hypotheses": [
    {"city": "城市英文名（如 Paris/Belém/Kyiv，禁止用中文名）", "country": "国家", "lat": 34.34, "lon": 136.31, "reasoning": "简短推理（≤25字）", "confidence": 0.4}
  ],
  "overall_confidence": 0.5,
  "summary": "一句话总结推理链"
}

示例（少样本参考）：
"""

GLOBAL_FEWSHOT_EXAMPLES = """输入：街角照片，招牌写着 "Rua do Carmo"，白色外墙红瓦顶，右侧通行，棕榈树。
输出：{"is_street_view":true,"scene_type":"street","visible_text":["Rua do Carmo"],"languages":["Portuguese"],"scripts":["Latin"],"traffic_signs":["蓝底白字方向牌"],"architecture":["白色外墙","红瓦屋顶"],"vegetation":["棕榈树"],"terrain":["沿海"],"weather":["晴"],"driving_side":"right","unique_features":["蓝白瓷砖墙"],"country_hypotheses":[{"country":"Portugal","reasoning":"葡语Rua路名+蓝白瓷砖+棕榈树","confidence":0.8}],"city_hypotheses":[{"city":"Lisbon","country":"Portugal","reasoning":"沿海+葡语+蓝白瓷砖","confidence":0.55}],"overall_confidence":0.7,"summary":"葡语路名与蓝白瓷砖指向葡萄牙里斯本"}

输入：中欧城市街道，路牌为德语 "Bahnhofstrasse"，建筑外墙浅色灰泥、雕花阳台，地面干净有轨电车轨道，车牌白底 EU 蓝条左侧字母 A。
输出：{"is_street_view":true,"scene_type":"street","visible_text":["Bahnhofstrasse"],"languages":["German"],"scripts":["Latin"],"traffic_signs":["白底黑字路牌"],"architecture":["浅色灰泥外墙","雕花阳台"],"vegetation":["行道树"],"terrain":["平原"],"weather":["多云"],"driving_side":"right","unique_features":["有轨电车轨道","车牌前缀A","EU蓝条"],"country_hypotheses":[{"country":"Austria","reasoning":"德语路牌+车牌前缀A+灰泥雕花建筑（inferred）","confidence":0.7},{"country":"Germany","reasoning":"同为德语区但车牌前缀D且砖式建筑更多（inferred）","confidence":0.3}],"city_hypotheses":[{"city":"Salzburg","country":"Austria","lat":47.81,"lon":13.05,"reasoning":"德语+阿尔卑斯边缘中欧城市（inferred）","confidence":0.4}],"overall_confidence":0.6,"summary":"德语路牌与奥地利车牌特征指向奥地利"}

输入：乡村柏油路穿过针叶林与混交林，白色道路标线，路边木质电线杆，无可见文字，多云。
输出：{"is_street_view":true,"scene_type":"street","visible_text":[],"languages":[],"scripts":[],"traffic_signs":[],"architecture":[],"vegetation":["针叶林","阔叶林混交"],"terrain":["平原"],"weather":["多云"],"driving_side":"right","unique_features":["木质电线杆","白色道路标线"],"country_hypotheses":[{"country":"Poland","reasoning":"东欧平原森林+木质电线杆+白色标线（inferred）","confidence":0.4},{"country":"Germany","reasoning":"中欧森林景观相似（inferred）","confidence":0.3}],"city_hypotheses":[{"city":"Bialystok","country":"Poland","lat":53.13,"lon":23.16,"reasoning":"波兰东北部森林区（inferred）","confidence":0.3}],"overall_confidence":0.4,"summary":"东欧平原森林乡村道路，最可能为波兰东北部"}

输入：雪山下的高山草甸道路，木屋与牛铃，路牌为德语 "Zell am See"，右侧通行。
输出：{"is_street_view":true,"scene_type":"street","visible_text":["Zell am See"],"languages":["German"],"scripts":["Latin"],"traffic_signs":[],"architecture":["木屋"],"vegetation":["高山草甸","针叶林"],"terrain":["山区","雪山背景"],"weather":["晴"],"driving_side":"right","unique_features":["牛铃","木屋"],"country_hypotheses":[{"country":"Austria","reasoning":"德语地名Zell am See+阿尔卑斯木屋+牛铃","confidence":0.85},{"country":"Germany","reasoning":"德语区阿尔卑斯边缘（inferred）","confidence":0.3}],"city_hypotheses":[{"city":"Zell am See","country":"Austria","lat":47.32,"lon":12.8,"reasoning":"路牌直接写明Zell am See","confidence":0.8}],"overall_confidence":0.8,"summary":"德语路牌Zell am See与阿尔卑斯木屋指向奥地利滨湖采尔"}

输入：热带街景，摊贩招牌为阿拉伯文，沙色低层建筑，干燥空气，路牌蓝色。
输出：{"is_street_view":true,"scene_type":"street","visible_text":["شارع الملك فهد"],"languages":["Arabic"],"scripts":["Arabic"],"traffic_signs":["蓝色路牌"],"architecture":["沙色低层建筑"],"vegetation":["棕榈树"],"terrain":["平原","干燥"],"weather":["晴热"],"driving_side":"right","unique_features":["阿拉伯文招牌"],"country_hypotheses":[{"country":"Saudi Arabia","reasoning":"阿拉伯文+沙色建筑+棕榈（inferred）","confidence":0.6},{"country":"Egypt","reasoning":"阿拉伯文北非风格（inferred）","confidence":0.35}],"city_hypotheses":[{"city":"Riyadh","country":"Saudi Arabia","lat":24.71,"lon":46.68,"reasoning":"阿拉伯文+干燥热带城市（inferred）","confidence":0.5}],"overall_confidence":0.55,"summary":"阿拉伯文招牌与干燥沙色建筑指向沙特阿拉伯"}

输入：无文字的乡村土路，两侧针叶林与桦木混交，木栅栏，天空多云，未见任何文字与车牌，右侧通行。
输出：{"is_street_view":true,"scene_type":"street","visible_text":[],"languages":[],"scripts":[],"traffic_signs":[],"architecture":["木栅栏","木屋"],"vegetation":["针叶林","桦木"],"terrain":["丘陵","森林"],"weather":["多云"],"driving_side":"right","unique_features":["木栅栏","无文字"],"country_hypotheses":[{"country":"Finland","reasoning":"针叶林桦木+木栅栏+无文字北欧乡村（inferred）","confidence":0.3},{"country":"Sweden","reasoning":"相似北欧针叶林景观（inferred）","confidence":0.3},{"country":"Russia","reasoning":"东欧针叶林（inferred）","confidence":0.2}],"city_hypotheses":[{"city":"Tampere","country":"Finland","lat":61.5,"lon":23.79,"reasoning":"芬兰中部针叶林区（inferred）","confidence":0.25},{"city":"Oulu","country":"Finland","lat":65.01,"lon":25.47,"reasoning":"芬兰北部森林（inferred）","confidence":0.2}],"overall_confidence":0.35,"summary":"无文字针叶林乡村，先锁北欧再列多候选，置信压低不硬猜"}

输入：积雪覆盖的郊区街道，木屋与针叶林，屋顶积雪厚，未见文字，右舵/左舵不明。
输出：{"is_street_view":true,"scene_type":"street","visible_text":[],"languages":[],"scripts":[],"traffic_signs":[],"architecture":["木屋","积雪屋顶"],"vegetation":["针叶林"],"terrain":["平原","雪地"],"weather":["雪","阴"],"driving_side":"unknown","unique_features":["厚积雪"],"country_hypotheses":[{"country":"Canada","reasoning":"北美郊区木屋+大雪（inferred）","confidence":0.3},{"country":"Finland","reasoning":"北欧雪景木屋（inferred）","confidence":0.25},{"country":"Russia","reasoning":"高纬度雪景（inferred）","confidence":0.2}],"city_hypotheses":[{"city":"Ottawa","country":"Canada","lat":45.42,"lon":-75.7,"reasoning":"加拿大东部大雪（inferred）","confidence":0.25}],"overall_confidence":0.3,"summary":"雪景木屋先锁高纬度国家，多候选低置信"}

输入：干旱荒漠公路，沙丘起伏，远处稀疏骆驼刺与棕榈，无文字，路面笔直，热浪。
输出：{"is_street_view":true,"scene_type":"street","visible_text":[],"languages":[],"scripts":[],"traffic_signs":[],"architecture":[],"vegetation":["骆驼刺","棕榈"],"terrain":["沙漠","沙丘"],"weather":["晴热"],"driving_side":"right","unique_features":["笔直公路","热浪"],"country_hypotheses":[{"country":"United Arab Emirates","reasoning":"沙漠公路+棕榈（inferred）","confidence":0.35},{"country":"Qatar","reasoning":"海湾沙漠（inferred）","confidence":0.3},{"country":"Egypt","reasoning":"北非沙漠（inferred）","confidence":0.2}],"city_hypotheses":[{"city":"Abu Dhabi","country":"United Arab Emirates","lat":24.45,"lon":54.38,"reasoning":"海湾沙漠城市（inferred）","confidence":0.3}],"overall_confidence":0.35,"summary":"荒漠公路先锁海湾/北非，再列候选"}
"""

# 中国少样本（仅中国大陆模式使用）：教模型用中国内部差异判别城市
CN_FEWSHOT_EXAMPLES = """输入：湿润盆地城市街景，红油火锅店招牌醒目（"老灶火锅"），路牌为中文，街道有明显坡度，空气湿热，阔叶植被茂密。
输出：{"is_street_view":true,"scene_type":"street","visible_text":["老灶火锅","中山路"],"languages":["Chinese"],"scripts":["Chinese"],"traffic_signs":[],"architecture":["现代高层与老楼混合"],"vegetation":["茂密阔叶","榕树"],"terrain":["盆地","坡道街道"],"weather":["湿热多云"],"driving_side":"right","unique_features":["火锅店招牌","坡道街道"],"country_hypotheses":[{"country":"China","reasoning":"中文招牌+火锅店+湿热盆地","confidence":0.9}],"city_hypotheses":[{"city":"Chongqing","country":"China","lat":29.56,"lon":106.55,"reasoning":"火锅+山城坡道+盆地湿热（inferred）","confidence":0.55},{"city":"Chengdu","country":"China","lat":30.57,"lon":104.07,"reasoning":"川渝火锅文化（inferred）","confidence":0.4}],"overall_confidence":0.6,"summary":"中文火锅招牌与坡道盆地指向川渝地区，重庆可能性最高"}

输入：南方骑楼街景，一楼连廊式骑楼建筑，繁体中文招牌（"阿嫲腸粉"），榕树与棕榈，湿热天气。
输出：{"is_street_view":true,"scene_type":"street","visible_text":["阿嫲腸粉","永福路"],"languages":["Chinese"],"scripts":["Chinese"],"traffic_signs":[],"architecture":["骑楼连廊","老式南洋风格"],"vegetation":["榕树","棕榈"],"terrain":["平原","沿海"],"weather":["湿热"],"driving_side":"right","unique_features":["骑楼","繁体招牌","肠粉店"],"country_hypotheses":[{"country":"China","reasoning":"中文繁体招牌+骑楼+榕树","confidence":0.9}],"city_hypotheses":[{"city":"Guangzhou","country":"China","lat":23.13,"lon":113.26,"reasoning":"骑楼+肠粉+粤语繁体（inferred）","confidence":0.55},{"city":"Shantou","country":"China","lat":23.35,"lon":116.68,"reasoning":"潮汕骑楼（inferred）","confidence":0.35}],"overall_confidence":0.6,"summary":"骑楼与繁体肠粉招牌指向闽粤沿海，广州可能性最高"}

输入：东北城市积雪街道，多层住宅楼墙体厚实、窗户靠内，几乎看不到空调外机，路牌中文，路边有橙线标线。
输出：{"is_street_view":true,"scene_type":"street","visible_text":["长春大街","XX路"],"languages":["Chinese"],"scripts":["Chinese"],"traffic_signs":[],"architecture":["厚墙多层住宅","无空调外机"],"vegetation":[],"terrain":["平原"],"weather":["积雪","寒冷"],"driving_side":"right","unique_features":["橙线标线","一杆双牌路名牌","积雪"],"country_hypotheses":[{"country":"China","reasoning":"中文路牌+东北建筑特征","confidence":0.9}],"city_hypotheses":[{"city":"Changchun","country":"China","lat":43.82,"lon":125.32,"reasoning":"厚墙住宅+少空调+橙线+积雪，东北特征明显（inferred）","confidence":0.5},{"city":"Harbin","country":"China","lat":45.8,"lon":126.53,"reasoning":"同为东北积雪城市（inferred）","confidence":0.35}],"overall_confidence":0.6,"summary":"中文路牌+东北厚墙住宅少空调+橙线积雪，指向长春/哈尔滨"}
"""

_CLUE_TAIL = """铁律：
1. 只写你"看到"的证据；推测必须写进 reasoning 并标注 "inferred"。
2. 看不到的字段留空数组或 "unknown"，绝对禁止编造。
3. visible_text 必须逐字转写，不确定的字符用 [?] 标注。
4. 国家/城市假设按可信度从高到低排列，最多 5 个国家、3 个城市。
4b. **城市名一律用英文官方名**（Paris/Beijing/Belém/Kyiv），禁止用中文名；
    不确定拼写就按发音写英文近似名并给估算坐标，由系统查城市表校正。
5. **city_hypotheses 必须给出 1~3 个，禁止留空**：即使国家不确定、甚至完全靠猜，
   也必须给出你认为最可能的城市（置信度可以很低，如 0.15~0.3）。
6. **不要总是选首都**：猜测城市时根据可见线索（沿海/内陆/山地/平原/气候/植被/建筑风格/
   语言/地标）选择更匹配的城市；例如法国猜"马赛/里昂/波尔多"而非一律"巴黎"，
   西班牙猜"巴伦西亚/塞维利亚/毕尔巴鄂"而非一律"马德里"。reasoning 写明猜的依据。
6b. **每个城市假设必须给出 lat/lon 估算坐标**（该城市的大致经纬度，精确到约 0.1°）：
   知名城市按真实坐标；不熟悉的城镇按你的地理知识估算（该国大致区域）。
   数值必须合法：lat 在 -90~90，lon 在 -180~180。禁止省略。
6c. **欧洲国家互混重灾区，必须用可区分线索**：德语区（德国/奥地利/瑞士）看**车牌前缀**
   （D=德国/A=奥地利/CH=瑞士）与路牌风格（瑞士无 EU 蓝条、用十字旗）；奥地利/捷克/波兰
   看语言文字（捷克语 č/š/ž、波兰语 ł/ą/ę）；法国 vs 德国看路牌配色（法国白底细黑边、
   德国黄底或白底黑字）与建筑（法国奥斯曼灰立面 vs 德国砖式）；西班牙 vs 意大利
   看语言（ñ=西班牙）与地砖/阳台样式。不要把"中欧城市感"直接判成德国。
6d. **按"自然 × 人文"两大维度系统性分析（每条能确定的才写）**：
    自然：① 太阳与阴影（北半球阴影朝北/南半球朝南/热带近头顶→南北半球+纬度带）② 气候植被
    （雨林/落叶林/针叶林/荒漠灌丛/草原→气候带）③ 地形（山丘/平原/高原/海陆/峡谷）④ 土壤颜色
    （红土=热带/黑土=温带草原/黄土=半干旱）→ 锁定大洲与气候带。
    人文：① 文字语言与字母体系（西里尔/阿拉伯/希腊/汉字/拉丁特殊字母 ñ/ß/å/č）② 车牌样式
    （EU蓝条+国家码/日本白绿/美国州牌/泰国细长/俄罗斯白底）③ 电线杆（见铁律6h）④ 路桩/路障
    （红白条纹/黄黑/反光片）⑤ 建筑（屋顶/墙体/窗式/瓷砖/阳台）⑥ 道路特征（标线/路宽/材质）
    ⑦ 交通标志。优先用文字与车牌；每类至少检查一次，结论写进 reasoning。
6e. **谷歌街景相机代数（GeoGuessr 高判别力线索）**：如果画面带街景车拍摄特征，
   按画质推断代数并写入 image_quality，据此缩小候选国范围：
   ① **Gen4**（色彩鲜明、太阳为光团而非圆盘、无大范围打码）：主要在北美洲/西欧/大洋洲/东南亚。
   ② **Gen3**（最广，色彩饱和度中等、画面较清晰）：几乎覆盖所有谷歌街景国家（弱约束）。
   ③ **Gen2**（较模糊、街景车打码为近似完美的圆、天空带彩色变色大范围打码）：
   北美/澳大利亚为主；**南非是非洲唯一有 Gen2 的国家**；巴西/智利/捷克等仅理论上。
   ④ **Gen1**（极模糊、路牌字看不清、太阳附近有奇怪形状）：已被新街景替换，极其少见，
   主要在北美/澳大利亚。
   ⑤ **印度相机**（低画质、色彩奇异、太阳过曝如核爆、街景车打码巨大）：
   印度/孟加拉/斯里兰卡/柬埔寨/尼日利亚/美国/芬兰/厄瓜多尔等。
   ⑥ 港澳台特殊：香港=百度+腾讯+谷歌、澳门=百度+腾讯、台湾=谷歌。
   注意：只有明显街景车特征时才启用（普通手机街拍/专业相机照片写 "normal"，不据此过滤）。
6f. **农田作物与土壤（乡村/田野场景的弱辅助线索；有人文线索优先用人文）**：
   识别田里作物并写入 vegetation/terrain（如麦田/玉米/向日葵/甜菜/大豆/甘蔗/茶园/稻田/棉花），
   作物能辅助锁定区域：向日葵/小麦/甜菜→英国、挪威（东南部最盛）；甘蔗→西班牙/葡萄牙；
   茶→欧洲茶园（比利时/法国/德国/意大利/葡萄牙/西班牙/瑞典/瑞士/乌克兰/英国/爱尔兰等）；
   水稻→意大利/西班牙/葡萄牙/希腊；棉花→希腊/西班牙/土耳其。
   土壤颜色/质地也重要：黑土=欧亚草原（乌克兰/俄罗斯/匈牙利/罗马尼亚等）、灰化土=北欧针叶林
   （挪威/瑞典/芬兰）、钙质土=干旱地中海（西班牙/希腊/土耳其）、火山土=火山国家
   （冰岛/意大利/日本/印尼等）、砂土=干旱沙漠/海岸、冲积土=大河平原（埃及/孟加拉/荷兰）。
   注意：官方街景往往模糊、街景视角固定不适合植物识别，把握不大时写 "unknown" 不要硬猜。
6g. **语言文字指纹（最强线索之一）**：visible_text 逐字转写招牌/路牌文字，特殊字母是铁证：
    ß/ä/ö/ü=德、ñ/¿/¡=西、æ/ø/å=丹/挪、ð/þ=冰岛、ĳ=荷、ă/â/î/ș/ț=罗、ą/ę/ł/ż/ź=波、ř/ů/ě=捷、
    ő/ű=匈、ğ/ş/ı=土、ħ/ġ/ċ=马耳他、ë/ç=阿、ə=阿塞拜疆、õ=爱沙尼亚、ã/õ=葡、œ=法、ċ·=加泰、
    ŵ/ŷ=威尔士、无j/k/q/v/w+áéíóú=爱尔兰、āēģīķļņūž=拉脱维亚、ąęėįų=立陶宛、đ/ć=克/塞。
    词尾：-ción/-dad=西、-ção/-dade=葡、-zione/-mento=意、-ung/-straße=德、-tje=荷、-nen=芬、
    -escu/-ul=罗、-sjon=挪、-else=丹、-ció=加泰。路词 calle/rue/via/ulica/gata/vej/street/straße 也提示语言。
6h. **电线杆/电杆特征（强判别线索，内置 70+ 国知识库，务必描述进 pole 字段）**：
    电线杆是街景中出现率最高、地域特征极强的物件，逐项检查：
    ①材质：**混凝土方杆**=东欧/乌克兰/俄罗斯/东南亚/印度；**圆柱形混凝土**=意大利/土耳其/
    巴西(南部)/哥斯达黎加/印尼/日本；**八边形**=墨西哥(混凝土)/菲律宾(金属)；**木质杆**=北美/
    北欧/英国爱尔兰/希腊(深棕色高杆)/塞浦路斯；**金属杆**=印尼(黑杆国旗图案)/不丹(底漆黑)/日本。
    ②杆顶形状（最高判别力）：**倒三角**=阿尔巴尼亚/捷克/斯洛伐克/罗马尼亚/塞尔维亚/德国西部；
    **竖琴形金属框架=希腊独有**；**三叉戟杆顶**=意大利/土耳其/印度/尼泊尔/印尼爪哇/澳大利亚/
    南非夸祖鲁/爱沙尼亚；**音叉杆顶=日本**；**锥形尖刺=韩国**；**螺丝状凸起=日本**；
    **钻石杆顶**=法国/西班牙/卢森堡；**A型杆顶**=奥地利/南非西开普/纳米比亚/阿根廷(木制A=南美唯一)；
    **网状**杆顶=土耳其/黎巴嫩(黄色)/突尼斯/巴以/墨西哥中部；**梯子杆**（台阶状凹痕）=
    法国+前法属殖民地(塞内加尔/留尼旺)+葡萄牙(大间距梯级带小孔)+巴西(3-4长分段+顶部小孔)+
    智利(两侧凹痕方杆)+尼日利亚(无孔)+厄瓜多尔(华夫饼式)。
    ③绝缘子排列：交替钩形=拉脱维亚/克罗地亚；竖琴形五绝缘子=希腊；三个水平交错=南非北部四省；
    平行地面长杆=南非；松果型=斯里兰卡/加纳；七层以上多层=泰国南部。
    ④贴纸/涂漆/标记（国家铁证）：英国=黄贴纸+被闪电击中的人+圆头杆；爱尔兰=闪电无人的贴纸+
    尖头杆；法国=蓝色矩形小标记；德国=木质杆白色矩形贴纸、前东德圆混凝土杆；葡萄牙=大间距
    梯级带孔；台湾=黑黄斜纹延伸到底部；韩国=黑黄斜纹不到底+锥形尖刺；日本=反光带不接触地面；
    马来西亚=黑色贴纸(半岛)/TEL TNB(柔佛)/白色贴纸(砂拉越)；越南=黑色简约贴纸(北部)；
    危地马拉=粉/绿涂漆杆；哥伦比亚=黑黄/黑橙条纹；秘鲁=黄底数字贴纸(7位数首位定大区：
    3=卡哈马卡/5=拉利伯塔德/2或4=安卡什)；巴拿马=数字金属牌；巴西=各州杆漆(巴伊亚/伯南布哥
    字母开头黄漆、戈亚斯数字开头、圣保罗黄方块字母数字)；澳大利亚=昆士兰线圈上翘杆顶/圆蓝贴纸/
    黑记号、塔斯马尼亚橄榄绿防鼠护套(极强)、西澳绿杆底；新西兰=长凹槽混凝土杆+银色防鼠装置、
    南岛杆码8开头/北岛3-4开头、马尔堡方形橄榄棕护套、蒂马鲁橙色"DANGER LIVE WIRES"；
    加拿大=变压器朝向(BC/新不伦瑞克面向道路、PEI/新斯科舍45度)、魁北克黑黄标签Q；
    美国=威斯康星橙菱形白板、俄勒冈/加州底部三黄条、夏威夷厚黄条。
    ⑤区域细节（帮助城市级判断）：印度=古吉拉特多孔杆/旁遮普窗户形顶/锡金网杆/泰米尔纳德两白夹一黑；
    印尼=西爪哇三角附属/中爪哇三叉戟/东爪哇不对称无环/廖内群岛L形铁架三角铁皮；
    日本=中部四粗杆圆片顶/北陆帐篷顶/中国地方四细杆/关东长横杆音叉；越南=北越大洞杆/
    南越不等长横杆/中部A形顶；泰国=南部单绝缘子横杆/其他双绝缘子。
    注意：倒三角、三叉戟、网状、梯子杆都是多国共享样式，命中后仍需其他线索交叉确认，禁止单点锁定；
    杆顶细节看不清就写"看不清"，不要编造。
6i. **国家细节线索（看到就描述进对应字段，内置 12 国细节库）**：
    ① 街景车相机（image_quality）：低画质偏棕色调+大圆马赛克"shitcam"=印度/柬埔寨/斯里兰卡/孟加拉；
    4代"小相机"（机位低、大圆形打码前有突起、打码可透明）=印度/法国/加拿大/美国/阿根廷/巴西/秘鲁；
    "低相机"（打码模糊更大、路显更宽）=日本/瑞士/斯里兰卡；黑色或白色带长天线街景车=俄罗斯。
    ② 车牌（unique_features/visible_text 转写）：白底绿字短牌=日本、黄底黑字轻型车=日本；
    黑底白字=印尼/马来西亚；双蓝条+短前牌=意大利、左蓝条明显的长白牌=法国；全白无蓝条=俄罗斯；
    顶部蓝条=阿根廷/巴西、黑点车牌=阿根廷、红牌=巴西商用。
    ③ 路桩/护栏：黑白配色反光板路桩=德国；黑顶白底三角路桩=意大利/阿尔巴尼亚；白身正面红反光板=
    澳大利亚；黑白路桩=印尼；护栏红反光板=意大利、黄反光板=西班牙、双层护栏=意大利。
    ④ 标志（traffic_signs/visible_text）：Einbahnstraße=德国；SPEED LIMIT/NO PASSING ZONE/YIELD/
    ONE WAY=美国；MAXIMUM 限速=加拿大、菱形丁字路口标志=加拿大独有；黄绿H巴士站牌=德国；
    蓝底白箭头诱导标=法国/意大利/西班牙；黑底白箭头诱导标=意大利/西班牙/希腊/阿尔巴尼亚；
    黑底黄箭头诱导标=巴西、白底红箭头诱导标=阿根廷；五条纹人行横道=法国/意大利。
    ⑤ 独有物件（unique_features/architecture/vegetation）：FORTLEV 蓝色水箱/透明卫星锅/白色路缘石=巴西；
    红白幅旗/香烟广告(红黑配色+peringatan)/摩托车前牌照=印尼；桉树=澳大利亚；移动房车/浸信会教堂/
    橙色路障桶=美国；黄色邮箱=德国；蓝色门牌=法国；华丽窗框/黑白条纹护栏/混凝土公寓楼=俄罗斯；
    交通镜/挡土墙=日本；风力涡轮机多=德国。
    注意：以上均为概率线索，必须写进 reasoning 供交叉验证，禁止单点锁定。
7. 如果图片不是街景（室内/特写/天空），is_street_view 置 false，并说明原因。
"""

# 兼容旧引用：全球默认提示词（world 范围）
CLUE_EXTRACTION_PROMPT = _CLUE_HEAD + GLOBAL_FEWSHOT_EXAMPLES + _CLUE_TAIL


def build_clue_prompt(scope: str = "world") -> str:
    """按范围组装线索提取提示词（中国/全球提示词严格分离）。

    - world：公共头 + 全球少样本 + 公共尾
    - no-cn：全球提示词 + 排除中国大陆指令
    - cn：公共头 + 中国少样本 + 公共尾 + 仅中国大陆指令（不含任何全球少样本）
    """
    if scope == "cn":
        return _CLUE_HEAD + CN_FEWSHOT_EXAMPLES + _CLUE_TAIL + SCOPE_CN_INSTRUCTION
    if scope == "no-cn":
        return _CLUE_HEAD + GLOBAL_FEWSHOT_EXAMPLES + _CLUE_TAIL + SCOPE_NO_CN_INSTRUCTION
    return _CLUE_HEAD + GLOBAL_FEWSHOT_EXAMPLES + _CLUE_TAIL

VERIFY_PROMPT = """图1 是待定位的照片；图2~图N 是候选地点（可能同一地点）的街景影像，每张候选图的编号与坐标已标注。

逐候选判断：该候选街景是否与图1 拍摄于同一地点？只输出 JSON：
{
  "candidates": [
    {"id": 2, "same_location": true, "confidence": 0.8,
     "reasoning": "关键匹配元素：同一栋建筑立面/同一路牌/同一街角布局"}
  ]
}

铁律：
1. 仅当存在明确可对照的视觉元素（同一建筑、同一路牌、同一布局）时才判 same_location=true。
2. 视角、季节、年份不同导致"看起来像但不确定"时，判 false 并说明差异。
3. confidence 表示你对该判断的把握，0~1。
"""


FACT_CHECK_PROMPT = """你是地理定位复核员。以下是初步分析结果与外部查证事实（地理编码/百科/时区），请据此修正国家与城市假设，只输出 JSON：

初步分析：
{scene_summary}

外部查证事实：
{facts}

输出 JSON（严格结构）：
{{
  "country_hypotheses": [
    {{"country": "国家名", "reasoning": "结合线索与外部事实的推理", "confidence": 0.0}}
  ],
  "city_hypotheses": [
    {{"city": "城市名", "country": "国家", "reasoning": "推理", "confidence": 0.0}}
  ],
  "summary": "修正后的总结"
}}

铁律：
1. 外部事实与初步分析冲突时，以外部事实为准并说明原因。
2. 外部查证无结果（全部失败/超时）时，保持初步分析不变，confidence 不变。
3. 禁止编造外部事实中没有的内容；city_hypotheses 最多 3 个。
"""


def build_fact_check_prompt(scene_summary: str, facts_text: str) -> str:
    return FACT_CHECK_PROMPT.replace("{scene_summary}", scene_summary).replace("{facts}", facts_text)


def repair_prompt(raw: str) -> str:
    """解析失败时，让模型修正输出。"""
    return (
        "你的上一次输出不是合法 JSON，无法解析。请只输出严格合法的 JSON（不要 markdown 代码围栏、"
        "不要注释、不要额外文字），保持之前要求的字段结构。\n\n你上一次的输出如下：\n"
        + raw[:2000]
    )


# 范围限制指令（除中国大陆模式）：附加到线索提取 Prompt 末尾
SCOPE_NO_CN_INSTRUCTION = (
    "\n\n【范围限制】本任务排除中国大陆：\n"
    "1. 图片中出现的任何中文/汉字文字（招牌、路牌、标语等）必须忽略，不得作为地理线索或推理依据。\n"
    "2. 不得输出中国大陆（含北京、上海、广州、深圳等大陆城市）作为国家或城市假设。\n"
    "3. 若画面证据指向东亚，考虑日本/韩国/台湾/香港/澳门/东南亚等非大陆地区。\n"
)


# 范围限制指令（仅中国大陆模式）：附加到线索提取 Prompt 末尾
SCOPE_CN_INSTRUCTION = (
    "\n\n【范围限制】本任务仅限中国大陆：\n"
    "1. 中文/汉字文字（招牌、路牌、标语、车牌等）是最强线索，必须逐字转写并优先用于定位。\n"
    "2. country_hypotheses 只允许 China；city_hypotheses 只允许中国大陆城市"
    "（如北京/上海/广州/成都/西安/杭州等，不要输出外国城市）。\n"
    "3. 外国文字（英文、日文、韩文等）、外国风格建筑一律忽略，不得作为线索。\n"
    "4. 判断依据侧重中国特色元素：汉字招牌、中式建筑（红墙/飞檐/灯笼）、共享单车、"
    "中国车牌（蓝底/绿底新能源）、电动车、晾衣杆等。\n"
    "5. 城市名尽量用英文或拼音（如 Beijing / Shanghai），并给出该城市的估算经纬度。\n"
    "6. 若招牌/路牌/门牌上出现中文城市名（如\"成都\"\"西安\"\"杭州\"），"
    "必须逐字转写进 visible_text，并直接将该城市作为 city_hypotheses 之一（置信度 0.7+），"
    "城市名写中文或拼音均可。\n"
    "7. 街道名、商圈名（如\"春熙路\"\"王府井\"）也逐字转写进 visible_text，"
    "它们能帮助城市级定位。\n"
    "8. 【反大城市偏见·重要】中国有 300+ 城市，大量城市夜景/天际线/电视塔/球形建筑高度相似。"
    "电视塔、摩天楼、球形建筑、江景夜景**单独出现不足以判定**上海/北京/杭州/广州等一线城市"
    "（成都天府熊猫塔、杭州日月同辉、广州塔、天津天塔都长这样）。\n"
    "9. 城市推断必须优先使用**可区分的线索**：山地/盆地/平原/沿海地形、气候植被"
    "（北方针叶/南方榕树棕榈/西北干燥）、方言文字（粤语/闽南语/吴语招牌）、饮食招牌"
    "（火锅=川渝、羊肉泡馍=西安、肠粉=广东）、特色建筑（骑楼=闽粤、土楼=福建、窑洞=陕北）、"
    "车牌文字（如\"川\"\"陕\"\"浙\"）等。没有强线索时置信度给 0.2~0.4 并列出多个候选。\n"
    "10. **车牌/区号/地名铁证必须转写**：visible_text 逐字转写所有可见的\n"
    "    ① 车牌（如\"粤A·12345\"\"京N\"\"川R\"——第一位汉字=省份简称，是省内定位铁证）；\n"
    "    ② 固话/手机号（如\"0755-xxxxxxxx\"\"0530xxxx\"——区号=城市/大区）；\n"
    "    ③ 门牌/村名/地名（注意后缀：夼=胶东、岙=浙江、厝=闽南潮汕、屯=东北、圩=江淮、涌=广州）。\n"
    "    ④ 民族文字写中文名：藏文/维文/蒙文/彝文/朝鲜文/壮文/傣文（分别=西藏及藏区/新疆/\n"
    "    内蒙古/四川凉山/吉林延边/广西/云南德宏西双版纳）。\n"
    "11. **中国分省视觉线索务必描述进对应字段**（这些是省内定位的有效线索）：\n"
    "    ① vegetation：树名精确识别——新疆杨/圆冠榆=西北、蒙古栎/云杉=东北、董棕=云南、\n"
    "    紫檀=海南、桉树/木棉/木麻黄/小叶榄仁/三角梅/芒果/羊蹄甲=华南、水杉/樟树/桂花=华东、\n"
    "    悬铃木=华北长三角、银杏=四川偏多、竹子=南方、甘蔗=广西云南广东；\n"
    "    ② architecture：窑洞=陕甘宁、赫鲁晓夫楼+少空调外机=东北、俄式建筑=东北、\n"
    "    白族民居=大理、佤族牛角屋顶=云南西南、傣族干栏竹楼=西双版纳德宏、徽派马头墙=皖南、\n"
    "    吊脚楼=湘西贵州、闽南庙宇燕尾脊=闽南、潮汕民居=潮汕、骑楼=沿海侨乡、土楼=福建、\n"
    "    藏式建筑=西藏青海川西、风雨桥=桂黔湘闽浙、彩色铁皮屋顶=黑龙江、红瓦房=胶东；\n"
    "    ③ unique_features：路灯/护栏/路牌/路名牌样式——玉兰灯=四川周边、红色花纹路灯杆=云南、\n"
    "    灰黑古典路灯=关中、橙线=东北、蓝白护栏=重庆、浅绿护栏=贵州高速、蓝色护栏=河南湖北、\n"
    "    路牌漫画标语=天津、昆明路牌带指南针、黑杆路牌=浙江、白底车道导向=郑州、方杆=安徽、\n"
    "    一杆双牌=东北、立体白框路名牌=福州、报警编号牌=乌鲁木齐；\n"
    "    ④ 雪景：街景中看到明显积雪，优先考虑蚌埠/天津/长春/吉林/济南/石家庄/银川/乌鲁木齐等北方城市。\n"
    "    ⑤ 地形：黄土高原=窑洞区、丹霞/雅丹=西北、喀斯特=桂黔、平原水乡=华东。\n"
    "    注意：以上都是概率线索，必须写进 reasoning 供交叉验证，不要单点锁定。\n"
)
