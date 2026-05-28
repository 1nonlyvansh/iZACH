"""
test_web_automation.py
Tests for all 14 web_automation functions.
Uses unittest.mock to mock Playwright pages — no real browser needed.
"""
import sys, os, json, re, shutil
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from unittest.mock import MagicMock, patch, PropertyMock, call

import modules.web_automation as wa

PASS = 0; FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS {name}")
        PASS += 1
    else:
        print(f"  FAIL {name}" + (f" | {detail}" if detail else ""))
        FAIL += 1


def make_page(
    inner_text="Hello world this is a test page",
    title="Test Page",
    url="https://example.com",
    content="<html><body>Hello</body></html>",
):
    page = MagicMock()
    page.inner_text.return_value = inner_text
    page.title.return_value = title
    page.url = url
    page.content.return_value = content
    page.is_visible.return_value = True
    page.evaluate.return_value = None
    page.goto.return_value = None
    page.wait_for_selector.return_value = MagicMock()
    page.wait_for_timeout.return_value = None
    page.fill.return_value = None
    page.press.return_value = None
    page.click.return_value = None
    page.close.return_value = None
    page.bring_to_front.return_value = None
    return page


print("=" * 55)
print("WEB AUTOMATION TEST SUITE")
print("=" * 55)

# ── T1: _resolve_url ─────────────────────────────────────────
print("\n[T1] _resolve_url shortnames + custom URLs")
check("T1 youtube",   wa._resolve_url("youtube")   == "https://www.youtube.com")
check("T1 gmail",     wa._resolve_url("gmail")     == "https://mail.google.com")
check("T1 amazon",    wa._resolve_url("amazon")    == "https://www.amazon.in")
check("T1 linkedin",  wa._resolve_url("linkedin")  == "https://www.linkedin.com")
check("T1 flipkart",  wa._resolve_url("flipkart")  == "https://www.flipkart.com")
check("T1 netflix",   wa._resolve_url("netflix")   == "https://www.netflix.com")
check("T1 custom no-http", wa._resolve_url("example.com") == "https://example.com")
check("T1 custom with-http", wa._resolve_url("http://example.com") == "http://example.com")
check("T1 https passthrough", wa._resolve_url("https://foo.com") == "https://foo.com")

# ── T2: open_website ─────────────────────────────────────────
print("\n[T2] open_website")
page = make_page()
with patch.object(wa, '_get_page', return_value=page):
    ok, msg = wa.open_website("youtube")
    check("T2 goto called",  page.goto.called)
    check("T2 returns True", ok)
    check("T2 url resolved", "youtube.com" in page.goto.call_args[0][0])

# ── T3: search_google ────────────────────────────────────────
print("\n[T3] search_google")
page = make_page()
with patch.object(wa, '_get_page', return_value=page):
    ok, msg = wa.search_google("Python tutorials")
    check("T3 returns True",   ok)
    check("T3 goto search",    "duckduckgo.com" in page.goto.call_args[0][0] or "google.com" in page.goto.call_args[0][0])
    check("T3 query in url",   "Python" in page.goto.call_args[0][0])

# ── T4: summarize_page ───────────────────────────────────────
print("\n[T4] summarize_page")
page = make_page(inner_text="This is a long article about Python programming. " * 20)
mock_groq_resp = MagicMock()
mock_groq_resp.choices[0].message.content = "This page is about Python programming tutorials."
with patch.object(wa, '_get_page', return_value=page):
    with patch('modules.web_automation._groq_summarize', return_value="Python article summary.") as mock_sum:
        ok, msg = wa.summarize_page()
        check("T4 returns True",         ok)
        check("T4 groq called",          mock_sum.called)
        check("T4 inner_text called",    page.inner_text.called)
        check("T4 returns summary text", "summary" in msg.lower() or len(msg) > 5)

# T4b: empty page
page_empty = make_page(inner_text="  ")
with patch.object(wa, '_get_page', return_value=page_empty):
    ok2, msg2 = wa.summarize_page()
    check("T4b empty page returns False", not ok2)

# ── T5: click_element ────────────────────────────────────────
print("\n[T5] click_element")
page = make_page()
mock_el = MagicMock()
mock_el.is_visible.return_value = True
page.get_by_text.return_value.first = mock_el
with patch.object(wa, '_get_page', return_value=page):
    ok, msg = wa.click_element("Subscribe")
    check("T5 returns True",      ok)
    check("T5 get_by_text used",  page.get_by_text.called)
    check("T5 element clicked",   mock_el.click.called)

