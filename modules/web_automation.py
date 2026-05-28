"""
web_automation.py
Playwright-based web automation for iZACH.

Functions:
  open_website(target)     - navigate to URL / shortname
  search_google(query)     - Google search
  summarize_page()         - extract + Groq-summarize active page
  click_element(target)    - click by text / role / vision fallback
  scroll(direction)        - scroll page up/down/top/bottom
  new_tab(url)             - open new browser tab
  close_tab()              - close current tab
  switch_tab(hint)         - switch to next/prev/named tab
  youtube_play(query)      - search YouTube and click first video
  get_news(topic)          - fetch + summarize news headlines
  lookup_price(product)    - Google Shopping price scrape
  login_to_site()          - auto-fill credentials + submit
  fill_form()              - fill generic form from memory profile
  extract_emails()         - regex scrape emails from page
"""

import re
import os
import json
import threading
import time
import subprocess

_playwright_instance = None
_browser = None
_context = None
_init_lock = threading.Lock()
_active_tab_idx = -1  # -1 = last tab
_last_used = 0.0
_IDLE_TIMEOUT = 120  # close browser after 2 min idle


def _idle_watcher():
    while True:
        time.sleep(60)
        global _browser, _context, _playwright_instance, _last_used
        with _init_lock:
            if _context is not None and _last_used > 0 and (time.time() - _last_used) > _IDLE_TIMEOUT:
                try:
                    _context.close()
                except Exception:
                    pass
                try:
                    _browser.close()
                except Exception:
                    pass
                try:
                    _playwright_instance.stop()
                except Exception:
                    pass
                _context = None
                _browser = None
                _playwright_instance = None
                _last_used = 0.0
                print("[WEB] Playwright browser closed — idle timeout.")


threading.Thread(target=_idle_watcher, daemon=True).start()


def restart_browser():
    """Close and reopen the browser — clears CAPTCHA-flagged sessions."""
    close_browser()
    _get_context()


def close_browser():
    """Immediately close Playwright browser and free memory."""
    global _browser, _context, _playwright_instance, _last_used
    with _init_lock:
        if _context is None:
            return
        try:
            _context.close()
        except Exception:
            pass
        try:
            _browser.close()
        except Exception:
            pass
        try:
            _playwright_instance.stop()
        except Exception:
            pass
        _context = None
        _browser = None
        _playwright_instance = None
        _last_used = 0.0
    print("[WEB] Playwright browser closed.")

_SHORTNAMES = {
    "youtube":      "https://www.youtube.com",
    "google":       "https://www.google.com",
    "github":       "https://www.github.com",
    "gmail":        "https://mail.google.com",
    "reddit":       "https://www.reddit.com",
    "twitter":      "https://www.twitter.com",
    "x":            "https://www.x.com",
    "instagram":    "https://www.instagram.com",
    "linkedin":     "https://www.linkedin.com",
    "netflix":      "https://www.netflix.com",
    "amazon":       "https://www.amazon.in",
    "flipkart":     "https://www.flipkart.com",
    "chatgpt":      "https://chatgpt.com",
    "chat gpt":     "https://chatgpt.com",
    "claude":       "https://claude.ai",
    "perplexity":   "https://www.perplexity.ai",
    "pinterest":    "https://www.pinterest.com",
    "google slides": "https://slides.google.com",
    "slides":       "https://slides.google.com",
    "google colab": "https://colab.research.google.com",
    "colab":        "https://colab.research.google.com",
}

# Services that may have a desktop app installed alongside their website.
# packages: partial Windows Store package names (matched with Get-AppxPackage -Name *<name>*)
# paths: filesystem paths to check for traditional desktop installs
_APP_CAPABLE = {
    "youtube":   {"packages": ["YouTube"],    "paths": []},
    "github":    {"packages": [],             "paths": [
        os.path.expandvars(r"%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe"),
        r"C:\Program Files\GitHub Desktop\GitHubDesktop.exe",
    ]},
    "instagram": {"packages": ["Instagram"],  "paths": []},
    "pinterest": {"packages": ["Pinterest"],  "paths": []},
}


