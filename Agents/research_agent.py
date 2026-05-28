"""
ResearchAgent — full LLM-driven handler for all research, live-data, and web queries.

Replaces/consolidates in command_chain.py:
  handle_realtime_query() call (~line 1864)   — gold/silver/petrol/weather/news/stock
  _get_crypto_price() block (~line 2429)       — Bitcoin, Ethereum, Dogecoin, Solana
  _RESEARCH_TRIGGERS block (~line 424)         — deep_research via research_agent
  news handler (~line 603)                     — web_automation.get_news()
  price lookup (~line 617)                     — web_automation.lookup_price()
  page summarize (in web_automation triggers)  — web_automation.summarize_page()

Intents handled:
  live_commodity     gold / silver / petrol / diesel price
  stock_price        NSE / global stock price
  crypto_price       Bitcoin / Ethereum / Dogecoin / Solana etc.
  weather            current weather / temperature for a city
  news               headlines (general or topic-specific)
  web_search         general DuckDuckGo query → spoken answer
  deep_research      multi-source synthesis via research_agent module
  price_lookup       product price via Google Shopping
  page_summarize     summarize current open browser tab
"""

from __future__ import annotations

import json
import re
import threading

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's research and information command parser. Parse the user command into JSON.

Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "commodity": "<gold|silver|petrol|diesel or null>",
  "city": "<city name or null>",
  "stock_symbol": "<NSE/NYSE ticker in CAPS or null>",
  "coin": "<bitcoin|ethereum|dogecoin|solana|bnb|xrp or null>",
  "news_topic": "<topic keyword or null — null means general India news>",
  "query": "<clean search query or research topic or null>",
  "product": "<product name for price lookup or null>"
}}

Intents (pick exactly one):
- live_commodity  : gold price, silver price, petrol rate, diesel rate, sone ka bhav, chandi, petrol kitna
- stock_price     : share price of X, X stock, RELIANCE stock, TCS share
- crypto_price    : bitcoin price, BTC rate, ethereum, ETH, dogecoin, crypto rate
- weather         : weather/temperature/mausam for any city or current location
- news            : latest news, headlines, what's happening, khabar, news about X
- web_search      : search for X, look up X, what is X, find information about X (short factual)
- deep_research   : research X, deep research, full report on X, investigate X, comprehensive info
- price_lookup    : how much does X cost, price of X (product), check price of X
- page_summarize  : summarize this page, what does this page say, read this page

