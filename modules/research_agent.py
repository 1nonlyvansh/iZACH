"""
modules/research_agent.py
Deep research mode — multi-source web synthesis.

Usage:
    research("best GPU for ML under 50k") -> spoken structured report

Flow:
  1. Groq generates 4 search queries from topic
  2. Each query → web_automation search → scrape top page text
  3. All snippets → Groq synthesis → structured spoken report
  4. Speak + return report text
"""

import re
import os
import threading
import time
import logging
import urllib.parse

logger = logging.getLogger(__name__)

_speak_fn = None
_groq_client = None


def init(speak_fn):
    global _speak_fn
    _speak_fn = speak_fn


def _groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _groq_client


def _call_groq(system: str, user: str, max_tokens: int = 400) -> str:
    resp = _groq().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def _generate_search_queries(topic: str) -> list[str]:
    """Ask Groq to split topic into 4 targeted search queries."""
    result = _call_groq(
        "Generate 4 specific Google search queries to research this topic thoroughly. "
        "Return ONLY a JSON array of 4 strings, nothing else.",
        f"Topic: {topic}",
        max_tokens=150,
    )
    try:
        import json
        queries = json.loads(re.search(r'\[.*\]', result, re.DOTALL).group())
        return [str(q) for q in queries[:4]]
    except Exception:
        return [topic, f"{topic} comparison", f"best {topic}", f"{topic} review 2024"]


def _ddg_requests(query: str) -> str:
    """Primary: requests-based DuckDuckGo HTML scrape (no browser needed)."""
    try:
        import requests
        from html.parser import HTMLParser

        class _SnippetParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.snippets: list[str] = []
                self._in_snippet = False
                self._buf = ""

            def handle_starttag(self, tag, attrs):
                classes = dict(attrs).get("class", "")
                if "result__snippet" in classes or "result__body" in classes:
                    self._in_snippet = True
                    self._buf = ""

            def handle_endtag(self, tag):
                if self._in_snippet and tag in ("a", "td", "div", "span"):
                    text = re.sub(r'\s+', ' ', self._buf).strip()
                    if len(text) > 25:
                        self.snippets.append(text)
                    self._in_snippet = False

            def handle_data(self, data):
                if self._in_snippet:
                    self._buf += data

        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()

        parser = _SnippetParser()
        parser.feed(resp.text)
        snippets = parser.snippets[:10]

        if snippets:
            return re.sub(r'\s+', ' ', " ".join(snippets)).strip()[:4000]

        # Fallback: strip all tags and return first 4000 chars of body text
        raw = re.sub(r'<[^>]+>', ' ', resp.text)
        return re.sub(r'\s+', ' ', raw).strip()[:4000]
    except Exception as e:
        logger.debug(f"[Research] requests DDG failed for '{query}': {e}")
        return ""


def _ddg_playwright(query: str) -> str:
    """Fallback: Playwright-based scrape."""
    try:
        from modules import web_automation as wa
        wa.search_google(query)
        time.sleep(2.0)
        page = wa._get_page()

        snippets = []
        for sel in [
            ".result__snippet",
            "[data-result='snippet']",
            ".OgdwYG",
            "article",
        ]:
            try:
                els = page.query_selector_all(sel)
                for el in els[:8]:
                    t = (el.inner_text() or "").strip()
                    if t and len(t) > 30:
                        snippets.append(t)
                if snippets:
                    break
            except Exception:
                pass

        if snippets:
            return re.sub(r'\s+', ' ', " ".join(snippets)).strip()[:4000]

        text = page.inner_text("body")
        return re.sub(r'\s+', ' ', text).strip()[:4000]
    except Exception as e:
        logger.debug(f"[Research] Playwright DDG failed for '{query}': {e}")
        return ""


def _search_and_scrape(query: str) -> str:
    """Search DuckDuckGo, scrape result snippets. requests first, Playwright fallback."""
    result = _ddg_requests(query)
    if result:
        return result
    logger.info(f"[Research] requests scrape empty, falling back to Playwright for: {query}")
    result = _ddg_playwright(query)
    if not result:
        logger.warning(f"[Research] Both scrapers returned empty for '{query}'")
    return result


def _synthesize(topic: str, snippets: list[str]) -> str:
    """Synthesize all snippets into a structured spoken research report."""
    combined = "\n\n---\n\n".join(
        f"[Source {i+1}]:\n{s}" for i, s in enumerate(snippets) if s
    )
    if not combined.strip():
        return f"Could not gather enough data on {topic}. Try a more specific query."

    return _call_groq(
        "You are iZACH, a JARVIS-style AI assistant. Synthesize the research data below "
        "into a clear spoken report. Structure it as: key finding, top 2-3 options or facts, "
        "and a recommendation. Speak naturally, max 120 words. No bullet points — full sentences only.",
        f"Research topic: {topic}\n\nData gathered:\n{combined[:10000]}",
        max_tokens=250,
    )


def research(topic: str) -> str:
    """
    Run full deep research on topic. Blocks until complete (~15-25s).
    Returns the spoken report string.
    """
    if _speak_fn:
        _speak_fn(f"Researching {topic}. Gathering sources, give me a moment.")

    logger.info(f"[Research] Starting research: {topic}")

    queries = _generate_search_queries(topic)
    logger.info(f"[Research] Queries: {queries}")

    snippets = []
    for q in queries:
        snippet = _search_and_scrape(q)
        if snippet:
            snippets.append(snippet)
        time.sleep(0.5)

    report = _synthesize(topic, snippets)
    logger.info(f"[Research] Report ready ({len(report)} chars)")
    return report


def research_async(topic: str):
    """Non-blocking version — speaks result when ready."""
    def _run():
        report = research(topic)
        if _speak_fn:
            _speak_fn(report)
    threading.Thread(target=_run, daemon=True).start()
