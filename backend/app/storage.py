"""任务结果持久化：简单 JSON 文件（单机够用，Phase 3 可换 SQLite）。

B6：保留上限 + TTL 修剪，防止 tasks.json 无限膨胀。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import settings
from .schemas import TaskResult


def _remove_image(task_id: str) -> None:
    """删除任务对应的原图文件（尽力而为，失败不阻塞）。"""
    try:
        from .config import settings
        for p in settings.upload_dir.glob(f"{task_id}.*"):
            try:
                p.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


class TaskStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._cache: dict[str, TaskResult] = {}
        self._load()

    def _load(self) -> None:
        if not self.db_path.exists():
            return
        try:
            data = json.loads(self.db_path.read_text(encoding="utf-8"))
            for tid, payload in data.items():
                self._cache[tid] = TaskResult.model_validate(payload)
        except Exception:
            # 损坏的任务文件不阻塞启动
            self._cache = {}

    def save(self, result: TaskResult) -> None:
        self._cache[result.task_id] = result
        # 异步写盘（尽力而为，不阻塞管线）
        asyncio.create_task(self._persist())

    async def _persist(self) -> None:
        async with self._lock:
            self._prune()
            payload = {tid: r.model_dump(mode="json") for tid, r in self._cache.items()}
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.db_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.db_path)

    def _prune(self) -> None:
        """B6：按上限与 TTL 修剪（保留最近、丢弃过期），并清理原图文件。"""
        removed: list[str] = []
        cutoff = datetime.now() - timedelta(days=settings.cache_ttl_days)
        for tid in list(self._cache.keys()):
            r = self._cache[tid]
            if r.created_at < cutoff:
                del self._cache[tid]
                removed.append(tid)
        if len(self._cache) > settings.cache_max_tasks:
            ordered = sorted(self._cache.values(), key=lambda r: r.created_at, reverse=True)
            keep = {r.task_id for r in ordered[: settings.cache_max_tasks]}
            for tid in list(self._cache.keys()):
                if tid not in keep:
                    del self._cache[tid]
                    removed.append(tid)
        for tid in removed:
            _remove_image(tid)

    def get(self, task_id: str) -> Optional[TaskResult]:
        return self._cache.get(task_id)

    def delete(self, task_id: str) -> bool:
        """B6：删除单条任务（供 API 清理用），同时清理原图文件。"""
        if task_id in self._cache:
            del self._cache[task_id]
            _remove_image(task_id)
            asyncio.create_task(self._persist())
            return True
        return False

    def list_recent(self, limit: int = 20) -> list[TaskResult]:
        items = sorted(self._cache.values(), key=lambda r: r.created_at, reverse=True)
        return items[:limit]
