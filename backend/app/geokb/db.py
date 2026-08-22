"""Geo-KB 数据库层：从种子数据构建 SQLite，支持后续扩展/覆盖。

表结构：
- countries(id, name UNIQUE, driving_side, speed_unit, plates, tld, phone, currency, plugs)
- country_langs(country_id, lang)          # 语言
- country_scripts(country_id, script)      # 文字体系
- country_suffixes(country_id, suffix)     # 街道后缀
- sign_keywords(keyword, countries_json)   # 路牌关键词 → 国家列表
- mailbox_keywords(keyword, countries_json)
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS countries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    driving_side TEXT,
    speed_unit TEXT,
    plates TEXT,
    tld TEXT,
    phone TEXT,
    currency TEXT,
    plugs TEXT
);
CREATE TABLE IF NOT EXISTS country_langs (
    country_id INTEGER NOT NULL REFERENCES countries(id),
    lang TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS country_scripts (
    country_id INTEGER NOT NULL REFERENCES countries(id),
    script TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS country_suffixes (
    country_id INTEGER NOT NULL REFERENCES countries(id),
    suffix TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sign_keywords (
    keyword TEXT PRIMARY KEY,
    countries_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mailbox_keywords (
    keyword TEXT PRIMARY KEY,
    countries_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bollard_keywords (
    keyword TEXT PRIMARY KEY,
    countries_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hydrant_keywords (
    keyword TEXT PRIMARY KEY,
    countries_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pole_keywords (
    keyword TEXT PRIMARY KEY,
    countries_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roadmark_keywords (
    keyword TEXT PRIMARY KEY,
    countries_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plate_keywords (
    keyword TEXT PRIMARY KEY,
    countries_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_langs ON country_langs(lang);
CREATE INDEX IF NOT EXISTS idx_suffixes ON country_suffixes(suffix);
"""

_KEYWORD_TABLES = (
    "sign_keywords", "mailbox_keywords", "bollard_keywords",
    "hydrant_keywords", "pole_keywords", "roadmark_keywords", "plate_keywords",
)

# schema 版本：结构变更时 +1，load 时发现旧版本自动重建
SCHEMA_VERSION = 2


def _rebuild_if_stale(db_path: Path) -> None:
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        try:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        ver = 0
    if ver < SCHEMA_VERSION:
        build_database(db_path)


def build_database(db_path: Path | None = None) -> Path:
    """构建（或重建）SQLite 数据库，返回路径。"""
    import sqlite3

    from .countries import (
        BOLLARD_KEYWORDS,
        COUNTRY_SEED,
        HYDRANT_KEYWORDS,
        MAILBOX_KEYWORDS,
        PLATE_KEYWORDS,
        POLE_KEYWORDS,
        ROADMARK_KEYWORDS,
        SIGN_KEYWORDS,
    )

    db_path = db_path or (settings.data_dir / "geokb.sqlite")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        # 幂等：清空重灌
        all_tables = ("countries", "country_langs", "country_scripts",
                      "country_suffixes") + _KEYWORD_TABLES
        for table in all_tables:
            conn.execute(f"DELETE FROM {table}")
        for c in COUNTRY_SEED:
            cur = conn.execute(
                "INSERT INTO countries(name, driving_side, speed_unit, plates, tld, phone, currency, plugs) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (c["name"], c.get("driving_side"), c.get("speed_unit"), c.get("plates", ""),
                 c.get("tld", ""), c.get("phone", ""), c.get("currency", ""), c.get("plugs", "")),
            )
            cid = cur.lastrowid
            conn.executemany("INSERT INTO country_langs(country_id, lang) VALUES (?,?)",
                             [(cid, lang) for lang in c.get("languages", [])])
            conn.executemany("INSERT INTO country_scripts(country_id, script) VALUES (?,?)",
                             [(cid, s) for s in c.get("scripts", [])])
            conn.executemany("INSERT INTO country_suffixes(country_id, suffix) VALUES (?,?)",
                             [(cid, s) for s in c.get("suffixes", [])])
        kw_sources = {
            "sign_keywords": SIGN_KEYWORDS,
            "mailbox_keywords": MAILBOX_KEYWORDS,
            "bollard_keywords": BOLLARD_KEYWORDS,
            "hydrant_keywords": HYDRANT_KEYWORDS,
            "pole_keywords": POLE_KEYWORDS,
            "roadmark_keywords": ROADMARK_KEYWORDS,
            "plate_keywords": PLATE_KEYWORDS,
        }
        for table, kw in kw_sources.items():
            conn.executemany(f"INSERT INTO {table}(keyword, countries_json) VALUES (?,?)",
                             [(k, json.dumps(v, ensure_ascii=False)) for k, v in kw.items()])
        conn.commit()
    finally:
        conn.close()
    return db_path


def load_database(db_path: Path | None = None) -> dict:
    """读取数据库为内存结构（engine 使用）。"""
    import sqlite3

    db_path = db_path or (settings.data_dir / "geokb.sqlite")
    if not db_path.exists():
        build_database(db_path)
    else:
        _rebuild_if_stale(db_path)

    conn = sqlite3.connect(db_path)
    data: dict = {"countries": {}, "sign_keywords": {}, "mailbox_keywords": {},
                  "bollard_keywords": {}, "hydrant_keywords": {}, "pole_keywords": {},
                  "roadmark_keywords": {}, "plate_keywords": {}}
    id_to_name: dict[int, str] = {}
    try:
        for row in conn.execute("SELECT id, name, driving_side, speed_unit, plates FROM countries"):
            cid, name, side, speed, plates = row
            id_to_name[cid] = name
            data["countries"][name] = {
                "driving_side": side, "speed_unit": speed, "plates": plates or "",
                "languages": [], "scripts": [], "suffixes": [],
            }
        for cid, lang in conn.execute("SELECT country_id, lang FROM country_langs"):
            name = id_to_name.get(cid)
            if name:
                data["countries"][name]["languages"].append(lang)
        for cid, script in conn.execute("SELECT country_id, script FROM country_scripts"):
            name = id_to_name.get(cid)
            if name:
                data["countries"][name]["scripts"].append(script)
        for cid, suffix in conn.execute("SELECT country_id, suffix FROM country_suffixes"):
            name = id_to_name.get(cid)
            if name:
                data["countries"][name]["suffixes"].append(suffix)
        for table in _KEYWORD_TABLES:
            for kw, j in conn.execute(f"SELECT keyword, countries_json FROM {table}"):
                data[table][kw] = json.loads(j)
    finally:
        conn.close()
    return data
