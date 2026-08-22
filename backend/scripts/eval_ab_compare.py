"""汇总 A/B 评测结果：知识库丰富前(B) vs 后(A) 的国家 Top1 对比表。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    pa = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND / "data" / "eval_ab_A.json"
    pb = Path(sys.argv[2]) if len(sys.argv) > 2 else BACKEND / "data" / "eval_ab_B.json"
    a, b = load(pa), load(pb)
    rows_a = {r["file"]: r for r in a["rows"]}
    rows_b = {r["file"]: r for r in b["rows"]}

    sa, sb = a["summary"], b["summary"]
    print(f"{'文件':<16}{'真值':<10}{'B旧Top1':<14}{'A新Top1':<14}{'B':<4}{'A':<4}")
    print("-" * 62)
    flip_ok, flip_bad = [], []
    for fname in rows_a:
        ra, rb = rows_a.get(fname), rows_b.get(fname)
        truth = ra["truth"]
        top_b = rb.get("top1", "?") if rb else "?"
        top_a = ra.get("top1", "?")
        cb = "✓" if rb and rb.get("correct") else "✗"
        ca = "✓" if ra.get("correct") else "✗"
        print(f"{fname:<16}{truth:<10}{top_b:<14}{top_a:<14}{cb:<4}{ca:<4}")
        if cb != ca:
            (flip_ok if ca == "✓" else flip_bad).append(
                f"{fname}: {truth}  {top_b}→{top_a}")

    print("-" * 62)
    print(f"B(旧知识库): {sb['correct']}/{sb['total']} = {sb['accuracy_top1']:.1%}"
          f"（降级 {sb['degraded']}）")
    print(f"A(新知识库): {sa['correct']}/{sa['total']} = {sa['accuracy_top1']:.1%}"
          f"（降级 {sa['degraded']}）")
    delta = sa["accuracy_top1"] - sb["accuracy_top1"]
    print(f"Δ = {delta:+.1%}")
    if flip_ok:
        print("\n改进（B错→A对）:")
        for x in flip_ok:
            print("  +", x)
    if flip_bad:
        print("\n回退（B对→A错）:")
        for x in flip_bad:
            print("  -", x)
    if not flip_ok and not flip_bad:
        print("\n无翻转：两版本判定完全一致")


if __name__ == "__main__":
    main()
