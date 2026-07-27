"""
modules/news_engine.py  —  iZACH Phase 6
News Panel: headlines, live TV embed, market ticker, voice narration.

Data sources (no API key required by default):
    Headlines : Google News RSS  (free, no key)
    NewsAPI   : newsapi.org      (optional, 100 req/day free tier)
    Markets   : Yahoo Finance v8 (free, unauthenticated)
    Fuel      : goodreturns.in   (via realtime_data)
    Crypto    : CoinGecko        (free tier)

YouTube live channels (all 24/7 news streams, no API key needed):
    Embed via: youtube-nocookie.com/embed/live_stream?channel=CHANNEL_ID
"""

import json
import logging
import os
import re
import time
import threading
import xml.etree.ElementTree as ET
from datetime import timezone

import requests

logger = logging.getLogger("iZACH.NewsEngine")

_BASE_DIR     = os.path.dirname(os.path.dirname(__file__))
_SETTINGS     = os.path.join(_BASE_DIR, "news_settings.json")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

# ──────────────────────────────────────────────────────────────
# YouTube live channel configs
# ──────────────────────────────────────────────────────────────

YOUTUBE_CHANNELS = {
    "ndtv":       {"name": "NDTV 24x7",      "id": "UCTi1q9_HHMtqOYGrqBh7L5g", "region": "india"},
    "republic":   {"name": "Republic TV",     "id": "UCGEmMouKT5HpSxU5qJGQC5Q", "region": "india"},
    "aajtak":     {"name": "Aaj Tak",         "id": "UCt4t-jeY85JegMlZ-E5UWuQ", "region": "india"},
    "aljazeera":  {"name": "Al Jazeera",      "id": "UCNye-wNBqNL5ZzHSJj3l8Bg", "region": "global"},
    "skynews":    {"name": "Sky News",        "id": "UC-ZklF9M_c09kNaD-1fL3Xg", "region": "uk"},
    "bbc":        {"name": "BBC News",        "id": "UC16niRr50-MSBwiO3YDb3RA", "region": "uk"},
    "cnn":        {"name": "CNN",             "id": "UCupvZG-5ko_eiXAupbDfxWw", "region": "us"},
    "wion":       {"name": "WION",            "id": "UCkNaKNNeNERzDLF4IgQFJ5A", "region": "india"},
}


def get_channel_embed_url(channel_key: str, autoplay: bool = True, muted: bool = True) -> str:
    ch = YOUTUBE_CHANNELS.get(channel_key, YOUTUBE_CHANNELS["ndtv"])
    params = f"autoplay={1 if autoplay else 0}&mute={1 if muted else 0}&controls=1"
    return f"https://www.youtube-nocookie.com/embed/live_stream?channel={ch['id']}&{params}"


# ──────────────────────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────────────────────

_DEFAULT_SETTINGS = {
    "region":            "india",            # india | global | us | uk
    "topics":            ["india", "world", "tech", "sports", "business"],
    "preferred_channel": "ndtv",             # key from YOUTUBE_CHANNELS
    "auto_narrate":      False,              # narrate headlines when panel opens
    "boot_news":         False,              # brief news at startup
    "headline_count":    5,
    "newsapi_key":       "",                 # optional — free tier 100/day
    "weather_city":      "New Delhi",
}

_TOPIC_QUERIES = {
    "india":    "india+news",
    "world":    "world+news",
    "tech":     "technology+news",
    "sports":   "sports+news+india",
    "business": "business+stock+market+india",
    "cricket":  "cricket+news+india",
    "politics": "india+politics+news",
    "health":   "health+news+india",
    "science":  "science+technology+news",
}


def load_settings() -> dict:
    try:
        with open(_SETTINGS) as f:
            d = json.load(f)
        merged = dict(_DEFAULT_SETTINGS)
        merged.update(d)
        return merged
    except Exception:
        return dict(_DEFAULT_SETTINGS)


def save_settings(patch: dict) -> dict:
    cfg = load_settings()
    cfg.update(patch)
    try:
        with open(_SETTINGS, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"[NEWS] Save settings: {e}")
    return {"ok": True}


# ──────────────────────────────────────────────────────────────
# Headlines — structured (list of dicts)
# ──────────────────────────────────────────────────────────────

_HEADLINE_CACHE: dict = {}   # topic → (items, timestamp)
_HEADLINE_TTL   = 300        # 5 minutes


def get_headline_items(topic: str = "india", count: int = 6) -> list[dict]:
    """
    Returns list of {title, source, link, published} dicts.
    Tries Google News RSS first; falls back to NewsAPI if key set.
    """
    cache_key = f"{topic}_{count}"
    if cache_key in _HEADLINE_CACHE:
        items, ts = _HEADLINE_CACHE[cache_key]
        if time.time() - ts < _HEADLINE_TTL:
            return items

    items = _fetch_gnews_rss(topic, count)
    if not items:
        items = _fetch_newsapi(topic, count)

    if items:
        _HEADLINE_CACHE[cache_key] = (items, time.time())
    return items