def _load_custom_websites():
    """Merge user-defined websites from custom_websites.json into _SHORTNAMES."""
    try:
        import json as _json
        with open("custom_websites.json") as _f:
            for site in _json.load(_f):
                _SHORTNAMES[site["key"]] = site["url"]
    except Exception:
        pass


def _load_custom_links():
    """Merge user-defined Custom Links (from Cortex UI settings) into _SHORTNAMES."""
    try:
        import json as _json, os as _os
        _path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "custom_links.json")
        with open(_path, encoding="utf-8") as _f:
            for lk in _json.load(_f):
                title = lk.get("title", "").strip().lower()
                url   = lk.get("url", "").strip()
                if title and url:
                    _SHORTNAMES[title] = url
    except Exception:
        pass


_load_custom_websites()
_load_custom_links()


def is_app_installed(service: str) -> bool:
    """Return True if a native desktop/Store app exists for the given service key."""
    info = _APP_CAPABLE.get(service.lower())
    if not info:
        return False
    for path in info["paths"]:
        if os.path.exists(path):
            return True
    for pkg in info["packages"]:
        try:
            result = subprocess.run(
                ["powershell", "-Command", f"Get-AppxPackage -Name '*{pkg}*' | Select-Object -First 1 Name"],
                capture_output=True, text=True, timeout=6,
            )
            if result.stdout.strip():
                return True
        except Exception:
            pass
    return False

_USER_PROFILE_PATH = "user_profile.json"


_STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-IN', 'en-US', 'en']});
    window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : origQuery(p);
