"""批量生成世界 Top300 城市特征档案（LLM 生成 → data/world_city_profiles.json）。

用法：
  python scripts/gen_city_profiles.py [--limit 300] [--out data/world_city_profiles.json]

- 城市清单：CITY_COORDS（按人口排序）中非中国前 limit 个
- 每城一次文本 LLM 调用（并发 3，走全局限流），输出 5-8 个中文判别关键词
- 断点续跑：已存在于输出文件的城市自动跳过；失败重试 1 次
- 产物 JSON：[{"city":en, "zh":中文, "country":en, "lat":.., "lon":.., "keywords":[...]}]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.llm.parsing import extract_json  # noqa: E402

PROMPT = """你是地理定位专家。为街景定位知识库生成城市特征档案。

城市：{city}（{country}）
请给出 6~8 个**中文判别关键词**，用于从街景照片识别该城市。维度覆盖（选最独特的）：
地标/建筑/河流山体/气候植被/饮食/方言文字/特色物件/街道样式/区域文化。
要求：
1. 必须是"看到就能联想到该城市"的具体词（如 埃菲尔铁塔、郁金香田、圣家堂、多瑙河），
   禁止通用词（城市、街道、建筑、公园）。
2. 如果该城市与其他城市共享同一地标（如多个城市都有长城），改选更独特的特征。
3. 只输出严格 JSON，不要其他文字：
{{"city": "{city}", "country": "{country}", "keywords": ["关键词1", "关键词2", ...]}}"""


def build_city_list(limit: int) -> list[dict]:
    from app.geokb.cities import CITY_COORDS
    from app.geokb.citylib import city_zh

    out = []
    for name, (lat, lon, country) in CITY_COORDS.items():
        if country == "China":
            continue
        out.append({"en": name, "zh": city_zh(name), "country": country,
                    "lat": lat, "lon": lon})
        if len(out) >= limit:
            break
    return out


async def gen_one(provider, city: dict, sem: asyncio.Semaphore) -> dict | None:
    prompt = PROMPT.format(city=city["en"], country=city["country"])
    for attempt in range(2):
        try:
            async with sem:
                res = await provider.complete_text(prompt)
            data = extract_json(res.content)
            kws = data.get("keywords") or []
            kws = [str(k).strip() for k in kws if str(k).strip()]
            if len(kws) < 4:
                raise ValueError(f"关键词过少：{len(kws)}")
            return {**city, "keywords": kws[:10]}
        except Exception as e:  # noqa: BLE001
            if attempt == 0:
                await asyncio.sleep(1.0)
                continue
            print(f"  !! {city['en']} 生成失败：{e}")
            return None


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--out", type=str, default=str(BACKEND / "data" / "world_city_profiles.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    existing: dict[str, dict] = {}
    if out_path.exists():
        for item in json.loads(out_path.read_text(encoding="utf-8")):
            existing[item["en"]] = item
    print(f"已有 {len(existing)} 城，继续生成...")

    from app.llm.factory import create_provider
    provider = create_provider()
    cities = [c for c in build_city_list(args.limit) if c["en"] not in existing]
    print(f"待生成 {len(cities)} 城（共 {args.limit} 目标）")

    sem = asyncio.Semaphore(3)
    results = await asyncio.gather(*[gen_one(provider, c, sem) for c in cities])
    ok = [r for r in results if r]
    merged = list(existing.values()) + ok
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成：新增 {len(ok)}，共 {len(merged)} 城 → {out_path}")
    if len(ok) < len(cities):
        print(f"失败 {len(cities) - len(ok)} 城（重跑脚本自动续传）")


if __name__ == "__main__":
    asyncio.run(main())