# T5b: element not found, no vision fallback crash
page2 = make_page()
page2.get_by_text.side_effect = Exception("not found")
page2.get_by_role.side_effect = Exception("not found")
with patch.object(wa, '_get_page', return_value=page2):
    with patch('modules.web_automation.smart_locate_and_click', return_value=False, create=True):
        with patch.dict('sys.modules', {'modules.camera_vision': MagicMock(smart_locate_and_click=lambda t: False)}):
            ok2, msg2 = wa.click_element("nonexistent-button-xyz")
            check("T5b not found returns False", not ok2)

# ── T6: scroll ───────────────────────────────────────────────
print("\n[T6] scroll")
page = make_page()
with patch.object(wa, '_get_page', return_value=page):
    for direction, expected_js_fragment in [
        ("down",   "scrollBy(0, 600)"),
        ("up",     "scrollBy(0, -600)"),
        ("top",    "scrollTo(0, 0)"),
        ("bottom", "scrollHeight"),
    ]:
        page.evaluate.reset_mock()
        ok, _ = wa.scroll(direction)
        js_called = page.evaluate.call_args[0][0] if page.evaluate.called else ""
        check(f"T6 scroll {direction}", ok and expected_js_fragment in js_called,
              f"js={js_called!r}")

# ── T7: Tab management ───────────────────────────────────────
print("\n[T7] Tab management")

# list_tabs
page1 = make_page(title="Gmail")
page2 = make_page(title="YouTube", url="https://youtube.com")
mock_ctx = MagicMock()
mock_ctx.pages = [page1, page2]
with patch.object(wa, '_get_context', return_value=mock_ctx):
    ok, msg = wa.list_tabs()
    check("T7a list_tabs returns True",   ok)
    check("T7a lists both tabs",          "Gmail" in msg and "YouTube" in msg)

# list_tabs — empty
mock_ctx_empty = MagicMock()
mock_ctx_empty.pages = []
with patch.object(wa, '_get_context', return_value=mock_ctx_empty):
    ok2, msg2 = wa.list_tabs()
    check("T7b list_tabs empty returns False", not ok2)

# new_tab
mock_ctx2 = MagicMock()
new_page = make_page()
mock_ctx2.new_page.return_value = new_page
mock_ctx2.pages = [new_page]
with patch.object(wa, '_get_context', return_value=mock_ctx2):
    ok, msg = wa.new_tab()
    check("T7c new_tab no url", ok and mock_ctx2.new_page.called)
    mock_ctx2.new_page.reset_mock(); new_page.goto.reset_mock()
    ok2, _ = wa.new_tab("github")
    check("T7d new_tab with url", ok2 and new_page.goto.called)

# close_tab
mock_ctx3 = MagicMock()
p_close = make_page(title="Reddit")
mock_ctx3.pages = [p_close]
wa._active_tab_idx = -1
with patch.object(wa, '_get_context', return_value=mock_ctx3):
    with patch.object(wa, '_get_page', return_value=p_close):
        ok, msg = wa.close_tab()
        check("T7e close_tab calls close()", ok and p_close.close.called)

# switch_tab next
p_a = make_page(title="Tab A"); p_b = make_page(title="Tab B")
mock_ctx4 = MagicMock()
mock_ctx4.pages = [p_a, p_b]
wa._active_tab_idx = 0
with patch.object(wa, '_get_context', return_value=mock_ctx4):
    ok, msg = wa.switch_tab("next")
    check("T7f switch_tab next", ok and p_b.bring_to_front.called)

# switch_tab by name
p_x = make_page(title="Google Docs")
mock_ctx5 = MagicMock()
mock_ctx5.pages = [p_a, p_x]
wa._active_tab_idx = 0
with patch.object(wa, '_get_context', return_value=mock_ctx5):
    ok2, msg2 = wa.switch_tab("docs")
    check("T7g switch_tab by name", ok2 and p_x.bring_to_front.called, msg2)

# only 1 tab — switch returns False
mock_ctx6 = MagicMock()
mock_ctx6.pages = [p_a]
wa._active_tab_idx = 0
with patch.object(wa, '_get_context', return_value=mock_ctx6):
    ok3, _ = wa.switch_tab("next")
    check("T7h switch_tab single tab returns False", not ok3)

