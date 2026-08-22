"""多 API 配置存储：data/llm_configs.json（配置列表，支持多供应商/多 Key 一键切换）。

- 每个配置：{id, name, provider, api_key, base_url, model, active, created_at}
- active=true 的配置为当前使用（启动时加载进 settings.llm_*）
- 旧版单配置文件 data/llm_key.json 在首次读取时自动迁移为列表
- key 以明文存本机（本地单机工具；对外一律脱敏展示）
- 添加时自动检测重复（同 key+模型+地址 → 不新增，激活已有）；重名自动加序号

注意：settings 必须惰性导入（config.py 的 Settings() 构造期间会调用本模块，
若顶层 import settings 会触发循环导入导致激活配置加载失败——曾导致
"重启后模型静默漂移回 .env 默认值"的回归）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional


def mask_key(key: str) -> str:
    """Key 脱敏：只露前 4 后 4（过短全掩码）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}***{key[-4:]}"


def load_configs() -> list[dict]:
    """读取配置列表（不存在/损坏时返回空；自动迁移旧 llm_key.json）。"""
    from ..config import settings  # 惰性导入（避免循环 import）

    path = settings.llm_configs_file
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:  # noqa: BLE001
            pass
    # 迁移旧版单配置（并一次性固化到 llm_configs.json）
    legacy = settings.llm_key_file
    if legacy.is_file():
        try:
            old = json.loads(legacy.read_text(encoding="utf-8"))
            if old.get("api_key"):
                migrated = [{
                    "id": uuid.uuid4().hex[:12],
                    "name": "默认配置",
                    "provider": old.get("provider", "openai"),
                    "api_key": old["api_key"],
                    "base_url": old.get("base_url", ""),
                    "model": old.get("model", ""),
                    "active": True,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }]
                save_configs(migrated)
                return migrated
        except Exception:  # noqa: BLE001
            pass
    return []


def save_configs(configs: list[dict]) -> None:
    """写回配置列表（原子写）。"""
    from ..config import settings  # 惰性导入

    path = settings.llm_configs_file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(configs, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def active_config(configs: list[dict] | None = None) -> Optional[dict]:
    """当前激活的配置（无则 None）。"""
    for c in configs or load_configs():
        if c.get("active"):
            return c
    return None


def apply_active_to_settings(configs: list[dict] | None = None) -> bool:
    """把激活配置写入 settings.llm_*（启动与切换时调用）。返回是否有激活配置。"""
    from ..config import settings  # 惰性导入

    cfg = active_config(configs)
    if cfg is None:
        return False
    settings.llm_provider = cfg.get("provider") or "openai"
    settings.llm_api_key = cfg.get("api_key", "")
    settings.llm_base_url = cfg.get("base_url", "")
    settings.llm_model = cfg.get("model", "")
    return True


def _unique_name(name: str, configs: list[dict], exclude_id: str | None = None) -> str:
    """同名配置自动加序号（"智谱 GLM · glm-4v-flash" → "... (2)"）。"""
    existing = {c.get("name") for c in configs if c.get("id") != exclude_id}
    if name not in existing:
        return name
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def add_config(name: str, api_key: str, base_url: str = "", model: str = "",
               provider: str = "openai") -> tuple[list[dict], bool]:
    """新增配置并激活（返回 (最新列表, 是否新增)；重复配置不新增，直接激活已有）。"""
    configs = load_configs()
    # 重复检测：同 key + 同模型 + 同地址 → 激活已有那条
    for c in configs:
        if (c.get("api_key") == api_key and (c.get("model") or "") == (model or "")
                and (c.get("base_url") or "") == (base_url or "")):
            c["active"] = True
            for other in configs:
                if other is not c:
                    other["active"] = False
            save_configs(configs)
            return configs, False
    for c in configs:
        c["active"] = False
    configs.append({
        "id": uuid.uuid4().hex[:12],
        "name": _unique_name(name or "未命名", configs),
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "active": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_configs(configs)
    return configs, True


def activate_config(config_id: str) -> list[dict]:
    """按 id 激活配置（返回最新列表；找不到返回原列表）。"""
    configs = load_configs()
    found = False
    for c in configs:
        c["active"] = (c.get("id") == config_id)
        if c.get("id") == config_id:
            found = True
    if found:
        save_configs(configs)
    return configs


def delete_config(config_id: str) -> list[dict]:
    """删除配置；若删除的是激活项，自动激活剩余第一条（无剩余则置空）。"""
    configs = load_configs()
    was_active = any(c.get("id") == config_id and c.get("active") for c in configs)
    configs = [c for c in configs if c.get("id") != config_id]
    if was_active and configs:
        configs[0]["active"] = True
    save_configs(configs)
    return configs


def public_configs(configs: list[dict] | None = None) -> list[dict]:
    """对外展示（key 脱敏）。"""
    return [{
        "id": c.get("id"),
        "name": c.get("name", "未命名"),
        "provider": c.get("provider", "openai"),
        "base_url": c.get("base_url", ""),
        "model": c.get("model", ""),
        "masked_key": mask_key(c.get("api_key", "")),
        "active": bool(c.get("active")),
        "created_at": c.get("created_at", ""),
    } for c in (configs if configs is not None else load_configs())]
