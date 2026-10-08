"""补道路图：KartaView radius=300（已验证参数），目标补足道路到40张。
每个公路坐标点尝试，成功即存。带 manifest。
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

# 道路坐标点（公路沿线，radius=300 已验证可用）——多备选点提高成功率
ROAD = [
    ("US_i40", 35.10, -106.60, "United States"),
    ("US_i70", 39.70, -104.99, "United States"),
    ("US_i80", 41.26, -95.94, "United States"),
    ("US_us101", 36.60, -121.90, "United States"),
    ("DE_a9", 51.16, 10.45, "Germany"),
    ("FR_a6", 46.80, 3.00, "France"),
    ("ES_a1", 40.40, -3.70, "Spain"),
    ("IT_a1", 44.13, 10.66, "Italy"),
    ("PL_a2", 52.23, 21.01, "Poland"),
    ("TR_d900", 39.93, 32.86, "Turkey"),
    ("KZ_m36", 43.24, 76.95, "Kazakhstan"),
    ("MN_a030", 47.90, 106.91, "Mongolia"),
    ("BR_br163", -14.23, -51.92, "Brazil"),
    ("AR_rn7", -34.60, -58.38, "Argentina"),
    ("CA_hwy1", 51.04, -114.07, "Canada"),
    ("AU_a87", -25.27, 133.77, "Australia"),
    ("IN_nh44", 20.59, 78.96, "India"),
    ("ZA_n1", -30.55, 22.93, "South Africa"),
    ("KE_a104", -0.02, 37.90, "Kenya"),
    ("MA_a3", 31.79, -7.09, "Morocco"),
    ("PT_a1", 39.39, -8.22, "Portugal"),
    ("NO_rv7", 60.47, 8.46, "Norway"),
    ("SE_e4", 59.32, 18.06, "Sweden"),
    ("GR_a1", 39.07, 21.82, "Greece"),
    ("CL_r5", -33.44, -70.66, "Chile"),
    ("PE_pe1n", -12.04, -77.04, "Peru"),
    ("CL_atacama_road", -23.50, -68.00, "Chile"),
    ("MN_altai_road", 47.50, 96.00, "Mongolia"),
    ("KZ_steppe_road", 48.50, 67.00, "Kazakhstan"),
    ("AU_outback_road", -24.50, 132.00, "Australia"),
    ("US_utah_road", 38.50, -110.00, "United States"),
    ("IS_road", 64.96, -19.02, "Iceland"),
    ("NO_fjord_road", 61.50, 7.00, "Norway"),
    ("PT_algarve", 37.01, -8.24, "Portugal"),
    ("GR_pelop", 37.50, 22.00, "Greece"),
    ("ES_extremadura", 39.47, -6.37, "Spain"),
    ("FR_limousin", 45.80, 1.26, "France"),
    ("DE_bavaria_road", 48.14, 11.58, "Germany"),
    ("IT_tuscany", 43.77, 11.26, "Italy"),
]


def fetch(lat, lon, dest, radius=300, tries=3):
    q = urllib.parse.urlencode({"lat": lat, "lng": lon, "radius": radius,
                                "page": 1, "itemsPerPage": 8})
    url = f"{API}?{q}"
    for t in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.load(r)
            data = (d.get("result") or {}).get("data") or []
            for ph in data:
                iu = ph.get("imageThUrl") or ph.get("filepath") or ""
                if not iu.startswith("http"):
                    continue
                try:
                    with urllib.request.urlopen(iu, timeout=15) as ir:
                        c = ir.read()
                except Exception:
                    continue
                if len(c) < 8000:
                    continue
                with open(dest, "wb") as f:
                    f.write(c)
                return True
        except Exception:
            time.sleep(1.0 * (t + 1))
    return False


def main():
    manifest_path = os.path.join(OUT, "new_manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        manifest = json.load(open(manifest_path, encoding="utf-8"))

    have_road = sum(1 for v in manifest.values() if v.get("cat") == "road")
    need = max(0, 40 - have_road)
    print(f"已有道路 {have_road}，还需 {need}")
    added = 0
    for name, lat, lon, country in ROAD:
        if added >= need:
            break
        fn = f"road_{name}.jpg"
        p = os.path.join(OUT, fn)
        if os.path.exists(p) and os.path.getsize(p) > 8000:
            continue
        if fetch(lat, lon, p):
            manifest[fn] = {"country": country, "cat": "road", "lat": lat, "lon": lon}
            added += 1
            print(f"  OK {name} ({added}/{need})")
        else:
            print(f"  FAIL {name}")
        time.sleep(0.8)

    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    total_road = sum(1 for v in manifest.values() if v.get("cat") == "road")
    print(f"\n新增 {added}，道路累计 {total_road}，manifest 总 {len(manifest)}")


if __name__ == "__main__":
    main()