def _fetch_gnews_rss(topic: str, count: int) -> list[dict]:
    q    = _TOPIC_QUERIES.get(topic.lower(), f"{topic}+news+india")
    url  = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        root  = ET.fromstring(r.content)
        items = root.findall(".//item")[:count]
        result = []
        for it in items:
            title  = (it.findtext("title") or "").rsplit(" - ", 1)
            source = title[1].strip() if len(title) > 1 else ""
            clean  = title[0].strip()
            link   = it.findtext("link") or ""
            pub    = it.findtext("pubDate") or ""
            result.append({
                "title":     clean,
                "source":    source,
                "link":      link,
                "published": _parse_pub_date(pub),
            })
        return result
    except Exception as e:
        logger.debug(f"[NEWS] GNews RSS error: {e}")
        return []


def _fetch_newsapi(topic: str, count: int) -> list[dict]:
    cfg = load_settings()
    key = cfg.get("newsapi_key", "")
    if not key:
        return []
    q_map = {
        "india":    "india", "world": "world", "tech": "technology",
        "sports":   "sports", "business": "business", "cricket": "cricket",
    }
    q = q_map.get(topic.lower(), topic)
    try:
        r = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"q": q, "language": "en", "pageSize": count, "apiKey": key},
            timeout=10,
        )
        d = r.json()
        if d.get("status") != "ok":
            return []
        result = []
        for a in d.get("articles", [])[:count]:
            result.append({
                "title":     a.get("title", ""),
                "source":    a.get("source", {}).get("name", ""),
                "link":      a.get("url", ""),
                "published": a.get("publishedAt", ""),
            })
        return result
    except Exception as e:
        logger.debug(f"[NEWS] NewsAPI error: {e}")
        return []


