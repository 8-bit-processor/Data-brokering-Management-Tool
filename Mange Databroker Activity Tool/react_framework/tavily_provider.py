"""Tavily adapter for approved, non-identifying public web searches."""

import json
import os
from datetime import datetime, timezone
from http.client import HTTPException
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from react_framework.research import PublicSource


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_RESPONSE_BYTES = 1_000_000
MAX_SNIPPET_CHARS = 2_000


class TavilySearchProvider:
    """Search public web results through Tavily's documented Search API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY")

    def search_public(self, query: str, limit: int) -> list[PublicSource]:
        """Return attributed results for one approved query."""
        if not query.strip() or len(query) > 2_000:
            raise ValueError("Research query must contain 1 to 2000 characters.")
        if not 1 <= limit <= 10:
            raise ValueError("Public search limit must be between 1 and 10.")

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            headers["X-Tavily-Access-Mode"] = "keyless"
        request = Request(
            TAVILY_SEARCH_URL,
            data=json.dumps(
                {
                    "query": query,
                    "search_depth": "basic",
                    "max_results": limit,
                    "include_answer": False,
                    "include_raw_content": False,
                }
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("Public search response exceeds the 1 MB limit.")
        except (HTTPError, URLError, HTTPException, TimeoutError, OSError) as error:
            raise RuntimeError(f"Tavily public search failed: {error}") from error

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Tavily returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise RuntimeError("Tavily returned an invalid search result.")
        payload = cast(dict[str, object], payload)
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise RuntimeError("Tavily returned an invalid search result.")

        accessed_at = datetime.now(timezone.utc).isoformat()
        sources: list[PublicSource] = []
        for raw_item in cast(list[object], raw_results[:limit]):
            if not isinstance(raw_item, dict):
                raise RuntimeError("Tavily returned an invalid source record.")
            item = cast(dict[str, object], raw_item)
            title = item.get("title")
            url = item.get("url")
            content = item.get("content")
            if not isinstance(title, str) or not isinstance(url, str) or not isinstance(content, str):
                raise RuntimeError(
                    "Tavily sources must include title, URL, and snippet."
                )
            parsed_url = urlsplit(url)
            if (
                parsed_url.scheme != "https"
                or not parsed_url.hostname
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                raise RuntimeError("Tavily returned a source with an invalid HTTPS URL.")
            sources.append(
                {
                    "title": title[:500],
                    "url": url[:2_048],
                    "publisher": parsed_url.hostname,
                    "snippet": content[:MAX_SNIPPET_CHARS],
                    "accessed_at": accessed_at,
                }
            )
        return sources
