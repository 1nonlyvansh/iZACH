import time
import re
from groq import Groq
from google import genai
from google.genai import types


class AIProvider:
    def __init__(self, groq_key, gemini_keys):
        self.groq_client = Groq(api_key=groq_key)
        self.gemini_keys = gemini_keys
        self.current_gem_idx = 0
        self.gemini_client = None
        self.gemini_chat = None
        self._init_gemini()

    def _init_gemini(self):
        try:
            self.gemini_client = genai.Client(
                api_key=self.gemini_keys[self.current_gem_idx]
            )
        except IndexError:
            print("[SYSTEM] Gemini Init Failed: Invalid API key index.")
        except Exception as e:
            print(f"[SYSTEM] Gemini Init Failed: {e}")

    def send_message(self, query):
        """Primary Logic: Groq -> Gemini Fallback"""
        # 1. TRY GROQ (Primary)
        try:
            return self._call_groq(query)
        except Exception as e:
            if self._is_rate_limit(e):
                return self._handle_429(query, "groq")
            print(f"[GROQ ERROR]: {e}")

        # 2. FALLBACK TO GEMINI
        print("[SYSTEM] Groq failed. Falling back to Gemini...")
        try:
            return self._call_gemini(query)
        except Exception as e:
            if self._is_rate_limit(e):
                return self._handle_429(query, "gemini")
            return "Neural link instability. Both providers offline."

    def _call_groq(self, query):
        completion = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": query}]
        )
        return completion.choices[0].message.content

    def _call_gemini(self, query):
        response = self.gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=query,
            config=types.GenerateContentConfig(
                system_instruction="iZACH: Concise AI."
            )
        )
        return response.text

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
        except:
            # If retry fails, pivot to the other provider
            if provider_type == "groq":
                print("[SYSTEM] Groq retry failed. Pivoting to Gemini.")
                return self._call_gemini(query)
            else:
                print("[SYSTEM] Gemini retry failed. No AI available.")
                return "Neural links exhausted. Please standby."