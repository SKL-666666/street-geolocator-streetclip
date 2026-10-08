"""GeoCLIP (Xenova ONNX) 国家级评测。
链路: vision_model(图->512d) -> 与 location_model(100K GPS->100K 512d) 余弦相似
     -> Top-K GPS -> 每个 GPS 用最近世界城市反查国家 -> 国家投票 -> Top1。
复用统一的 bench 加载 + 归一化。CPU。
"""
import io
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "street-geolocator-streetclip"))
sys.path.insert(0, HERE)

from iso_map import ISO2_TO_NAME  # noqa: E402

W = os.path.join(HERE, "weights", "geoclip")
BENCHES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_final"),
]
GALLERY_GEOJSON = None  # 用 world_cities 反查
CITIES = os.path.join(ROOT, "backend", "data", "geokb", "world_cities.json")
K = 20  # Top-K GPS 参与投票

_city_lats = None
_city_lons = None
_city_iso = None
_coord_country_cache = {}
_poly_geoms = None

NE_COUNTRIES = os.path.join(ROOT, "backend", "data", "geokb", "ne_countries.json")


def load_polygons():
    """加载 Natural Earth 国界多边形（prepared，用于点在国界内判定）。"""
    global _poly_geoms
    if _poly_geoms is not None:
        return
    from shapely.geometry import shape
    from shapely.prepared import prep
    d = json.load(open(NE_COUNTRIES, encoding="utf-8"))
    _poly_geoms = [(f["properties"]["name"], prep(shape(f["geometry"])))
                   for f in d["features"]]


def load_cities():
    global _city_lats, _city_lons, _city_iso
    if _city_lats is not None:
        return
    rows = json.load(open(CITIES, encoding="utf-8"))
    _city_lats = np.array([float(r["lat"]) for r in rows], dtype=np.float32)
    _city_lons = np.array([float(r["lng"]) for r in rows], dtype=np.float32)
    _city_iso = [r["country"] for r in rows]


def coord_to_country(lat, lon):
    """坐标→国家：国界多边形包含优先（乡村/荒野/远海更准），无命中则回退最近城市。"""
    key = (round(lat, 2), round(lon, 2))
    if key in _coord_country_cache:
        return _coord_country_cache[key]
    name = None
    # 1) 点在国界多边形内
    try:
        load_polygons()
        from shapely.geometry import Point
        pt = Point(lon, lat)  # shapely 用 (x=lon, y=lat)
        for cname, pg in _poly_geoms:
            if pg.contains(pt):
                name = cname
                break
    except Exception:
        pass
    # 2) 回退最近城市（海上/边界外）
    if name is None:
        load_cities()
        latv = _city_lats
        mask = np.abs(latv - lat) < 3.0
        if mask.sum() < 5:
            mask = np.ones_like(latv, dtype=bool)
        lats = _city_lats[mask]
        lons = _city_lons[mask]
        isos = [c for c, m in zip(_city_iso, mask) if m]
        d2 = (lats - lat) ** 2 + ((lons - lon) * np.cos(np.radians(lat))) ** 2
        idx = int(np.argmin(d2))
        name = ISO2_TO_NAME.get(isos[idx], isos[idx])
    if len(_coord_country_cache) < 500000:
        _coord_country_cache[key] = name
    return name


def _unused_coord_to_country(lat, lon):
    """旧版：最近世界城市（仅作回退逻辑参考）。"""
    load_cities()
    key = (round(lat, 1), round(lon, 1))
    if key in _coord_country_cache:
        return _coord_country_cache[key]
    # 粗筛：先按 lat 范围裁剪，减少计算
    latv = _city_lats
    mask = np.abs(latv - lat) < 3.0
    if mask.sum() < 5:
        mask = np.ones_like(latv, dtype=bool)
    lats = _city_lats[mask]
    lons = _city_lons[mask]
    isos = [c for c, m in zip(_city_iso, mask) if m]
    d2 = (lats - lat) ** 2 + ((lons - lon) * np.cos(np.radians(lat))) ** 2
    idx = int(np.argmin(d2))
    name = ISO2_TO_NAME.get(isos[idx], isos[idx])
    if len(_coord_country_cache) < 500000:
        _coord_country_cache[key] = name
    return name


def norm_country(name):
    n = name.strip().lower()
    alias = {
        "uk": "united kingdom", "usa": "united states",
        "united states of america": "united states",
        "czech republic": "czechia", "russian federation": "russia",
        "turkiye": "turkey", "republic of korea": "south korea",
        "vietnam": "vietnam",
    }
    return alias.get(n, n)


