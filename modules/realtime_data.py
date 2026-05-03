"""
modules/realtime_data.py
Phase 4 — Real-time data fetching for iZACH.

Handles:
- Gold/Silver rates (India)
- Petrol/Diesel prices (location-aware)
- Stock prices (NSE/BSE + global)
- News headlines
- Weather

All functions return short, speak-ready strings.
No heavy dependencies — uses requests + basic parsing.
"""

import requests
import json
import time
from typing import Optional

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
DEFAULT_CITY    = "New Delhi"
DEFAULT_COUNTRY = "India"
REQUEST_TIMEOUT = 8
CACHE_TTL       = 300   # 5 minutes cache

_cache: dict = {}

def _cached(key: str, fn):
    """Simple in-memory cache with TTL."""
    now = time.time()
    if key in _cache:
        val, ts = _cache[key]
        if now - ts < CACHE_TTL:
            return val
    result = fn()
    _cache[key] = (result, now)
    return result


# ─────────────────────────────────────────────
# GOLD & SILVER RATES
# ─────────────────────────────────────────────

def get_gold_rate(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            # metals-api free alternative — use metals.live
            r = requests.get(
                "https://api.metals.live/v1/spot/gold",
                timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                usd_per_oz = data[0].get("price", 0)
                # Convert to INR per gram (1 oz = 31.1g, approx USD to INR)
                inr_rate = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
                inr = 83.0  # fallback rate
                if inr_rate.status_code == 200:
                    inr = inr_rate.json()["rates"].get("INR", 83.0)
                per_gram = round((usd_per_oz / 31.1035) * inr, 2)
                return f"Gold is at ₹{per_gram:,.2f} per gram today. International rate."
            return "Gold rate unavailable."
        except Exception as e:
            return f"Couldn't fetch gold rate: {e}"
    return _cached(f"gold_{city}", _fetch)


def get_silver_rate(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            r = requests.get(
                "https://api.metals.live/v1/spot/silver",
                timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                usd_per_oz = data[0].get("price", 0)
                inr_rate = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
                inr = 83.0
                if inr_rate.status_code == 200:
                    inr = inr_rate.json()["rates"].get("INR", 83.0)
                per_gram = round((usd_per_oz / 31.1035) * inr, 2)
                return f"Silver is at ₹{per_gram:,.2f} per gram today."
            return "Silver rate unavailable."
        except Exception as e:
            return f"Couldn't fetch silver rate: {e}"
    return _cached(f"silver_{city}", _fetch)


# ─────────────────────────────────────────────
# PETROL / DIESEL PRICES
# ─────────────────────────────────────────────

def get_petrol_price(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            # mypetrolprice.com is more scraping-friendly
            city_slug = city.lower().replace(" ", "-")
            url = f"https://www.mypetrolprice.com/petrol-price-in-{city_slug}.aspx"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                import re
                matches = re.findall(r'Rs\.\s*([\d.]+)', r.text)
                if not matches:
                    matches = re.findall(r'₹\s*([\d.]+)', r.text)
                if matches:
                    return f"Petrol in {city} is ₹{matches[0]} per litre."
            return f"Petrol price for {city} not found. Try a major city name."
        except Exception as e:
            return f"Couldn't fetch petrol price: {e}"
    return _cached(f"petrol_{city}", _fetch)


def get_diesel_price(city: str = DEFAULT_CITY) -> str:
    def _fetch():
        try:
            city_slug = city.lower().replace(" ", "-")
            url = f"https://www.goodreturns.in/diesel-price-in-{city_slug}.html"
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                import re
                matches = re.findall(r'(?:₹|Rs\.?)\s*([\d.]+)', r.text)
                if matches:
                    price = matches[0]
                    return f"Diesel in {city} is ₹{price} per litre."
            return f"Diesel price for {city} unavailable."
        except Exception as e:
            return f"Couldn't fetch diesel price: {e}"
    return _cached(f"diesel_{city}", _fetch)


# ─────────────────────────────────────────────
# STOCK PRICES
# ─────────────────────────────────────────────

def get_stock_price(symbol: str) -> str:
    """
    Fetch stock price.
    Works for NSE (RELIANCE, TCS, INFY) and global (AAPL, TSLA).
    Uses Yahoo Finance unofficial API.
    """
    def _fetch():
        try:
            # Try NSE first, then global
            symbol_clean = symbol.upper().strip()
            # Yahoo Finance API (no key needed for basic quotes)
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_clean}.NS"
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            if r.status_code == 200:
                data = r.json()
                price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
                currency = data["chart"]["result"][0]["meta"]["currency"]
                return f"{symbol_clean} is trading at {currency} {price:,.2f}."

            # Try global (without .NS)
            url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_clean}"
            r2 = requests.get(url2, headers=headers, timeout=REQUEST_TIMEOUT)
            if r2.status_code == 200:
                data2 = r2.json()
                result = data2["chart"]["result"]
                if result:
                    price = result[0]["meta"]["regularMarketPrice"]
                    currency = result[0]["meta"]["currency"]
                    name = result[0]["meta"].get("shortName", symbol_clean)
                    return f"{name} is at {currency} {price:,.2f}."

            return f"Couldn't find stock data for {symbol}."
        except Exception as e:
            return f"Stock lookup failed: {e}"
    return _cached(f"stock_{symbol}", _fetch)


# ─────────────────────────────────────────────
# NEWS HEADLINES
# ─────────────────────────────────────────────

def get_news(topic: str = "india", count: int = 3) -> str:
    """Fetch top news headlines using GNews API (free tier)."""
    def _fetch():
        try:
            # Using RSS feed — no API key needed
            import xml.etree.ElementTree as ET
            topic_map = {
                "india":    "https://news.google.com/rss/search?q=india+news&hl=en-IN&gl=IN&ceid=IN:en",
                "world":    "https://news.google.com/rss/search?q=world+news&hl=en&gl=US&ceid=US:en",
                "tech":     "https://news.google.com/rss/search?q=technology+news&hl=en&gl=IN&ceid=IN:en",
                "sports":   "https://news.google.com/rss/search?q=sports+news+india&hl=en-IN&gl=IN&ceid=IN:en",
                "business": "https://news.google.com/rss/search?q=business+news+india&hl=en-IN&gl=IN&ceid=IN:en",
            }
            url = topic_map.get(topic.lower(), topic_map["india"])
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            if r.status_code == 200:
                root = ET.fromstring(r.content)
                items = root.findall(".//item")[:count]
                headlines = []
                for item in items:
                    title = item.find("title")
                    if title is not None:
                        # Clean up Google News title format "Story - Source"
                        clean = title.text.rsplit(" - ", 1)[0].strip()
                        headlines.append(clean)
                if headlines:
                    result = ". ".join(headlines)
                    return f"Top {topic} news: {result}."
            return "News unavailable right now."
        except Exception as e:
            return f"News fetch failed: {e}"
    return _cached(f"news_{topic}", _fetch)


# ─────────────────────────────────────────────
# WEATHER
# ─────────────────────────────────────────────

def get_weather(city: str = DEFAULT_CITY) -> str:
    """Fetch weather using wttr.in (no API key needed)."""
    def _fetch():
        try:
            url = f"https://wttr.in/{city.replace(' ', '+')}?format=3"
            headers = {"User-Agent": "curl/7.68.0"}
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                # wttr format 3: "City: ⛅  +28°C"
                result = r.text.strip()
                return result
            return f"Weather for {city} unavailable."
        except Exception as e:
            return f"Weather fetch failed: {e}"
    return _cached(f"weather_{city}", _fetch)


# ─────────────────────────────────────────────
# SMART QUERY ROUTER
# ─────────────────────────────────────────────

def handle_realtime_query(cmd: str) -> Optional[str]:
    """
    Route a command to the right data fetcher.
    Returns a speak-ready string or None if not a realtime query.
    """
    cmd_lower = cmd.lower()

    # Extract city if mentioned
    city = DEFAULT_CITY
    city_keywords = ["in ", "at ", "for "]
    city_names = ["delhi", "mumbai", "bangalore", "chennai", "hyderabad",
                  "pune", "kolkata", "jaipur", "ahmedabad", "new delhi",
                  "noida", "gurgaon", "lucknow"]
    for name in city_names:
        if name in cmd_lower:
            city = name.title()
            break

    # Gold
    if any(w in cmd_lower for w in ["gold rate", "gold price", "gold ka rate", "sone ka bhav"]):
        return get_gold_rate(city)

    # Silver
    if any(w in cmd_lower for w in ["silver rate", "silver price", "chandi ka bhav"]):
        return get_silver_rate(city)

    # Petrol
    if any(w in cmd_lower for w in ["petrol price", "petrol rate", "petrol ka bhav", "petrol kitna hai"]):
        return get_petrol_price(city)

    # Diesel
    if any(w in cmd_lower for w in ["diesel price", "diesel rate", "diesel ka bhav"]):
        return get_diesel_price(city)

    # Weather
    if any(w in cmd_lower for w in ["weather", "temperature", "mausam", "garmi", "thand", "barish"]):
        return get_weather(city)

    # News
    if any(w in cmd_lower for w in ["news", "headlines", "khabar", "latest news"]):
        topic = "india"
        for t in ["tech", "sports", "business", "world"]:
            if t in cmd_lower:
                topic = t
                break
        return get_news(topic)

    # Stock
    stock_triggers = ["stock price", "share price", "stock of", "how is", "trading at"]
    if any(t in cmd_lower for t in stock_triggers):
        # Extract symbol
        import re
        # Look for ALL CAPS word or known symbols
        symbols = re.findall(r'\b([A-Z]{2,6})\b', cmd)
        common = {"RELIANCE", "TCS", "INFY", "WIPRO", "HDFC", "ICICI",
                  "AAPL", "TSLA", "GOOGL", "MSFT", "AMZN", "META"}
        for s in symbols:
            if s in common or s.upper() in cmd.upper():
                return get_stock_price(s)
        # Try extracting from lowercase
        words = cmd_lower.split()
        for i, w in enumerate(words):
            if w in ["price", "stock", "of"] and i + 1 < len(words):
                return get_stock_price(words[i + 1].upper())

    return None   # not a realtime query