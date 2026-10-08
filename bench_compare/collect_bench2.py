"""采集v2：更稳的 KartaView 拉图（长超时+多页重试+多点备选）。
补齐缺口：目标 城市30/道路40/荒野30。
已有 bench100/ 6张 + 现有旧题库可复用图。
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse

API = "https://api.kartaview.org/2.0/photo/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench100")
os.makedirs(OUT, exist_ok=True)

# 城市：每个国家给多个备选点（市中心→次点）
CITY_POINTS = [
    ("DE_berlin", 52.5200, 13.4050, "Germany", [(52.52,13.405),(52.50,13.42),(52.51,13.38)]),
    ("GR_athens", 37.9838, 23.7275, "Greece", [(37.9838,23.7275),(37.97,23.74),(37.99,23.72)]),
    ("IE_dublin", 53.3498, -6.2603, "Ireland", [(53.3498,-6.2603),(53.35,-6.25),(53.34,-6.27)]),
    ("CL_santiago", -33.4489, -70.6693, "Chile", [(-33.4489,-70.6693),(-33.45,-70.65),(-33.43,-70.68)]),
    ("PE_lima", -12.0464, -77.0428, "Peru", [(-12.0464,-77.0428),(-12.05,-77.03),(-12.03,-77.05)]),
    ("JP_osaka", 34.6937, 135.5023, "Japan", [(34.6937,135.5023),(34.68,135.50),(34.70,135.49)]),
    ("CA_toronto", 43.6532, -79.3832, "Canada", [(43.6532,-79.3832),(43.66,-79.39),(43.64,-79.37)]),
    ("AE_dubai", 25.2048, 55.2708, "United Arab Emirates", [(25.2048,55.2708),(25.21,55.26),(25.19,55.28)]),
    ("TH_chiangmai", 18.7883, 98.9853, "Thailand", [(18.7883,98.9853),(18.79,98.98),(18.78,98.99)]),
    ("HU_debrecen", 47.5316, 21.6273, "Hungary", [(47.5316,21.6273),(47.53,21.63),(47.52,21.62)]),
]

# 道路：每点备选
ROAD_POINTS = [
    ("US_route66", 35.2065, -114.0100, "United States", [(35.2065,-114.01),(35.5,-114.5),(36.0,-115.0)]),
    ("US_texas", 31.9686, -99.9018, "United States", [(31.97,-99.90),(32.5,-99.5),(31.5,-100.0)]),
    ("DE_autobahn", 51.1657, 10.4515, "Germany", [(51.1657,10.45),(51.2,10.5),(51.1,10.4)]),
    ("FR_a7", 44.8378, 4.3763, "France", [(44.8378,4.3763),(45.0,5.0),(44.5,4.5)]),
    ("IT_autostrada", 44.1391, 10.6612, "Italy", [(44.1391,10.66),(44.5,11.0),(44.0,10.5)]),
    ("PL_a1", 51.9194, 19.1451, "Poland", [(51.92,19.14),(52.0,19.5),(51.8,19.0)]),
    ("KZ_highway", 48.0196, 66.9237, "Kazakhstan", [(48.02,66.92),(48.5,67.0),(47.8,66.8)]),
    ("MN_road", 46.8625, 103.8467, "Mongolia", [(46.86,103.85),(47.0,104.0),(46.7,103.7)]),
    ("BR_road", -14.2350, -51.9253, "Brazil", [(-14.23,-51.92),(-14.5,-52.0),(-14.0,-51.8)]),
    ("AR_ruta40", -34.6037, -58.3816, "Argentina", [(-34.60,-58.38),(-35.0,-58.5),(-34.3,-58.2)]),
    ("CA_transcanada", 51.0447, -114.0719, "Canada", [(51.04,-114.07),(51.5,-114.5),(50.8,-113.9)]),
    ("AU_highway", -25.2744, 133.7751, "Australia", [(-25.27,133.77),(-25.5,134.0),(-25.0,133.5)]),
    ("IN_highway", 20.5937, 78.9629, "India", [(20.59,78.96),(21.0,79.0),(20.3,78.8)]),
    ("ZA_road", -30.5595, 22.9375, "South Africa", [(-30.56,22.94),(-31.0,23.0),(-30.3,22.8)]),
    ("KE_road", -0.0236, 37.9062, "Kenya", [(0.0,37.9),(0.2,38.0),(-0.2,37.8)]),
    ("MA_road", 31.7917, -7.0926, "Morocco", [(31.79,-7.09),(32.0,-7.2),(31.6,-7.0)]),
    ("PT_n2", 39.3999, -8.2245, "Portugal", [(39.40,-8.22),(39.5,-8.3),(39.3,-8.1)]),
    ("NO_road", 60.4720, 8.4689, "Norway", [(60.47,8.47),(60.5,8.5),(60.4,8.4)]),
    ("US_i80", 41.2619, -95.9372, "United States", [(41.26,-95.94),(41.5,-96.0),(41.0,-95.8)]),
    ("ES_a2b", 40.4168, -3.7038, "Spain", [(40.42,-3.70),(40.6,-3.8),(40.2,-3.6)]),
    ("TR_e90", 39.9334, 32.8597, "Turkey", [(39.93,32.86),(40.0,33.0),(39.8,32.7)]),
]

# 荒野补足（现有35张里选30，这里补几张确保配比）
WILD_POINTS = [
    ("AU_outback", -24.0, 132.0, "Australia", [(-24.0,132.0),(-24.5,125.0),(-23.5,131.0)]),
    ("CL_atacama2", -23.0, -68.0, "Chile", [(-23.0,-68.0),(-22.5,-68.5),(-23.5,-67.5)]),
    ("MN_steppe", 46.5, 105.0, "Mongolia", [(46.5,105.0),(47.0,105.5),(46.0,104.5)]),
]


def fetch_one(lat, lon, dest_path, radius=400, tries=4):
    """拉一张图，重试。"""
    q = urllib.parse.urlencode({"lat": lat, "lng": lon, "radius": radius,
                                "page": 1, "itemsPerPage": 12})
    url = f"{API}?{q}"
    for t in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                d = json.load(r)
            data = (d.get("result") or {}).get("data") or []
            # 轮询多张，挑一张没下过的
            for ph in data:
                img_url = ph.get("imageThUrl") or ph.get("filepath") or ""
                if not img_url.startswith("http"):
                    continue
                try:
                    with urllib.request.urlopen(img_url, timeout=20) as ir:
                        content = ir.read()
                except Exception:
                    continue
                if len(content) < 8000:
                    continue
                with open(dest_path, "wb") as f:
                    f.write(content)
                return True
        except Exception:
            time.sleep(1.5 * (t + 1))
    return False


def collect(group, points, prefix):
    got = []
    for name, lat0, lon0, country, alts in points:
        p = os.path.join(OUT, f"{prefix}_{name}.jpg")
        if os.path.exists(p) and os.path.getsize(p) > 8000:
            print(f"  [skip] {name}")
            got.append((f"{prefix}_{name}.jpg", country, prefix, lat0, lon0))
            continue
        ok = False
        for (lat, lon) in alts:
            if fetch_one(lat, lon, p):
                ok = True
                break
        print(f"  {'OK' if ok else 'FAIL'} {name}")
        if os.path.exists(p):
            got.append((f"{prefix}_{name}.jpg", country, prefix, lat0, lon0))
        time.sleep(0.5)
    return got


def main():
    all_new = []
    print("=== 城市 ===")
    all_new += collect("city", CITY_POINTS, "city")
    print("=== 道路 ===")
    all_new += collect("road", ROAD_POINTS, "road")
    print("=== 荒野(补) ===")
    all_new += collect("wild", WILD_POINTS, "wild")

    manifest = {fn: {"country": c, "cat": cat, "lat": la, "lon": lo}
                for fn, c, cat, la, lo in all_new}
    mp = os.path.join(OUT, "new_manifest.json")
    old = {}
    if os.path.exists(mp):
        old = json.load(open(mp, encoding="utf-8"))
    old.update(manifest)
    json.dump(old, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n本轮 {len(manifest)} 张，累计 manifest {len(old)} 张")


if __name__ == "__main__":
    main()
