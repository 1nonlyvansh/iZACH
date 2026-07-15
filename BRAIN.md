# BRAIN.md — iZACH Project Reference

> **Purpose of this file**: this is a pre-digested map of the entire iZACH codebase, meant to be read once by any coding agent (Claude, GPT/Codex, Gemini, DeepSeek, etc.) before doing work here. It exists so the agent does **not** need to re-explore the repo from scratch — file structure, architecture, module responsibilities, integrations, and known quirks are all documented below. Treat this as ground truth for orientation, but verify specifics (line numbers, exact function names) against the actual files before editing, since this snapshot can drift out of date. Last generated: 2026-07-14. Last updated: 2026-07-16 (Forge browser overhaul, phone-pairing security hardening, nickname feature, calendar-driven auto-DND, pattern-to-automation suggestions, screen-aware assistance, email agent, unified notification triage — see §4, §8, §13). This closes the 5-phase "JARVIS-like feature" plan started 2026-07-15.

---

## 1. What iZACH Is

**iZACH** is a large, JARVIS-style always-on personal AI assistant, primarily Python, running on Windows. It has:
- Voice I/O (STT via Google Speech Recognition, TTS via edge-tts neural voices, Hindi/English auto-split)
- A multi-provider LLM brain (Groq, Gemini, Anthropic, OpenRouter — with failover/rotation)
- Persistent memory (MongoDB + ChromaDB RAG + an Obsidian vault used as a long-term "brain")
- WhatsApp automation (send/receive, auto-reply, AI-drafted replies, call handling)
- Spotify control (mood-based playback, OAuth)
- Camera/vision, face auth, voice ID, speaker diarization
- Smart-home integration (Google Nest/SDM, Chromecast, SmartThings)
- Two desktop UIs: legacy Tkinter ("Forge") and modern Electron+React ("Cortex")
- A native Android companion app (22 activities)
- A "second PC" remote-control layer ("Allied Node")
- A Chrome extension for browser automation
- Background/tray mode for low-footprint always-on operation

Everything is orchestrated through a central Flask REST API (`modules/ui_api.py`) and a WebSocket event bus (`modules/ws_bridge.py`, port 5051).

---

## 2. Top-Level Directory Map

```
iZACH/
├── main.py                    — backend brain entry point (voice loop, TTS/STT, start_brain())
├── forge_ui.py                — legacy Tkinter "Forge" desktop UI
├── cortex-ui.html             — static/legacy shell for the Cortex UI
├── launch_izach.py            — master launcher: n8n → backend → MMA agent → WhatsApp bridge → ngrok
├── whatsapp_bridge.js         — Node/Express WhatsApp Web bridge (port 3000)
├── config_loader.py, logging_config.py, tray_monitor.py, dnd_action.pyw
├── requirements.txt, package.json, .env / .env.example
├── Agents/                    — orchestrator + new domain-specific LLM agents
├── modules/                   — ~80 feature modules (the bulk of the app's logic)
├── izach-ui/                  — "Cortex" Electron + React (Vite) desktop UI
│   ├── electron/                (main.cjs, preload.cjs, password-store.cjs, adblock-list.cjs)
│   ├── src/
│   │   ├── components/           (App.jsx, NeuralOrb, ChatPanel, DevicesWidget, SettingsPanel, ...)
│   │   ├── hooks/useIZACH.js      — talks to Flask :5050 + WS :5051
│   │   └── utils/clipboard.js
│   └── public/, dist/
├── izach-android/             — native Android companion app (Kotlin)
│   └── app/src/main/java/com/izach/android/
│       ├── *Activity.kt          (~25 screens, see §9)
│       ├── network/               (IZACHApi.kt, IZACHWebSocket.kt)
│       └── model/, ui/, widget/, tile/
├── izach-flutter/             — secondary/experimental Flutter client
├── izach-godot/                — experimental Godot client
├── node_receiver/              — lightweight Python agent for the SECOND PC ("Allied Node 2")
│   └── receiver.py, node_ui.html, start_izach_node.bat
├── chrome_extension/           — browser extension (background.js, content.js, popup), talks to ws_bridge
├── iZACH-Brain/                — Obsidian vault: iZACH's own long-term memory notes (Memory/, People/, Calls/)
├── skills/                     — markdown "#skill"-triggerable persona definitions (python-dev, sql-expert, hindi-mode, ...)
├── izach_rag_db/               — ChromaDB vector store
├── browser_recordings/         — recorded browser macros as JSON (played back by web_automation.replay_recording)
├── logs/, screenshots/, shared/, voice_profiles/, speaker_profiles/, assets/
├── .wwebjs_auth/, .wwebjs_cache/ — whatsapp-web.js session/auth persistence (used by whatsapp_bridge.js)
├── .githooks/pre-commit         — repo's git hook (set via `git config core.hooksPath .githooks` if not already active)
├── test_*.py                   — pytest suite (agents, calendar, face_auth, phase4/5, web_automation)
└── top-level *.json state files — contacts.json, memory.json, api_keys.json, known_devices.json,
                                     smart_memory.json, calendar_event_map.json, pairing_secret.json,
                                     device_memory.json, wa_processed_msgs.json, api_usage.json, etc.
```

---

## 3. Core Entry Points & Architecture

### `main.py`
The actual running brain process:
- Installs a crash handler first (`modules/crash_handler.py`); sets env vars to dodge known TensorFlow/numba/OpenCV native crashes on Windows (e.g. numba forced single-threaded LLVM to avoid a SIGABRT race with Spotify's SSL calls — this is a documented workaround, don't "clean it up").
- Instantiates `AIProvider` (`modules/ai_handler.py`), `SpotifyController`, pygame mixer for TTS playback.
- `generate_and_play()` / `tts_worker()`: edge-tts neural TTS, Hindi/English auto-splitting, SSML tone injection, live word-by-word caption broadcast over the WS bridge.
- `get_ai_response()`: builds the full LLM prompt — skill-engine detection (`#skill`), personal memory, smart memory, conversation history, active window/location context, language directive — then calls `ai_manager.send_message`.
- `listen()`: Google Speech Recognition STT loop with barge-in interrupt handling, wake-word gating, speaker diarization.
- `start_brain(ui=None)`: giant startup sequence spinning up ~25+ subsystems — `TaskOrchestrator`, `PerformanceGuard`, `TaskScheduler`, `automation_scheduler`, `ContextManager`, `OrchestratorAgent`, `CommandChain`, WhatsApp init, interrupt engine, mic calibration, Mongo brain, response generator, smart alarm, WhatsApp context sync, proactive agent, subconsciousness, Instagram/news engines, pattern learner, curiosity engine, syslog analyzer, window watcher, network monitor, face auth, voice ID, research agent, WA group summarizer, app preloader, clipboard sync, download monitor, speaker diarization, DND/busy mode, synonym learner — then starts `ws_bridge.py` (port 5051) and the voice loop thread.
- A battery/lid monitor auto-switches `api_keys.json["ui"]` to `"background"` mode to save power.

