"""把 data/world_city_profiles.json 转换为 app/geokb/world_cities.py（PyInstaller 打包友好）。

用法：python scripts/json_to_py.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SRC = BACKEND / "data" / "world_city_profiles.json"
DST = BACKEND / "app" / "geokb" / "world_cities.py"


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    out = ['"""世界城市特征档案（LLM 批量生成，人口 Top300 非中国城市）。',
           '由 scripts/gen_city_profiles.py 生成 → scripts/json_to_py.py 转换，勿手改。',
           '"""',
           "from __future__ import annotations",
           "",
           "WORLD_CITY_PROFILES: list[dict] = ["]
    for c in data:
        kw = ",\n            ".join(f'"{k}"' for k in c["keywords"])
        out.append("    {")
        out.append(f'        "en": {c["en"]!r}, "zh": {c["zh"]!r}, '
                   f'"country": {c["country"]!r},')
        out.append(f'        "lat": {c["lat"]!r}, "lon": {c["lon"]!r},')
        out.append("        \"keywords\": [")
        out.append(f"            {kw},")
        out.append("        ],")
        out.append("    },")
    out.append("]")
    DST.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(data)} 城 → {DST}")


if __name__ == "__main__":
    sys.exit(main())
