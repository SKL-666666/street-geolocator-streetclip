"""替换 bench_final 里的 25 张 200x150 缩略图为 KartaView 原图 (imageProcUrl)。
- src=bench_hard: 文件名含 photo ID → ?id= 端点
- src=karta: manifest 有坐标 → 按坐标查 → 匹配最近的
保留原文件名和真值，只换图片内容。
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(HERE, "bench_final")
CATS = json.load(open(os.path.join(BENCH, "categories.json"), encoding="utf-8"))


def get_json(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def download(url, dest):
    with urllib.request.urlopen(url, timeout=25) as r:
        content = r.read()
    if len(content) < 20000:  # 原图应 >20KB，太小说明还是缩略图
        return False
    with open(dest, "wb") as f:
        f.write(content)
    return True


def find_thumbs():
    from PIL import Image
    out = []
    for fn, meta in CATS.items():
        p = os.path.join(BENCH, fn)
        im = Image.open(p)
        w, h = im.size
        sz = os.path.getsize(p)
        if w <= 300 and sz < 45000:
            out.append((fn, meta, w, h, sz))
    return out


def replace_by_id(fn, pid, dest):
    """用 photo ID 查原图。"""
    try:
        d = get_json(f"https://api.kartaview.org/2.0/photo/?id={pid}")
        data = (d.get("result") or {}).get("data") or []
        for ph in data:
            ip = ph.get("imageProcUrl") or ph.get("imageLthUrl")
            if ip and download(ip, dest):
                return True, ph.get("lat"), ph.get("lng")
    except Exception as e:
        return False, None, f"ERR:{e}"
    return False, None, None


def replace_by_coord(fn, meta, dest):
    """按 manifest 坐标查，取最近的一张原图。"""
    lat, lon = meta["lat"], meta["lon"]
    q = urllib.parse.urlencode({"lat": lat, "lng": lon, "radius": 300,
                                "page": 1, "itemsPerPage": 8})
    try:
        d = get_json(f"https://api.kartaview.org/2.0/photo/?{q}")
        data = (d.get("result") or {}).get("data") or []
        # 按距离排序取最近
        def dist(ph):
            pla = float(ph.get("lat") or 0)
            pln = float(ph.get("lng") or 0)
            return (pla - lat) ** 2 + (pln - lon) ** 2
        for ph in sorted(data, key=dist):
            ip = ph.get("imageProcUrl")
            if ip and download(ip, dest):
                return True, ph.get("lat"), ph.get("lng")
    except Exception as e:
        return False, None, f"ERR:{e}"
    return False, None, None


def main():
    thumbs = find_thumbs()
    print(f"发现 {len(thumbs)} 张缩略图")
    manifest = {}
    mp = os.path.join(HERE, "bench100", "new_manifest.json")
    if os.path.exists(mp):
        manifest = json.load(open(mp, encoding="utf-8"))

    ok = fail = 0
    backup_dir = os.path.join(HERE, "thumbs_backup")
    os.makedirs(backup_dir, exist_ok=True)

    for fn, meta, w, h, sz in thumbs:
        dest = os.path.join(BENCH, fn)
        # 备份原缩略图
        import shutil
        shutil.copy2(dest, os.path.join(backup_dir, fn))

        if meta["src"] == "bench_hard":
            m = re.search(r"(\d{9,})", fn)
            pid = m.group(1) if m else None
            if pid:
                success, lat, lon = replace_by_id(fn, pid, dest)
            else:
                success, lat, lon = False, None, "no_id"
        else:
            info = manifest.get(fn)
            if info and "lat" in info:
                success, lat, lon = replace_by_coord(fn, info, dest)
            else:
                success, lat, lon = False, None, "no_coord"

        if success:
            from PIL import Image
            im = Image.open(dest)
            ok += 1
            print(f"  OK {fn}: {sz//1024}KB->{os.path.getsize(dest)//1024}KB {im.size} ({lat},{lon})")
        else:
            fail += 1
            print(f"  FAIL {fn}: {lon}")  # lon 此时是错误信息
        time.sleep(0.5)

    print(f"\n替换成功 {ok}, 失败 {fail}")
    # 统计最终分辨率分布
    from PIL import Image
    import collections
    sizes = []
    for fn in CATS:
        im = Image.open(os.path.join(BENCH, fn))
        sizes.append(im.size[0] * im.size[1])
    hi = sum(1 for s in sizes if s >= 1000000)
    lo = sum(1 for s in sizes if s < 40000)
    print(f"最终: >=1MP {hi}张, <40K像素(缩略图) {lo}张")


if __name__ == "__main__":
    main()