### `Agents/orchestrator.py` — `OrchestratorAgent`
Single fast Groq call (`llama-3.1-8b-instant`, temp 0) that classifies every query into one of 9 domains (whatsapp / spotify / calendar / system / research / memory / vision / file / chat) with a confidence score, routing to specialized handlers before falling into general chat.

### `Agents/system_agent.py` — `SystemAgent`
Fully LLM-driven parser/dispatcher for OS commands (open/kill apps, volume, brightness, theme, timers, screenshot, shutdown/restart with confirm-first safety, WiFi, battery, CPU temp, RAM, firewall, drives, process priority). JSON-intent LLM prompt → dispatch to `modules/system_control.py`.

Other `Agents/*.py` (`calendar_agent`, `file_agent`, `memory_agent`, `research_agent`, `spotify_agent`, `vision_agent`, `whatsapp_agent`) follow the same pattern — domain-specific LLM-intent-parsing handlers. **These are an active migration**: they're incrementally replacing the older giant if/elif block in `modules/command_chain.py` (per that file's own docstring). When touching command routing, check whether logic already exists in an `Agents/` file before adding to `command_chain.py`.

### `modules/command_chain.py` — `CommandChain`
The pre-existing central `.process()` router that all voice/text commands pass through; wires together context engine, scheduler, AI handler, Spotify, orchestrator agent, etc. `_chain_ref` is exposed globally so `ws_bridge.py` can route UI-originated commands into it.

---

## 4. The Two UIs

### Forge (`forge_ui.py`)
Legacy **Tkinter** desktop GUI, custom dark cyberpunk theme (deep blue/cyan). Components: `NeuralCore` (animated canvas orb reacting to speaking state), `ChatPanel`, `StatsPanel`, `CameraPanel`, `SpotifyPanel`, `OCRPanel`, `PrinterPanel`, `BrowserWindow`, `SettingsPage`, composed into `JarvisUI`. `main.py`'s `start_brain(ui=...)` accepts either a `JarvisUI` instance or `ui=None` (headless/Electron mode). Being superseded by Cortex but still present and functional.

