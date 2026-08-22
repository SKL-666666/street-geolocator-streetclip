"""最小验证：MixVPR 描述子 + 参考画廊检索（任务要求的端到端检查）。

用法：
    python scripts/validate_prior.py [图片...]
    默认对 backend/data 下的 real_budapest.jpg / real_kyiv.jpg / real_budapest3.jpg 检索，
    也可传入任意图片路径。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.embedding.mixvpr import MixVPRDescriptor  # noqa: E402
from app.pipeline.prior import PriorEngine  # noqa: E402


def main() -> int:
    images = [Path(p) for p in sys.argv[1:]] or [
        BACKEND_DIR / "data" / "real_budapest.jpg",
        BACKEND_DIR / "data" / "real_kyiv.jpg",
        BACKEND_DIR / "data" / "real_budapest3.jpg",
    ]

    desc = MixVPRDescriptor()
    t0 = time.monotonic()
    engine = PriorEngine(descriptor=desc)
    print(f"[env] torch 描述子维度: {desc.descriptor_dim}  权重: {desc.weights_path}")
    print(f"[env] 画廊规模: {engine.gallery_size}  构建耗时: {time.monotonic() - t0:.1f}s")
    print(f"[env] 城市坐标表: {engine.city_coordinates()}")
    if engine.build_error:
        print(f"[warn] 画廊构建提示: {engine.build_error}")
    print()

    for path in images:
        if not path.is_file():
            print(f"[skip] 不存在: {path}")
            continue
        data = path.read_bytes()
        t0 = time.monotonic()
        result = engine.compute_prior(data)
        elapsed = time.monotonic() - t0
        name = path.name
        if result is None:
            print(f"[{name}] -> (无结果：画廊为空或模型不可用)")
            continue
        print(
            f"[{name}] top1 城市 = {result.city} ({result.country})  "
            f"score = {result.score:.4f}  "
            f"坐标 = ({result.lat:.4f}, {result.lon:.4f})  "
            f"gallery = {result.gallery_size}  耗时 {elapsed:.2f}s"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
