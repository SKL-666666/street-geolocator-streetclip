"""新架构 A/B 端到端评测：
  原版: StreetCLIP国家Top1 + CLIP-B/16城市池
  新版: margin>=0.04直通 / <0.04 Top3内复核(换prompt) + StreetCLIP城市池
国家评测: bench_final(89张) | 城市评测: eval_kartaview(32张, 端到端)
输出: 准确率 + 单图耗时。
"""
import json
import os
import sys
import time

import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "street-geolocator-streetclip", "backend")))

from PIL import Image  # noqa: E402
from app.geokb import local_engine as le  # noqa: E402
from app.geokb.local_engine import COUNTRIES, _country_cities, _city_pool_size  # noqa: E402

MARGIN = 0.04
CITY_TEMPLATES = [
    "a street view photo taken in {c}",
    "a photo of the city of {c}",
    "urban street scene in {c}",
]
RECHECK_TEMPLATES = [
    "a street view photo taken in {c}, recognizable by road signs, language and architecture",
    "climate, vegetation and building style typical of {c}",
    "road infrastructure and landscape of {c}",
]


def norm(s):
    n = s.strip().lower()
    alias = {"uk": "united kingdom", "usa": "united states",
             "czech republic": "czechia", "russian federation": "russia",
             "turkiye": "turkey", "republic of korea": "south korea"}
    return alias.get(n, n)


class Engine:
    """StreetCLIP 单实例：一次图像编码 → 国家/复核/城市全部打分(复用特征)。"""

    def __init__(self):
        self.model, self.proc, self.nat_tf = le._load_engine()
        # 国家文本(原版3模板) 已在 le._load_engine 缓存
        self._recheck_tf = None
        self._city_tf_cache = {}

    def encode(self, pil):
        inp = self.proc(images=pil, return_tensors="pt")
        with torch.no_grad():
            f = self.model.get_image_features(**inp)
        return f / f.norm(dim=-1, keepdim=True)

    def _text(self, templates, labels):
        key = (tuple(templates), tuple(labels))
        cached = self._city_tf_cache.get(key)
        if cached is not None:
            return cached
        texts = [t.format(c=c) for c in labels for t in templates]
        inp = self.proc(text=texts, return_tensors="pt", padding=True)
        with torch.no_grad():
            tf = self.model.get_text_features(**inp)
        tf = tf / tf.norm(dim=-1, keepdim=True)
        tf = tf.view(len(labels), len(templates), -1).mean(1)
        tf = tf / tf.norm(dim=-1, keepdim=True)
        if len(self._city_tf_cache) < 64:
            self._city_tf_cache[key] = tf
        return tf

    def country_scores(self, feat):
        """原版国家打分(3模板均值), 返回 [(label, score)] 降序。"""
        sims = (feat @ self.nat_tf.T).squeeze(0)
        scores = []
        for i, c in enumerate(COUNTRIES):
            s = sims[i * 3:(i + 1) * 3].mean().item()
            scores.append((c, s))
        scores.sort(key=lambda x: -x[1])
        return scores

    def recheck(self, feat, top_labels):
        """Top-N 内换 prompt 复核打分。"""
        tf = self._text(RECHECK_TEMPLATES, top_labels)
        sims = (feat @ tf.T).squeeze(0)
        pairs = sorted(zip(top_labels, sims.tolist()), key=lambda x: -x[1])
        return pairs

    def city_top1(self, feat, country):
        """StreetCLIP 在该国城市池判城市, 返回 (city, score)。"""
        country = {"United Kingdom": "United Kingdom"}.get(country, country)
        from app.geokb.countries import COUNTRY_ALIASES
        country = COUNTRY_ALIASES.get(country, country)
        cities = _country_cities(country, _city_pool_size(country))
        if not cities:
            return None, 0.0
        tf = self._text(CITY_TEMPLATES, cities)
        sims = (feat @ tf.T).squeeze(0)
        i = int(sims.argmax())
        return cities[i], float(sims[i])


def clipb16_city_top1(pil, country):
    """原版第二级: CLIP-B/16 城市池打分(独立编码)。"""
    import open_clip as oc
    from app.geokb.countries import COUNTRY_ALIASES
    country = COUNTRY_ALIASES.get(country, country)
    cities = _country_cities(country, _city_pool_size(country))
    if not cities:
        return None, 0.0
    model, preprocess = le._load_city_engine()
    texts = [f"a street view photo taken in {c}" for c in cities]
    with torch.no_grad():
        tf = model.encode_text(oc.tokenize(texts))
        tf = tf / tf.norm(dim=-1, keepdim=True)
        x = preprocess(pil).unsqueeze(0)
        f = model.encode_image(x)
        f = f / f.norm(dim=-1, keepdim=True)
        sims = (f @ tf.T).squeeze(0)
    i = int(sims.argmax())
    return cities[i], float(sims[i])


