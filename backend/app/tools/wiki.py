"""Wikipedia 查证工具：搜索店名/地标/独特文字。

可配置 WIKI_BASE_URL 指向镜像（如国内可达的镜像）或替代百科。
"""
from __future__ import annotations

import re

import httpx

from . import ToolNetworkError

DEFAULT_BASE = "https://en.wikipedia.org"


async def wiki_search(query: str, lang: str = "en", base_url: str = "",
                      timeout: float = 3.0, limit: int = 3) -> list[dict]:
    """关键词 → 百科条目摘要。返回 [{title, snippet, url}]。

    网络级失败抛 ToolNetworkError；HTTP 错误/无结果返回空列表。
    """
    q = query.strip()
    if not q or len(q) < 3:
        return []
    base = base_url or f"https://{lang}.wikipedia.org"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{base}/w/api.php",
                params={
                    "action": "query", "list": "search", "srsearch": q,
                    "format": "json", "srlimit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except ToolNetworkError:
        raise
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
        raise ToolNetworkError(f"百科网络不可达：{base}") from None
    except Exception:
        return []
    out = []
    for it in (data.get("query") or {}).get("search", []):
        title = it.get("title", "")
        snippet = re.sub(r"<[^>]+>", "", it.get("snippet", ""))
        out.append({
            "title": title,
            "snippet": snippet[:220],
            "url": f"{base}/wiki/{title.replace(' ', '_')}",
        })
    return out