"""

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--disable-extensions",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _get_context():
    global _playwright_instance, _browser, _context, _last_used
    with _init_lock:
        if _context is None:
            from playwright.sync_api import sync_playwright
            _playwright_instance = sync_playwright().start()
            # Prefer real Chrome (channel) — much harder to fingerprint than bare Chromium
            try:
                _browser = _playwright_instance.chromium.launch(
                    headless=False, channel="chrome", args=_LAUNCH_ARGS
                )
            except Exception:
                _browser = _playwright_instance.chromium.launch(
                    headless=False, args=_LAUNCH_ARGS
                )
            _context = _browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            _context.add_init_script(_STEALTH_JS)
        _last_used = time.time()
    return _context


def _get_page():
    ctx = _get_context()
    pages = ctx.pages
    if not pages:
        return ctx.new_page()
    global _active_tab_idx
    if 0 <= _active_tab_idx < len(pages):
        return pages[_active_tab_idx]
    return pages[-1]


def _resolve_url(target: str) -> str:
    target = target.strip().lower()
    url = _SHORTNAMES.get(target, target)
    if not url.startswith("http"):
        url = "https://" + url
    return url


_groq_client = None

def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _groq_client

def _groq_summarize(prompt_system: str, content: str, max_tokens: int = 200) -> str:
    resp = _get_groq_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": prompt_system},
            {"role": "user",   "content": content},
        ],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ── Navigate ──────────────────────────────────────────────────

def open_website(target: str):
    try:
        url = _resolve_url(target)
        page = _get_page()
        page.goto(url, timeout=15000)
        return True, f"Opened {target}."
    except Exception as e:
        return False, f"Could not open website: {e}"


def search_google(query: str):
    """Search via DuckDuckGo — avoids Google CAPTCHA while returning equivalent results."""
    try:
        page = _get_page()
        url = "https://duckduckgo.com/?q=" + query.replace(" ", "+") + "&ia=web"
        page.goto(url, timeout=12000)
        page.wait_for_load_state("domcontentloaded", timeout=8000)
        return True, f"Searching for {query}."
    except Exception as e:
        return False, f"Search failed: {e}"


# ── Summarize page ────────────────────────────────────────────

def summarize_page(max_chars: int = 8000):
    try:
        page = _get_page()
        text = page.inner_text("body")
        text = re.sub(r'\s+', ' ', text).strip()[:max_chars]
        if len(text) < 80:
            return False, "Page has no readable text to summarize."
        title = page.title() or "this page"
        summary = _groq_summarize(
            "Summarize the webpage content in 3-4 spoken sentences. Be concise and natural.",
            f"Page title: {title}\n\n{text}",
            max_tokens=180,
        )
        return True, summary
    except Exception as e:
        return False, f"Page summarize failed: {e}"


# ── Click ─────────────────────────────────────────────────────

def click_element(target: str):
    try:
        page = _get_page()
        # 1. By visible text
        try:
            el = page.get_by_text(target, exact=False).first
            if el.is_visible():
                el.click(timeout=4000)
                return True, f"Clicked '{target}'."
        except Exception:
            pass
        # 2. By button role
        try:
            el = page.get_by_role("button", name=re.compile(target, re.IGNORECASE))
            if el.is_visible():
                el.click(timeout=3000)
                return True, f"Clicked '{target}'."
        except Exception:
            pass
        # 3. By link role
        try:
            el = page.get_by_role("link", name=re.compile(target, re.IGNORECASE))
            if el.is_visible():
                el.click(timeout=3000)
                return True, f"Clicked '{target}'."
        except Exception:
            pass
        # 4. Vision fallback via camera_vision
        try:
            from modules.camera_vision import smart_locate_and_click
            result = smart_locate_and_click(target)
            if result:
                return True, f"Found and clicked '{target}' using vision."
        except Exception:
            pass
        return False, f"Could not find '{target}' on the page."
    except Exception as e:
        return False, f"Click failed: {e}"


# ── Scroll ────────────────────────────────────────────────────

def scroll(direction: str = "down", amount: int = 600):
    try:
        page = _get_page()
        js = {
            "down":   f"window.scrollBy(0, {amount})",
            "up":     f"window.scrollBy(0, -{amount})",
            "top":    "window.scrollTo(0, 0)",
            "bottom": "window.scrollTo(0, document.body.scrollHeight)",
        }.get(direction, f"window.scrollBy(0, {amount})")
        page.evaluate(js)
        return True, f"Scrolled {direction}."
    except Exception as e:
        return False, f"Scroll failed: {e}"


# ── Tab management ────────────────────────────────────────────

def new_tab(url: str = None):
    global _active_tab_idx
    try:
        ctx = _get_context()
        page = ctx.new_page()
        _active_tab_idx = len(ctx.pages) - 1
        if url:
            resolved = _resolve_url(url)
            page.goto(resolved, timeout=15000)
            return True, f"Opened new tab at {url}."
        return True, "Opened new tab."
    except Exception as e:
        return False, f"New tab failed: {e}"


def close_tab():
    global _active_tab_idx
    try:
        ctx = _get_context()
        pages = ctx.pages
        if not pages:
            return False, "No tabs open."
        page = _get_page()
        title = page.title() or "tab"
        page.close()
        _active_tab_idx = -1
        return True, f"Closed {title}."
    except Exception as e:
        return False, f"Close tab failed: {e}"


def switch_tab(hint: str = "next"):
    global _active_tab_idx
    try:
        ctx = _get_context()
        pages = ctx.pages
        if len(pages) < 2:
            return False, "Only one tab is open."
        current_idx = _active_tab_idx if 0 <= _active_tab_idx < len(pages) else len(pages) - 1

        if hint in ("next", "forward"):
            new_idx = (current_idx + 1) % len(pages)
        elif hint in ("prev", "previous", "back"):
            new_idx = (current_idx - 1) % len(pages)
        else:
            # Search by title/URL keyword
            hint_lower = hint.lower()
            for i, p in enumerate(pages):
                if hint_lower in (p.title() or "").lower() or hint_lower in p.url.lower():
                    new_idx = i
                    break
            else:
                return False, f"No tab matching '{hint}'."

        pages[new_idx].bring_to_front()
        _active_tab_idx = new_idx
        return True, f"Switched to {pages[new_idx].title() or 'tab'}."
    except Exception as e:
        return False, f"Switch tab failed: {e}"


def list_tabs():
    try:
        ctx = _get_context()
        pages = ctx.pages
        if not pages:
            return False, "No tabs open."
        names = [f"{i+1}. {p.title() or p.url}" for i, p in enumerate(pages)]
        return True, "Open tabs: " + ", ".join(names) + "."
    except Exception as e:
        return False, f"List tabs failed: {e}"


def open_multiple_tabs(tab_actions: list):
    """
    tab_actions: [{"action": "navigate"|"search", "target": str}, ...]
    Reuses current page for tab 0, opens new pages for the rest.
    """
    results = []
    for i, tab in enumerate(tab_actions):
        try:
            action = tab.get("action", "navigate")
            target = tab.get("target", "")
            if i == 0:
                page = _get_page()
            else:
                ctx = _get_context()
                page = ctx.new_page()
                global _active_tab_idx
                _active_tab_idx = len(ctx.pages) - 1

            if action == "search":
                url = "https://duckduckgo.com/?q=" + target.replace(" ", "+") + "&ia=web"
                page.goto(url, timeout=12000)
                results.append(f"tab {i+1}: searching {target}")
            else:
                url = _resolve_url(target)
                page.goto(url, timeout=15000)
                results.append(f"tab {i+1}: {target}")
        except Exception as e:
            results.append(f"tab {i+1} failed: {e}")

    return True, "Opened " + ", ".join(results) + "."


# ── YouTube autoplay ──────────────────────────────────────────

def youtube_play(query: str):
    try:
        page = _get_page()
        search_url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
        page.goto(search_url, timeout=15000)
        # Wait for video results and click first non-ad result
        page.wait_for_selector("ytd-video-renderer", timeout=8000)
        first_video = page.query_selector("ytd-video-renderer a#video-title")
        if not first_video:
            first_video = page.query_selector("a#video-title")
        if first_video:
            first_video.click()
            return True, f"Playing {query} on YouTube."
        return False, "Could not find video results."
    except Exception as e:
        return False, f"YouTube play failed: {e}"


# ── News headlines ────────────────────────────────────────────

def get_news(topic: str = ""):
    try:
        page = _get_page()
        if topic:
            url = "https://news.google.com/search?q=" + topic.replace(" ", "+") + "&hl=en-IN&gl=IN"
        else:
            url = "https://news.google.com/topstories?hl=en-IN&gl=IN"
        page.goto(url, timeout=15000)
        page.wait_for_timeout(2500)

        titles = []
        for sel in ["article h3", "article h4", "h3.ipQwMb", "h4.xBbh9"]:
            els = page.query_selector_all(sel)
            for el in els:
                text = (el.inner_text() or "").strip()
                if text and len(text) > 15 and text not in titles:
                    titles.append(text)
            if len(titles) >= 8:
                break

        if not titles:
            return False, "Could not fetch news headlines right now."

        headlines_text = "\n".join(f"- {t}" for t in titles[:8])
        topic_label = f"about {topic}" if topic else "today"
        summary = _groq_summarize(
            f"Summarize these news headlines {topic_label} in 3-4 natural spoken sentences. "
            "Sound like a news anchor giving a quick briefing.",
            headlines_text,
            max_tokens=160,
        )
        return True, summary
    except Exception as e:
        return False, f"News fetch failed: {e}"


# ── Price lookup ──────────────────────────────────────────────

def lookup_price(product: str):
    try:
        page = _get_page()
        page.goto(
            "https://duckduckgo.com/?q=" + product.replace(" ", "+") + "+price+india&ia=shopping",
            timeout=15000,
        )
        page.wait_for_timeout(2000)

        # Pull visible page text and let Groq find the price
        text = page.inner_text("body")
        text = re.sub(r'\s+', ' ', text).strip()[:5000]

        price_info = _groq_summarize(
            "From this Google search result page, extract the price of the product. "
            "Respond in one sentence like: 'The iPhone 15 is priced at ₹79,900 on Amazon.' "
            "If multiple prices, mention the range. If not found, say so.",
            f"Product: {product}\n\nPage content:\n{text}",
            max_tokens=80,
        )
        return True, price_info
    except Exception as e:
        return False, f"Price lookup failed: {e}"


# ── Login automation ──────────────────────────────────────────

def login_to_site():
    try:
        from modules.memory import load_memory
        memory = load_memory() or {}

        username = password = None
        for key, val in memory.items():
            v = val["value"] if isinstance(val, dict) else str(val)
            k = key.lower()
            if k in ("email", "username", "user", "mail", "login"):
                username = v
            elif k in ("password", "pass", "passwd"):
                password = v

        if not username or not password:
            return False, "No credentials in memory. Save your email and password in iZACH settings first."

        page = _get_page()
        filled = 0

        # Fill username/email
        for sel in [
            'input[type="email"]', 'input[name*="user"]', 'input[name*="email"]',
            'input[id*="user"]', 'input[id*="email"]', 'input[name="login"]',
            'input[autocomplete="username"]', 'input[autocomplete="email"]',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(username)
                    filled += 1
                    break
            except Exception:
                continue

        # Fill password
        try:
            el = page.query_selector('input[type="password"]')
            if el and el.is_visible():
                el.fill(password)
                filled += 1
        except Exception:
            pass

        if filled == 0:
            return False, "Could not find login fields on this page."

        # Submit
        for sel in [
            'button[type="submit"]', 'input[type="submit"]',
            'button:has-text("Sign in")', 'button:has-text("Log in")',
            'button:has-text("Login")', 'button:has-text("Continue")',
            'button:has-text("Next")',
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    return True, "Login submitted."
            except Exception:
                continue

        return True, f"Filled {filled} credential fields. Click submit when ready."
    except Exception as e:
        return False, f"Login failed: {e}"


# ── Form fill (existing, improved) ───────────────────────────

def fill_form():
    try:
        if not os.path.exists(_USER_PROFILE_PATH):
            return False, "user_profile.json not found."
        with open(_USER_PROFILE_PATH) as f:
            profile = json.load(f)

        page = _get_page()
        inputs = page.query_selector_all("input, textarea, select")
        filled = 0

        for inp in inputs:
            try:
                current_val = inp.input_value()
                if current_val and current_val.strip():
                    continue
                attrs = {}
                for attr in ["name", "id", "placeholder"]:
                    val = inp.get_attribute(attr)
                    if val:
                        attrs[attr] = val.lower()
                inp_id = inp.get_attribute("id")
                label_text = ""
                if inp_id:
                    label = page.query_selector(f"label[for='{inp_id}']")
                    if label:
                        label_text = (label.inner_text() or "").lower()
                for key, val in profile.items():
                    k = key.lower()
                    if any(k in a for a in attrs.values()) or k in label_text:
                        inp.fill(str(val))
                        filled += 1
                        break
            except Exception:
                continue

        if filled == 0:
            return False, "No matching fields found to fill."
        return True, f"Filled {filled} field{'s' if filled != 1 else ''}. Review before submitting."
    except Exception as e:
        return False, f"Form fill failed: {e}"


# ── Email extraction (existing) ───────────────────────────────

def extract_emails():
    try:
        page = _get_page()
        content = page.content()
        emails = list(set(re.findall(
            r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', content
        )))
        if not emails:
            return False, "No emails found on this page."
        preview = ", ".join(emails[:5])
        extra = f" and {len(emails) - 5} more" if len(emails) > 5 else ""
        return True, f"Found {len(emails)} email{'s' if len(emails) != 1 else ''}: {preview}{extra}."
    except Exception as e:
        return False, f"Email extraction failed: {e}"