def _parse_pub_date(s: str) -> str:
    """Convert RSS pubDate to 'HH:MM' string."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s).astimezone(timezone.utc)
        return dt.strftime("%H:%M UTC")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────
# Market snapshot
# ──────────────────────────────────────────────────────────────

_MARKET_CACHE: dict  = {}
_MARKET_TTL    = 180  # 3 minutes

_INDICES = {
    "SENSEX": "^BSESN",
    "NIFTY":  "^NSEI",
    "NASDAQ": "^IXIC",
    "S&P500": "^GSPC",
}

_CRYPTO_IDS = {
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "SOL":  "solana",
}


def get_market_snapshot() -> dict:
    """Returns dict with indices, crypto, gold, petrol."""
    now = time.time()
    if "data" in _MARKET_CACHE and now - _MARKET_CACHE["ts"] < _MARKET_TTL:
        return _MARKET_CACHE["data"]

    snap: dict = {"indices": {}, "crypto": {}, "gold": None, "petrol": None, "fetched_at": int(now)}

    # Indices via Yahoo Finance
    for label, symbol in _INDICES.items():
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                headers=_HEADERS, timeout=8,
            )
            res = r.json().get("chart", {}).get("result", [])
            if res:
                meta   = res[0]["meta"]
                price  = meta.get("regularMarketPrice", 0)
                prev   = meta.get("chartPreviousClose", price)
                change = price - prev
                pct    = (change / prev * 100) if prev else 0
                snap["indices"][label] = {
                    "price":  round(price, 2),
                    "change": round(change, 2),
                    "pct":    round(pct, 2),
                }
        except Exception:
            pass

    # Crypto via CoinGecko (no key, free)
    try:
        ids = ",".join(_CRYPTO_IDS.values())
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids, "vs_currencies": "usd,inr", "include_24hr_change": "true"},
            timeout=8,
        )
        d = r.json()
        for label, cg_id in _CRYPTO_IDS.items():
            if cg_id in d:
                snap["crypto"][label] = {
                    "usd":    d[cg_id].get("usd", 0),
                    "inr":    d[cg_id].get("inr", 0),
                    "change": round(d[cg_id].get("usd_24h_change", 0), 2),
                }
    except Exception:
        pass

    # Gold (Yahoo Finance: GC=F)
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
            headers=_HEADERS, timeout=8,
        )
        res = r.json().get("chart", {}).get("result", [])
        if res:
            snap["gold"] = {"usd_oz": round(res[0]["meta"]["regularMarketPrice"], 2)}
    except Exception:
        pass

    # Petrol (reuse realtime_data)
    try:
        from modules.realtime_data import get_petrol_price
        cfg  = load_settings()
        city = cfg.get("weather_city", "New Delhi")
        snap["petrol"] = get_petrol_price(city)
    except Exception:
        pass

    _MARKET_CACHE["data"] = snap
    _MARKET_CACHE["ts"]   = now
    return snap


def build_ticker_text() -> str:
    """One-line ticker string for all market data."""
    snap  = get_market_snapshot()
    parts = []

    for label, d in snap.get("indices", {}).items():
        arrow = "▲" if d["pct"] >= 0 else "▼"
        parts.append(f"{label} {arrow}{abs(d['pct']):.1f}%")

    for label, d in snap.get("crypto", {}).items():
        arrow = "▲" if d["change"] >= 0 else "▼"
        usd   = d.get("usd", 0)
        parts.append(f"{label} ${usd:,.0f} {arrow}{abs(d['change']):.1f}%")

    if snap.get("gold"):
        parts.append(f"GOLD ${snap['gold']['usd_oz']}/oz")

    if snap.get("petrol"):
        petrol_str = str(snap["petrol"])
        m = re.search(r"₹\s*([\d.]+)", petrol_str)
        if m:
            parts.append(f"PETROL ₹{m.group(1)}/L")

    return "  ·  ".join(parts)


# ──────────────────────────────────────────────────────────────
# Voice narration
# ──────────────────────────────────────────────────────────────

_speak_fn = None
_ai_fn    = None


def init(speak_fn=None, ai_fn=None):
    global _speak_fn, _ai_fn
    _speak_fn = speak_fn
    _ai_fn    = ai_fn
    cfg = load_settings()
    if cfg.get("boot_news"):
        threading.Thread(target=_boot_news_briefing, daemon=True).start()


def _boot_news_briefing():
    time.sleep(8)  # wait until system ready
    narrate_headlines(speak_immediately=True)


def narrate_headlines(topic: str = "india", count: int = 5, speak_immediately: bool = False) -> str:
    """
    Generate a spoken news briefing. Returns the text.
    If speak_immediately=True and _speak_fn set, also speaks it.
    """
    items = get_headline_items(topic, count)
    if not items:
        msg = "Could not fetch news headlines right now."
        if speak_immediately and _speak_fn:
            _speak_fn(msg)
        return msg

    titles    = [it["title"] for it in items]
    combined  = ". ".join(titles)

    if _ai_fn:
        try:
            briefing = _ai_fn(
                f"Summarize these {topic} news headlines in 3–4 natural spoken sentences "
                f"like a friendly news anchor giving a quick briefing. "
                f"Don't say 'here are the headlines' — just deliver the briefing:\n\n{combined}"
            ).strip()
        except Exception:
            briefing = f"Here are the top {topic} headlines: {combined}"
    else:
        briefing = f"Top {topic} news: {combined}"

    if speak_immediately and _speak_fn:
        _speak_fn(briefing)
    return briefing


def narrate_single(index: int, topic: str = "india") -> str:
    """Speak more about headline at 1-based index."""
    items = get_headline_items(topic, 10)
    if not items or index < 1 or index > len(items):
        return "Headline not found."
    item  = items[index - 1]
    title = item["title"]
    if _ai_fn:
        try:
            detail = _ai_fn(
                f"Give a 2–3 sentence spoken explanation of this news headline, "
                f"as if briefing someone who hasn't heard it yet:\n\n\"{title}\""
            ).strip()
        except Exception:
            detail = title
    else:
        detail = title
    if _speak_fn:
        _speak_fn(detail)
    return detail


# ──────────────────────────────────────────────────────────────
# Voice command dispatcher
# ──────────────────────────────────────────────────────────────

def execute_voice_command(cmd: str) -> dict:
    cmd_l = cmd.lower()

    # "read news" / "today's news" / "latest news"
    if any(w in cmd_l for w in ["read news", "today's news", "latest news", "tell me the news", "news briefing", "morning briefing"]):
        topic = "india"
        for t in ["world", "tech", "sports", "business", "cricket"]:
            if t in cmd_l:
                topic = t
                break
        text = narrate_headlines(topic, speak_immediately=True)
        return {"success": True, "message": text}

    # "tell me more about headline 3"
    m = re.search(r'headline\s+(\d+)|number\s+(\d+)', cmd_l)
    if m:
        idx = int(m.group(1) or m.group(2))
        text = narrate_single(idx)
        return {"success": True, "message": text}

    # "tech news" / "sports news" etc
    for topic in _TOPIC_QUERIES:
        if topic in cmd_l and "news" in cmd_l:
            text = narrate_headlines(topic, speak_immediately=True)
            return {"success": True, "message": text}

    # "market update" / "stock market"
    if any(w in cmd_l for w in ["market update", "stock market", "sensex", "nifty", "market snapshot"]):
        snap  = get_market_snapshot()
        parts = []
        for label, d in snap.get("indices", {}).items():
            direction = "up" if d["pct"] >= 0 else "down"
            parts.append(f"{label} is {direction} {abs(d['pct']):.1f}%")
        if snap.get("crypto", {}).get("BTC"):
            btc = snap["crypto"]["BTC"]
            parts.append(f"Bitcoin is at ${btc['usd']:,.0f}")
        msg = "Market update: " + ", ".join(parts) + "." if parts else "Market data unavailable."
        if _speak_fn:
            _speak_fn(msg)
        return {"success": True, "message": msg}

    return {"success": False, "message": "Command not recognized for news."}
