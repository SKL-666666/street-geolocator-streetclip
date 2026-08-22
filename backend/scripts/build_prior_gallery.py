"""构建 MixVPR 参考画廊：从 AI_GeoDetect 仓库下载带真值街景图 → data/prior_gallery/。

图片来源（带城市/国家真值）：
    https://github.com/Totsamuychel/AI_GeoDetect
    webapp/static/examples/{city}/{city}_{n}.jpg   （budapest / kyiv / warsaw / prague）

用法：
    python scripts/build_prior_gallery.py                       # 默认 4 城市 × 5 张
    python scripts/build_prior_gallery.py --cities kyiv budapest
    python scripts/build_prior_gallery.py --proxy http://8.216.41.196:3829
    python scripts/build_prior_gallery.py --force               # 重新下载全部

输出：
    backend/data/prior_gallery/*.jpg
    backend/data/prior_gallery/metadata.json   # [{"file","city","country","lat","lon"}]

说明：
    - 先尝试拉取仓库 manifest.json（webapp/static/examples/manifest.json）确定每个城市的
      实际图片清单；manifest 拉不到时回退到 {city}_1..5.jpg 并跳过下载失败的条目。
    - urllib 自动遵循 HTTP_PROXY / HTTPS_PROXY 环境变量（本机可用 gh-proxy.ps1 里
      的转发代理访问 GitHub raw）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 本机无外网时可用转发代理访问 GitHub（见仓库根目录 gh-proxy.ps1）
GITHUB_PROXY = "http://8.216.41.196:3829"

GALLERY_DIR = Path(__file__).resolve().parent.parent / "data" / "prior_gallery"
DEFAULT_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/Totsamuychel/AI_GeoDetect/main/"
    "webapp/static/examples/{city}/{city}_{n}.jpg"
)
MANIFEST_URL = (
    "https://raw.githubusercontent.com/Totsamuychel/AI_GeoDetect/main/"
    "webapp/static/examples/manifest.json"
)

# 城市 → (国家, 纬度, 经度)
CITY_META: dict[str, tuple[str, float, float]] = {
    "Budapest": ("Hungary", 47.4979, 19.0402),
    "Kyiv": ("Ukraine", 50.4501, 30.5234),
    "Warsaw": ("Poland", 52.2297, 21.0122),
    "Prague": ("Czech Republic", 50.0755, 14.4378),
}
# URL 里的城市目录名（小写）
CITY_DIR_NAMES = {city.lower(): city for city in CITY_META}


def fetch(url: str, timeout: float) -> bytes:
    """带重试的 GET（遵循环境代理）。"""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dsh-prior-gallery/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"下载失败（重试 3 次）：{url} -> {last_err}")


def discover_photos() -> dict[str, list[str]]:
    """尝试从仓库 manifest.json 获取各城市图片清单；失败返回 None。"""
    try:
        data = json.loads(fetch(MANIFEST_URL, timeout=20).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[manifest] 拉取失败，回退到 {city}_{{1..5}}.jpg 约定：{type(e).__name__}: {e}")
        return None

    photos: dict[str, list[str]] = {}
    for city_entry in data.get("cities", []):
        city_id = str(city_entry.get("id", ""))
        city = CITY_DIR_NAMES.get(city_id.lower())
        if not city:
            continue
        files = []
        for rel in city_entry.get("photos", []):
            name = rel.rsplit("/", 1)[-1]
            if name:
                files.append(name)
        if files:
            photos[city] = files
    return photos


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="构建 MixVPR 参考画廊（AI_GeoDetect 街景图）")
    ap.add_argument("--cities", nargs="+", default=None,
                    help="城市（Budapest/Kyiv/Warsaw/Prague，大小写不敏感）；默认全部")
    ap.add_argument("--out", type=Path, default=GALLERY_DIR, help="输出目录")
    ap.add_argument("--url-template", type=str, default=DEFAULT_URL_TEMPLATE,
                    help="图片 URL 模板，含 {city} 与 {n} 占位符")
    ap.add_argument("--proxy", type=str, default=None,
                    help=f"HTTP/HTTPS 代理，如 {GITHUB_PROXY}")
    ap.add_argument("--timeout", type=float, default=30.0, help="单次请求超时（秒）")
    ap.add_argument("--force", action="store_true", help="忽略已存在的文件，强制重新下载")
    ap.add_argument("--max-n", type=int, default=5, help="回退模式下每个城市的图片数（默认 5）")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    if args.proxy:
        import os

        os.environ["HTTP_PROXY"] = args.proxy
        os.environ["HTTPS_PROXY"] = args.proxy

    if args.cities:
        cities = [CITY_DIR_NAMES[c.lower()] for c in args.cities if c.lower() in CITY_DIR_NAMES]
        if not cities:
            print(f"[error] 未知城市：{args.cities}，可用：{sorted(CITY_DIR_NAMES)}")
            return 1
    else:
        cities = list(CITY_META)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 图片清单
    photos_by_city = discover_photos()
    if photos_by_city is None:
        photos_by_city = {
            city: [f"{city_dir}_{n}.jpg" for n in range(1, args.max_n + 1)]
            for city_dir, city in CITY_DIR_NAMES.items()
        }

    # 2) 逐个下载
    ok: list[dict] = []
    fail: list[str] = []
    for city in cities:
        for fname in photos_by_city.get(city, []):
            city_dir = city.lower()
            n = fname.rsplit("_", 1)[-1].split(".", 1)[0]  # "budapest_1.jpg" -> "1"
            url = args.url_template.format(city=city_dir, n=n)
            dest = out_dir / fname
            if dest.is_file() and not args.force:
                print(f"[skip ] {fname}（已存在）")
                ok.append(_entry(city, fname))
                continue
            try:
                data = fetch(url, timeout=args.timeout)
                _verify_jpeg(data, fname)  # 校验确为图片
                dest.write_bytes(data)
                print(f"[ok   ] {fname}  ({len(data) / 1024:.0f} KB) <- {url}")
                ok.append(_entry(city, fname))
            except Exception as e:  # noqa: BLE001
                print(f"[fail ] {fname}  <- {url}\n        {type(e).__name__}: {e}")
                fail.append(fname)

    # 3) metadata.json
    meta_path = out_dir / "metadata.json"
    if ok:
        meta_path.write_text(
            json.dumps(ok, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    elif meta_path.exists():
        meta_path.unlink()

    # 4) 汇总
    print("\n" + "=" * 60)
    print(f"成功：{len(ok)} 张 -> {out_dir}")
    for e in ok:
        print(f"  + {e['file']}  [{e['city']} / {e['country']}]")
    if fail:
        print(f"失败：{len(fail)} 张")
        for f in fail:
            print(f"  - {f}")
    if ok:
        print(f"metadata.json 已写入：{meta_path}（{len(ok)} 条）")
        return 0
    print("[error] 没有成功下载任何图片，未生成 metadata.json")
    return 1


def _entry(city: str, fname: str) -> dict:
    country, lat, lon = CITY_META[city]
    return {
        "file": fname,
        "city": city,
        "country": country,
        "lat": lat,
        "lon": lon,
    }


def _verify_jpeg(data: bytes, fname: str) -> None:
    """用 PIL 验证下载内容确实是可解码图片，防 HTML 错误页。"""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{fname} 不是有效图片（{type(e).__name__}: {e}）") from e


if __name__ == "__main__":
    sys.exit(main())