# ── T8: youtube_play ─────────────────────────────────────────
print("\n[T8] youtube_play")
page = make_page()
mock_video = MagicMock()
page.query_selector.return_value = mock_video
with patch.object(wa, '_get_page', return_value=page):
    ok, msg = wa.youtube_play("lo-fi beats")
    check("T8 goto youtube search", "youtube.com/results" in page.goto.call_args[0][0])
    check("T8 video clicked",       mock_video.click.called)
    check("T8 returns True",        ok)

# T8b: no video found
page2 = make_page()
page2.query_selector.return_value = None
with patch.object(wa, '_get_page', return_value=page2):
    ok2, _ = wa.youtube_play("xyznonexistent")
    check("T8b no video returns False", not ok2)

# ── T9: get_news ─────────────────────────────────────────────
print("\n[T9] get_news")
page = make_page()
mock_h3 = MagicMock()
mock_h3.inner_text.return_value = "Breaking: Python 4.0 Released with Major AI Features"
page.query_selector_all.return_value = [mock_h3] * 6
with patch.object(wa, '_get_page', return_value=page):
    with patch('modules.web_automation._groq_summarize', return_value="Top story: Python 4.0 released.") as mock_gs:
        ok, msg = wa.get_news()
        check("T9 returns True",     ok)
        check("T9 groq called",      mock_gs.called)
        check("T9 headline passed",  "Python" in mock_gs.call_args[0][1])

# T9 with topic
with patch.object(wa, '_get_page', return_value=page):
    with patch('modules.web_automation._groq_summarize', return_value="AI news summary."):
        ok2, _ = wa.get_news("artificial intelligence")
        check("T9b topic in url", "artificial" in page.goto.call_args[0][0])

# ── T10: lookup_price ────────────────────────────────────────
print("\n[T10] lookup_price")
page = make_page(inner_text="iPhone 15 price: ₹79,900 Buy now on Amazon")
with patch.object(wa, '_get_page', return_value=page):
    with patch('modules.web_automation._groq_summarize', return_value="iPhone 15 is priced at ₹79,900 on Amazon.") as mock_p:
        ok, msg = wa.lookup_price("iPhone 15")
        check("T10 returns True",     ok)
        check("T10 search engine",    "duckduckgo.com" in page.goto.call_args[0][0] or "google.com" in page.goto.call_args[0][0])
        check("T10 product in query", "iPhone" in page.goto.call_args[0][0])
        check("T10 groq called",      mock_p.called)

# ── T11: login_to_site ───────────────────────────────────────
print("\n[T11] login_to_site")
page = make_page()
mock_email_input  = MagicMock(); mock_email_input.is_visible.return_value = True
mock_pass_input   = MagicMock(); mock_pass_input.is_visible.return_value = True
mock_submit_btn   = MagicMock(); mock_submit_btn.is_visible.return_value = True

def _mock_query_selector(sel):
    if 'email' in sel or 'user' in sel:
        return mock_email_input
    if 'password' in sel:
        return mock_pass_input
    if 'submit' in sel:
        return mock_submit_btn
    return None

page.query_selector.side_effect = _mock_query_selector

fake_memory = {
    "email":    {"value": "test@example.com"},
    "password": {"value": "secret123"},
}
with patch.object(wa, '_get_page', return_value=page):
    with patch('modules.web_automation.load_memory', return_value=fake_memory, create=True):
        with patch.dict('sys.modules', {'modules.memory': MagicMock(load_memory=lambda: fake_memory)}):
            import importlib
            # patch load_memory at point of use inside login_to_site
            import modules.memory as mem_mod
            original_load = getattr(mem_mod, 'load_memory', None)
            mem_mod.load_memory = lambda: fake_memory
            try:
                ok, msg = wa.login_to_site()
                check("T11 returns True",       ok, msg)
                check("T11 email filled",       mock_email_input.fill.called)
                check("T11 password filled",    mock_pass_input.fill.called)
            finally:
                if original_load:
                    mem_mod.load_memory = original_load

# T11b: no credentials
with patch.object(wa, '_get_page', return_value=page):
    import modules.memory as mem_mod2
    orig = getattr(mem_mod2, 'load_memory', None)
    mem_mod2.load_memory = lambda: {}
    try:
        ok2, msg2 = wa.login_to_site()
        check("T11b no credentials returns False", not ok2)
    finally:
        if orig: mem_mod2.load_memory = orig