def load_gt(bench_dir):
    with open(os.path.join(bench_dir, "ground_truth.json"), encoding="utf-8") as f:
        return json.load(f)


def build_gallery_embeds(sess, location_model_in, coords):
    """100K GPS -> location_model -> embeds (分批)。返回 (N,512) float32。"""
    import onnxruntime as ort
    out_batches = []
    B = 4096
    for i in range(0, len(coords), B):
        chunk = np.asarray(coords[i:i + B], dtype=np.float32)
        emb = location_model_in.run(None, {"location": chunk})[0]
        out_batches.append(emb)
    return np.vstack(out_batches)


def main():
    import onnxruntime as ort
    from transformers import CLIPImageProcessor

    t0 = time.time()
    so = ort.SessionOptions()
    so.intra_op_num_threads = os.cpu_count() or 4
    vis = ort.InferenceSession(
        os.path.join(W, "vision_model.onnx"), so,
        providers=["CPUExecutionProvider"])
    loc = ort.InferenceSession(
        os.path.join(W, "location_model.onnx"), so,
        providers=["CPUExecutionProvider"])
    proc = CLIPImageProcessor.from_pretrained(
        "openai/clip-vit-large-patch14", local_files_only=False)

    coords = json.load(open(os.path.join(W, "coordinates_100K.json"), encoding="utf-8"))
    print(f"[load] sessions + gallery coords ({len(coords)}) ready", file=sys.stderr)

    # 一次性算 100K GPS embeds
    tg = time.time()
    gallery_emb = build_gallery_embeds(loc, loc, coords)
    gallery_emb = gallery_emb / (np.linalg.norm(gallery_emb, axis=1, keepdims=True) + 1e-9)
    print(f"[gallery] 100K GPS embed done in {time.time()-tg:.1f}s", file=sys.stderr)

    # 预反查每个 gallery 坐标的国家（一次，之后 O(1)）
    tc = time.time()
    gallery_country = [coord_to_country(lat, lon) for lat, lon in coords]
    print(f"[country] gallery->country done in {time.time()-tc:.1f}s", file=sys.stderr)

    load_s = time.time() - t0
    print(f"[warmup] total load {load_s:.1f}s", file=sys.stderr)

    total = correct = 0
    lat_list = []
    per_bench = {}

    for bench_dir in BENCHES:
        name = os.path.basename(bench_dir)
        gt = load_gt(bench_dir)
        b_t = b_c = 0
        for fname, truth in gt.items():
            img_path = os.path.join(bench_dir, fname)
            if not os.path.exists(img_path):
                continue
            from PIL import Image
            img = Image.open(img_path).convert("RGB")
            inputs = proc(images=img, return_tensors="np")
            t1 = time.time()
            img_emb = vis.run(None, {"pixel_values": inputs["pixel_values"]})[0]
            img_emb = img_emb / (np.linalg.norm(img_emb, axis=1, keepdims=True) + 1e-9)
            sims = (gallery_emb @ img_emb[0])
            top_idx = np.argsort(-sims)[:K]
            # 国家投票
            votes = {}
            for gi in top_idx:
                c = gallery_country[int(gi)]
                votes[c] = votes.get(c, 0) + 1.0
            pred = max(votes.items(), key=lambda x: x[1])[0] if votes else "?"
            dt = (time.time() - t1) * 1000
            lat_list.append(dt)
            b_t += 1
            hit = norm_country(pred) == norm_country(truth)
            b_c += 1 if hit else 0
            if not hit:
                print(f"  [miss] {fname}: pred={pred} | truth={truth}", file=sys.stderr)
        per_bench[name] = (b_c, b_t)
        total += b_t
        correct += b_c

    lat_list.sort()
    avg = sum(lat_list) / len(lat_list)
    med = lat_list[len(lat_list) // 2]
    print("\n===== GeoCLIP (ONNX, 国家级 Top-1, CPU) =====")
    for n, (c, t) in per_bench.items():
        print(f"  {n:14s}: {c}/{t} = {100*c/t:.1f}%")
    print(f"  {'总计':12s}: {correct}/{total} = {100*correct/total:.1f}%")
    print(f"  单张耗时: 平均 {avg:.0f}ms | 中位 {med:.0f}ms | 加载 {load_s:.1f}s")


if __name__ == "__main__":
    main()
