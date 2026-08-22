"""CLIP ViT-B/16 零成本试点：本地视觉先验 vs LLM 的国家 Top1 对比。

只做本地推理（不调 LLM API）：
1. 加载 open_clip ViT-B/16（openai 权重，~150MB，HF_ENDPOINT 走 hf-mirror 国内镜像）
2. 对 eval_kartaview 全部图片编码，与 60 个主要国家文本描述算相似度 → 国家 Top5
3. 与已有 LLM 评测结果（data/eval_ab_A2.json）对比：
   - CLIP 单独国家 Top1 准确率
   - LLM 单独国家 Top1 准确率（来自 A2）
   - LLM+CLIP 投票（LLM top1 是否落在 CLIP topK 内）一致性分析

用法：python scripts/clip_pilot.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # HF 被墙，走国内镜像
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# 主要国家英文名（覆盖 eval 集 + 常见候选；文本编码一次即可）
COUNTRIES = [
    "France", "Italy", "Spain", "Austria", "Germany", "Switzerland", "Netherlands",
    "Belgium", "Luxembourg", "Portugal", "United Kingdom", "Ireland", "Denmark",
    "Sweden", "Norway", "Finland", "Iceland", "Poland", "Czechia", "Slovakia",
    "Hungary", "Romania", "Bulgaria", "Serbia", "Croatia", "Slovenia", "Greece",
    "Turkey", "Ukraine", "Russia", "Belarus", "Lithuania", "Latvia", "Estonia",
    "Moldova", "Albania", "North Macedonia", "Montenegro", "Bosnia and Herzegovina",
    "United States", "Canada", "Mexico", "Brazil", "Argentina", "Chile", "Peru",
    "Colombia", "Uruguay", "Bolivia", "Ecuador", "Venezuela", "Paraguay",
    "Japan", "South Korea", "Taiwan", "India", "Thailand", "Vietnam", "Indonesia",
    "Malaysia", "Philippines", "Singapore", "Cambodia", "Laos", "Sri Lanka", "Nepal",
    "Australia", "New Zealand", "South Africa", "Egypt", "Morocco", "Tunisia",
    "Kenya", "Nigeria", "Ghana", "Israel", "United Arab Emirates", "Saudi Arabia",
    "Qatar", "Jordan", "Lebanon", "Oman", "Kazakhstan", "Mongolia",
]

PROMPT_TEMPLATE = "a street view photo taken in {c}, typical street scene"


def load_clip():
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-16", pretrained="openai")
    model.eval()
    return model, preprocess


def clip_top_countries(model, preprocess, img_path, text_tokens) -> list[str]:
    import torch
    from PIL import Image
    img = preprocess(Image.open(img_path).convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        img_feat = model.encode_image(img)
        img_feat /= img_feat.norm(dim=-1, keepdim=True)
        sims = (img_feat @ text_tokens.T).squeeze(0)
    top = sims.topk(5)
    return [COUNTRIES[i] for i in top.indices.tolist()]


def main() -> None:
    meta = json.loads((BACKEND / "data" / "eval_kartaview" / "metadata.json").read_text(encoding="utf-8"))
    a2_path = BACKEND / "data" / "eval_ab_A2.json"
    a2 = json.loads(a2_path.read_text(encoding="utf-8")) if a2_path.exists() else None
    llm_by_file = {r["file"]: r for r in (a2 or {}).get("rows", [])} if a2 else {}

    print("加载 CLIP ViT-B/16（首次需从 hf-mirror 下载 ~150MB）...")
    t0 = time.monotonic()
    model, preprocess = load_clip()
    print(f"模型加载完成 {time.monotonic()-t0:.1f}s")

    import torch
    texts = [PROMPT_TEMPLATE.format(c=c) for c in COUNTRIES]
    with torch.no_grad():
        text_feats = model.encode_text(_tokenize(model, texts))
        text_feats /= text_feats.norm(dim=-1, keepdim=True)

    rows = []
    for m in meta:
        fname = Path(m["file"]).name
        try:
            top5 = clip_top_countries(model, preprocess, m["file"], text_feats)
        except Exception as e:  # noqa: BLE001
            print(f"  !! {fname}: {e}")
            continue
        truth = m["country"]
        llm = llm_by_file.get(fname)
        rows.append({
            "file": fname, "truth": truth, "clip_top1": top5[0], "clip_top5": top5,
            "llm_top1": (llm or {}).get("top1", ""),
            "llm_correct": bool((llm or {}).get("correct")),
            "clip_top1_correct": top5[0] == truth,
            "truth_in_clip_top3": truth in top5[:3],
            "truth_in_clip_top5": truth in top5,
        })

    n = len(rows)
    clip1 = sum(1 for r in rows if r["clip_top1_correct"])
    clip3 = sum(1 for r in rows if r["truth_in_clip_top3"])
    clip5 = sum(1 for r in rows if r["truth_in_clip_top5"])
    print(f"\n=== CLIP ViT-B/16 零样本（{n} 张，本地推理）===")
    print(f"国家 Top1: {clip1}/{n} = {clip1/n:.1%}")
    print(f"真值在 Top3: {clip3}/{n} = {clip3/n:.1%}")
    print(f"真值在 Top5: {clip5}/{n} = {clip5/n:.1%}")

    if llm_by_file:
        sub = [r for r in rows if r["llm_top1"]]
        m = len(sub)
        llm_ok = sum(1 for r in sub if r["llm_correct"])
        agree_ok = sum(1 for r in sub if r["llm_correct"] and r["truth_in_clip_top3"])
        llm_ok_clip_miss = sum(1 for r in sub if r["llm_correct"] and not r["truth_in_clip_top3"])
        llm_bad_clip_hit = sum(1 for r in sub if not r["llm_correct"] and r["truth_in_clip_top3"])
        print(f"\n=== 与 LLM（A2 评测）对比（{m} 张有 LLM 结果）===")
        print(f"LLM 单独 Top1: {llm_ok}/{m} = {llm_ok/m:.1%}")
        print(f"LLM 对 + 真值在 CLIP Top3（双通道一致）: {agree_ok}/{m}")
        print(f"LLM 对但 CLIP Top3 漏（CLIP 拖后腿风险）: {llm_ok_clip_miss}/{m}")
        print(f"LLM 错但真值在 CLIP Top3（CLIP 可救回）: {llm_bad_clip_hit}/{m}")
        # 简单投票：LLM top1 在 CLIP top3 → 保持；否则提示分歧
        for r in sub:
            flag = "一致" if r["truth_in_clip_top3"] else ("⚠分歧" if r["llm_top1"] not in r["clip_top5"] else "CLIP弱")
            print(f"  {r['file']:<16} 真值={r['truth']:<10} LLM={r['llm_top1']:<12} "
                  f"CLIP_top1={r['clip_top1']:<12} [{flag}]")

    out = BACKEND / "data" / "clip_pilot_results.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已保存 {out}")


def _tokenize(model, texts):
    """open_clip 的 tokenizer（版本差异兜底）。"""
    import open_clip
    tok = open_clip.tokenize(texts)
    return tok


if __name__ == "__main__":
    main()
