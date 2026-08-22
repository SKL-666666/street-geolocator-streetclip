"""生成 cities.py：城市坐标表（约 500 城）+ 中文名映射。

数据源：https://github.com/lutangar/cities.json（全球 1000 大城市，ISO2 国家码）
用法：python scripts/build_cities.py（失败自动重试；生成 app/geokb/cities.py）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "geokb" / "ne_populated.json"
OUT = REPO / "app" / "geokb" / "cities.py"
URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places.geojson"

# 全球城市上限：Natural Earth 10m 共约 7300 个主要居民点，全量导入（覆盖世界上所有主要城市）
MAX_CITIES = 10000

# NE 主权国名 → 本工具规范名
SOV_ALIASES = {
    "United States of America": "United States",
    "Czechia": "Czechia",
    "South Korea": "South Korea",
    "United Kingdom": "United Kingdom",
    "Russia": "Russia",
    "Taiwan": "Taiwan",
    "Vietnam": "Vietnam",
    "Laos": "Laos",
    "Tanzania": "Tanzania",
    "Dominican Republic": "Dominican Republic",
    "Moldova": "Moldova",
    "United Arab Emirates": "United Arab Emirates",
    "South Africa": "South Africa",
    "Turkey": "Turkey",
    "Iran": "Iran",
    "North Korea": "North Korea",
    # 实测差异（NE 官方主权名）
    "French Republic": "France",
    "Kingdom of Spain": "Spain",
    "Kingdom of the Netherlands": "Netherlands",
    "Kingdom of Norway": "Norway",
    "Republic of Serbia": "Serbia",
    "Republic of Korea": "South Korea",
    "United Republic of Tanzania": "Tanzania",
    "Korea, South": "South Korea",
}

# 89 国 → ISO2（与 geokb 规范名一致）
COUNTRY_ISO: dict[str, str] = {
    "United Kingdom": "GB", "Ireland": "IE", "Germany": "DE", "France": "FR",
    "Spain": "ES", "Portugal": "PT", "Italy": "IT", "Netherlands": "NL",
    "Belgium": "BE", "Switzerland": "CH", "Austria": "AT", "Poland": "PL",
    "Czechia": "CZ", "Hungary": "HU", "Ukraine": "UA", "Romania": "RO",
    "Bulgaria": "BG", "Greece": "GR", "Turkey": "TR", "Russia": "RU",
    "Sweden": "SE", "Norway": "NO", "Denmark": "DK", "Finland": "FI",
    "Iceland": "IS", "Slovakia": "SK", "Croatia": "HR", "Serbia": "RS",
    "United States": "US", "Canada": "CA", "Mexico": "MX", "Brazil": "BR",
    "Argentina": "AR", "Australia": "AU", "New Zealand": "NZ", "Japan": "JP",
    "South Korea": "KR", "China": "CN", "Taiwan": "TW", "India": "IN",
    "Thailand": "TH", "Vietnam": "VN", "Indonesia": "ID", "Philippines": "PH",
    "South Africa": "ZA", "Morocco": "MA", "Egypt": "EG",
    "United Arab Emirates": "AE", "Israel": "IL", "Saudi Arabia": "SA",
    "Belarus": "BY", "Latvia": "LV", "Lithuania": "LT", "Estonia": "EE",
    "Slovenia": "SI", "Luxembourg": "LU", "Malta": "MT", "Cyprus": "CY",
    "Moldova": "MD", "Chile": "CL", "Peru": "PE", "Colombia": "CO",
    "Uruguay": "UY", "Paraguay": "PY", "Ecuador": "EC", "Panama": "PA",
    "Costa Rica": "CR", "Dominican Republic": "DO", "Kenya": "KE",
    "Nigeria": "NG", "Ghana": "GH", "Tanzania": "TZ", "Ethiopia": "ET",
    "Algeria": "DZ", "Tunisia": "TN", "Jordan": "JO", "Lebanon": "LB",
    "Iran": "IR", "Pakistan": "PK", "Bangladesh": "BD", "Sri Lanka": "LK",
    "Myanmar": "MM", "Cambodia": "KH", "Laos": "LA", "Mongolia": "MN",
    "Kazakhstan": "KZ", "Azerbaijan": "AZ", "Georgia": "GE", "Armenia": "AM",
    "Malaysia": "MY", "Singapore": "SG",
}
ISO_COUNTRY = {v: k for k, v in COUNTRY_ISO.items()}

# 主要城市中文名（其余城市回退英文名）
CITY_ZH: dict[str, str] = {
    # 英国
    "London": "伦敦", "Birmingham": "伯明翰", "Manchester": "曼彻斯特", "Glasgow": "格拉斯哥",
    "Liverpool": "利物浦", "Leeds": "利兹", "Edinburgh": "爱丁堡", "Bristol": "布里斯托尔",
    # 爱尔兰
    "Dublin": "都柏林", "Cork": "科克",
    # 德国
    "Berlin": "柏林", "Hamburg": "汉堡", "Munich": "慕尼黑", "Cologne": "科隆",
    "Frankfurt": "法兰克福", "Stuttgart": "斯图加特", "Düsseldorf": "杜塞尔多夫",
    "Leipzig": "莱比锡", "Dresden": "德累斯顿", "Nuremberg": "纽伦堡", "Hanover": "汉诺威",
    # 法国
    "Paris": "巴黎", "Marseille": "马赛", "Lyon": "里昂", "Toulouse": "图卢兹",
    "Nice": "尼斯", "Nantes": "南特", "Strasbourg": "斯特拉斯堡", "Bordeaux": "波尔多",
    "Lille": "里尔", "Rennes": "雷恩",
    # 西班牙
    "Madrid": "马德里", "Barcelona": "巴塞罗那", "Valencia": "瓦伦西亚", "Seville": "塞维利亚",
    "Zaragoza": "萨拉戈萨", "Málaga": "马拉加", "Murcia": "穆尔西亚", "Bilbao": "毕尔巴鄂",
    "Granada": "格拉纳达", "Palma": "帕尔马", "Alicante": "阿利坎特",
    # 葡萄牙
    "Lisbon": "里斯本", "Porto": "波尔图", "Braga": "布拉加", "Coimbra": "科英布拉", "Faro": "法鲁",
    # 意大利
    "Rome": "罗马", "Milan": "米兰", "Naples": "那不勒斯", "Turin": "都灵",
    "Palermo": "巴勒莫", "Genoa": "热那亚", "Bologna": "博洛尼亚", "Florence": "佛罗伦萨",
    "Bari": "巴里", "Venice": "威尼斯", "Verona": "维罗纳",
    # 荷兰
    "Amsterdam": "阿姆斯特丹", "Rotterdam": "鹿特丹", "The Hague": "海牙", "Utrecht": "乌得勒支",
    "Eindhoven": "埃因霍温", "Groningen": "格罗宁根",
    # 比利时
    "Brussels": "布鲁塞尔", "Antwerp": "安特卫普", "Ghent": "根特", "Bruges": "布鲁日", "Liège": "列日",
    # 瑞士
    "Zürich": "苏黎世", "Zurich": "苏黎世", "Geneva": "日内瓦", "Basel": "巴塞尔", "Bern": "伯尔尼",
    "Lausanne": "洛桑",
    # 奥地利
    "Vienna": "维也纳", "Graz": "格拉茨", "Linz": "林茨", "Salzburg": "萨尔茨堡", "Innsbruck": "因斯布鲁克",
    # 波兰
    "Warsaw": "华沙", "Kraków": "克拉科夫", "Krakow": "克拉科夫", "Łódź": "罗兹", "Lodz": "罗兹",
    "Wrocław": "弗罗茨瓦夫", "Wroclaw": "弗罗茨瓦夫", "Poznań": "波兹南", "Poznan": "波兹南",
    "Gdańsk": "格但斯克", "Gdansk": "格但斯克",
    # 捷克
    "Prague": "布拉格", "Brno": "布尔诺", "Ostrava": "俄斯特拉发", "Plzeň": "比尔森", "Plzen": "比尔森",
    # 匈牙利
    "Budapest": "布达佩斯", "Debrecen": "德布勒森", "Szeged": "塞格德",
    # 乌克兰
    "Kyiv": "基辅", "Kiev": "基辅", "Kharkiv": "哈尔科夫", "Odesa": "敖德萨", "Odessa": "敖德萨",
    "Dnipro": "第聂伯罗", "Lviv": "利沃夫", "Zaporizhzhia": "扎波罗热",
    # 罗马尼亚
    "Bucharest": "布加勒斯特", "Cluj-Napoca": "克卢日-纳波卡", "Timișoara": "蒂米什瓦拉",
    "Timişoara": "蒂米什瓦拉", "Iași": "雅西", "Iaşi": "雅西", "Constanța": "康斯坦察",
    # 保加利亚
    "Sofia": "索非亚", "Plovdiv": "普罗夫迪夫", "Varna": "瓦尔纳", "Burgas": "布尔加斯",
    # 希腊
    "Athens": "雅典", "Thessaloniki": "塞萨洛尼基", "Patras": "帕特雷", "Heraklion": "伊拉克利翁",
    # 土耳其
    "Istanbul": "伊斯坦布尔", "Ankara": "安卡拉", "İzmir": "伊兹密尔", "Izmir": "伊兹密尔",
    "Bursa": "布尔萨", "Antalya": "安塔利亚", "Adana": "阿达纳",
    # 俄罗斯
    "Moscow": "莫斯科", "Saint Petersburg": "圣彼得堡", "Novosibirsk": "新西伯利亚",
    "Yekaterinburg": "叶卡捷琳堡", "Kazan": "喀山", "Nizhny Novgorod": "下诺夫哥罗德",
    "Samara": "萨马拉", "Rostov-on-Don": "顿河畔罗斯托夫", "Sochi": "索契",
    # 北欧
    "Stockholm": "斯德哥尔摩", "Gothenburg": "哥德堡", "Malmö": "马尔默", "Malmo": "马尔默",
    "Oslo": "奥斯陆", "Bergen": "卑尔根", "Copenhagen": "哥本哈根", "Aarhus": "奥胡斯",
    "Helsinki": "赫尔辛基", "Tampere": "坦佩雷", "Turku": "图尔库", "Reykjavík": "雷克雅未克",
    "Reykjavik": "雷克雅未克",
    # 中欧东欧
    "Bratislava": "布拉迪斯拉发", "Zagreb": "萨格勒布", "Belgrade": "贝尔格莱德",
    "Novi Sad": "诺维萨德", "Minsk": "明斯克", "Riga": "里加", "Vilnius": "维尔纽斯",
    "Tallinn": "塔林", "Ljubljana": "卢布尔雅那", "Luxembourg": "卢森堡市", "Valletta": "瓦莱塔",
    "Nicosia": "尼科西亚", "Chișinău": "基希讷乌", "Chisinau": "基希讷乌",
    # 美国
    "New York": "纽约", "Los Angeles": "洛杉矶", "Chicago": "芝加哥", "Houston": "休斯顿",
    "Phoenix": "菲尼克斯", "Philadelphia": "费城", "San Antonio": "圣安东尼奥",
    "San Diego": "圣迭戈", "Dallas": "达拉斯", "San Jose": "圣何塞", "Austin": "奥斯汀",
    "Jacksonville": "杰克逊维尔", "Fort Worth": "沃斯堡", "Columbus": "哥伦布",
    "San Francisco": "旧金山", "Charlotte": "夏洛特", "Indianapolis": "印第安纳波利斯",
    "Seattle": "西雅图", "Denver": "丹佛", "Washington": "华盛顿", "Boston": "波士顿",
    "Nashville": "纳什维尔", "Detroit": "底特律", "Portland": "波特兰", "Miami": "迈阿密",
    "Atlanta": "亚特兰大", "Las Vegas": "拉斯维加斯",
    # 加拿大
    "Toronto": "多伦多", "Montreal": "蒙特利尔", "Vancouver": "温哥华", "Calgary": "卡尔加里",
    "Edmonton": "埃德蒙顿", "Ottawa": "渥太华", "Winnipeg": "温尼伯", "Quebec": "魁北克城",
    "Hamilton": "汉密尔顿",
    # 墨西哥
    "Mexico City": "墨西哥城", "Guadalajara": "瓜达拉哈拉", "Monterrey": "蒙特雷",
    "Puebla": "普埃布拉", "Tijuana": "蒂华纳",
    # 巴西
    "São Paulo": "圣保罗", "Sao Paulo": "圣保罗", "Rio de Janeiro": "里约热内卢",
    "Brasília": "巴西利亚", "Brasilia": "巴西利亚", "Salvador": "萨尔瓦多",
    "Fortaleza": "福塔莱萨", "Belo Horizonte": "贝洛奥里藏特", "Manaus": "马瑙斯",
    "Curitiba": "库里蒂巴", "Recife": "累西腓", "Porto Alegre": "阿雷格里港",
    # 阿根廷
    "Buenos Aires": "布宜诺斯艾利斯", "Córdoba": "科尔多瓦", "Cordoba": "科尔多瓦",
    "Rosario": "罗萨里奥", "Mendoza": "门多萨",
    # 大洋洲
    "Sydney": "悉尼", "Melbourne": "墨尔本", "Brisbane": "布里斯班", "Perth": "珀斯",
    "Adelaide": "阿德莱德", "Canberra": "堪培拉", "Gold Coast": "黄金海岸",
    "Auckland": "奥克兰", "Wellington": "惠灵顿", "Christchurch": "基督城",
    # 日韩
    "Tokyo": "东京", "Yokohama": "横滨", "Osaka": "大阪", "Nagoya": "名古屋",
    "Sapporo": "札幌", "Fukuoka": "福冈", "Kobe": "神户", "Kyoto": "京都",
    "Seoul": "首尔", "Busan": "釜山", "Incheon": "仁川", "Daegu": "大邱",
    # 中国
    "Shanghai": "上海", "Beijing": "北京", "Shenzhen": "深圳", "Guangzhou": "广州",
    "Chengdu": "成都", "Tianjin": "天津", "Wuhan": "武汉", "Hangzhou": "杭州",
    "Nanjing": "南京", "Chongqing": "重庆", "Suzhou": "苏州", "Xian": "西安",
    "Xi'an": "西安", "Qingdao": "青岛", "Shenyang": "沈阳", "Dalian": "大连",
    "Harbin": "哈尔滨", "Changsha": "长沙", "Kunming": "昆明", "Xiamen": "厦门",
    # 台湾
    "Taipei": "台北", "Kaohsiung": "高雄", "Taichung": "台中", "Tainan": "台南",
    # 南亚东南亚
    "New Delhi": "新德里", "Mumbai": "孟买", "Bengaluru": "班加罗尔", "Bangalore": "班加罗尔",
    "Hyderabad": "海得拉巴", "Chennai": "金奈", "Kolkata": "加尔各答", "Delhi": "德里",
    "Bangkok": "曼谷", "Chiang Mai": "清迈", "Hanoi": "河内", "Ho Chi Minh City": "胡志明市",
    "Da Nang": "岘港", "Jakarta": "雅加达", "Surabaya": "泗水", "Bandung": "万隆",
    "Manila": "马尼拉", "Quezon City": "奎松城", "Cebu": "宿务", "Kuala Lumpur": "吉隆坡",
    "Singapore": "新加坡", "Yangon": "仰光", "Phnom Penh": "金边", "Vientiane": "万象",
    "Ulaanbaatar": "乌兰巴托", "Astana": "阿斯塔纳", "Almaty": "阿拉木图",
    "Baku": "巴库", "Tbilisi": "第比利斯", "Yerevan": "埃里温",
    # 中东非洲
    "Dubai": "迪拜", "Abu Dhabi": "阿布扎比", "Sharjah": "沙迦", "Tel Aviv": "特拉维夫",
    "Jerusalem": "耶路撒冷", "Haifa": "海法", "Riyadh": "利雅得", "Jeddah": "吉达",
    "Mecca": "麦加", "Cairo": "开罗", "Alexandria": "亚历山大", "Giza": "吉萨",
    "Casablanca": "卡萨布兰卡", "Rabat": "拉巴特", "Marrakesh": "马拉喀什",
    "Algiers": "阿尔及尔", "Tunis": "突尼斯市", "Amman": "安曼", "Beirut": "贝鲁特",
    "Tehran": "德黑兰", "Mashhad": "马什哈德", "Islamabad": "伊斯兰堡", "Karachi": "卡拉奇",
    "Lahore": "拉合尔", "Dhaka": "达卡", "Chittagong": "吉大港", "Colombo": "科伦坡",
    "Nairobi": "内罗毕", "Mombasa": "蒙巴萨", "Lagos": "拉各斯", "Abuja": "阿布贾",
    "Kano": "卡诺", "Accra": "阿克拉", "Kumasi": "库马西", "Dodoma": "多多马",
    "Dar es Salaam": "达累斯萨拉姆", "Addis Ababa": "亚的斯亚贝巴", "Pretoria": "比勒陀利亚",
    "Johannesburg": "约翰内斯堡", "Cape Town": "开普敦", "Durban": "德班",
    # 拉美
    "Santiago": "圣地亚哥", "Lima": "利马", "Bogotá": "波哥大", "Bogota": "波哥大",
    "Medellín": "麦德林", "Medellin": "麦德林", "Cali": "卡利", "Montevideo": "蒙得维的亚",
    "Asunción": "亚松森", "Asuncion": "亚松森", "Quito": "基多", "Guayaquil": "瓜亚基尔",
    "Panama City": "巴拿马城", "San José": "圣何塞", "San Jose": "圣何塞",
    "Santo Domingo": "圣多明各", "Havana": "哈瓦那",
    # 非洲各国首都（补充）
    "Lomé": "洛美", "Lome": "洛美", "Bujumbura": "布琼布拉", "Paramaribo": "帕拉马里博",
    "Funafuti": "富纳富提", "Banjul": "班珠尔", "Lilongwe": "利隆圭", "Gaborone": "哈博罗内",
    "Maseru": "马塞卢", "Mbabane": "姆巴巴内", "N'Djamena": "恩贾梅纳", "N'Djamena": "恩贾梅纳",
    "Ouagadougou": "瓦加杜古", "Bamako": "巴马科", "Conakry": "科纳克里",
    "Freetown": "弗里敦", "Monrovia": "蒙罗维亚", "Niamey": "尼亚美", "Dakar": "达喀尔",
    "Nouakchott": "努瓦克肖特", "Kigali": "基加利", "Kampala": "坎帕拉", "Asmara": "阿斯马拉",
    "Djibouti": "吉布提市", "Mogadishu": "摩加迪沙", "Antananarivo": "塔那那利佛",
    "Lusaka": "卢萨卡", "Harare": "哈拉雷", "Windhoek": "温得和克", "Maputo": "马普托",
    "Libreville": "利伯维尔", "Brazzaville": "布拉柴维尔", "Kinshasa": "金沙萨",
    "Bangui": "班吉", "Yaoundé": "雅温得", "Yaounde": "雅温得", "Malabo": "马拉博",
    "São Tomé": "圣多美", "Sao Tome": "圣多美", "Bissau": "比绍", "Praia": "普拉亚",
    "Juba": "朱巴", "Khartoum": "喀土穆", "Addis Ababa": "亚的斯亚贝巴", "Hargeisa": "哈尔格萨",
    "Porto-Novo": "波多诺伏", "Cotonou": "科托努", "Accra": "阿克拉", "Kumasi": "库马西",
    # 亚太小国首都（补充）
    "Suva": "苏瓦", "Port Moresby": "莫尔兹比港", "Honiara": "霍尼亚拉",
    "Port Vila": "维拉港", "Nuku'alofa": "努库阿洛法", "Tarawa": "塔拉瓦",
    "Bandar Seri Begawan": "斯里巴加湾市", "Dili": "帝力", "Thimphu": "廷布",
    "Malé": "马累", "Male": "马累", "Colombo": "科伦坡", "Kathmandu": "加德满都",
    "Sa Pa": "沙坝", "Sapa": "沙坝", "Hanoi": "河内", "Ho Chi Minh City": "胡志明市",
    "Da Nang": "岘港", "Hue": "顺化", "Nha Trang": "芽庄",
}


def main() -> int:
    import time

    import httpx

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    data = None
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
            print("使用缓存数据")
        except Exception:
            data = None
    if data is None:
        for attempt in range(5):
            try:
                resp = httpx.get(URL, timeout=120, follow_redirects=True)
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                data = resp.json()
                CACHE.write_text(json.dumps(data), encoding="utf-8")
                print(f"下载成功（第{attempt + 1}次尝试）：{len(resp.content)//1024} KB")
                break
            except Exception as e:
                print(f"  第{attempt + 1}次失败：{str(e)[:80]}")
                time.sleep(2)
    if data is None:
        print("下载失败")
        return 1

    # 解析 NE 居民点：全部国家（不限 89 国）；先排序后去重（同名保留人口最大者）
    raw: list[dict] = []
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        sov = props.get("SOV0NAME") or props.get("SOVEREIGNT") or ""
        canonical = SOV_ALIASES.get(sov, sov)
        name = (props.get("NAME") or props.get("name") or "").strip()
        if not name:
            continue
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        try:
            pop = int(props.get("POP_MAX") or 0)
        except (TypeError, ValueError):
            pop = 0
        raw.append({"name": name, "lat": float(coords[1]), "lng": float(coords[0]),
                    "country": canonical, "pop": pop})

    raw.sort(key=lambda r: -r["pop"])
    items: list[dict] = []
    seen: set[str] = set()
    for it in raw:
        # 同名城市全局去重（保留人口最大者；字典字面量同名键会后者覆盖前者）
        if it["name"] in seen:
            continue
        seen.add(it["name"])
        items.append(it)
        if len(items) >= MAX_CITIES:
            break
    print(f"匹配城市：{len(raw)}，取前 {len(items)}（按人口）")

    lines = ['"""由 scripts/build_cities.py 自动生成：城市坐标表 + 中文名。\n请勿手改；重新生成：python scripts/build_cities.py\n"""\n']
    lines.append("from __future__ import annotations\n\n")
    lines.append("# 城市中文名（主要城市；其余回退英文名）\nCITY_ZH: dict[str, str] = {")
    for name, zh in sorted(CITY_ZH.items()):
        lines.append(f'    "{name}": "{zh}",')
    lines.append("}\n\n")
    lines.append("# 城市坐标：{英文名: (lat, lon, 国家规范名)}\nCITY_COORDS: dict[str, tuple[float, float, str]] = {")
    for it in items:
        name = it["name"].replace('"', '\\"')
        lines.append(f'    "{name}": ({it["lat"]:.5f}, {it["lng"]:.5f}, "{it["country"]}"),')
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"生成 {OUT}：{len(items)} 城")
    return 0


if __name__ == "__main__":
    sys.exit(main())
