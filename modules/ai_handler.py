import os
import time
import httpx
from groq import Groq
from google import genai
from google.genai import types
from modules import rag_memory

_HTTP_LIMITS = httpx.Limits(max_connections=5, max_keepalive_connections=2)

_style_cache: dict = {}
_STYLE_TTL = 30  # seconds

_connectivity_cache: dict = {"online": None, "ts": 0}
_CONNECTIVITY_TTL = 15  # seconds — recheck every 15s


def _check_internet() -> bool:
    global _connectivity_cache
    now = time.time()
    if _connectivity_cache["online"] is not None and now - _connectivity_cache["ts"] < _CONNECTIVITY_TTL:
        return _connectivity_cache["online"]
    try:
        httpx.get("https://www.google.com", timeout=3.0)
        _connectivity_cache = {"online": True, "ts": now}
        return True
    except Exception:
        _connectivity_cache = {"online": False, "ts": now}
        return False


class AIProvider:
    def __init__(self, groq_key, gemini_keys, anthropic_key: str = ""):
        self.groq_client = Groq(api_key=groq_key, http_client=httpx.Client(limits=_HTTP_LIMITS))
        self.gemini_keys = gemini_keys
        self.current_gem_idx = 0
        self.gemini_client = None
        self.gemini_chat = None
        self.anthropic_key = (anthropic_key or "").strip()
        self._init_gemini()

    def reload_keys(self, groq_key: str = None, gemini_keys: list = None,
                    anthropic_key: str = None):
        """Hot-swap API keys at runtime. Rebuilds underlying clients."""
        if groq_key:
            try:
                self.groq_client = Groq(api_key=groq_key, http_client=httpx.Client(limits=_HTTP_LIMITS))
                print(f"[AIProvider] Groq client rebuilt with new key ({groq_key[:8]}...).")
            except Exception as e:
                print(f"[AIProvider] Groq reload failed: {e}")
        if anthropic_key is not None:
            self.anthropic_key = anthropic_key.strip()
            if self.anthropic_key:
                print(f"[AIProvider] Anthropic/Claude key set ({self.anthropic_key[:12]}...).")
            else:
                print("[AIProvider] Anthropic/Claude key cleared — reverting to Groq primary.")
        if gemini_keys:
            self.gemini_keys = gemini_keys
            self.current_gem_idx = 0
            self._init_gemini()
            print(f"[AIProvider] Gemini keys reloaded ({len([k for k in gemini_keys if k])} active).")

    def _init_gemini(self):
        try:
            self.gemini_client = genai.Client(
                api_key=self.gemini_keys[self.current_gem_idx]
            )
        except IndexError:
            print("[SYSTEM] Gemini Init Failed: Invalid API key index.")
        except Exception as e:
            print(f"[SYSTEM] Gemini Init Failed: {e}")

    def _call_claude(self, query, model: str = "claude-sonnet-4-5") -> str:
        """
        Call Anthropic-compatible Claude endpoint.
        Supports:
          sk-ant-...  → standard Anthropic API (api.anthropic.com)
          ksk_...     → Kiro / Amazon endpoint (set KIRO_API_BASE in .env)
          Any key     → falls back to ANTHROPIC_API_BASE env override if set
        """
        import anthropic as _ant, os as _os
        key = self.anthropic_key

        # Determine base URL
        base_url = (
            _os.getenv("KIRO_API_BASE") or
            _os.getenv("ANTHROPIC_API_BASE") or
            None
        )
        # Kiro keys (ksk_...) need their own endpoint if KIRO_API_BASE is set;
        # if not set, try standard Anthropic endpoint anyway (may 401 — will fall to Groq)
        client_kwargs = {"api_key": key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = _ant.Anthropic(**client_kwargs)
        system_content = self._build_system_prompt(query)
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_content,
            messages=[{"role": "user", "content": query}],
        )
        result = msg.content[0].text
        try:
            from modules.api_usage_tracker import record as _rec
            _rec("anthropic")
        except Exception:
            pass
        return result

    def send_message(self, query):
        """Online cloud providers only: Claude (if key set) → Groq → Gemini."""
        online = _check_internet()
        if not online:
            return "Offline — cloud providers unreachable."

        response = None

        # 0. CLAUDE PRIMARY (if Anthropic/Kiro key configured)
        if self.anthropic_key:
            try:
                response = self._call_claude(query)
            except Exception as e:
                print(f"[CLAUDE ERROR]: {e} — falling back to Groq")

        if response is not None:
            return response

        # 1. TRY GROQ (Primary when no Claude key)
        try:
            response = self._call_groq(query)
        except Exception as e:
            if self._is_rate_limit(e):
                print("[ALERT] Groq rate limited — trying Groq retry once...")
                try:
                    time.sleep(3)
                    response = self._call_groq(query)
                except Exception:
                    pass
            else:
                print(f"[GROQ ERROR]: {e}")

        # 2. FALLBACK: rotate through ALL Gemini keys
        if response is None:
            valid_keys = [k for k in self.gemini_keys if k]
            for attempt, key in enumerate(valid_keys):
                try:
                    print(f"[SYSTEM] Trying Gemini key {attempt + 1}/{len(valid_keys)}...")
                    client = genai.Client(api_key=key)
                    from google.genai import types as _types
                    sys_instr = self._build_system_prompt(query)
                    resp = client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents=query,
                        config=_types.GenerateContentConfig(system_instruction=sys_instr)
                    )
                    response = resp.text
                    if response:
                        # Update active key index on success
                        self.current_gem_idx = attempt
                        self._init_gemini()
                        break
                except Exception as e:
                    if self._is_rate_limit(e):
                        print(f"[SYSTEM] Gemini key {attempt + 1} rate limited — trying next key...")
                        continue
                    else:
                        print(f"[GEMINI ERROR key {attempt + 1}]: {e}")
                        break

        # 3. FINAL FALLBACK: OpenRouter (free tier, no daily quota)
        if response is None:
            print("[SYSTEM] All Groq/Gemini keys exhausted — trying OpenRouter...")
            try:
                response = self._call_openrouter(query)
            except Exception as e:
                print(f"[OPENROUTER ERROR]: {e}")

        if response:
            rag_memory.add_conversation(query, response)
        return response or "Neural link instability. All providers offline."

    def _call_openrouter(self, query: str) -> str | None:
        """OpenRouter fallback — uses free models, no daily quota."""
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return None
        import httpx as _hx
        sys_prompt = self._build_system_prompt(query)
        payload = {
            "model": "openai/gpt-oss-20b:free",
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": query},
            ],
        }
        r = _hx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()["choices"][0]["message"]["content"]
        try:
            from modules.api_usage_tracker import record as _rec
            _rec("openrouter")
        except Exception:
            pass
        return result

    # Override send_with_model to track DeepSeek calls
    def _track_deepseek(self):
        try:
            from modules.api_usage_tracker import record as _rec
            _rec("deepseek")
        except Exception:
            pass

    @staticmethod
    def _style_instruction() -> str:
        global _style_cache
        now = time.time()
        if _style_cache and now - _style_cache.get("ts", 0) < _STYLE_TTL:
            return _style_cache["value"]
        try:
            import json as _j
            with open("api_keys.json") as _f:
                cfg = _j.load(_f)
        except Exception:
            return ""
        parts = []
        style = cfg.get("response_style", "casual")
        verbosity = cfg.get("response_verbosity", "balanced")
        if style == "professional":
            parts.append("Be formal and professional. Avoid humor and sarcasm. Use proper sentence structure.")
        elif style == "concise":
            parts.append("Be extremely concise and direct. Strip all filler.")
        if verbosity == "brief":
            parts.append("Keep every response to 1-2 sentences maximum, no exceptions.")
        elif verbosity == "detailed":
            parts.append("Provide thorough explanations with examples and context where relevant.")
        result = " ".join(parts)
        _style_cache = {"value": result, "ts": now}
        return result

    @staticmethod
    def _datetime_context() -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(tz=ZoneInfo("Asia/Kolkata"))
        return now.strftime("Current date and time: %A, %d %B %Y, %I:%M %p IST.")

    # Structured data rendering instruction — injected into every system prompt
    _TABLE_INSTR = (
        "When presenting structured or comparative data — college comparisons, rankings, "
        "differences between two things, feature comparisons, schedules, price lists, "
        "admission criteria, or any multi-attribute list — format it as a markdown table "
        "with clear column headers. After the table, explain the key takeaway in one "
        "conversational sentence. Do NOT read out each table row individually. "
        "For non-structured responses (single facts, opinions, actions), use plain prose."
    )

    def _build_system_prompt(self, query: str) -> str:
        style = self._style_instruction()
        dt_ctx = self._datetime_context()
        try:
            from modules.personality import PERSONALITY_PROMPT as _pp
            base = f"{_pp}\n{dt_ctx}"
        except Exception:
            base = f"You are iZACH, a sharp witty AI assistant. {dt_ctx}"
        parts = [base, self._TABLE_INSTR]
        if style:
            parts.append(style)
        ctx = rag_memory.get_relevant_context(query)
        if ctx:
            parts.append(ctx)
        return " ".join(parts)

    def _call_groq(self, query, key_name: str = "groq_main"):
        system_content = self._build_system_prompt(query)
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query},
        ]
        completion = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=300,   # keeps replies short and punchy — no essays
            temperature=0.85, # slight warmth for more natural tone
        )
        result = completion.choices[0].message.content
        try:
            from modules.api_usage_tracker import record as _rec
            _rec(key_name)
        except Exception:
            pass
        return result

    def _call_gemini(self, query):
        system_instr = self._build_system_prompt(query)
        response = self.gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=query,
            config=types.GenerateContentConfig(
                system_instruction=system_instr
            )
        )
        result = response.text
        try:
            from modules.api_usage_tracker import record as _rec
            key_name = f"gemini_{self.current_gem_idx + 1}"
            _rec(key_name)
        except Exception:
            pass
        return result

    def _is_rate_limit(self, error):
        """Detects 429 errors in either Groq or Gemini responses."""
        err_msg = str(error).lower()
        return "429" in err_msg or "resource_exhausted" in err_msg or "rate_limit" in err_msg

    def _handle_429(self, query, provider_type):
        """Smart 429 Handling: Sleep and Retry once, else pivot."""
        print(f"[ALERT] 429 Rate Limit on {provider_type}. Attempting recovery...")
        
        # Extraction logic for retryDelay if it exists in the error string
        # Default to 5 seconds if not found
        time.sleep(5) 

        try:
            if provider_type == "groq":
                return self._call_groq(query)
            else:
                return self._call_gemini(query)
        except Exception:
            # If retry fails, pivot to the other provider
            if provider_type == "groq":
                print("[SYSTEM] Groq retry failed. Pivoting to Gemini.")
                return self._call_gemini(query)
            else:
                print("[SYSTEM] Gemini retry failed. No AI available.")
                return "Neural links exhausted. Please standby."

    # ── DeepSeek ──────────────────────────────────────────────────────────────

    def send_deepseek(self, query: str, system_prompt: str = "", model: str = "deepseek-chat") -> str | None:
        """
        Send query to DeepSeek API (OpenAI-compatible).
        model: 'deepseek-chat' (fast, free tier) or 'deepseek-reasoner' (R1, shows thinking)
        """
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            print("[DeepSeek] No API key — falling back to Groq")
            return None
        try:
            from openai import OpenAI as _OAI
            client = _OAI(api_key=api_key, base_url="https://api.deepseek.com")
            sys_content = system_prompt or self._build_system_prompt(query)
            messages = [
                {"role": "system", "content": sys_content},
                {"role": "user",   "content": query},
            ]
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=8192,
            )
            result = resp.choices[0].message.content
            rag_memory.add_conversation(query, result)
            try:
                from modules.api_usage_tracker import record as _rec
                _rec("deepseek")
            except Exception:
                pass
            return result
        except Exception as e:
            print(f"[DeepSeek ERROR]: {e}")
            return None

    def send_with_model(self, query: str, model_pref: str, skill_system: str = "") -> str:
        """
        Route to preferred model. Used by skill engine.
        model_pref: 'deepseek' | 'groq' | 'gemini' | 'auto'
        skill_system: extra system prompt text from skill .md
        """
        sys_prompt = ""
        if skill_system:
            base = self._build_system_prompt(query)
            sys_prompt = f"{skill_system}\n\n---\n{base}"

        if model_pref == "deepseek":
            result = self.send_deepseek(query, sys_prompt or self._build_system_prompt(query))
            if result:
                return result
            print("[SkillRoute] DeepSeek failed, falling back to Groq")

        if model_pref == "gemini":
            try:
                q = f"{sys_prompt}\n\nUser: {query}" if sys_prompt else query
                return self._call_gemini(q)
            except Exception as e:
                print(f"[SkillRoute] Gemini failed: {e}")

        if model_pref in ("groq", "auto") or True:
            try:
                q = f"{sys_prompt}\n\nUser: {query}" if sys_prompt else query
                result = self._call_groq(q)
                if result:
                    return result
            except Exception as e:
                print(f"[SkillRoute] Groq failed: {e}")
            # Final fallback
            try:
                q = f"{sys_prompt}\n\nUser: {query}" if sys_prompt else query
                return self._call_gemini(q)
            except Exception as e:
                print(f"[SkillRoute] All providers failed: {e}")

        return "All AI providers unavailable for skill request."