"""
modules/realtime_data.py
Real-time data for iZACH.

Rates:    goodreturns.in  (Scrapling Fetcher → PlayWrightFetcher fallback)
Search:   DuckDuckGo DDGS → Groq spoken summary
"""

import re
import os
import time
import requests
from typing import Optional

DEFAULT_CITY    = "New Delhi"
REQUEST_TIMEOUT = 10
CACHE_TTL       = 300  # 5 min

_cache: dict = {}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── CACHE ────────────────────────────────────────────────────────

def _cached(key: str, fn):
    now = time.time()
    if key in _cache:
        val, ts = _cache[key]
        if now - ts < CACHE_TTL:
            return val
    result = fn()
    _cache[key] = (result, now)
    return result


# ── GROQ CLIENT ──────────────────────────────────────────────────

_groq_client = None

def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _groq_client

def _groq_summarize(system: str, content: str, max_tokens: int = 130) -> str:
    resp = _get_groq().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": content},
        ],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ── PAGE FETCH (Scrapling → fallback chain) ──────────────────────

def _fetch_page_text(url: str) -> str:
    """
    Fetch page as plain text.
    1. requests + stealth headers  (fast, no browser)
    2. Scrapling Fetcher            (better headers + anti-bot)
    3. Scrapling PlayWrightFetcher  (full JS, reuses existing Playwright)
    """
    # 1. Plain requests
    try:
        r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200 and len(r.text) > 500:
            return r.text
    except Exception:
        pass

    # 2. Scrapling Fetcher (no browser needed)
    try:
        from scrapling import Fetcher
        page = Fetcher(auto_match=False).get(url, stealthy_headers=True)
        text = page.get_all_text(ignore_tags=("script", "style", "noscript"))
        if text and len(text) > 200:
            return text
    except Exception:
        pass

    # 3. Scrapling PlayWrightFetcher (uses existing Playwright install)
    try:
        from scrapling.fetchers import PlayWrightFetcher
        page = PlayWrightFetcher.fetch(url, headless=True, network_idle=True)
        text = page.get_all_text(ignore_tags=("script", "style", "noscript"))
        if text:
            return text
    except Exception:
        pass

    return ""


# ── GOLD RATE ────────────────────────────────────────────────────

