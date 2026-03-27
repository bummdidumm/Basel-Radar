"""Shared fetch layer with optional Scrapling fallback."""

from __future__ import annotations

import re
import time
from pathlib import Path
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


def _get_block_reason(status_code: Optional[int], text: str) -> Optional[str]:
    t = (text or "").lower()
    if status_code == 429:
        return "rate_limited_429"
    if status_code == 403:
        return "forbidden_403"
    if status_code in {401, 503}:
        return f"http_{status_code}"
    if "captcha" in t:
        return "captcha_page"
    if "checking your browser" in t or "cf-chl" in t:
        return "bot_challenge"
    if "enable javascript" in t:
        return "js_required"
    return None


def _extract_page_title(html: str) -> str:
    if not html:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _content_snippet(html: str, limit: int = 500) -> str:
    if not html:
        return ""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


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
    debug_dump: bool = False,
    debug_screenshot: bool = False,
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
                    "block_reason": None,
                    "page_title": _extract_page_title(html),
                    "content_snippet": _content_snippet(html),
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
                payload = {
                    "html": html,
                    "soup": BeautifulSoup(html, "html.parser"),
                    "final_url": _extract_url(result, url),
                    "mode": "dynamic",
                    "status_code": status,
                    "blocked": False,
                    "block_reason": None,
                    "page_title": _extract_page_title(html),
                    "content_snippet": _content_snippet(html),
                    "document": result,
                }
                _maybe_write_debug_artifacts(source_id, payload, debug_dump=debug_dump, debug_screenshot=debug_screenshot)
                return payload

    # 3) stealth fetch
    if prefer_stealth or source_id in {"ra_basel", "ra_zurich", "basellive", "denkmal"}:
        result = _scrapling_fetch(url, dynamic=False, stealth=True, timeout=timeout + 20)
        if result is not None:
            html = _extract_text(result)
            status = _extract_status(result)
            if html:
                payload = {
                    "html": html,
                    "soup": BeautifulSoup(html, "html.parser"),
                    "final_url": _extract_url(result, url),
                    "mode": "stealth",
                    "status_code": status,
                    "blocked": _looks_blocked(status, html),
                    "block_reason": _get_block_reason(status, html),
                    "page_title": _extract_page_title(html),
                    "content_snippet": _content_snippet(html),
                    "document": result,
                }
                _maybe_write_debug_artifacts(source_id, payload, debug_dump=debug_dump, debug_screenshot=debug_screenshot)
                return payload

    failed = {
        "html": "",
        "soup": None,
        "final_url": url,
        "mode": "failed",
        "status_code": locals().get("last_status"),
        "blocked": True,
        "block_reason": _get_block_reason(locals().get("last_status"), ""),
        "page_title": "",
        "content_snippet": "",
        "document": None,
    }
    _maybe_write_debug_artifacts(source_id, failed, debug_dump=debug_dump, debug_screenshot=debug_screenshot)
    return failed


def _maybe_write_debug_artifacts(source_id: str, fetched: Dict[str, Any], debug_dump: bool = False, debug_screenshot: bool = False):
    if not (debug_dump or debug_screenshot):
        return
    debug_dir = Path("debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", source_id or "unknown")
    if debug_dump and fetched.get("html"):
        (debug_dir / f"{safe_id}.html").write_text(fetched["html"], encoding="utf-8")
    if debug_screenshot and fetched.get("document") is not None:
        doc = fetched["document"]
        for name in ("screenshot", "save_screenshot"):
            fn = getattr(doc, name, None)
            if callable(fn):
                try:
                    fn(str(debug_dir / f"{safe_id}.png"))
                    break
                except Exception:
                    pass


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