Rules:
- commodity: always lowercase (gold, silver, petrol, diesel)
- coin: lowercase canonical name (bitcoin not BTC, ethereum not ETH)
- stock_symbol: UPPERCASE ticker; if user says "Reliance" → "RELIANCE", "TCS" → "TCS"
- city: extract city name as-is from command; null = use default city
- web_search vs deep_research: short factual → web_search; "research/full report/investigate" → deep_research
- query: stripped of trigger words; just the topic/question
- Output ONLY the JSON object
"""

# Coin name → canonical id mapping for CoinGecko
_COIN_IDS = {
    "bitcoin": "bitcoin",   "btc": "bitcoin",
    "ethereum": "ethereum", "eth": "ethereum",
    "dogecoin": "dogecoin", "doge": "dogecoin",
    "solana": "solana",     "sol": "solana",
    "bnb": "binancecoin",   "xrp": "ripple",
    "cardano": "cardano",   "ada": "cardano",
    "polygon": "matic-network", "matic": "matic-network",
}


def _bg(fn, *args, announce: str = ""):
    """Run fn(*args) in a daemon thread, optionally announce first."""
    def _run():
        fn(*args)
    if announce:
        # announce is spoken by the caller before spawning
        pass
    threading.Thread(target=_run, daemon=True).start()


class ResearchAgent:
    """
    Handles all research/information domain commands via LLM intent parsing.
    """

    def __init__(self, speak_fn, raw_ai_fn):
        self.speak   = speak_fn
        self._raw_ai = raw_ai_fn
        # Init research_agent module with speak callback
        try:
            from modules.research_agent import init as _init_research
            _init_research(speak_fn)
        except Exception:
            pass

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Parse and execute research/info command.
        Returns True if handled, False to fall through.
        """
        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        print(f"[RES_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "live_commodity": self._live_commodity,
            "stock_price":    self._stock_price,
            "crypto_price":   self._crypto_price,
            "weather":        self._weather,
            "news":           self._news,
            "web_search":     self._web_search,
            "deep_research":  self._deep_research,
            "price_lookup":   self._price_lookup,
            "page_summarize": self._page_summarize,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        prompt   = _PARSE_PROMPT.format(cmd=cmd)
        response = ""
        try:
            response = self._raw_ai(prompt)
            clean    = re.sub(r'^```(?:json)?\s*', '', response.strip(), flags=re.IGNORECASE)
            clean    = re.sub(r'\s*```$', '', clean)
            m        = re.search(r'\{.*\}', clean, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            return data if "intent" in data else {"intent": "unknown"}
        except Exception as e:
            print(f"[RES_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Helpers ───────────────────────────────────────────────────

    def _default_city(self) -> str:
        try:
            from modules.realtime_data import DEFAULT_CITY
            return DEFAULT_CITY
        except Exception:
            return "Delhi"

    # ── Handlers ─────────────────────────────────────────────────

    def _live_commodity(self, d: dict, cmd: str) -> bool:
        commodity = (d.get("commodity") or "").lower().strip()
        city      = (d.get("city") or self._default_city()).strip()

        from modules.realtime_data import (
            get_gold_rate, get_silver_rate,
            get_petrol_price, get_diesel_price,
        )

        handlers = {
            "gold":    get_gold_rate,
            "silver":  get_silver_rate,
            "petrol":  get_petrol_price,
            "diesel":  get_diesel_price,
        }

        fn = handlers.get(commodity)
        if not fn:
            # Fallback: infer from raw command
            c = cmd.lower()
            if "gold" in c or "sona" in c:
                fn = get_gold_rate
            elif "silver" in c or "chandi" in c:
                fn = get_silver_rate
            elif "diesel" in c:
                fn = get_diesel_price
            elif "petrol" in c:
                fn = get_petrol_price
            else:
                self.speak("Which commodity rate should I check?")
                return True

        try:
            result = fn(city)
            self.speak(result)
        except Exception as e:
            self.speak(f"Couldn't fetch {commodity} rate: {e}")
        return True

    def _stock_price(self, d: dict, cmd: str) -> bool:
        symbol = (d.get("stock_symbol") or "").strip().upper()
        if not symbol:
            # Try extracting uppercase ticker from command
            m = re.search(r'\b([A-Z]{2,8})\b', cmd)
            if m:
                symbol = m.group(1)
        if not symbol:
            self.speak("Which stock should I check?")
            return True
        try:
            from modules.realtime_data import get_stock_price
            self.speak(get_stock_price(symbol))
        except Exception as e:
            self.speak(f"Couldn't fetch {symbol} price: {e}")
        return True

    def _crypto_price(self, d: dict, cmd: str) -> bool:
        coin = (d.get("coin") or "").lower().strip()
        if not coin:
            # Infer from raw command
            for name in _COIN_IDS:
                if name in cmd.lower():
                    coin = name
                    break
            if not coin:
                coin = "bitcoin"

        coin_id = _COIN_IDS.get(coin, coin)
        try:
            import requests as _req
            r = _req.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd,inr"},
                timeout=6,
            )
            data = r.json()
            if coin_id in data:
                usd  = data[coin_id].get("usd", 0)
                inr  = data[coin_id].get("inr", 0)
                name = coin_id.replace("-", " ").title()
                self.speak(
                    f"{name} is ₹{inr:,.0f} rupees, that's ${usd:,.0f} US dollars."
                )
            else:
                self.speak(f"Couldn't find price for {coin}.")
        except Exception as e:
            self.speak(f"Crypto price error: {e}")
        return True

    def _weather(self, d: dict, cmd: str) -> bool:
        city = (d.get("city") or self._default_city()).strip()
        try:
            from modules.realtime_data import get_weather
            self.speak(get_weather(city))
        except Exception as e:
            self.speak(f"Couldn't fetch weather for {city}: {e}")
        return True

    def _news(self, d: dict, cmd: str) -> bool:
        topic = (d.get("news_topic") or "india").strip().lower()
        try:
            from modules.realtime_data import get_news
            self.speak(get_news(topic))
        except Exception as e:
            self.speak(f"Couldn't fetch news: {e}")
        return True

    def _web_search(self, d: dict, cmd: str) -> bool:
        query = (d.get("query") or "").strip()
        if not query:
            # Strip common search prefixes from cmd
            for pfx in ["search for", "search", "look up", "what is", "what are",
                        "who is", "tell me about", "find information about", "find"]:
                if cmd.lower().startswith(pfx):
                    query = cmd[len(pfx):].strip()
                    break
            if not query:
                query = cmd
        try:
            from modules.realtime_data import live_web_search
            result = live_web_search(query)
            self.speak(result)
        except Exception as e:
            self.speak(f"Search failed: {e}")
        return True

    def _deep_research(self, d: dict, cmd: str) -> bool:
        topic = (d.get("query") or "").strip()
        if not topic:
            # Strip trigger prefixes
            for pfx in [
                "deep research on", "research on", "research",
                "look into", "investigate", "find out about",
                "give me a report on", "gather info on",
                "full report on", "comprehensive info on",
                "what do you know about",
            ]:
                lc = cmd.lower()
                if lc.startswith(pfx):
                    topic = cmd[len(pfx):].strip()
                    break
            if not topic:
                topic = cmd.strip()
        if not topic:
            self.speak("What should I research?")
            return True
        try:
            from modules.research_agent import research_async
            self.speak(f"Starting deep research on {topic}. I'll report back shortly.")
            research_async(topic)
        except Exception as e:
            self.speak(f"Research module error: {e}")
        return True

    def _price_lookup(self, d: dict, cmd: str) -> bool:
        product = (d.get("product") or "").strip()
        if not product:
            for pfx in ["check price of", "price of", "how much is",
                        "how much does", "find price of", "find price",
                        "what's the price of", "what's the price",
                        "price check for", "price check"]:
                if pfx in cmd.lower():
                    product = cmd.lower().replace(pfx, "").strip()
                    break
        if not product:
            self.speak("What product should I check the price of?")
            return True
        try:
            from modules import web_automation
            self.speak(f"Checking price of {product}.")
            _bg(web_automation.lookup_price, product)
        except Exception as e:
            self.speak(f"Price lookup error: {e}")
        return True

    def _page_summarize(self, d: dict, cmd: str) -> bool:
        try:
            from modules import web_automation
            self.speak("Reading the page. One moment.")
            _bg(web_automation.summarize_page)
        except Exception as e:
            self.speak(f"Page summarize error: {e}")
        return True