def get_gold_rate(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            text = _fetch_page_text("https://www.goodreturns.in/gold-rates/")
            if text:
                # Ticker format: <span class="value">₹ 14,385/gm</span>
                # Try 24K ticker first, then 22K
                for label in ("24k Gold", "24K Gold", "22k Gold", "22K Gold"):
                    idx = text.find(label)
                    if idx >= 0:
                        chunk = text[idx:idx + 150]
                        m = re.search(r'₹\s*([\d,]+(?:\.\d+)?)\s*/gm', chunk)
                        if m:
                            karat = label.split()[0]
                            return f"Gold ({karat}) today is ₹{m.group(1)} per gram. Source: goodreturns.in."
                # Fallback: any ₹X,XXX/gm pattern
                m2 = re.search(r'₹\s*([\d,]+(?:\.\d+)?)\s*/gm', text)
                if m2:
                    val = float(m2.group(1).replace(",", ""))
                    if 8000 < val < 30000:
                        return f"Gold today is ₹{m2.group(1)} per gram. Source: goodreturns.in."
                # Range fallback: bare ₹ amounts in gold-per-gram zone
                prices = re.findall(r'₹\s*([\d,]+(?:\.\d+)?)', text)
                for p in prices:
                    val = float(p.replace(",", ""))
                    if 8000 < val < 30000:
                        return f"Gold today is ₹{p} per gram. Source: goodreturns.in."
        except Exception:
            pass
        return live_web_search("gold rate today India 22K 24K per gram in rupees")
    return _cached(f"gold_{city}", _fetch)


# ── SILVER RATE ──────────────────────────────────────────────────

def get_silver_rate(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            text = _fetch_page_text("https://www.goodreturns.in/silver-rates/")
            if text:
                m = re.search(
                    r'(?:silver|Silver)[^\n₹]{0,120}₹\s*([\d,]+(?:\.\d+)?)',
                    text
                )
                if m:
                    return f"Silver today is ₹{m.group(1)} per gram. Source: goodreturns.in."
                # Fallback: ₹ amount in silver-per-gram range (₹50 – ₹250)
                prices = re.findall(r'₹\s*([\d,]+(?:\.\d+)?)', text)
                for p in prices:
                    val = float(p.replace(",", ""))
                    if 50 < val < 250:
                        return f"Silver today is ₹{p} per gram. Source: goodreturns.in."
        except Exception:
            pass
        return live_web_search("silver rate today India per gram in rupees")
    return _cached(f"silver_{city}", _fetch)


# ── PETROL PRICE ─────────────────────────────────────────────────

def get_petrol_price(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            city_slug = city.lower().replace(" ", "-")
            url = f"https://www.goodreturns.in/petrol-price-in-{city_slug}.html"
            text = _fetch_page_text(url)
            if text:
                m = re.search(
                    r'(?:petrol|Petrol)[^\n₹]{0,80}₹\s*([\d.]+)',
                    text
                )
                if m:
                    return f"Petrol in {city} is ₹{m.group(1)} per litre. Source: goodreturns.in."
                matches = re.findall(
                    r'₹\s*([\d.]+)\s*(?:per litre|/litre|per liter)', text, re.IGNORECASE
                )
                if matches:
                    return f"Petrol in {city} is ₹{matches[0]} per litre."
        except Exception:
            pass
        return live_web_search(f"petrol price today {city} India per litre in rupees")
    return _cached(f"petrol_{city}", _fetch)


# ── DIESEL PRICE ─────────────────────────────────────────────────

def get_diesel_price(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            city_slug = city.lower().replace(" ", "-")
            url = f"https://www.goodreturns.in/diesel-price-in-{city_slug}.html"
            text = _fetch_page_text(url)
            if text:
                m = re.search(
                    r'(?:diesel|Diesel)[^\n₹]{0,80}₹\s*([\d.]+)',
                    text
                )
                if m:
                    return f"Diesel in {city} is ₹{m.group(1)} per litre. Source: goodreturns.in."
                matches = re.findall(
                    r'₹\s*([\d.]+)\s*(?:per litre|/litre|per liter)', text, re.IGNORECASE
                )
                if matches:
                    return f"Diesel in {city} is ₹{matches[0]} per litre."
        except Exception:
            pass
        return live_web_search(f"diesel price today {city} India per litre in rupees")
    return _cached(f"diesel_{city}", _fetch)


# ── STOCK PRICE ──────────────────────────────────────────────────

def get_stock_price(symbol: str) -> str:
    def _fetch():
        try:
            s = symbol.upper().strip()
            # Try NSE first
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{s}.NS",
                headers=_HEADERS, timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                result = r.json().get("chart", {}).get("result", [])
                if result:
                    price = result[0]["meta"]["regularMarketPrice"]
                    currency = result[0]["meta"].get("currency", "INR")
                    return f"{s} is trading at {currency} {price:,.2f}."
            # Global fallback
            r2 = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{s}",
                headers=_HEADERS, timeout=REQUEST_TIMEOUT,
            )
            if r2.status_code == 200:
                result2 = r2.json().get("chart", {}).get("result", [])
                if result2:
                    price = result2[0]["meta"]["regularMarketPrice"]
                    currency = result2[0]["meta"].get("currency", "USD")
                    name = result2[0]["meta"].get("shortName", s)
                    return f"{name} is at {currency} {price:,.2f}."
        except Exception:
            pass
        return live_web_search(f"{symbol} stock price today in rupees")
    return _cached(f"stock_{symbol}", _fetch)


# ── WEATHER ──────────────────────────────────────────────────────

def get_weather(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            url = f"https://wttr.in/{city.replace(' ', '+')}?format=3"
            r = requests.get(url, headers={"User-Agent": "curl/7.68.0"}, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200 and r.text.strip():
                return r.text.strip()
        except Exception:
            pass
        return live_web_search(f"weather today in {city} India temperature")
    return _cached(f"weather_{city}", _fetch)


# ── NEWS HEADLINES ───────────────────────────────────────────────

def get_news(topic: str = "india", count: int = 3) -> str:
    def _fetch():
        try:
            import xml.etree.ElementTree as ET
            topic_map = {
                "india":    "india+news",
                "world":    "world+news",
                "tech":     "technology+news+india",
                "sports":   "sports+news+india",
                "business": "business+news+india",
                "cricket":  "cricket+news+india",
                "ipl":      "IPL+2025+cricket",
            }
            q = topic_map.get(topic.lower(), f"{topic}+news+india")
            url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
            r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                items = root.findall(".//item")[:count]
                headlines = []
                for item in items:
                    title = item.find("title")
                    if title is not None and title.text:
                        clean = title.text.rsplit(" - ", 1)[0].strip()
                        headlines.append(clean)
                if headlines:
                    combined = ". ".join(headlines)
                    return _groq_summarize(
                        "Summarize these news headlines in 2-3 natural spoken sentences "
                        "like a news anchor giving a quick briefing.",
                        combined,
                        max_tokens=150,
                    )
        except Exception:
            pass
        return live_web_search(f"latest {topic} news today India")
    return _cached(f"news_{topic}", _fetch)


# alias used by command_chain.py briefing
get_news_headlines = get_news


# ── GENERAL LIVE WEB SEARCH (DuckDuckGo + Groq) ─────────────────

def live_web_search(query: str) -> str:
    """
    DuckDuckGo search → top snippets → Groq spoken answer.
    Fallback for any live query not covered by structured handlers.
    """
    try:
        from ddgs import DDGS

        # Bias toward India for geo-neutral queries
        search_q = query
        geo_words = {"india", "usa", "uk", "china", "pakistan", "japan", "europe", "america"}
        if not any(g in query.lower() for g in geo_words):
            search_q = query + " india"

        results = list(DDGS().text(search_q, region="in-en", max_results=4))
        if not results:
            return f"Couldn't find live results for: {query}"

        snippets = "\n\n".join(
            f"[{r.get('title', '')}]\n{r.get('body', '')}"
            for r in results
        )
        return _groq_summarize(
            "You are iZACH, a voice assistant. Answer the question ONLY based on what the "
            "search results explicitly say about the specific item being asked. "
            "CRITICAL: Do NOT apply prices or data from unrelated topics — if the user asks "
            "about golgappe, do not quote gold prices; if they ask about apples, do not quote "
            "stock prices. If the search results do not contain relevant information about the "
            "specific item asked, say 'I couldn't find that information right now.' "
            "Be concise, 1-3 sentences. No bullet points, no markdown.",
            f"Question: {query}\n\nSearch results:\n{snippets}",
            max_tokens=150,
        )
    except ImportError:
        return "Live search needs ddgs. Run: pip install ddgs scrapling"
    except Exception as e:
        return f"Live search failed: {e}"


# ── LIVE QUERY DETECTION ─────────────────────────────────────────

# Words that signal the user wants real-time data.
# Keep these SPECIFIC — bare words like "rate"/"price"/"kitna" are too generic
# and fire on casual queries like "golgappe ka rate" → wrong finance pages.
# Known commodity prices are handled by structured handlers above; unknown items
# fall through to AI which gives a better answer than a confused web search.
_LIVE_KEYWORDS = frozenset({
    # specific multi-word price signals (not bare "rate"/"price"/"kitna")
    "exchange rate", "dollar rate", "usd to inr", "inr to usd",
    # sports results (clearly real-time)
    "score", "who won", "winner", "match result", "standings",
    # finance tickers (clearly real-time)
    "sensex", "nifty", "bitcoin", "crypto",
    # breaking events
    "breaking", "latest update", "just happened",
    # temporal — only when paired with a specific subject (detected below)
    "right now", "live score", "live update",
})

# Prefixes already routed by structured handlers — skip web search for these
_STRUCTURED_PREFIXES = frozenset({
    "gold rate", "gold price", "silver rate", "silver price",
    "petrol price", "petrol rate", "diesel price", "diesel rate",
    "weather", "temperature", "mausam",
    "news", "headlines", "khabar",
    "stock price", "share price",
})


def _is_live_query(cmd_lower: str) -> bool:
    """True if query needs live internet but wasn't caught by structured handlers."""
    if any(cmd_lower.startswith(p) or p in cmd_lower for p in _STRUCTURED_PREFIXES):
        return False
    return any(kw in cmd_lower for kw in _LIVE_KEYWORDS)


# ── SMART QUERY ROUTER ───────────────────────────────────────────

def handle_realtime_query(cmd: str) -> Optional[str]:
    """
    Route cmd to correct data source.
    Returns speak-ready string or None (→ falls through to AI).
    """
    cmd_lower = cmd.lower()

    # Resolve city
    city = DEFAULT_CITY
    _CITIES = [
        "delhi", "mumbai", "bangalore", "bengaluru", "chennai",
        "hyderabad", "pune", "kolkata", "jaipur", "ahmedabad",
        "new delhi", "noida", "gurgaon", "gurugram", "lucknow",
        "surat", "bhopal", "indore", "patna", "chandigarh",
    ]
    for name in _CITIES:
        if name in cmd_lower:
            city = name.title()
            break

    # ── Gold ──────────────────────────────────────────────────────
    if any(w in cmd_lower for w in [
        "gold rate", "gold price", "gold ka rate", "sone ka bhav",
        "gold kitna", "aaj ka sona", "gold today",
    ]):
        return get_gold_rate(city)

    # ── Silver ────────────────────────────────────────────────────
    if any(w in cmd_lower for w in [
        "silver rate", "silver price", "chandi ka bhav",
        "silver kitna", "aaj ka chandi", "silver today",
    ]):
        return get_silver_rate(city)

    # ── Petrol ────────────────────────────────────────────────────
    if any(w in cmd_lower for w in [
        "petrol price", "petrol rate", "petrol ka bhav",
        "petrol kitna", "petrol today",
    ]):
        return get_petrol_price(city)

    # ── Diesel ────────────────────────────────────────────────────
    if any(w in cmd_lower for w in [
        "diesel price", "diesel rate", "diesel ka bhav",
        "diesel kitna", "diesel today",
    ]):
        return get_diesel_price(city)

    # ── Weather ───────────────────────────────────────────────────
    if any(w in cmd_lower for w in [
        "weather", "temperature", "mausam", "garmi", "thand",
        "barish", "kitni garmi", "kitni thand",
    ]):
        return get_weather(city)

    # ── News ──────────────────────────────────────────────────────
    if any(w in cmd_lower for w in [
        "news", "headlines", "khabar", "latest news", "aaj ki khabar",
        "kya ho raha", "what's happening",
    ]):
        topic = "india"
        for t in ["tech", "sports", "business", "world", "cricket", "ipl"]:
            if t in cmd_lower:
                topic = t
                break
        return get_news(topic)

    # ── Stock ─────────────────────────────────────────────────────
    if any(t in cmd_lower for t in ["stock price", "share price", "trading at"]):
        _COMMON = {
            "RELIANCE", "TCS", "INFY", "WIPRO", "HDFC", "ICICI",
            "AAPL", "TSLA", "GOOGL", "MSFT", "AMZN", "META",
            "TATAMOTORS", "ADANI", "BAJAJ", "MARUTI", "HCLTECH",
        }
        symbols = re.findall(r'\b([A-Z]{2,8})\b', cmd)
        for s in symbols:
            if s in _COMMON:
                return get_stock_price(s)
        words = cmd_lower.split()
        for i, w in enumerate(words):
            if w in ("price", "stock", "of", "for") and i + 1 < len(words):
                return get_stock_price(words[i + 1].upper())

    # ── General live fallback (DuckDuckGo) ───────────────────────
    if _is_live_query(cmd_lower):
        return live_web_search(cmd)

    return None  # not a realtime query → falls through to AI
