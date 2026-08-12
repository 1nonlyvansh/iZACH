# iZACH bug-fix batch — pull + verify, Forge UI parity where relevant

Mac already fixed and pushed the confirmed-real bugs from a large batch report. Pull first — everything below already exists on `main`, don't reimplement.

## What was actually fixed

1. **SEC-003 — WhatsApp bridge open on LAN**: `whatsapp_bridge.js` now binds `127.0.0.1` only (was `0.0.0.0` — any device on the LAN could POST `/send-message` and send WhatsApp as you). Backend-only, verify by confirming the bridge still works locally and (if you can test from a second LAN device) that it's no longer reachable remotely.

2. **PERF-002 — `/status` blocked 100-200ms per request**: `ui_api.py` now samples CPU in a background thread every 2s; `/status` reads the cache instead of blocking on `psutil.cpu_percent(interval=0.1)` twice per call. Backend-only.

3. **BUG-006 — WhatsApp session wiped on slow init**: `whatsapp_bridge.js`'s 90s "not ready" watchdog now waits 180s and no longer nukes `.wwebjs_auth` on a plain timeout (a slow first run, network blip, or CPU contention isn't corruption) — it now only wipes on the actual `'already running'`/`'Execution context'` init-error path further down, which is a real corruption signal. Combined with the stale-Chromium-lock cleanup from an earlier push. Backend-only.

4. **BUG-015 — hung task blocks the whole task queue forever**: `modules/task_manager.py`'s `TaskOrchestrator` now runs each task on its own daemon thread with a 30s `join(timeout=...)` — a hung task no longer blocks every subsequent queued task (reminders, etc). Backend-only.

5. **ARCH-004 — `taskkill /F /IM python.exe /T` kills every Python process on the machine**: `izach-ui/electron/main.cjs`'s Windows branch (`window-all-closed`) now filters by command line via PowerShell (`Get-CimInstance Win32_Process | Where CommandLine -like '*main.py*'`) instead of killing by image name alone — was killing any unrelated Python app/IDE/venv you had open too. **This is the one Windows-specific fix in the batch — please actually test it**: open some other Python process (a venv REPL, a script, whatever), close the iZACH Cortex window, confirm the other Python process survives and iZACH's own backend still dies. I can't test Windows PowerShell behavior from Mac.

6. **BUG-004 — dual-instance promotion used `os._exit(0)`**: `modules/instance_coordinator.py`'s `restart_as_primary()` now uses `os.execv()` on Mac (in-place process replacement, no port-release race) but **keeps** `subprocess.Popen(..., CREATE_NEW_CONSOLE) + os._exit(0)` on Windows deliberately — `execv` would swallow Windows' visible-console UX (`CREATE_NEW_CONSOLE`) since it reuses whatever console the current process has instead of opening a fresh one. No Windows-side change needed, just verify a Windows→Mac→Windows round-trip switch still opens a fresh console each time.

7. **BUG-005 (partial) — stale Groq client after key rotation**: `web_automation.py` caches its Groq client forever after first use; rotating `GROQ_API_KEY` in Settings didn't affect it until restart. `ui_api.py`'s key-reload handler now resets it. Backend-only.

8. **Bonus find — barge-in used the wrong mic**: `modules/interrupt_engine.py`'s voice monitor (listens for "stop"/interrupt while iZACH is talking) hardcoded device index `(0, None)`, ignoring whatever mic you'd actually selected in Settings. Now tries the selected mic first. Backend-only, but if Forge UI has a mic selector, double check the same underlying `_mic_device_index` global in `main.py` is what it writes to (matches Cortex's `/mic/select`).

## Claims from the report that turned out FALSE — do not implement these

- **BUG-001** ("hardcoded API keys in `.env` committed to repo"): false. Checked `git ls-files .env`, `git check-ignore -v .env`, and full history — `.env` was never tracked, zero commits reference it. No leak, no rotation needed, don't touch `.githooks`.
- **BUG-009** ("web_automation `_last_used` updated after lock released"): false. Read the actual code — `_last_used = time.time()` is inside the `with _init_lock:` block, correctly ordered already.
- **BUG-010** ("wake word extends active window forever on silence"): false as described — `extend_active()` is already gated behind `_wake_detector.is_active()`, which has its own 8s expiry. Not a bug, it's the intended "stay in conversation during a brief pause" behavior.
- **BUG-005** (full claim — "misses camera_vision, OrchestratorAgent"): false for both. `camera_vision.py`'s keys are already explicitly hot-reloaded in `ui_api.py`'s `/api-keys` POST handler. `orchestrator.py` doesn't hold its own API key at all — no reload needed. Only the `web_automation.py` Groq-client-cache gap (item 7 above) was real.

## Rejected — real concern, but the suggested fix would make things worse

- **BUG-004's suggested implementation** (call `safe_shutdown()` then `os.execv()`): `safe_shutdown()` ends in `sys.exit(0)`, which only kills the *calling thread* — and `restart_as_primary()` runs on a background thread, so calling it there wouldn't have terminated the process at all. Implemented a narrower, verified-correct fix instead (item 6 above).
- **BUG-003's suggested implementation** (delete `_patch_agents_for_text_reply`/`_unpatch_agents`, rely on `main.py`'s `_SPEAK_SOURCE == "text"` check): would have broken text-command replies entirely. That patching mechanism doesn't just suppress duplicate TTS — it **captures** the actual reply text each specialized agent generates, which becomes the HTTP response body for `/command`. `_SPEAK_SOURCE == "text"` in `main.py:speak()` just silently drops the message with no way to get the text back to the caller. Also: the report's premise ("agents created once at startup; patches don't survive recreation") doesn't apply — `CommandChain` and its agents are built exactly once per process lifetime, never recreated mid-session. Left this code untouched.

## Not touched — needs live testing I can't do blind, or doesn't apply to this deployment

- **BUG-002** (mic race between `main.py:listen()` and `interrupt_engine.py`'s monitor): the two are actually gated to run at disjoint times already (`set_speaking(True/False)` starts/stops the interrupt monitor specifically around TTS playback, while `listen()` runs when *not* speaking) — this looks like a deliberate hand-off design, not a naive race. The suggested fix is a full rewrite of the core voice pipeline (new `MicrophoneManager` class, refactor both call sites) — too high-risk to do without extensive live voice testing. Didn't touch it.
- **BUG-007** (diarization energy threshold): the current value has its own comment — `"lowered — was rejecting normal speech"` — meaning someone already tuned this specifically to fix a prior false-rejection bug. Changing it back risks reintroducing that. Left as-is; if it's still misbehaving, needs live A/B testing with real audio, not another blind guess.
- **BUG-008** (scheduler DST bug): technically correct in general, but this deployment's timezone is Asia/Kolkata (see `web_automation.py`'s `timezone_id="Asia/Kolkata"`), which does not observe DST at all — the described failure mode can't occur here. Not fixing a moderate-risk rewrite of the reminders code for a scenario that doesn't apply.
- **RV-001 through RV-004**: these are manual/live verification tasks (voice-vs-text parity, network-partition role negotiation, WhatsApp durability under kill, Playwright tab isolation), not code fixes. Can't execute any of them without booting the full stack and running real multi-minute scenarios. Best done by whichever of us tests next.

## Verify after pulling

- Restart-after-promote (item 6) still shows a fresh console window on Windows.
- Close iZACH's Cortex window with some *other* unrelated Python process running — confirm only iZACH's own backend dies (item 5, the one you should actually test since I can't).
- WhatsApp bridge still reachable from `main.py` locally after the `127.0.0.1` bind (item 1) — should be unaffected since that's how it already talks to it.