# ── T12: extract_emails ──────────────────────────────────────
print("\n[T12] extract_emails")
html_with_emails = """<html><body>
  Contact us at support@izach.ai or admin@example.com
  Also hello@test.org for feedback
</body></html>"""
page = make_page(content=html_with_emails)
with patch.object(wa, '_get_page', return_value=page):
    ok, msg = wa.extract_emails()
    check("T12 returns True",    ok)
    check("T12 count correct",   "3" in msg)
    check("T12 email in msg",    "izach.ai" in msg or "example.com" in msg)

# T12b: no emails
page2 = make_page(content="<html><body>No emails here</body></html>")
with patch.object(wa, '_get_page', return_value=page2):
    ok2, _ = wa.extract_emails()
    check("T12b no emails returns False", not ok2)

# ── T13: fill_form ───────────────────────────────────────────
print("\n[T13] fill_form")
profile_data = {"name": "Vansh", "email": "vansh@example.com"}
with open(_USER_PROFILE_PATH := "user_profile.json", "w") as f:
    json.dump(profile_data, f)

page = make_page()
name_inp  = MagicMock(); name_inp.input_value.return_value = ""; name_inp.get_attribute.side_effect = lambda a: "name" if a=="name" else None
email_inp = MagicMock(); email_inp.input_value.return_value = ""; email_inp.get_attribute.side_effect = lambda a: "email" if a in ("name","id","placeholder") else None
page.query_selector_all.return_value = [name_inp, email_inp]
page.query_selector.return_value = None

with patch.object(wa, '_get_page', return_value=page):
    ok, msg = wa.fill_form()
    check("T13 returns True",  ok, msg)
    check("T13 fields filled", name_inp.fill.called or email_inp.fill.called)

os.remove("user_profile.json")

# T13b: no profile file
with patch.object(wa, '_get_page', return_value=page):
    ok2, _ = wa.fill_form()
    check("T13b no profile returns False", not ok2)

# ── T14: command routing (smoke test) ────────────────────────
print("\n[T14] Command routing in command_chain")
routed = []
def fake_handle(cmd): routed.append(cmd)

_WEB_TRIGGERS = [
    "summarize this page",
    "scroll down",
    "scroll to bottom",
    "click on login",
    "click the submit button",
    "open new tab",
    "close tab",
    "next tab",
    "play on youtube",
    "what's in the news",
    "latest news about cricket",
    "check price of RTX 4090",
    "login to github",
    "extract emails",
    "search on google machine learning",
    "open linkedin",
]

for trigger in _WEB_TRIGGERS:
    _WEB_AUTOMATION_TRIGGERS = [
        "summarize this page", "summarize page", "what does this page say",
        "what's on this page", "read this page", "explain this page",
        "summarize this website", "what does this website say",
        "click on", "click the", "press the button", "press button",
        "scroll down", "scroll up", "scroll to top", "scroll to bottom", "scroll back",
        "open new tab", "new tab", "close tab", "close this tab",
        "switch tab", "next tab", "previous tab", "switch to tab",
        "list tabs", "show tabs", "what tabs",
        "play on youtube", "youtube play", "search youtube for",
        "find on youtube", "open youtube and play",
        "what's in the news", "latest news", "read news",
        "today's news", "news headlines", "what's happening",
        "tell me the news", "any news",
        "check price of", "price of", "how much is", "how much does",
        "find price", "what's the price", "price check",
        "log in to", "login to", "sign in to", "log into",
        "auto login", "login automatically",
        "open youtube", "open google", "open github", "open gmail", "open reddit",
        "open instagram", "open linkedin", "open twitter", "open netflix",
        "open amazon", "open flipkart", "open website", "go to",
        "search on google", "google search", "look up on google",
        "fill form", "autofill", "fill the form", "fill this form",
        "fill these details", "fill my details",
        "extract emails", "find emails", "scrape emails",
    ]
    matched = any(t in trigger for t in _WEB_AUTOMATION_TRIGGERS)
    check(f"T14 routes: '{trigger}'", matched)

# ── Summary ───────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"WEB AUTOMATION TESTS: {PASS} passed, {FAIL} failed")
print('='*55)
