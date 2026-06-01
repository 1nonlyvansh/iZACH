<div align="center">

```
██╗███████╗ █████╗  ██████╗██╗  ██╗
██║╚══███╔╝██╔══██╗██╔════╝██║  ██║
██║  ███╔╝ ███████║██║     ███████║
██║ ███╔╝  ██╔══██║██║     ██╔══██║
██║███████╗██║  ██║╚██████╗██║  ██║
╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝
```

**Intent Zenith Adaptive Cognitive Handler**

*A voice-driven AI assistant for Windows — context-aware, system-deep, always on.*

---

[![Version](https://img.shields.io/badge/Version-v2.1.0-00e5ff?style=flat-square&labelColor=050d1a)](.)
[![Python](https://img.shields.io/badge/Python-3.10%2B-00e5ff?style=flat-square&logo=python&logoColor=00e5ff&labelColor=050d1a)](https://python.org)
[![React](https://img.shields.io/badge/React-18-00e5ff?style=flat-square&logo=react&logoColor=00e5ff&labelColor=050d1a)](https://react.dev)
[![Electron](https://img.shields.io/badge/Electron-Desktop-00e5ff?style=flat-square&logo=electron&logoColor=00e5ff&labelColor=050d1a)](https://electronjs.org)
[![Flask](https://img.shields.io/badge/Flask-Backend-00e5ff?style=flat-square&logo=flask&logoColor=00e5ff&labelColor=050d1a)](https://flask.palletsprojects.com)
[![Groq](https://img.shields.io/badge/Groq-LLM-00e5ff?style=flat-square&logoColor=00e5ff&labelColor=050d1a)](https://groq.com)
[![Android](https://img.shields.io/badge/Android-Companion%20App-00e5ff?style=flat-square&logo=android&logoColor=00e5ff&labelColor=050d1a)](https://github.com/1nonlyvansh/iZACH/releases/latest)
[![Platform](https://img.shields.io/badge/Platform-Windows%20Only-0d2a3a?style=flat-square&logo=windows&logoColor=c8e8f0&labelColor=050d1a)](.)
[![Status](https://img.shields.io/badge/Status-Active%20Dev-1db954?style=flat-square&labelColor=050d1a)](.)

</div>

---

## What is iZACH?

iZACH is a local-first, voice-controlled AI assistant that runs natively on Windows. It doesn't just answer questions — it **acts**. Control Spotify, automate WhatsApp, execute PowerShell, manage files, browse the web, read your calendar, watch your camera, and learn your behavioral patterns — all through natural speech or a neural-themed desktop UI.

**v2.1.0** ships a full Skills system (on-demand AI agents with `#id` activation), a modular widget UI with an API usage monitor, 5 critical backend crash fixes, and a heavily upgraded Android app with PC audio streaming, DND inline reply, Quick Tiles, and App Shortcuts.

---

## What's New in v2.1.0

### Skills System

| Feature | Detail |
|---|---|
| **`#skill-id` activation** | Type `#html-builder build me a portfolio site` — routes to specialised AI agent with a domain-tuned prompt |
| **DeepSeek routing** | Code skills (`python-dev`, `react-builder`, `api-builder`, `bash-scripter`) route to DeepSeek for better code output |
| **Project file saving** | Skill output saved as a file in a dated project folder automatically |
| **Multi-skill `&` operator** | Chain skills: `#python-dev & #bash-scripter` — runs both in sequence |
| **NEVER ASK mandate** | Skills never ask clarifying questions — always produce full output on first message |
| **10 built-in skills** | html-builder v2.1, python-dev, react-builder, data-science, api-builder, bash-scripter, hindi-mode, math-solver, and more |
| **Skills widget** | RightPanel widget shows all skills with activation instructions and recent projects |

### UI Upgrades

| Feature | Detail |
|---|---|
| **Modular widget system** | RightPanel widgets are independently collapsible, reorderable by drag, with per-widget settings |
| **API Key Usage Monitor** | Live widget showing token consumption, cost estimate, and key rotation status across Gemini/Groq/OpenRouter |
| **Widget picker z-fix** | Widget picker now renders above taskbar (z-index 9001) |
| **Device bar alignment** | Phone/device status bar pixel-aligned to taskbar centre via `getBoundingClientRect` |
| **DND/busy bar layout** | DND and busy mode banners moved into flex flow — no longer overlap TitleBar navigation |

### Backend Fixes & Stability

| Fix | Detail |
|---|---|
| **`web_automation` NameError** | `web_automation` + `_bg` referenced outside their defining scope in `command_chain.py` → NameError on any "open in browser" branch |
| **DND `_queue` UnboundLocalError** | `_queue = _queue[-cap:]` made queue local → `UnboundLocalError` when queue hit cap. Added `global _queue` |
| **`_ai_handle_reply` NameError** | `number` undefined in DND AI reply handler — should be `sender` parameter |
| **`forge_ui` lambda NameError** | `except Exception as e` captured in deferred `lambda` — `e` cleared by Python after except block exits → NameError on any print error |
| **Duplicate `execute_voice_command`** | `smart_home_engine.py` had two definitions — old Nest-only one silently shadowed the full SmartThings+TV+Cast version. Renamed dead copy. |
| **PyAudio crash fix** | `PYAUDIO_INIT_LOCK` held across `Pa_Initialize` in both `listen()` and `interrupt_engine` — prevents access violation on concurrent mic init |
| **Camera enumeration crash** | Serialised camera enumeration — prevents `VideoCapture` crash when multiple threads enumerate simultaneously |
| **Printer false-positive camera** | Printer/scanner devices now skipped in camera enumeration |
| **Gemini key rotation** | Improved round-robin key rotation + OpenRouter as final fallback when all Gemini keys exhaust |
| **Werkzeug poll flood** | Suppressed repetitive werkzeug dev server polling logs from terminal output |
| **DND queue cap** | Queue capped at configurable max — prevents unbounded memory growth during long DND sessions |
| **RAG memory pruning** | Stale RAG entries pruned on load — reduces context injection overhead |
| **Double logging removed** | Removed duplicate log handler registration that doubled every log line |
| **41 unused imports removed** | Cleaned across 35 files — `os`, `re`, `time`, `json`, `threading`, `timezone`, `Path`, `rapidfuzz`, etc. |

### Android App v2.1.0

| Feature | Detail |
|---|---|
| **PC Audio Stream** | New `AudioStreamActivity` — streams raw PCM audio from PC to phone over local Wi-Fi. Backend: `GET /audio/stream` (s16le 22050Hz mono). Low-latency via `AudioTrack` in STREAM mode |
| **DND Inline Reply** | `DndInlineReplyReceiver` — reply to DND WhatsApp alerts directly from Android notification tray without opening the app |
| **Quick Tiles (5 new)** | Pull-down Quick Settings tiles: **DND Mode**, **Busy Mode**, **Lock PC**, **Mute PC** — toggle directly from Android notification shade |
| **App Shortcuts** | Long-press iZACH app icon: **Lock PC**, **Take Screenshot**, **Voice Command** (launches mic instantly) |
| **DndStatusWidget improvements** | Home screen widget updated — shows DND queue count + last sender; toggle receiver wired up |

---

## What's New in v2.0.0

| Area | Change |
|---|---|
| **Smart Memory** | Full persistent memory — Profile, Instruction, Automation types; conflict resolution; Obsidian sync |
| **Cortex UI** | Redesigned single-file Electron frontend with drag orb, cmd history, typewriter effect, real mic waveform, Ctrl+K palette, suggestion chips |
| **Android App** | Live WebSocket connection, phone command mirroring in PC chatbox, phone status widget, process list, file transfer |
| **Memory UI** | Category tabs, search, toggle/edit/delete cards, import from ChatGPT/Claude export, export, Obsidian sync button |
| **Automation Scheduler** | APScheduler cron jobs created automatically from natural language Automation memories |
| **Security** | All tokens moved to `.env`; comprehensive `.gitignore` covering MAC addresses, command logs, Obsidian vault, WhatsApp cache |

---

## Feature Matrix

<table>
<tr>
<td width="50%" valign="top">

**🎤 Voice & Language**
- Continuous wake-word detection
- Natural language command parsing
- Groq LLM (`llama-3.3-70b`) for intent resolution
- Gemini fallback (3 rotated keys) + OpenRouter final fallback
- Context memory across sessions
- Disambiguation for ambiguous commands
- Hinglish language matching
- Mic muted during TTS playback (0.6s cooldown)

**🖥️ System Control**
- Volume, brightness, Wi-Fi, dark/light mode
- Battery health, CPU temp, RAM usage
- Timer, alarm, reminder engine
- Drive management + eject by name
- Firewall & Windows Update status
- Network device discovery

**🤖 Automation**
- Web automation via Playwright (14 functions)
- Playwright browser auto-closes after 10 min idle
- PowerShell executor with safety block list
- File manager: open, find, rename, move, copy, delete, sort, organize
- Screenshot capture → phone transfer
- Screen reader (Tesseract OCR)
- **Automation memories** — say "play lofi at 4 PM daily" → stored + cron job auto-created

**🧠 Smart Memory (v2.0.0)**
- **Profile memories** — "My favorite singer is Kanye West" → stored as contextual fact, injected into every AI prompt
- **Instruction memories** — "Always reply briefly" → modifies AI behavior globally; new conflicting instruction auto-supersedes old
- **Automation memories** — natural language → APScheduler cron job
- Import from ChatGPT/Claude export paste
- Export all memories as text
- Obsidian vault sync (Identity/ · Instructions/ · Automations/)
- Enable/disable individual memories

**⚡ Skills System (v2.1.0)**
- `#html-builder` — full multi-page websites, no placeholder hrefs
- `#python-dev` — complete Python scripts, DeepSeek-routed
- `#react-builder` — full React apps with hooks/state
- `#api-builder` — REST API scaffolding (FastAPI/Express)
- `#bash-scripter` — complete shell scripts
- `#data-science` — pandas/numpy/matplotlib pipelines
- `#math-solver` — step-by-step solutions
- `#hindi-mode` — full Hindi responses
- Multi-skill: `#skill-a & #skill-b` chains two agents
- All projects auto-saved to dated folders

</td>
<td width="50%" valign="top">

**🧠 Intelligence**
- Behavioral pattern learner (Phase 5)
- Routine suggestions from usage history
- Short + long-term context memory
- MongoDB brain (falls back to local JSON)
- Proactive task suggestions
- Calendar event extraction from speech
- Curiosity engine — builds personal profile during idle moments
- System log analyzer — Gemini analysis of 10-day Windows event logs
- Obsidian brain graph — `[[wikilinks]]` between all memory nodes
- Relationship memory — people profiles linked to WhatsApp contacts

**📱 Connectivity**
- WhatsApp bridge — lazy-started on first WA command
- Spotify — play, pause, skip, playlists, device switch
- Google Calendar sync
- Android companion app (Wi-Fi + WebSocket)
- Ngrok tunnel for remote access
- Auto-draft WhatsApp reply with voice approval flow
- Samsung SmartThings smart home control

**🔐 Security**
- Face authentication — lazy-loaded on first face command
- Face-gated file deletion
- Pre-commit hook blocks secrets & large files
- PowerShell command safety block list
- OAuth tokens never committed

**📷 Vision**
- Camera object identification (Gemini Vision)
- Calorie estimation from food photos
- Brand/item recognition
- Screen element detection
- MJPEG live stream (`GET /vision/stream` at ~15 fps)

**🎵 PC Audio Stream (v2.1.0)**
- Stream PC system audio to Android phone over Wi-Fi
- Raw PCM s16le 22050Hz mono → `AudioTrack` stream mode
- Low-latency playback, stop/start controls in app

**⚡ Performance**
- WhatsApp bridge lazy-starts — Puppeteer not loaded until first WA command
- Face auth lazy-loads — dlib/cv2 not imported until first face command
- `api_keys.json` + `memory.json` reads cached (30s TTL / dirty-flag)
- Playwright browser freed after idle — no persistent Chromium in background
- RAG memory pruned on load — stale entries removed automatically

</td>
</tr>
</table>

---

## Cortex UI

The **Cortex UI** (`cortex-ui.html`) is iZACH's primary desktop interface — a single-file Electron app with zero build steps.

**Features:**

| Feature | Description |
|---|---|
| **Neural Orb** | Drag anywhere on screen; pulses during speech; animated on processing |
| **Command History** | ↑/↓ arrow keys cycle through previous commands |
| **Typewriter Effect** | AI responses type out character-by-character |
| **Slide-in Panels** | Settings, Memory, and Processes panels animate in from right |
| **Collapsible Panels** | Each settings section independently collapsible |
| **Ctrl+K Palette** | Quick-launch command palette for keyboard-first workflows |
| **Real Mic Waveform** | Live audio level visualizer on voice input |
| **Suggestion Chips** | Context-aware command suggestions shown after each response |
| **Phone Status Widget** | Shows Android companion connection state in real time |
| **Memory Tab** | Full memory management UI — categories, search, cards, import/export |
| **IDLE Screen** | Animated ambient screen when idle; shows clock, phone status, quick stats |
| **Modular Widget System** | RightPanel widgets drag-reorderable, independently collapsible, per-widget settings *(v2.1.0)* |
| **API Usage Monitor** | Live token consumption, cost estimate, key rotation status *(v2.1.0)* |
| **Skills Widget** | Lists all skills with `#id` activation hints and recent project history *(v2.1.0)* |

---

## Android Companion App

<table>
<tr>
<td width="50%" valign="top">

**Features**
- Chat interface — send voice or text commands
- Real-time WebSocket connection (live status in Cortex UI)
- Commands sent from phone appear in PC chatbox instantly
- Floating mic overlay — trigger iZACH from any app
- File transfer — send files from phone → PC
- **PC Audio Stream** — hear PC audio through phone speaker *(v2.1.0)*
- Spotify remote control
- System dashboard (CPU, RAM, battery, processes)
- Screenshot viewer
- Quick command shortcuts
- Download monitor
- Clipboard sync
- Notification history
- **DND Inline Reply** — reply to WhatsApp DND alerts from notification tray *(v2.1.0)*
- **5 Quick Settings Tiles** — DND, Busy, Lock PC, Mute PC toggles in notification shade *(v2.1.0)*
- **App Shortcuts** — long-press icon for Lock PC / Screenshot / Voice Command *(v2.1.0)*

</td>
<td width="50%" valign="top">

**Requirements**
- Android 7.0+
- Same Wi-Fi network as PC
- iZACH backend running on PC (port 5050)

**Download**

[![Download APK](https://img.shields.io/badge/Download-iZACH.apk-00e5ff?style=for-the-badge&logo=android&logoColor=00e5ff&labelColor=050d1a)](https://github.com/1nonlyvansh/iZACH/releases/latest)

> Enable *Install from unknown sources* in Android Settings → Security before installing.

**Quick Tiles Setup**

1. Pull down notification shade → tap pencil (edit tiles)
2. Find **iZACH DND**, **iZACH Busy**, **iZACH Lock PC**, **iZACH Mute PC**
3. Drag into active tiles row

</td>
</tr>
</table>

### Connecting the App

**Both devices must be on the same Wi-Fi network.**

1. Find your PC's local IP:
   ```
   ipconfig
   ```
   Look for `IPv4 Address` under your Wi-Fi adapter — e.g. `192.168.1.105`

2. Start iZACH: `python launch_izach.py`

3. Open iZACH app → **Settings** (gear icon)

4. Enter backend URL:
   ```
   http://192.168.1.105:5050
   ```
   Or tap the **QR** button — Cortex UI can display a QR code.

5. Tap **Save** — app tests connection and shows status.

> If it fails: check Windows Firewall allows port 5050, and both devices are on the same subnet.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INPUT                              │
│    Voice Mic  ──  Cortex UI  ──  PS> Terminal  ──  Android App  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│             CORTEX UI  (cortex-ui.html · Electron)              │
│   Neural Orb  •  Chat  •  Skills  •  Widgets  •  Memory         │
└──────────────────────────┬──────────────────────────────────────┘
                           │  HTTP :5050  /  WS :5051
┌──────────────────────────▼──────────────────────────────────────┐
│                    FLASK BACKEND  :5050                         │
│                                                                 │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────────┐  │
│  │ CommandChain │  │ IntentRouter  │  │   AutoScheduler      │  │
│  └──────┬───────┘  └──────┬────────┘  └─────────┬────────────┘  │
│         │                 │                     │               │
│  ┌──────▼─────────────────┘                     │               │
│  │      Skill Engine  (#id · DeepSeek route)    │               │
│  └───────────────────────────────────────────────               │
│                                                                 │
│  ┌──────────┬────────────┬─────────────┬──────────────────────┐  │
│  │ AI Layer │  System    │   Vision    │  Smart Memory        │  │
│  │Groq/Gem/ │  Control   │   Camera   │  Profile/Instr/Auto  │  │
│  │OpenRouter│            │  /audio    │  APScheduler crons   │  │
│  └──────────┴────────────┴─────────────┴──────────────────────┘  │
└────────┬───────────────────────┬────────────────────────────────┘
         │                       │
┌────────▼──────┐      ┌─────────▼────────┐      ┌──────────────┐
│  WhatsApp     │      │   WS Bridge      │      │  Android App │
│  Bridge :3000 │      │   :5051          │      │  (Wi-Fi)     │
└───────────────┘      └──────────────────┘      └──────────────┘
         │
┌────────▼──────────────────────────────────────────────────────┐
│  Obsidian Vault  (iZACH-Brain/)                               │
│  Identity/  ·  Instructions/  ·  Automations/  ·  People/     │
└───────────────────────────────────────────────────────────────┘
```

---

## Smart Memory System

iZACH v2.0.0+ ships a full persistent memory system modeled after ChatGPT and Claude memory.

### Memory Types

**Profile** — user facts, injected into every AI system prompt:
```
"My favorite singer is Kanye West"
→ stored: "Vansh's favorite singer is Kanye West"
```

**Instruction** — behavioral rules that modify AI globally:
```
"Always reply briefly"
→ stored, applied to every response
→ if new instruction conflicts with old, old is auto-superseded
```

**Automation** — scheduled recurring tasks:
```
"Play lofi songs on Spotify at 4 PM daily"
→ stored as memory
→ APScheduler cron job created automatically
→ appears in Memory UI with enable/disable toggle
```

### Memory UI

Access via **Settings → Memory** tab in Cortex UI:
- Category tabs: All · Profile · Instructions · Automations
- Search across all memories
- Cards with timestamps, enable/disable toggle, edit, delete
- Import button: paste ChatGPT/Claude memory export → auto-classified
- Export button: copy all memories as text
- Obsidian Sync button: push all memories to vault

---

## Skills System

Activate any skill by prefixing your message with `#skill-id`:

```
#html-builder   build me a portfolio website for a photographer
#python-dev     write a web scraper for Amazon product prices
#react-builder  create a dashboard with charts and dark mode
#api-builder    scaffold a REST API for a todo app with auth
#bash-scripter  script to backup /home and upload to S3
#data-science   analyse this CSV: sales.csv
#math-solver    solve ∫(x² + 3x) dx with full working
#hindi-mode     apna din kaisa raha?
```

Chain multiple skills with `&`:
```
#python-dev & #bash-scripter  write a Python ETL script and a cron job to run it nightly
```

All skill output is saved automatically to:
```
projects/
└── YYYY-MM-DD_skill-name_[title]/
    └── output file
```

---

## Voice Command Examples

```
// Memory
"Remember that my favorite singer is Kanye West"
"Always reply briefly"
"Play lofi songs on Spotify at 4 PM daily"
"What do you remember about me?"
"Forget that"

// System
"Set volume to 60"
"Dim the screen"
"Toggle dark mode"
"What's my battery health?"
"Who's on my network?"

// Automation
"Open Chrome and go to GitHub"
"Search for Python tutorials"
"Run PowerShell get top 10 processes by CPU"
"Scroll down"
"Summarize this page"

// Media
"Play my gym playlist on Spotify"
"Skip this song"
"Play lo-fi music on YouTube"
"Stream PC audio to my phone"

// Files
"Find my resume"
"Organize my Downloads folder"
"Delete project.zip"    ← triggers face auth

// Communication
"What did she say on WhatsApp?"
"Reply: I'll be there in 10 minutes"
"Draft a reply"         ← iZACH generates draft, reads it aloud
"Send it"               ← confirm
"Change it to: I'm busy right now"

// People
"Divya is my college friend"
"Remember that Rohan works at Google"
"Who is Divya?"

// Vision
"What am I holding?"
"How many calories is this?"
"Read the screen"

// Intelligence
"What's on my calendar tomorrow?"
"Remember that the meeting is at 3"
"What do you remember?"
"Show my routines"

// Security
"Enroll my face"
"Face auth status"
```

---

## Installation

> **Windows only.** iZACH uses `pywin32`, PowerShell APIs, and Windows system calls.

### Prerequisites

| Tool | Required | Notes |
|---|---|---|
| Python | 3.10 – 3.12 | python.org |
| Node.js | 18+ | nodejs.org |
| Git | any | git-scm.com |
| ngrok | optional | ngrok.com — needed for remote/WA access |
| Tesseract OCR | optional | `winget install UB-Mannheim.TesseractOCR` |
| MongoDB | optional | Falls back to local JSON |
| n8n | optional | `npm install -g n8n` |

---

### 1 — Clone & virtual env

```bash
git clone https://github.com/1nonlyvansh/iZACH.git
cd iZACH
python -m venv .venv
.venv\Scripts\activate
```

---

### 2 — Python dependencies

`dlib` (face recognition) requires a prebuilt wheel — avoid cmake hell:

```bash
# Python 3.12:
pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.99-cp312-cp312-win_amd64.whl

# Python 3.11:
pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.1-cp311-cp311-win_amd64.whl

# Then everything else
pip install -r requirements.txt

# Playwright browser
playwright install chromium
```

---

### 3 — Node dependencies

```bash
# WhatsApp bridge (project root)
npm install

# Electron / React UI
cd izach-ui && npm install && cd ..
```

---

### 4 — API keys

```bash
copy .env.example .env
# Open .env and fill in your keys
```

| Variable | Source |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free tier |
| `GEMINI_KEY_1/2/3` | [aistudio.google.com](https://aistudio.google.com) — free |
| `SPOTIPY_CLIENT_ID` | [developer.spotify.com](https://developer.spotify.com) → create app |
| `SPOTIPY_REDIRECT_URI` | set `http://127.0.0.1:8888/callback` in Spotify dashboard |
| `SMARTTHINGS_TOKEN` | [account.smartthings.com/tokens](https://account.smartthings.com/tokens) |
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) — for code skills |
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) — LLM fallback |

**Google Calendar** (optional):
1. Google Cloud Console → enable Calendar API
2. OAuth 2.0 credentials → desktop app → download as `credentials.json` → place in root
3. First run will open browser OAuth flow → creates `token.json` automatically

---

### 5 — Fix launch paths

`launch_izach.py` has hardcoded paths. Edit the top section:

```python
BASE      = r"C:\your\path\to\iZACH"
IZACH_CMD = [r"C:\your\path\to\iZACH\.venv\Scripts\python.exe", os.path.join(BASE, "main.py")]
# Comment out MMA_CMD if you don't have the MMA agent repo
```

---

### 6 — Launch

```bash
python launch_izach.py
```

Services start in order with health checks:

```
● N8N            :5678   workflow engine
● iZACH Backend  :5050   Flask + command engine
● MMA Agent      :6060   remote agent (optional)
● WhatsApp       :3000   Node.js bridge (optional)
● Ngrok Tunnel   ——      exposes :5050 publicly (optional)
● Electron UI    :5173   React desktop app
```

**First-run notes:**
- **WhatsApp** — bridge window shows QR. Scan in WhatsApp → Linked Devices.
- **Spotify** — first command opens browser OAuth. Approve it.
- **Face auth** — say *"enroll my face"* to register biometrics.
- **Memory** — memories persist in `smart_memory.json` (gitignored).

---

## Port Reference

| Port | Service |
|---|---|
| `5050` | iZACH Flask backend (REST API) |
| `5051` | WebSocket — real-time events (UI + Android) |
| `3000` | WhatsApp bridge (Node.js) |
| `6060` | MMA remote agent |
| `5678` | n8n workflow engine |
| `4040` | ngrok local dashboard |
| `5173` | Vite dev server (Electron UI) |
| `8888` | Spotify OAuth redirect |

---

## Project Structure

```
iZACH/
├── main.py                       # Backend entry point
├── launch_izach.py               # System launcher (all services)
├── cortex-ui.html                # Single-file Electron UI (primary)
├── modules/
│   ├── command_chain.py          # Central command router
│   ├── ai_handler.py             # Groq / Gemini / OpenRouter inference
│   ├── skill_engine.py           # Skills system — #id routing + DeepSeek (v2.1.0)
│   ├── smart_memory.py           # Smart memory engine (v2.0.0)
│   ├── automation_scheduler.py   # APScheduler cron jobs (v2.0.0)
│   ├── system_control.py         # Volume, brightness, WiFi, drives
│   ├── web_automation.py         # Playwright browser automation
│   ├── shell_executor.py         # PowerShell executor + safety list
│   ├── face_auth.py              # Face enrollment & verification
│   ├── file_manager.py           # File operations
│   ├── calendar_agent.py         # Google Calendar sync
│   ├── pattern_learner.py        # Behavioral pattern engine
│   ├── curiosity_engine.py       # Proactive questioning + answer capture
│   ├── system_log_analyzer.py    # 10-day Windows system analysis
│   ├── obsidian_brain.py         # Obsidian vault writer + brain graph
│   ├── relationship_memory.py    # People profiles (MongoDB + Obsidian)
│   ├── wa_draft_engine.py        # WhatsApp auto-draft + voice approval
│   ├── smart_home_engine.py      # Samsung SmartThings + Nest SDM
│   ├── audio_streamer.py         # PC audio stream endpoint (v2.1.0)
│   ├── dnd_mode.py               # DND mode + WhatsApp alert queue
│   ├── spotify_controller.py
│   ├── whatsapp_handler.py
│   ├── camera_vision.py          # Gemini Vision + MJPEG stream
│   ├── ws_bridge.py              # WebSocket broadcast hub
│   └── ui_api.py                 # Flask REST endpoints
├── Agents/
│   ├── memory_agent.py           # Voice → memory intent handler
│   └── reminder_agent.py
├── izach-ui/                     # Electron + React desktop app (Forge UI)
│   └── src/
│       ├── App.jsx
│       ├── components/
│       └── hooks/useIZACH.js
├── izach-android/                # Android companion app (Kotlin)
│   └── app/src/main/java/com/izach/android/
│       ├── MainActivity.kt
│       ├── AudioStreamActivity.kt        ← (v2.1.0)
│       ├── DndInlineReplyReceiver.kt     ← (v2.1.0)
│       ├── tile/                         ← Quick Tiles (v2.1.0)
│       │   ├── DndTileService.kt
│       │   ├── BusyTileService.kt
│       │   ├── LockPcTileService.kt
│       │   └── MutePcTileService.kt
│       ├── widget/
│       │   └── DndStatusWidget.kt
│       └── network/
│           ├── IZACHApi.kt
│           └── IZACHWebSocket.kt
├── skills/                       # Skill definition files (v2.1.0)
├── chrome_extension/             # Browser extension helper
├── whatsapp_bridge.js            # WhatsApp Web.js bridge
├── iZACH-Brain/                  # Obsidian vault (gitignored contents)
│   └── Memory/
│       ├── Identity/
│       ├── Instructions/
│       └── Automations/
├── .env.example                  # API key template
└── requirements.txt
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq (`llama-3.3-70b-versatile`) + Google Gemini + OpenRouter (fallback) |
| Code Skills | DeepSeek (routed via skill engine for `#python-dev`, `#react-builder`, etc.) |
| Speech | `SpeechRecognition` + `edge-tts` (Microsoft Neural voices) |
| Backend | Python 3.12 · Flask · WebSockets |
| Primary UI | Single-file HTML/JS — `cortex-ui.html` (Electron) |
| Forge UI | React 18 · Electron · Vite · Tailwind |
| Browser Automation | Playwright (Chromium) |
| Vision | OpenCV · face_recognition (dlib) · Gemini Vision |
| System Automation | PyAutoGUI · pywin32 · psutil |
| Memory | MongoDB · Obsidian vault (`[[wikilinks]]`) · JSON fallback |
| Smart Memory | `smart_memory.json` · APScheduler · Obsidian sync |
| Android | Kotlin · OkHttp · WebSocket · Quick Tiles API · AudioTrack |
| Smart Home | Samsung SmartThings API · Google Nest SDM |

---

## Common Issues

| Problem | Fix |
|---|---|
| `dlib` install fails | Use prebuilt wheel from step 2 |
| Mic not detected | Windows Settings → Privacy → Microphone → allow app access |
| Port 5050 in use | `netstat -ano \| findstr :5050` → `taskkill /PID <pid> /F` |
| Electron blank screen | Backend not up — check `http://localhost:5050/health` |
| `playwright install` fails | Activate `.venv` first: `.venv\Scripts\activate` |
| WhatsApp QR not showing | Run `node whatsapp_bridge.js` manually; wait 30s for browser |
| Android app can't connect | Firewall must allow port 5050; both devices same Wi-Fi subnet |
| Android shows DISCONNECTED | Backend must be running before opening app; check IP address |
| Audio stream crackling | Ensure both devices on same subnet; check `/audio/stream` endpoint |
| Quick tiles not appearing | Pull down shade → edit tiles → find iZACH tiles in available list |
| Smart memory not persisting | Check `smart_memory.json` not gitignored locally (it is by default) |
| Spotify OAuth fails | Verify `SPOTIPY_REDIRECT_URI` matches Spotify dashboard exactly |
| Skills not activating | Prefix must be exactly `#skill-id` with no space between `#` and id |

---

<div align="center">

**iZACH v2.1.0** — Skills system · Android audio stream · Quick Tiles · 5 crash fixes · 41 unused imports cleaned

*Voice → AI → Action.*

<br>

[![GitHub](https://img.shields.io/badge/GitHub-1nonlyvansh%2FiZACH-00e5ff?style=flat-square&logo=github&logoColor=00e5ff&labelColor=050d1a)](https://github.com/1nonlyvansh/iZACH)
&nbsp;
[![Instagram](https://img.shields.io/badge/Instagram-%401nonlyvansh-00e5ff?style=flat-square&logo=instagram&logoColor=00e5ff&labelColor=050d1a)](https://instagram.com/1nonlyvansh)
&nbsp;
[![iZACH Instagram](https://img.shields.io/badge/Instagram-%40intent__zach-00e5ff?style=flat-square&logo=instagram&logoColor=00e5ff&labelColor=050d1a)](https://instagram.com/intent_zach)

</div>