- **`BrowserWindow`** (added 2026-07-15, replacing the old embedded `BrowserPage` overlay): a standalone `tk.Toplevel`, multi-tab, embedding Edge WebView2 via `tkwebview2`/`pywebview`. Feature-parity with Cortex's browser: bookmarks (`/api/custom_links`), history (`/browser/history`), find-in-page (custom JS injection, no native WebView2 find API used), zoom (`webview.web.ZoomFactor`), DevTools (`webview.core.OpenDevToolsWindow()`), Send to Phone / Phone Tabs handoff, a tab cap (`MAX_TABS = 6`, guardrail against unbounded RAM growth — see gotcha below). **Shares Cortex's live login sessions**: a monkeypatch on `tkwebview2.tkwebview2.EdgeChrome` (`forge_ui.py`'s `_patch_shared_webview_profile()`) points every WebView2 instance at Cortex's Electron Chromium profile folder (`%APPDATA%\izach-ui\Partitions\izach-browser`). **Shares Cortex's saved-password vault**: `modules/password_vault.py` re-implements Electron `safeStorage`'s Windows scheme in pure Python (DPAPI-unwrapped AES-256-GCM master key read from Electron's `Local State` file) so both UIs read/write the identical `browser_passwords.json`, gated behind the same WebAuthn/Windows Hello enrollment (`browser_webauthn.json`) Cortex uses. See §13 for load-bearing pythonnet/threading constraints before touching this code.

### Cortex (`cortex-ui.html` + `izach-ui/`)
Modern **Electron + React (Vite)** app — "iZACH Neural Interface". Key deps: `framer-motion`, `d3`, `cmdk`, `@react-spring/web`, `lucide-react`.
- `src/components/`: `App.jsx`, `NeuralOrb.jsx`, `ChatPanel.jsx`, `CameraPanel.jsx`, `CommandPalette.jsx`, `DevicesWidget.jsx`, `InputBar.jsx`, `LeftPanel.jsx`, `RightPanel.jsx`, `RelationshipGraph.jsx`, `SettingsPanel.jsx`, `StatusBar.jsx`, `TitleBar.jsx`.
- `hooks/useIZACH.js`: talks to Flask backend at `http://localhost:5050` and WS at port 5051.
- `DevicesWidget.jsx`: renders a `NodeCard` per registered remote PC node (hardcoded entry: `alliednode 2` @ `192.168.0.137`); polls `GET /nodes/vitals` every 12s; posts `POST /nodes/control` for volume/brightness/media/power actions.
- `electron/main.cjs`: manages a `persist:izach-browser` session partition (separate from backend traffic), ad-block webRequest filter (`adblock-list.cjs`), an encrypted local password manager (`password-store.cjs`) gated by WebAuthn/Windows Hello before autofill reveal, browser recording playback (encrypts sensitive typed values), download tracking, permission-management IPC.
- `electron/preload.cjs`: `contextBridge`-exposed APIs — `electronAPI`, `izachPasswords`, `izachWebAuthn`, `izachPermissions`, `izachDownloads`, `izachRecordings`, plus a `webview:new-window` forwarding event.
- Backend surface: **`modules/ui_api.py`** (~5700 lines) — a Flask `Blueprint` (`ui_bp`), CORS-enabled, hundreds of REST endpoints consumed by both Cortex and Android (chat, memory, spotify, calendar, files, screenshots, mic control, `/nodes/*`, DND, busy mode, WhatsApp, etc.).

---

## 5. WhatsApp Integration

- **Bridge**: `whatsapp_bridge.js` — Node/Express (port 3000) wrapping `whatsapp-web.js` (headless Puppeteer WhatsApp Web client). Routes: `POST /send-message`, `POST /send-voice`, `GET /health`, `GET /messages/history`, `GET /messages/chat`, `POST /logout`, `POST /restart`. Notifies the Python backend (`http://127.0.0.1:5050`) on QR code, connect/disconnect, incoming calls, incoming messages.
- **Python side**: `modules/whatsapp_handler.py` runs its own Flask `app` (separate from `ui_api.py`'s blueprint), routes: `/whatsapp/call`, `/health`, `/remote_command`, `/whatsapp/qr`, `/whatsapp/status` (GET/POST), `/whatsapp/message`, `/whatsapp/media`. Handles incoming call/message webhooks, auto-reply during busy/DND mode, media text extraction, contact resolution (`contacts.json`).
- Supporting modules: `modules/whatsapp_context.py` (24h history sync/dedup via `wa_processed_msgs.json`), `modules/wa_draft_engine.py` (AI-drafted reply approval flow, intercepted in `main.py`'s voice loop), `modules/wa_group_summarizer.py`, `modules/whatsapp_sender.py`.
- **Known fix history** (commit `c35bd4c`, "whatsapp bridge re-registering duplicate routes on reconnect"): route handlers used to be defined *inside* `createClient()`. Every reconnect (disconnect event, `/restart`, or the "already running"/session-clear retry path) called `createClient()` again and re-registered every route on the shared `app`, stacking duplicate Express handlers over time. Fixed by moving all routes to module scope (registered once) plus a module-level `activeClient` variable repointed on each reconnect; handlers now read `activeClient` instead of closing over a stale client. Also fixed `SIGINT`/`SIGTERM` destroying a stale client reference post-reconnect, and added a `sendReady`/`_waitUntilSendReady()` gate (~8s wait after `ready`) to work around an upstream whatsapp-web.js "No LID for user" bug.

---

## 6. Spotify Integration (`modules/spotify_controller.py`)

- Uses **Spotipy** (`SpotifyOAuth`) against the real Spotify Web API — OAuth Authorization Code flow, local browser login. Credentials from `.env`: `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI` (default `http://127.0.0.1:8888/callback`). Token cached in `.cache`.
- Scopes: `user-modify-playback-state`, `user-read-playback-state`, `playlist-read-private`, `user-library-read`, `user-read-recently-played`.
- `_MOOD_MAP`: maps mood words ("chill", "study", "workout", "romantic", "sleep", ...) to Spotify search queries.
- Remembers last-used playback device (`device_memory.json`).
- `get_auth_status()` / background `_run_reconnect()` (thread + lock guarded, polled via Settings UI `GET /spotify/auth/status`) so reauth doesn't block a Flask request thread.
- "Build 8.2: Strict Duplicate & Artist Filter" — dedupes generated playlists/queues by track/artist.
- Android has a dedicated `SpotifyRemoteActivity.kt`.

---

## 7. Connected External APIs / Services

From `.env.example`:
- **LLMs**: `GROQ_API_KEY` / `GROQ_VISION_KEY` / `GROQ_WA_KEY`, `GEMINI_KEY_1-3` + `GEMINI_VISION_KEY_1-3` (rotated for rate limits), `OPENROUTER_API_KEY` (fallback), `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`
- **Spotify**: `SPOTIPY_CLIENT_ID/SECRET/REDIRECT_URI`
- **Nutrition/fitness**: `EDAMAM_APP_ID/KEY`
- **Automation**: `N8N_URL` / `N8N_SHARED_TOKEN`
- **Second-agent health check**: `MMA_TOKEN` (separate "MMA" remote agent, port 6060, pinged at startup)
- **Smart home**: `SMARTTHINGS_TOKEN` (Samsung SmartThings); `modules/smart_home_engine.py` also integrates Google SDM API (Nest) and `pychromecast` (Google TV/Chromecast)
- **Owner identity**: `OWNER_NAME`
- **Memory infra**: MongoDB (`modules/mongo_brain.py`), ChromaDB (`modules/rag_memory.py`, stored in `izach_rag_db/`)
- **Push**: Firebase Cloud Messaging (`modules/fcm_push.py`) to Android
- **Tunneling**: ngrok (used by `launch_izach.py`)

---

## 8. Module Inventory (`modules/*.py`, 88 files)

| Module | Purpose |
|---|---|
| `ai_handler.py` | Multi-provider AI client (Groq/Gemini/Anthropic) with failover |
| `alias_engine.py` | User-defined voice command aliases |
| `api_usage_tracker.py` | Tracks API call usage/quotas (`api_usage.json`) |
| `app_installer.py` | Installs/detects applications |
| `app_preloader.py` | Pre-loads frequently used apps in background |
| `audio_init_lock.py` | Shared lock serializing PyAudio/PortAudio init (crash prevention) |
| `audio_streamer.py` | Streams PC audio (used by Android AudioStreamActivity) |
| `automation.py` | App-install detection / window automation helpers |
| `automation_scheduler.py` | APScheduler-based recurring automation/memory jobs |
| `busy_mode.py` | "Busy" status engine (auto-replies, WS/toast alerts) |
| `calendar_agent.py` | Calendar event polling for proactive agent |
| `calendar_dnd.py` | Calendar-driven auto-DND (added 2026-07-16) — periodic poll (not per-event timers) auto-enables DND N minutes before an event starts and disables it at event end, via `dnd_mode.turn_on("calendar")`/`turn_off()`; settings `auto_dnd_before_meetings`/`auto_dnd_lead_minutes` |
| `camera_vision.py` | Multi-provider camera/vision (Groq Vision → Gemini → OpenRouter fallback) |
| `clipboard_sync.py` | Polls Windows clipboard, broadcasts changes over WS |
| `command_chain.py` | Central command router/dispatcher (legacy, being replaced by `Agents/`) |
| `command_logger.py` | Logs commands to CSV/Mongo |
| `context_engine.py` | Window management / app launch positioning |
| `context_manager.py` | Conversation/session context manager |
| `context_memory.py` | Short-term follow-up/conversation memory |
| `crash_handler.py` | Global crash/exception persistence to logs |
| `curiosity_engine.py` | Proactively asks the user questions, captures answers |
| `dnd_mode.py` | Do Not Disturb state manager (suppresses TTS/mic, toast alerts). `turn_on(reason)` accepts `"manual"`, app-detected `"meet"/"zoom"/"teams"` (own `_check_meetings()` polling loop), and now `"calendar"` (driven externally by `calendar_dnd.py`) — see §13 gotcha on why `_check_meetings()`'s auto-off is scoped to `_APP_DETECTED_REASONS` only |
| `document_engine.py` | Document generation/parsing |
| `download_monitor.py` | Watches Downloads folder, broadcasts progress |
| `email_agent.py` | Email agent (added 2026-07-16) — off by default (`email_agent_enabled`). Own Gmail OAuth (`token_gmail.json`, `gmail.readonly` scope, SEPARATE from Calendar's `token.json` so enabling one never forces re-consent on the other — same `credentials.json` Desktop OAuth client works for both, just needs Gmail API enabled on the same Cloud project). Poll loop (90s) classifies new inbox mail: OTP extraction and reply/keyword-watchlist matching are deterministic regex/string match (no LLM, no email content leaves the process) with instant delivery via `speak()`+`fcm_push` for OTPs; shipment emails are keyword-prefiltered then LLM-extracted (Groq 70B, `event_extractor.py`-style JSON prompt) into `tracked_orders.json` (list-of-dicts store, dedup by tracking number). Companion `Agents/email_agent.py` does lightweight regex-based voice routing ("where's my order", "email agent status") — intentionally not a full LLM intent parser given the narrow scope |
| `event_extractor.py` | Extracts calendar events from text |
| `face_auth.py` | Face-recognition auth (subprocess-isolated, dlib) |
| `fcm_push.py` | Firebase Cloud Messaging push to Android |
| `file_manager.py` | File operations (open/move/delete/search) |
| `fitness_engine.py` | Fitness tracking (Edamam nutrition API) |
| `instagram_engine.py` | Instagram automation/engine |
| `intent_router.py` | Older intent routing helper (Spotify/task engine) |
| `interrupt_engine.py` | Barge-in / TTS interrupt handling |
| `location_engine.py` | Location tracking (on-demand via UI toggle) |
| `log_analyzer.py` | Analyzes iZACH's own logs on startup |
| `memory.py` | Long-term personal memory store |
| `mongo_brain.py` | MongoDB-backed persistent memory/profile store |
| `network_monitor.py` | Monitors local network/devices |
| `news_engine.py` | News summarization engine |
| `notification_system.py` | Pushes categorized PC events/notifications to Android/Cortex/Forge. Phase 5 (2026-07-16) — unified triage: `push()` gained an optional `source` field; new `feed()` ranks all history by a deterministic score (category weight + VIP-sender bonus via `dnd_priority_contacts`, no LLM). Before this phase WhatsApp (raw `ws_bridge.broadcast`) and Calendar reminders (voice-only via `speak()`) never touched this module at all — both now also `push()` here, so `/notifications/feed` (new) and the pre-existing `/notifications/history` are the first place all four sources (WhatsApp/Calendar/system/email) are actually unified |
| `obsidian_brain.py` | Writes learned facts/weaknesses into the iZACH-Brain vault |
| `overlay_ui.py` | Themed floating overlay windows for Background Mode |
| `password_vault.py` | Python-side read/write of the shared browser password vault (`browser_passwords.json`) for Forge's `BrowserWindow` — DPAPI+AES-256-GCM, matching Electron `safeStorage` exactly (added 2026-07-15) |
| `pattern_learner.py` | Learns behavioral patterns from usage (time-bucketed recurring commands, `patterns.json`). `offer_next_pattern()`/`confirm_suggestion()`/`reject_suggestion()` already existed (spoken via `proactive_agent._check_pattern_suggestion()`, answered via `command_chain._handle_routine_command`'s "yes automate"/"no skip" voice match) — as of 2026-07-16, `confirm_suggestion()` now creates a real automation via `smart_memory.add_smart_memory("automation", ..., auto_schedule={...})` instead of the old private `routines.json`/`_routine_runner` mechanism, so confirmed patterns show up in the actual Automations UI (Android) and fire via the shared `automation_scheduler`. Old `_save_routine`/`routines.json`/`_routine_runner` kept as a fallback if `smart_memory` integration errors. Gated by new setting `pattern_automation_suggestions_enabled` |
| `pc_context.py` | PC introspection (RAM/CPU/disk/battery/apps) |
| `performance_analyzer.py` | Performance metrics analysis |
| `performance_guard.py` | Monitors system performance, proactive alerts |
| `personality.py` | iZACH's personality prompt, sentiment/tone logic — `PERSONALITY_PROMPT` also mentions the user-set nickname (same `api_keys.json["nickname"]` as `wake_word.py`) if one is set, so iZACH knows to answer to/mention it, not just react to it as a trigger word |
| `print_engine.py` | Printing support |
| `proactive_agent.py` | Initiates proactive suggestions from interaction patterns |
| `rag_memory.py` | ChromaDB-backed RAG memory |
| `realtime_data.py` | Live data (stocks, weather, etc.) |
| `relationship_memory.py` | Tracks relationships/people context |
| `remote_node.py` | Controls the second PC ("AlliedNode 2") — see §10 |
| `research_agent.py` | Web research/search agent |
| `response_generator.py` | Generates fallback/background responses |
| `scheduler.py` | Reminder/task scheduler engine |
| `screen_awareness.py` | Screen-aware assistance (added 2026-07-16) — off by default (`screen_aware_enabled`). Two narrow, deterministic checks, no LLM call (OCR'd text never leaves the process): stack-trace regex match via `pytesseract` OCR of just the active window (win32gui rect crop, not full desktop), and idle-browser-tab timing via `window_watcher`. Per-app exclusion list (`screen_aware_excluded_apps`, default: common password managers) checked before any OCR, plus a fixed non-editable sensitive-title-keyword skip (bank/password/wallet/etc.) so browsers aren't excluded wholesale (would defeat idle-tab detection) |
| `screenshot_engine.py` | Screen capture (pyautogui + PIL) |
| `shell_executor.py` | Safe shell command execution (blocklist for dangerous patterns) |
| `skill_engine.py` | `#skill`-triggered persona/skill system (reads `skills/*.md`) |
| `smart_alarm.py` | Persistent T-30/T-0 alarm scheduler tied to calendar events |
| `smart_home_engine.py` | Nest thermostat (SDM API) + Chromecast/Google TV control |
| `smart_memory.py` | Profile facts + behavioral instruction memory |
| `speaker_diarization.py` | Identifies/filters speakers from mic audio |
| `spotify_controller.py` | Spotify Web API control via Spotipy OAuth — see §6 |
| `state_engine.py` | Global assistant state (persona prefix, etc.) |
| `subconsciousness.py` | Background "subconscious" agent |
| `synonym_learner.py` | Learns command synonyms from success/failure |
| `system_control.py` | Low-level OS control (volume, brightness, WiFi, shutdown, etc.) |
| `system_log_analyzer.py` | Analyzes Windows system logs |
| `task_engine.py` | Task/reminder engine |
| `task_events.py` | Broadcasts task progress events to WS clients |
| `task_manager.py` | Background `TaskOrchestrator`/worker queue |
| `toast_notify.py` | Windows toast notifications (winotify) |
| `tray_icon.py` | Windows system tray icon for Background Mode |
| `ui_api.py` | Massive Flask Blueprint — REST API for Cortex UI + Android |
| `voice_id.py` | Voice enrollment/identification (resemblyzer) |
| `wa_draft_engine.py` | AI-drafted WhatsApp reply + voice approval flow |
| `wa_group_summarizer.py` | Summarizes WhatsApp group chats |
| `wake_word.py` | "Hey iZACH" wake-word state machine — `_NAME_VARIANTS` also gets a user-set nickname (`api_keys.json["nickname"]`, Settings → Nickname in both UIs) merged in at import time, so it works as an additional trigger word everywhere "iZACH" is recognized (mic wake-word gate + `command_chain.py`'s leading-word stripper, which imports `_NAME_VARIANTS` directly) — restart required to pick up a change |
| `web_automation.py` | Browser automation (form-fill, recorded macros) |
| `whatsapp_context.py` | 24h WhatsApp history sync/dedup |
| `whatsapp_handler.py` | WhatsApp Flask webhook server + command handling |
| `whatsapp_sender.py` | Sends WhatsApp messages/voice notes |
| `window_watcher.py` | Tracks active window/app for context |
| `ws_bridge.py` | WebSocket server (port 5051) — broadcasts events to Cortex UI, Chrome extension, Android |

---

## 9. Background Mode

- `api_keys.json["ui"]` supports a `"background"` value. Auto-triggered by `main.py`'s `_start_battery_monitor()` (battery unplugged, if `battery_auto_switch` set) or a WMI lid-close event (`lid_close_trigger` setting).
- `modules/tray_icon.py`: runs in-process when in Background Mode — Windows system-tray icon (pystray + Pillow, chosen for small footprint over Electron), color-coded status dot (DND=orange, busy=yellow, mic-off=red, normal=green), right-click menu (open UI, toggle mic, toggle DND/Busy, quit).
- `modules/overlay_ui.py`: themed floating overlay windows used in Background Mode instead of a full window.
- `node_receiver/receiver.py` (second PC): similarly runs a pystray tray icon (idle/connected/error states) alongside an `http.server` receiver on port 9797 — the always-on background service for Allied Node 2.
- `launch_izach.py` supervises the stack as separate console-windowed processes (not a true Windows Service): n8n → iZACH backend → MMA agent → WhatsApp bridge → ngrok, each health-checked in order.

---

## 10. Second PC / Remote Node ("Allied Node")

Primary/secondary PC pair architecture:
- **Primary PC** runs the full iZACH backend + `modules/remote_node.py`, holding a static `NODES` registry (currently one entry: `"alliednode 2"` → `host: 192.168.0.137, port: 9797, token: "izach-node-2026", mac: <WoWLAN MAC>`).
- **Secondary PC ("Allied Node 2")** runs `node_receiver/receiver.py` — lightweight `http.server` on port 9797, protected by `X-iZACH-Token` header, exposing `/ping`, `/vitals`, `/open_app`, `/open_file`, `/execute`, `/upload`, `/download/<path>`, `/system_control`, `/processes`, `/screenshot`.
- `remote_node.py` primary-side client functions: `ping`, `get_vitals`, `open_app`, `open_file`, `execute` (shell), `send_file`/`fetch_file` (base64 transfer), `system_control` (shutdown/restart/sleep/lock/kill_process), `get_processes`, `take_screenshot`, `upload_bytes`, `wake_on_lan` (magic packet via stored MAC — wakes a fully powered-off second PC).
- Surfaced via:
  - `ui_api.py` REST: `GET /nodes/vitals`, `POST /nodes/control`, `GET /nodes/processes`, `GET /nodes/screenshot`, `POST /nodes/execute`, `POST /nodes/file`, `POST /nodes/wol`.
  - Cortex UI's `DevicesWidget.jsx` (vitals card, volume/brightness sliders, media controls, power buttons).
  - Android's `AlliedNodeActivity.kt` + `IZACHApi.kt` (`api.alliedPower/alliedVolume/alliedBrightness`, confirmation dialogs for lock/sleep/restart/shutdown).
- **This is PC-to-PC control**, distinct from phone-to-PC (handled directly by `IZACHApi.kt`/`IZACHWebSocket.kt` talking to the primary PC's `ui_api.py` + `ws_bridge.py`, authenticated per-install via `pairing_secret.json` obtained via QR scan and signed into every request header).

---

## 11. Android App (`izach-android/`)

Native Kotlin app, `MainActivity.kt` is the hub. Pairs with the PC backend via `IZACHApi.kt` (OkHttp REST, signs every request with the pairing secret) and `IZACHWebSocket.kt` (persistent WS, auto-reconnect, 20s ping interval, callbacks for chat/notifications/screenshots/clipboard/task progress/PC notifications/download events/DND/busy status/reminders/browser handoff).

Key activities (22 total):
- `AudioStreamActivity` — streams live PC mic/system audio to phone
- `ClipboardActivity` — syncs/views PC clipboard history
- `FileTransferActivity` — browse/transfer files phone↔PC
- `ScreenshotViewerActivity` — views remotely captured PC screenshots
- `SpotifyRemoteActivity` — remote-controls PC Spotify playback
- `SystemDashboardActivity` — PC vitals dashboard (CPU/RAM/disk/battery)
- `TerminalActivity` — remote shell/terminal to PC
- `QuickShortcutsActivity` — customizable quick-command shortcuts
- `AlliedNodeActivity` — controls the second PC (§10)
- `BrowserActivity` / `BookmarksActivity` — remote browser control
- `CalendarActivity`
- `WhatsAppActivity` / `WhatsAppThreadActivity` — WhatsApp relay
- `MemoryActivity` — view/manage iZACH's memory
- `NewsActivity`
- `GeofencesActivity` — location-based automation triggers
- `AutomationsActivity`
- `RecordingsActivity` — browser macro recordings
- `SearchActivity`, `SettingsActivity`
- `ShareReceiverActivity` — Android share-sheet target

Background services/widgets: `FloatingMicService` (floating mic overlay), `FcmService` (push), `BootReceiver` (auto-start on boot), `DndActionReceiver`/`DndInlineReplyReceiver` (DND notification actions), quick-settings `BaseTileService`/`BusyTileService`/`DndTileService`/`LockPcTileService`/`MutePcTileService`, home-screen widgets (`DndStatusWidget`, `PCStatusWidget`, `QuickMicWidget`).

---

## 12. Other Clients / Peripheral Pieces

- **`izach-flutter/`** — secondary/experimental Flutter client (status: exploratory, not primary).
- **`izach-godot/`** — experimental Godot-based client (status: exploratory, not primary).
- **`chrome_extension/`** — browser extension (`background.js`, `content.js`, popup) that talks to `ws_bridge.py` for form-fill/browser automation.
- **`iZACH-Brain/`** — Obsidian vault serving as iZACH's own long-term knowledge base (Memory/, People/, Calls/, Learned Facts, System Weaknesses notes), written to by `modules/obsidian_brain.py`.
- **`skills/`** — markdown files defining `#skill`-triggerable personas (e.g. `python-dev`, `sql-expert`, `hindi-mode`), read by `modules/skill_engine.py`.
- **`test_*.py`** at repo root — pytest suite covering agents, calendar, face_auth, and phased feature rollouts (phase4/phase5).

---

## 13. Conventions & Gotchas Worth Knowing

- **Agent migration in progress**: new domain logic belongs in `Agents/*.py` (LLM-intent-parse → dispatch pattern), not appended to the legacy `modules/command_chain.py` if/elif chain. Check both before assuming where a command is handled.
- **Env var workarounds in `main.py`** (numba threading, TF/OpenCV crash avoidance) are intentional fixes for real Windows native-lib crashes — don't remove them without understanding the original crash.
- **WhatsApp bridge routes must be module-scoped**, not defined inside `createClient()` — see §5 fix history. Any future change to `whatsapp_bridge.js` reconnect logic should preserve this pattern.
- **Ports**: Flask/`ui_api.py` on 5050, WS bridge on 5051, WhatsApp bridge on 3000, node_receiver (second PC) on 9797, MMA agent on 6060, Spotify OAuth callback on 8888.
- **State is file-based JSON** at repo root for most settings/toggles (`api_keys.json`, `contacts.json`, `device_memory.json`, `pairing_secret.json`, etc.) — not all state lives in Mongo/ChromaDB.
- **Security-sensitive areas**: `izach-ui/electron/password-store.cjs` (encrypted password manager, WebAuthn-gated), `pairing_secret.json` (phone↔PC auth), `node_receiver` token auth (`X-iZACH-Token`) — treat changes here as high-risk/high-care.
- **`keys and ids`** (repo root, no extension) is a plaintext notes file containing real API keys/IDs. It's correctly excluded via `.gitignore` (`keys and ids*`), alongside `credentials.json`, `fitness_credentials.json`, `smart_home_credentials.json`, and `.env*` (except `.env.example`) — never `cat`/print/commit any of these.
- Two UIs coexist (Forge/Tkinter legacy, Cortex/Electron current) — confirm which one a UI-facing task actually targets before editing, since some features may only exist in one.
- **`forge_ui.py` + `pythonnet`/WebView2 threading (added 2026-07-15)**: `tkwebview2` must stay pinned to `pywebview==4.4.1` in `requirements.txt` — newer pywebview renamed internals (`EdgeChrome.web_view`→`.webview`, changed `evaluate_js`'s signature) and `tkwebview2` crashes on construction against it. WebView2 also needs the COM STA apartment set via pythonnet's own `clr.Thread.CurrentThread.SetApartmentState` (done once at the top of `forge_ui.py`) — **never** use `pythoncom.CoInitialize()` for this, it silently corrupts unrelated background `threading.Thread` workers once combined with pythonnet in the same process. More importantly: **once a `WebView2` control has been constructed anywhere in the process, do not spawn plain `threading.Thread` workers that do network/file I/O** — this reliably segfaults the interpreter (`PyEval_RestoreThread`/GIL corruption, a pythonnet reentrancy bug, not fixable at the application level). `BrowserWindow`'s HTTP/file calls all run synchronously on the Tk main thread specifically because of this — don't "fix" that back to background threads. This is a process-wide risk, not scoped to the browser: any pre-existing background-thread feature (OCR, print, dashboard polling, Spotify controls) could theoretically destabilize too if exercised *after* the browser has been opened once in that process.
- **Phone↔PC pairing is now verified at three layers** (hardened 2026-07-15, after a real bug where the desktop showed "phone connected" and the in-app Android banner showed "ONLINE" while every actual `/command` 401'd as unpaired): (1) HTTP requests are HMAC-signed and checked in `ui_api.py`'s `before_request` hook (pre-existing); (2) the WS hello (`ws_bridge.py`, port 5051 — otherwise unauthenticated) now also requires an HMAC proof over `"ws_hello|<ts>"` using the same pairing secret before setting `_phone_connected=True` or adding the client to `_android_clients`, so an unverified device no longer flips the desktop's indicator or receives phone-targeted broadcasts; (3) Android's `MainActivity` status banner calls `verifyPairing()` (hits the signed `/dnd/vip`, not the HMAC-exempt `/status`) instead of trusting reachability alone, and `sendCommand()` throws a distinct `PairingRejectedException` on HTTP 401 so the offline-command queue stops silently retrying a rejected secret forever. `_get_or_create_pairing_secret()` (`ui_api.py`) is also now cached in-process and only ever auto-generates a new secret when `pairing_secret.json` is genuinely missing — any other read error fails closed instead of silently minting a fresh secret and invalidating every paired device.
- **RAG memory (`modules/rag_memory.py`) skips retrieval for bare greetings** (`_is_trivial_greeting()`) — a fix for the LLM occasionally parroting back an unrelated stored reply verbatim when the query ("hi") carried too little semantic signal for the 0.8 cosine-distance threshold to filter out noise. Don't remove this without re-checking that failure mode.
- **User-set nickname** (`api_keys.json["nickname"]`, configurable in both UIs' Settings) feeds two places at process-start: `modules/wake_word.py` (`_NAME_VARIANTS`, additional trigger word) and `modules/personality.py` (`PERSONALITY_PROMPT`, so iZACH knows to answer to it). Both load once at import time — changing the nickname needs a backend restart, same convention as `wake_word_enabled`.
- **`dnd_mode.py`'s auto-off must stay reason-scoped** (added 2026-07-16): `_check_meetings()` (its own 15s-interval Zoom/Teams/Meet process-detector loop) used to auto-disable DND whenever `_auto_triggered` was true, i.e. for *any* non-manual reason. Adding `calendar_dnd.py`'s "calendar" reason exposed a real bug this would've caused: a calendar-driven DND session (e.g. an in-person meeting with no video-call app running) would get killed within one 15s poll, since `_check_meetings()` would see "no meeting app process" and auto-off it immediately. Fixed by scoping `_check_meetings()`'s auto-off to `_APP_DETECTED_REASONS = {"meet","zoom","teams",...}` only — a session with `reason="calendar"` can now only be ended by `calendar_dnd.py`'s own poll (which tracks the actual event end time). Any *new* auto-DND trigger source added later must follow this same pattern: give it its own reason string and make sure `_check_meetings()`'s auto-off condition doesn't also try to manage it.
- **`proactive_enabled` was a silent no-op setting until 2026-07-16**: Android's Settings screen has always written it and `proactive_agent.py` has always read it, but it was missing from `ui_api.py`'s `/settings` POST `allowed` whitelist, so every write was silently dropped — toggling "Proactive Agent" off in the app did nothing server-side. Fixed alongside adding `pattern_automation_suggestions_enabled`. If a setting appears to have no effect, check this whitelist first — it's a recurring class of bug in this codebase.
- **`apscheduler` was missing from `requirements.txt`** despite `modules/automation_scheduler.py` depending on it entirely (added 2026-07-16, pinned to `3.11.3`) — a fresh `pip install -r requirements.txt` would leave the whole Automations feature (Android's Automations screen, `smart_memory.py`'s automation category) silently failing to actually schedule anything.
- **Two separate Google OAuth tokens by design**: `token.json` (Calendar, `calendar_agent.py`) and `token_gmail.json` (Email agent, `email_agent.py`) both use the same `credentials.json` Desktop OAuth client (just needs each API enabled on the same Cloud project) but are kept as separate token files intentionally — widening one shared `SCOPES` list would force every Calendar user to re-consent to Gmail access (and vice versa) the next time either token refreshes. Don't merge them.
- **`google-auth-oauthlib` was missing from `requirements.txt`** despite `calendar_agent.py` depending on it since before this session (added 2026-07-16, pinned `1.4.0`) — same class of gap as `apscheduler` (Phase 2). If a Google-OAuth-using feature works locally but fails in a fresh env, check this file first.
- **Browser tabs are capped at 6 in both UIs** (`BROWSER_MAX_TABS`/`BrowserWindow.MAX_TABS`, added 2026-07-15) as a RAM guardrail: each tab (Electron `<webview>` in Cortex, WebView2 control in Forge) is a full separate Chromium renderer process that **switching tabs never destroys** — only closing a tab's ✕ frees it. This was the single biggest RAM driver found in a perf audit; the cap stops unbounded pile-up but doesn't free tabs already open. A fuller fix (auto-suspend/reload inactive tabs) was scoped but deliberately not built — see if revisiting RAM usage again.

---

## 14. Full Repository Folder Structure

Generated directly from the filesystem (2026-07-14). Build/dependency/IDE-cache directories are collapsed to a single annotated line since their internals are generated and never hand-edited; personal Obsidian note filenames under `iZACH-Brain/` are similarly collapsed to counts rather than listed (they encode real personal facts — name, DOB, relationships — and aren't relevant to code orientation). Root-level generated JSON state files and stray personal documents are grouped in prose under the tree rather than listed one-by-one.

```
iZACH/
├── .githooks/
│   └── pre-commit
├── Agents/
│   ├── __init__.py
│   ├── calendar_agent.py
│   ├── file_agent.py
│   ├── memory_agent.py
│   ├── orchestrator.py
│   ├── research_agent.py
│   ├── spotify_agent.py
│   ├── system_agent.py
│   ├── vision_agent.py
│   └── whatsapp_agent.py
├── assets/
│   └── icons/
├── browser_recordings/            — recorded browser macros (JSON), e.g. IPU_Admission.json
├── chrome_extension/
│   ├── background.js
│   ├── content.js
│   ├── manifest.json
│   ├── popup.html
│   └── popup.js
├── izach-android/                 — native Kotlin app (Gradle project)
│   ├── .gradle/, .idea/           — generated Gradle/Android Studio metadata (not source)
│   ├── app/
│   │   ├── build/                  — compiled output (iZACH.apk lands here)
│   │   ├── src/main/
│   │   │   ├── java/com/izach/android/
│   │   │   │   ├── *Activity.kt      — 22 screens, see §11
│   │   │   │   ├── *Receiver.kt, *Service.kt  — BootReceiver, FcmService, FloatingMicService,
│   │   │   │   │                                 DndActionReceiver, DndInlineReplyReceiver,
│   │   │   │   │                                 GeofenceBroadcastReceiver, GeofenceManager
│   │   │   │   ├── model/            — Automation, Bookmark, BrowserHistoryEntry, BusyStatus,
│   │   │   │   │                        CalendarEvent, CommandResponse, DndAlert, DndStatus,
│   │   │   │   │                        FileEntry, FileInfo, GeofenceLocation, MemoryEntry,
│   │   │   │   │                        Message, NewsHeadline, OpenTabEntry, ProcessInfo,
│   │   │   │   │                        Recording, Shortcut, SpotifyStatus, SystemStatus, WaChat
│   │   │   │   ├── network/          — IZACHApi.kt (OkHttp REST), IZACHWebSocket.kt
│   │   │   │   ├── tile/             — BaseTileService, BusyTileService, DndTileService,
│   │   │   │   │                        LockPcTileService, MutePcTileService (Quick Settings)
│   │   │   │   ├── ui/               — bottom sheets/adapters (ChatAdapter, DndQueueBottomSheet,
│   │   │   │   │                        DownloadMonitorBottomSheet, FilePickerAdapter/BottomSheet,
│   │   │   │   │                        FilesAdapter, NotificationHistoryBottomSheet,
│   │   │   │   │                        ProcessListBottomSheet, QuickCommandBar,
│   │   │   │   │                        TaskStreamBottomSheet, WaQuickReplyBottomSheet)
│   │   │   │   └── widget/           — DndStatusWidget, PCStatusWidget, QuickMicWidget,
│   │   │   │                            WidgetToggleReceiver (home-screen widgets)
│   │   │   ├── res/                  — layouts, drawables, values (themes.xml, strings.xml, etc.)
│   │   │   └── AndroidManifest.xml
│   │   ├── build.gradle.kts
│   │   └── google-services.json      — Firebase config (placeholder until real project wired up)
│   ├── gradle/wrapper/, gradlew.bat, build.gradle.kts, settings.gradle.kts, gradle.properties
├── iZACH-Brain/                    — Obsidian vault (iZACH's own long-term memory)
│   ├── .obsidian/                   — Obsidian app config (not content)
│   ├── Calls/                       — per-call transcripts/summaries (5 notes)
│   ├── Memory/
│   │   ├── Automations/               — saved automation definitions (3 notes)
│   │   ├── Call-Messages-Logs/
│   │   ├── Identity/                  — personal facts about the owner (21 notes)
│   │   ├── Instructions/              — standing behavioral instructions (10 notes)
│   │   ├── Projects/
│   │   ├── User/                      — mirror of Identity (17 notes)
│   │   └── iZACH Brain.md
│   ├── People/                      — per-contact relationship notes (14 notes)
│   └── *.md, *.base, *.canvas        — Learned Facts.md, System Weaknesses.md, Usage Insights.md,
│                                        Frequent Commands.md, Welcome.md, iZACH Brain.md, etc.
├── izach-flutter/                  — experimental Flutter client (status: exploratory)
│   ├── .dart_tool/, build/, windows/flutter/ephemeral/  — generated, not source
│   ├── lib/                          — home_screen.dart, main.dart, orb_painter.dart
│   ├── windows/runner/                — native Windows embedder (CMake + C++)
│   └── test/widget_test.dart
├── izach-godot/                    — experimental Godot client (status: exploratory)
│   ├── environments/world.tres
│   ├── scenes/Main.tscn
│   ├── scripts/                      — IZACHBridge.gd, Main.gd, NeuralOrb.gd
│   ├── shaders/                      — orb.gdshader, panel_glass.gdshader, scanline.gdshader
│   └── project.godot
├── izach-ui/                       — "Cortex" Electron + React desktop UI
│   ├── node_modules/, dist/          — generated, not source
│   ├── electron/                     — main.cjs, preload.cjs, password-store.cjs, adblock-list.cjs,
│   │                                    browser-recorder-preload.cjs, webauthn-gate-preload.cjs,
│   │                                    browser-window.html
│   ├── public/icon.png
│   ├── src/
│   │   ├── components/                — App.jsx, CameraPanel, ChatPanel, CommandPalette,
│   │   │                                  DevicesWidget, InputBar, LeftPanel, NeuralOrb,
│   │   │                                  RelationshipGraph, RightPanel, SettingsPanel,
│   │   │                                  StatusBar, TitleBar
│   │   ├── hooks/useIZACH.js
│   │   └── utils/clipboard.js
│   └── package.json, vite.config.js, tailwind.config.js, postcss.config.js
├── izach_rag_db/                   — ChromaDB vector store (binary index files)
├── logs/                           — runtime log files (console.log, crash.log, electron_*.log, ...)
├── modules/                        — 88 feature modules, see §8 for the full table
├── node_modules/                   — root npm deps (for whatsapp_bridge.js)
├── node_receiver/                  — "Allied Node 2" lightweight receiver, see §10
│   ├── generate_icon.py
│   ├── node_ui.html
│   ├── receiver.py
│   └── start_izach_node.bat
├── screenshots/                    — captured PC screenshots
├── shared/                         — phone↔PC file-transfer drop folder (user files)
├── skills/                         — `#skill`-triggerable persona markdown files (13 + .stats.json):
│                                      api-builder, bash-scripter, c-programming, code-reviewer,
│                                      data-science, hindi-mode, html-builder, java-dev, math-solver,
│                                      python-dev, react-builder, sql-expert, study-mode
├── speaker_profiles/manifest.json
├── temp/                           — scratch/staging files
├── tools/godot/                    — bundled Godot editor binaries (for izach-godot/)
└── voice_profiles/profiles.json
```

**Root-level loose files** (not shown individually above):
- **Entry points/scripts**: `main.py`, `forge_ui.py`, `cortex-ui.html`, `launch_izach.py`, `whatsapp_bridge.js`, `config_loader.py`, `logging_config.py`, `tray_monitor.py`, `dnd_action.pyw`, `debug_e6.py`, `debug_phase5.py`
- **Tests**: `test_agents.py`, `test_calendar.py`, `test_event_extractor.py`, `test_face_auth.py`, `test_phase4.py`, `test_phase4_events.py`, `test_phase5.py`, `test_phase5_deep.py`, `test_web_automation.py`
- **Config/manifests**: `requirements.txt`, `package.json`/`package-lock.json`, `.env`/`.env.example`, `.gitignore`
- **JSON state files** (file-based persistence, not in Mongo/ChromaDB): `api_keys.json`, `api_usage.json`, `browser_history.json`, `browser_passwords.json`, `browser_permissions.json`, `browser_tabs.json`, `calendar_alarm_jobs.json`, `calendar_event_map.json`, `config.json`, `contacts.json`, `curiosity_state.json`, `custom_links.json`, `custom_websites.json`, `device_alias.json`, `dnd_queue.json`, `file_manager_config.json`, `instagram_settings.json`, `known_devices.json`, `memory.json`, `news_settings.json`, `pairing_secret.json`, `pattern_last_run.json`, `patterns.json`, `print_settings.json`, `smart_home_settings.json`, `smart_memory.json`, `users.json`, `wa_processed_msgs.json`, plus `busy_session.jsonl`, `command_log.csv`, `performance_report*.csv`
- **Credentials — gitignored, never read/print**: `credentials.json`, `fitness_credentials.json`, `smart_home_credentials.json`, `fitness_token.json`, `keys and ids`
- **Voice/audio cache**: `owner_voice.json`, `owner_voice.npy`, plus ad hoc `speech_*.mp3` TTS cache files (regenerated at runtime, safe to delete)
- **Personal documents/media/branding** (not code, safe to ignore for orientation purposes): various `iZACH *.png/.ico/.jpg`, `iZACH * Report.docx/.pdf`, `iZACH Sample Website.zip`, `iZACH MMA2*.json`, `iZACH DND Auto-Reply.json`, `!!tP9no_qhlogs.txt`, `!qhlogs.doc`, stray Word lock file (`~$ACH Project Report.docx`), `desktop.ini`
- One stray oddly-named file at root, `CProjectsiZACHsetup` (no extension) — looks like an accidental artifact from a mangled path; verify before relying on it for anything

---

*This file is a snapshot, not a live index. If it conflicts with what you observe in the code, trust the code and consider updating this file.*