def eval_country(eng):
    """国家级: bench_final 89张, 新旧对比。"""
    cats = json.load(open(os.path.join(HERE, "bench_final", "categories.json"), encoding="utf-8"))
    res = {"old_ok": 0, "new_ok": 0, "n": 0,
           "old_ms": [], "new_ms": [], "recheck_used": 0, "recheck_rescued": 0, "recheck_killed": 0}
    for fn, meta in cats.items():
        pil = Image.open(os.path.join(HERE, "bench_final", fn)).convert("RGB")
        truth = meta["country"]
        # 新版: 一次编码
        t0 = time.time()
        feat = eng.encode(pil)
        scores = eng.country_scores(feat)
        new_pred = scores[0][0]
        margin = scores[0][1] - scores[1][1]
        if margin < MARGIN:
            res["recheck_used"] += 1
            # Top3 内复核(排除Top1强制换?) → V1: 含Top3全体
            top3 = [s[0] for s in scores[:3]]
            rc = eng.recheck(feat, top3)
            new_pred = rc[0][0]
        res["new_ms"].append((time.time() - t0) * 1000)
        # 原版: 同编码同打分取Top1(等价于不复核)
        old_pred = scores[0][0]
        nok = norm(new_pred) == norm(truth)
        ook = norm(old_pred) == norm(truth)
        res["n"] += 1
        res["new_ok"] += nok
        res["old_ok"] += ook
        if margin < MARGIN and not ook and nok:
            res["recheck_rescued"] += 1
        if margin < MARGIN and ook and not nok:
            res["recheck_killed"] += 1
    return res


def eval_city(eng):
    """城市级: eval_kartaview 32张端到端(国家也自己判), 新旧对比。"""
    EVAL = os.path.join(HERE, "..", "street-geolocator-streetclip", "backend", "data", "eval_kartaview")
    rows = json.load(open(os.path.join(EVAL, "metadata.json"), encoding="utf-8"))
    res = {"old_city_ok": 0, "new_city_ok": 0, "old_country_ok": 0, "new_country_ok": 0,
           "n": 0, "old_ms": [], "new_ms": []}
    for row in rows:
        fp = os.path.join(EVAL, os.path.basename(row["file"]))
        if not os.path.exists(fp):
            continue
        truth_city = row["city"]
        truth_country = row["country"]
        pil = Image.open(fp).convert("RGB")
        # ---- 新版: 一次编码 → 国家(分诊) → StreetCLIP城市 ----
        t0 = time.time()
        feat = eng.encode(pil)
        scores = eng.country_scores(feat)
        ctry = scores[0][0]
        if scores[0][1] - scores[1][1] < MARGIN:
            rc = eng.recheck(feat, [s[0] for s in scores[:3]])
            ctry = rc[0][0]
        city, _ = eng.city_top1(feat, ctry)
        res["new_ms"].append((time.time() - t0) * 1000)
        # ---- 原版: SC国家Top1 + CLIP-B/16城市 ----
        t0 = time.time()
        old_ctry = scores[0][0]  # 同SC打分(原版无分诊)
        old_city, _ = clipb16_city_top1(pil, old_ctry)
        res["old_ms"].append((time.time() - t0) * 1000)
        res["n"] += 1
        res["new_country_ok"] += norm(ctry) == norm(truth_country)
        res["old_country_ok"] += norm(old_ctry) == norm(truth_country)
        res["new_city_ok"] += norm(city or "") == norm(truth_city)
        res["old_city_ok"] += norm(old_city or "") == norm(truth_city)
    return res


def main():
    t0 = time.time()
    eng = Engine()
    print(f"[load] {time.time()-t0:.1f}s", file=sys.stderr)

    print("=" * 56)
    print(f"国家级 A/B (bench_final 89张, margin阈值={MARGIN})")
    r = eval_country(eng)
    print(f"  原版(纯SC Top1):      {r['old_ok']}/{r['n']} = {100*r['old_ok']/r['n']:.1f}%")
    print(f"  新版(分诊+Top3复核):   {r['new_ok']}/{r['n']} = {100*r['new_ok']/r['n']:.1f}%")
    print(f"  复核触发 {r['recheck_used']}张: 救回 {r['recheck_rescued']} / 误杀 {r['recheck_killed']}")
    print(f"  新版单图: 平均{sum(r['new_ms'])/len(r['new_ms']):.0f}ms")

    print("=" * 56)
    print("城市级 A/B (eval_kartaview 32张, 端到端)")
    c = eval_city(eng)
    print(f"  国家: 原版 {c['old_country_ok']}/{c['n']} = {100*c['old_country_ok']/c['n']:.1f}%"
          f" | 新版 {c['new_country_ok']}/{c['n']} = {100*c['new_country_ok']/c['n']:.1f}%")
    print(f"  城市: 原版(SC+CLIP-B16) {c['old_city_ok']}/{c['n']} = {100*c['old_city_ok']/c['n']:.1f}%"
          f" | 新版(SC+SC) {c['new_city_ok']}/{c['n']} = {100*c['new_city_ok']/c['n']:.1f}%")
    print(f"  耗时: 原版 {sum(c['old_ms'])/len(c['old_ms']):.0f}ms/张 | "
          f"新版 {sum(c['new_ms'])/len(c['new_ms']):.0f}ms/张")

    out = {"country": {k: v for k, v in r.items() if not k.endswith("_ms")},
           "city": {k: v for k, v in c.items() if not k.endswith("_ms")}}
    json.dump(out, open(os.path.join(HERE, "ab_newarch_result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\nsaved ab_newarch_result.json")


if __name__ == "__main__":
    main()
