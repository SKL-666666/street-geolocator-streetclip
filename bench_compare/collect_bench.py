"""采集新题库缺口图（KartaView）。
目标配比：城市30% / 道路40% / 荒野30%，总100张。
现有可复用：城市22、乡村道路19、荒野35。
本脚本补：城市8张 + 城际道路21张。
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

# --- 城市街景坐标（补8个新城市，避开已有的22个）---
CITY_POINTS = [
    ("DE_berlin", 52.5200, 13.4050, "Germany"),
    ("PT_lisbon", 38.7223, -9.1393, "Portugal"),
    ("GR_athens", 37.9838, 23.7275, "Greece"),
    ("SE_stockholm", 59.3293, 18.0686, "Sweden"),
    ("IE_dublin", 53.3498, -6.2603, "Ireland"),
    ("CL_santiago", -33.4489, -70.6693, "Chile"),
    ("PE_lima", -12.0464, -77.0428, "Peru"),
    ("VN_hanoi", 21.0278, 105.8342, "Vietnam"),
]

# --- 城际/普通道路坐标（补21张，公路沿线）---
ROAD_POINTS = [
    ("US_route66", 35.2065, -114.0100, "United States"),      # 66号公路
    ("US_texas", 31.9686, -99.9018, "United States"),
    ("DE_autobahn", 51.1657, 10.4515, "Germany"),             # 高速
    ("FR_a7", 44.8378, 4.3763, "France"),                     # A7高速
    ("ES_a2", 40.4168, -3.7038, "Spain"),
    ("IT_autostrada", 44.1391, 10.6612, "Italy"),
    ("PL_a1", 51.9194, 19.1451, "Poland"),
    ("TR_e80", 39.9334, 32.8597, "Turkey"),
    ("KZ_highway", 48.0196, 66.9237, "Kazakhstan"),
    ("MN_road", 46.8625, 103.8467, "Mongolia"),
    ("BR_road", -14.2350, -51.9253, "Brazil"),                # 中西部
    ("AR_ruta40", -34.6037, -58.3816, "Argentina"),
    ("CA_transcanada", 51.0447, -114.0719, "Canada"),         # 加拿大
    ("AU_highway", -25.2744, 133.7751, "Australia"),
    ("IN_highway", 20.5937, 78.9629, "India"),
    ("ZA_road", -30.5595, 22.9375, "South Africa"),
    ("KE_road", -0.0236, 37.9062, "Kenya"),
    ("MA_road", 31.7917, -7.0926, "Morocco"),
    ("PT_n2", 39.3999, -8.2245, "Portugal"),
    ("GR_road", 39.0742, 21.8243, "Greece"),
    ("NO_road", 60.4720, 8.4689, "Norway"),
]


def fetch(lat, lon, dest_path, tries=3):
    """从 KartaView 拉一张图，返回 True/False。"""
    q = urllib.parse.urlencode({
        "lat": lat, "lng": lon, "radius": 400,
        "page": 1, "itemsPerPage": 10})
    url = f"{API}?{q}"
    for t in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.load(r)
            data = (d.get("result") or {}).get("data") or []
            for ph in data:
                img_url = ph.get("imageThUrl") or ph.get("filepath") or ""
                if not img_url.startswith("http"):
                    continue
                with urllib.request.urlopen(img_url, timeout=15) as ir:
                    content = ir.read()
                if len(content) < 5000:
                    continue
                with open(dest_path, "wb") as f:
                    f.write(content)
                return True
        except Exception as e:
            if t == tries - 1:
                print(f"    FAIL {dest_path}: {e}", file=sys.stderr)
            time.sleep(1)
    return False


def main():
    manifest = {}
    # 城市
    print("=== 城市街景 (补8) ===")
    for name, lat, lon, country in CITY_POINTS:
        p = os.path.join(OUT, f"city_{name}.jpg")
        if os.path.exists(p) and os.path.getsize(p) > 5000:
            print(f"  [skip] {name}")
        else:
            ok = fetch(lat, lon, p)
            print(f"  {'OK' if ok else 'FAIL'} {name}")
        if os.path.exists(p):
            manifest[f"city_{name}.jpg"] = {"country": country, "cat": "city", "lat": lat, "lon": lon}

    # 道路
    print("=== 普通道路 (补21) ===")
    for name, lat, lon, country in ROAD_POINTS:
        p = os.path.join(OUT, f"road_{name}.jpg")
        if os.path.exists(p) and os.path.getsize(p) > 5000:
            print(f"  [skip] {name}")
        else:
            ok = fetch(lat, lon, p)
            print(f"  {'OK' if ok else 'FAIL'} {name}")
        if os.path.exists(p):
            manifest[f"road_{name}.jpg"] = {"country": country, "cat": "road", "lat": lat, "lon": lon}

    with open(os.path.join(OUT, "new_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n共 {len(manifest)} 张新图 → {OUT}")


if __name__ == "__main__":
    main()
