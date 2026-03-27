"""Shared fetch layer with optional Scrapling fallback."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _looks_blocked(status_code: Optional[int], text: str) -> bool:
    if status_code in {401, 403, 429, 503}:
        return True
    t = (text or "").lower()
    return any(marker in t for marker in ["enable javascript", "checking your browser", "cf-chl", "captcha"])


def _extract_text(result: Any) -> str:
    for attr in ("text", "html", "content"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    if isinstance(result, str):
        return result
    return ""


def _extract_status(result: Any) -> Optional[int]:
    for attr in ("status", "status_code"):
        value = getattr(result, attr, None)
        if isinstance(value, int):
            return value
    return None


def _extract_url(result: Any, fallback_url: str) -> str:
    for attr in ("url", "final_url"):
        value = getattr(result, attr, None)
        if value:
            return str(value)
    return fallback_url


def _scrapling_fetch(url: str, *, dynamic: bool, stealth: bool, timeout: int = 30):
    try:
        if stealth:
            from scrapling.fetchers import StealthyFetcher as Fetcher
        elif dynamic:
            from scrapling.fetchers import DynamicFetcher as Fetcher
        else:
            return None
    except Exception:
        return None

    try:
        fetcher = Fetcher(timeout=timeout)
    except Exception:
        fetcher = Fetcher()

    # Support multiple API variants.
    call_patterns = [
        lambda: fetcher.get(url),
        lambda: fetcher.fetch(url),
        lambda: fetcher(url),
    ]
    for call in call_patterns:
        try:
            return call()
        except TypeError:
            continue
        except Exception:
            return None
    return None


def fetch_html(
    url: str,
    source_id: Optional[str] = None,
    prefer_dynamic: bool = False,
    prefer_stealth: bool = False,
    timeout: int = 25,
) -> Dict[str, Any]:
    """
    Fetch HTML with layered fallbacks:
      1) plain HTTP
      2) Scrapling DynamicFetcher
      3) Scrapling StealthyFetcher
    """
    source_id = source_id or "unknown"
    http_retries = 2 if source_id == "basellive" else 1

    # 1) plain HTTP
    delay = 1.0
    for _ in range(http_retries + 1):
        try:
            with httpx.Client(follow_redirects=True) as client:
                resp = client.get(url, headers=HEADERS, timeout=timeout)
            html = resp.text
            blocked = _looks_blocked(resp.status_code, html)
            if not blocked:
                return {
                    "html": html,
                    "soup": BeautifulSoup(html, "html.parser"),
                    "final_url": str(resp.url),
                    "mode": "http",
                    "status_code": resp.status_code,
                    "blocked": False,
                    "document": None,
                }
            last_status = resp.status_code
        except Exception:
            last_status = None
        time.sleep(delay)
        delay *= 1.6

    # 2) dynamic fetch
    try_dynamic = prefer_dynamic or source_id in {"ra_basel", "ra_zurich", "basellive", "denkmal", "kuppel", "kaserne"}
    if try_dynamic:
        result = _scrapling_fetch(url, dynamic=True, stealth=False, timeout=timeout + 10)
        if result is not None:
            html = _extract_text(result)
            status = _extract_status(result)
            if html and not _looks_blocked(status, html):
                return {
                    "html": html,
                    "soup": BeautifulSoup(html, "html.parser"),
                    "final_url": _extract_url(result, url),
                    "mode": "dynamic",
                    "status_code": status,
                    "blocked": False,
                    "document": result,
                }

    # 3) stealth fetch
    if prefer_stealth or source_id in {"ra_basel", "ra_zurich", "basellive", "denkmal"}:
        result = _scrapling_fetch(url, dynamic=False, stealth=True, timeout=timeout + 20)
        if result is not None:
            html = _extract_text(result)
            status = _extract_status(result)
            if html:
                return {
                    "html": html,
                    "soup": BeautifulSoup(html, "html.parser"),
                    "final_url": _extract_url(result, url),
                    "mode": "stealth",
                    "status_code": status,
                    "blocked": _looks_blocked(status, html),
                    "document": result,
                }

    return {
        "html": "",
        "soup": None,
        "final_url": url,
        "mode": "failed",
        "status_code": locals().get("last_status"),
        "blocked": True,
        "document": None,
    }


def adaptive_select(document: Any, selector: str, *, profile_key: str, auto_save: bool = False, adaptive: bool = False):
    """Best-effort adapter for Scrapling adaptive selectors."""
    if document is None:
        return []

    css_fn = getattr(document, "css", None)
    if callable(css_fn):
        try:
            nodes = css_fn(selector, auto_save=auto_save, adaptive=adaptive, profile=profile_key)
            return nodes or []
        except TypeError:
            try:
                nodes = css_fn(selector, auto_save=auto_save, adaptive=adaptive)
                return nodes or []
            except Exception:
                pass
        except Exception:
            pass

    select_fn = getattr(document, "select", None)
    if callable(select_fn):
        try:
            return select_fn(selector) or []
        except Exception:
            return []
    return []
