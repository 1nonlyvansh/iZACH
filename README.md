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

*A voice-driven AI assistant for Windows and macOS — context-aware, system-deep, always on.*

---

[![Version](https://img.shields.io/badge/Version-v3.2.0-00e5ff?style=flat-square&labelColor=050d1a)](.)
[![Python](https://img.shields.io/badge/Python-3.10%2B-00e5ff?style=flat-square&logo=python&logoColor=00e5ff&labelColor=050d1a)](https://python.org)
[![React](https://img.shields.io/badge/React-18-00e5ff?style=flat-square&logo=react&logoColor=00e5ff&labelColor=050d1a)](https://react.dev)
[![Electron](https://img.shields.io/badge/Electron-Desktop-00e5ff?style=flat-square&logo=electron&logoColor=00e5ff&labelColor=050d1a)](https://electronjs.org)
[![Flask](https://img.shields.io/badge/Flask-Backend-00e5ff?style=flat-square&logo=flask&logoColor=00e5ff&labelColor=050d1a)](https://flask.palletsprojects.com)
[![Groq](https://img.shields.io/badge/Groq-LLM-00e5ff?style=flat-square&logoColor=00e5ff&labelColor=050d1a)](https://groq.com)
[![Android](https://img.shields.io/badge/Android-Companion%20App-00e5ff?style=flat-square&logo=android&logoColor=00e5ff&labelColor=050d1a)](https://github.com/1nonlyvansh/iZACH/releases/latest)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%26%20macOS-0d2a3a?style=flat-square&logo=apple&logoColor=c8e8f0&labelColor=050d1a)](.)
[![Status](https://img.shields.io/badge/Status-Active%20Dev-1db954?style=flat-square&labelColor=050d1a)](.)

</div>

---

## What is iZACH?

iZACH is a local-first, voice-controlled AI assistant that runs natively on **Windows and macOS**. It doesn't just answer questions — it **acts**. Control Spotify, automate WhatsApp, execute system commands, manage files, browse the web, read your calendar, watch your camera, and learn your behavioral patterns — all through natural speech or a neural-themed desktop UI.

**v3.2.0** brings iZACH to macOS as a full native port — not a compatibility shim — with system control, camera/mic, app launching, and notifications all reimplemented on Apple's own APIs. It also adds dual-instance coordination so a Mac and a Windows PC running iZACH can detect each other, hand off primary duty, and share one memory brain; a full Settings UI overhaul; and Android multi-device profiles with a QR-based pairing flow. Full technical log: [CHANGELOG.md](CHANGELOG.md).

---

## What's New in v3.2.0

### macOS Compatibility — Full Native Port

iZACH now runs natively on macOS, not through a compatibility layer. Every OS-coupled subsystem was ported to Apple's own frameworks rather than stubbed out.

| Area | Windows | macOS |
|---|---|---|
| System control (volume/mute/brightness/Wi-Fi/theme) | `pycaw`/WMI/registry | AppleScript (`osascript`) |
| App launching & detection | Start Menu / registry scan | `.app` bundle scan across `/Applications`, `~/Applications`, `/System/Applications` |
| Camera | DirectShow | AVFoundation |
| Microphone | WASAPI | CoreAudio — proper OS-level release on mute, not just a stream pause |
| Notifications | Windows Toast | `osascript display notification` |
| Process/app control | `taskkill`, Win32 process APIs | `psutil` + POSIX signals |

`modules/system_control.py` is now a thin dispatcher over `system_control_windows.py` / `system_control_mac.py` / `system_control_unsupported.py`, chosen at runtime by the new `modules/platform_utils.py`. iZACH also knows what machine it's running on now — ask "which OS are you on?" and it answers correctly.

### Dual-Instance Coordination (Mac ↔ Windows)

If you run iZACH on both a Mac and a Windows PC, the two instances can now detect each other on the LAN, negotiate a Primary/Secondary role, and hand off between them:

- **Peer detection** — each instance checks in with the other; a pin/tie-break mechanism decides which is Primary if both start at once.
- **"Hand off to Windows/Mac"** — a voice/chat command that promotes the other machine to Primary and demotes this one.
- **Auto-promotion** — optional watchdog: if the Primary goes offline, the Secondary can auto-promote itself after a configurable timeout.
- **Shared brain mirror** — via Syncthing, both machines' Obsidian memory vault stays in sync, so context isn't stranded on whichever machine was Primary at the time.
- **WhatsApp bridge gating** — only the Primary runs the WhatsApp bridge, avoiding duplicate/conflicting sessions from two machines racing the same account.

### Settings UI Overhaul

Cortex UI's Settings went from one flat page to a 15-tab reorganization: Personalisation, Appearance, Device Connection, Notifications & Announcements, Connected Services, Security, Boot Settings, Others, Advanced, and more — each a focused panel instead of one long scroll. Tab bar now scrolls horizontally instead of overflowing off-screen on smaller windows.

### Connected Services — OAuth Fixed

Calendar, Google Fit, and Smart Home OAuth previously used Google's `urn:ietf:wg:oauth:2.0:oob` flow, which Google discontinued in 2022 — the consent screen simply refused to render, making these integrations unusable regardless of OS. All three now use the standard local-server OAuth flow (same pattern Gmail/Calendar already used correctly): click Connect, approve in your browser, done — no more getting stuck at "Not Connected."

### Android — Multi-Device Profiles

- **Device profiles** — save and switch between multiple paired PCs from one app (new Devices screen, Add Device flow, per-device launcher).
- **QR-based pairing** — dedicated in-app QR scanner (`QrCaptureActivity`) replaces manual IP entry as the primary pairing method.
- **Command queue view** — see commands queued while your PC was unreachable, instead of them silently vanishing.
- Fixed: re-scanning a QR code for one profile no longer corrupts a different, currently-active profile's saved connection.
- Fixed: screenshot viewer showing solid black on decode failure — now shows a clear error instead of a blank image.
- Fixed: Save/Share buttons overlapping the status bar on devices with tall notches/cutouts.

### Also Fixed

- **Spotify "device not found"** — device discovery now checks for a live active device first, falling back to the last-known device only if nothing live is found (was backwards — stale cache took priority over reality).
- **Mic staying open after mute** — muting in the UI now actually releases the OS-level microphone reservation (macOS previously kept showing the mic as in-use by the app after mute).
- **Voice response latency** — tightened speech-recognition pause/silence thresholds for a snappier turnaround, closer to a real assistant than a walkie-talkie.
- **App detection false negatives** — apps installed but not detected (e.g. "WhatsApp is not installed" when it clearly was) fixed via the new macOS `.app` bundle scan; same class of bug checked and fixed on Windows too.
- Dead code and dead UI buttons removed following a full audit pass across the backend, Cortex UI, and Android app.

---

## What's New in v2.2.0

### Forge UI Browser — Full Rebuild

| Feature | Detail |
|---|---|
| **Standalone window** | Forge's browser is now its own OS window (multi-tab, up to 6 tabs), not an overlay inside the main Forge window |
| **Shared login sessions** | Forge's browser and Cortex UI's browser share the exact same live cookies/sessions — log in once, stay logged in on both |
| **Shared password vault** | Same encrypted `browser_passwords.json` vault as Cortex, same Windows Hello gate before any password is revealed/autofilled |
| **Bookmarks, history, find-in-page** | Full parity with Cortex's browser — star/folder bookmarks, searchable history, in-page search, zoom, DevTools |
| **Phone Tabs / Send to Phone** | Continue a tab from your phone, or push the current page to your phone, from Forge same as Cortex |
| **Tab cap (6)** | Guardrail against unbounded RAM growth — each tab is a full browser engine instance under the hood |

### Nickname

| Feature | Detail |
|---|---|
| **Custom trigger word** | Set a nickname (e.g. "Neo") in Settings — works as an additional wake word/trigger alongside "iZACH", doesn't replace it |
| **Self-aware** | iZACH knows its own nickname — ask "what's your nickname?" and it'll answer correctly |

### Email Agent

| Feature | Detail |
|---|---|
| **Off by default** | Nothing reads your inbox until you connect Gmail and turn it on in Settings |
| **OTP watch** | Detects one-time codes in incoming mail and reads them out instantly — no waiting on a polling cycle |
| **Reply watch** | Flags when someone replies to an email thread |
| **Keyword/sender watch** | Configurable watchlist (e.g. "Dell Support Assist", "Amazon Delivery") |
| **Order tracking** | Extracts carrier, description, and delivery date from shipping emails; tracks the same order across "shipped → out for delivery → delivered" updates |
| **Own Gmail OAuth** | Separate, read-only Gmail connection from Google Calendar — connecting one never forces you to re-consent the other |

### Calendar-Driven Auto-DND

Automatically enables Do Not Disturb a configurable number of minutes before a calendar meeting starts, and disables it when the meeting ends — without clobbering a manually-enabled DND session or an app-detected Zoom/Teams/Meet session.

### Pattern-to-Automation Suggestions

iZACH already noticed recurring habits ("you play the coding playlist every weekday around 9") and asked if you wanted it automated — confirming "yes" now creates a **real** automation visible in the Android Automations screen, instead of a private routine only iZACH itself could see.

### Screen-Aware Assistance

| Feature | Detail |
|---|---|
| **Off by default** | Opt-in only, with a per-app exclusion list (password managers excluded by default) |
| **Stack-trace detection** | Notices an error/exception on your active window and offers to help — pure regex match, no AI ever sees your screen content |
| **Idle-tab nudge** | Notices a browser tab that's been sitting untouched for 20+ minutes and offers to close it |

### Unified Notification Feed

WhatsApp, Calendar reminders, system alerts, and email agent notifications are now aggregated into one feed, ranked by priority (VIP contacts + urgency) instead of scattered across separate channels with no shared history.

### Security Hardening

| Fix | Detail |
|---|---|
| **Phone pairing over WebSocket** | The WebSocket port used to trust *any* device on the LAN claiming to be the Android app — now requires the same signed proof every HTTP request already needed |
| **Pairing-secret file safety** | A transient disk read error used to silently regenerate the pairing secret, invalidating every paired device — now only a genuinely missing file creates a new one |
| **Android offline queue** | A rejected pairing secret (401) was queued for endless retry as if the PC were merely offline — now surfaces "not paired, re-scan the QR" instead |
| **Android status accuracy** | The in-app "ONLINE" indicator could show connected even when commands would 401 — now verifies real pairing, not just reachability |

### Also Fixed

- **RAG memory bleeding into greetings** — a plain "hi" could echo back an unrelated stored reply from a past conversation; greetings now skip memory retrieval
- **"Play X on YouTube" reusing the last video** — now always opens a fresh tab and searches correctly
- **Browser-window playback handoff** — resuming playback in a new external window now carries over the current timestamp/pause state
- **Android silent-failure bugs** — `pcPower`/`alliedPower`/`alliedVolume`/`alliedBrightness`/`alliedScreenshot` no longer report success on an HTTP error
- **Android persistent status notification** — ongoing notification showing PC connection + DND/Busy/Background mode state
- **Android file-transfer progress** — upload notifications now show live percentage instead of just start/done
- Missing dependencies (`apscheduler`, `google-auth-oauthlib`, `tkwebview2`/`pywebview`) pinned in `requirements.txt` that the app silently relied on being installed

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
- PowerShell executor with safety block list *(Windows only — not yet ported to macOS shell)*
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

**✉️ Email Agent (v2.2.0)**
- Off by default — connect Gmail (read-only) to enable
- Instant OTP read-out on arrival
- Reply + configurable keyword/sender watch
- Order/shipment tracking with carrier + ETA extraction
- Separate OAuth from Google Calendar

</td>
<td width="50%" valign="top">

**🧠 Intelligence**
- Behavioral pattern learner (Phase 5)
- Routine suggestions — confirming one now creates a **real** automation (v2.2.0)
- Screen-aware assistance — stack-trace + idle-tab detection, opt-in (v2.2.0)
- Short + long-term context memory
- MongoDB brain (falls back to local JSON)
- Proactive task suggestions
- Calendar event extraction from speech
- Calendar-driven auto-DND (v2.2.0)
- Curiosity engine — builds personal profile during idle moments
- System log analyzer — Gemini analysis of 10-day Windows event logs
- Obsidian brain graph — `[[wikilinks]]` between all memory nodes
- Relationship memory — people profiles linked to WhatsApp contacts
- Unified, priority-ranked notification feed across WhatsApp/Calendar/system/email (v2.2.0)

**📱 Connectivity**
- WhatsApp bridge — lazy-started on first WA command
- Spotify — play, pause, skip, playlists, device switch
- Google Calendar sync
- Android companion app (Wi-Fi + WebSocket)
- Ngrok tunnel for remote access
- Auto-draft WhatsApp reply with voice approval flow
- Samsung SmartThings smart home control
- Custom nickname — extra voice trigger alongside "iZACH" (v2.2.0)

**🔐 Security**
- Face authentication — lazy-loaded on first face command
- Face-gated file deletion
- Pre-commit hook blocks secrets & large files
- PowerShell command safety block list *(Windows only)*
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
- **Persistent status notification** — ongoing notification showing PC connection + DND/Busy/Background mode *(v2.2.0)*
- **File-transfer progress** — upload notifications show live percentage, not just start/done *(v2.2.0)*
- **Accurate pairing status** — "ONLINE" now reflects real signed-pairing state, not just reachability *(v2.2.0)*
- **Multi-device profiles** — save and switch between several paired PCs (Mac and/or Windows) from one app *(v3.2.0)*
- **QR-based pairing** — dedicated in-app scanner as the primary way to pair, manual IP entry still available *(v3.2.0)*
- **Command queue view** — see commands queued while your PC was unreachable instead of losing them silently *(v3.2.0)*
- **Per-device launcher** — jump straight into a specific paired PC's session from a device list *(v3.2.0)*

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

> **Windows and macOS.** `launch_izach.py` auto-detects your OS and paths — no manual path editing on either platform.

### Prerequisites

| Tool | Required | Windows | macOS |
|---|---|---|---|
| Python | 3.10 – 3.12 | python.org | `brew install python@3.12` |
| Node.js | 18+ | nodejs.org | `brew install node` |
| Git | any | git-scm.com | preinstalled / `brew install git` |
| ngrok | optional — remote/WA access | ngrok.com | `brew install ngrok` |
| Tesseract OCR | optional | `winget install UB-Mannheim.TesseractOCR` | `brew install tesseract` |
| MongoDB | optional — falls back to local JSON | — | `brew install mongodb-community` |
| n8n | optional | `npm install -g n8n` | `npm install -g n8n` |
| BlackHole 2ch | macOS only — needed for PC-audio-to-phone streaming | — | `brew install blackhole-2ch` |
| Xcode Command Line Tools | macOS only — needed to build `dlib` | — | `xcode-select --install` |

---

### 1 — Clone & virtual env

```bash
git clone https://github.com/1nonlyvansh/iZACH.git
cd iZACH
python -m venv .venv
```

Windows:
```bash
.venv\Scripts\activate
```

macOS:
```bash
source .venv/bin/activate
```

---

### 2 — Python dependencies

`dlib` (face recognition) needs a prebuilt wheel on Windows to avoid a full cmake build:

```bash
# Windows, Python 3.12:
pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.99-cp312-cp312-win_amd64.whl

# Windows, Python 3.11:
pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.1-cp311-cp311-win_amd64.whl

# macOS — Xcode Command Line Tools must already be installed (see Prerequisites), then just:
pip install dlib

# Then everything else, both platforms:
pip install -r requirements.txt

# Playwright browser
playwright install chromium
```

`requirements.txt` uses PEP 508 environment markers — Windows-only packages (`pywin32`, `pycaw`, `WMI`, `comtypes`) and macOS-only packages (`pyobjc-framework-Cocoa`, `pyobjc-framework-Quartz`, `pyobjc-framework-AVFoundation`) install automatically based on your OS from the same `pip install -r requirements.txt` command — nothing to comment out or pick manually.

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

Windows: `copy .env.example .env` — macOS: `cp .env.example .env` — then open `.env` and fill in your keys.

| Variable | Source |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free tier |
| `GEMINI_KEY_1/2/3` | [aistudio.google.com](https://aistudio.google.com) — free |
| `SPOTIPY_CLIENT_ID` | [developer.spotify.com](https://developer.spotify.com) → create app |
| `SPOTIPY_REDIRECT_URI` | set `http://127.0.0.1:8888/callback` in Spotify dashboard |
| `SMARTTHINGS_TOKEN` | [account.smartthings.com/tokens](https://account.smartthings.com/tokens) |
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) — for code skills |
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) — LLM fallback |

**Google Calendar / Google Fit / Smart Home** (all optional, same pattern):
1. Google Cloud Console → enable the relevant API (Calendar / Fitness)
2. OAuth 2.0 credentials → desktop app → download as `credentials.json` (or `fitness_credentials.json`/`smart_home_credentials.json`) → place in root
3. Connect from Settings → Connected Services — opens your browser for consent, no code to paste, polls automatically until connected

---

### 5 — Launch

```bash
python launch_izach.py       # Windows
python3 launch_izach.py      # macOS
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
- **macOS permissions** — first run will prompt for Microphone, Camera, and (for window/app-awareness features) Screen Recording access. Grant all three, or the voice loop and vision features won't work.
- **macOS audio streaming to phone** — requires BlackHole (see Prerequisites) plus a Multi-Output Device set up in Audio MIDI Setup so you still hear audio locally while it's also captured for streaming.

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
├── izach-ui/                     # Electron + React desktop app (Cortex UI)
│   └── src/
│       ├── App.jsx
│       ├── components/
│       └── hooks/useIZACH.js
├── forge_ui.py                   # Legacy Tkinter desktop UI (Forge) — standalone
│                                  #   multi-tab browser w/ shared Cortex sessions (v2.2.0)
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
| Cortex UI | React 18 · Electron · Vite · Tailwind (`izach-ui/`) |
| Forge UI | Python · Tkinter — legacy desktop UI, standalone WebView2 browser (v2.2.0) |
| Browser Automation | Playwright (Chromium) |
| Vision | OpenCV · face_recognition (dlib) · Gemini Vision |
| System Automation | PyAutoGUI · psutil · pywin32 (Windows) / PyObjC + AppleScript (macOS) |
| Cross-Platform Layer | `modules/platform_utils.py` · `system_control_{windows,mac,common,unsupported}.py` dispatcher |
| Dual-Instance | `instance_coordinator.py` (peer detection/handoff) · Syncthing (shared brain mirror) |
| Memory | MongoDB · Obsidian vault (`[[wikilinks]]`) · JSON fallback |
| Smart Memory | `smart_memory.json` · APScheduler · Obsidian sync |
| Android | Kotlin · OkHttp · WebSocket · Quick Tiles API · AudioTrack |
| Smart Home | Samsung SmartThings API · Google Nest SDM |

---

## Common Issues

| Problem | Fix |
|---|---|
| `dlib` install fails (Windows) | Use prebuilt wheel from step 2 |
| `dlib` install fails (macOS) | Install Xcode Command Line Tools first: `xcode-select --install` |
| Mic not detected (Windows) | Windows Settings → Privacy → Microphone → allow app access |
| Mic not detected (macOS) | System Settings → Privacy & Security → Microphone → allow Terminal/iZACH |
| Port 5050 in use (Windows) | `netstat -ano \| findstr :5050` → `taskkill /PID <pid> /F` |
| Port 5050 in use (macOS) | `lsof -ti :5050 \| xargs kill -9` |
| Electron blank screen | Backend not up — check `http://localhost:5050/health` |
| `playwright install` fails | Activate `.venv` first (see step 1 for your OS) |
| WhatsApp QR not showing | Run `node whatsapp_bridge.js` manually; wait 30s for browser |
| Android app can't connect | Firewall must allow port 5050; both devices same Wi-Fi subnet |
| Android shows DISCONNECTED | Backend must be running before opening app; check IP address |
| Audio stream crackling | Ensure both devices on same subnet; check `/audio/stream` endpoint |
| macOS audio streaming silent | BlackHole not installed, or no Multi-Output Device set up in Audio MIDI Setup |
| Quick tiles not appearing | Pull down shade → edit tiles → find iZACH tiles in available list |
| Smart memory not persisting | Check `smart_memory.json` not gitignored locally (it is by default) |
| Spotify OAuth fails | Verify `SPOTIPY_REDIRECT_URI` matches Spotify dashboard exactly |
| Skills not activating | Prefix must be exactly `#skill-id` with no space between `#` and id |
| Dual-instance not detecting peer | Both machines need `dual_instance.enabled=true` **and** the other machine's real LAN IP set as `peer_host` in `api_keys.json` — no auto-discovery |

---

<div align="center">

**iZACH v3.2.0** — macOS native port · dual-instance Mac↔Windows coordination · 15-tab Settings rebuild · Android multi-device profiles

*Voice → AI → Action.*

<br>

[![GitHub](https://img.shields.io/badge/GitHub-1nonlyvansh%2FiZACH-00e5ff?style=flat-square&logo=github&logoColor=00e5ff&labelColor=050d1a)](https://github.com/1nonlyvansh/iZACH)
&nbsp;
[![Instagram](https://img.shields.io/badge/Instagram-%401nonlyvansh-00e5ff?style=flat-square&logo=instagram&logoColor=00e5ff&labelColor=050d1a)](https://instagram.com/1nonlyvansh)
&nbsp;
[![iZACH Instagram](https://img.shields.io/badge/Instagram-%40intent__zach-00e5ff?style=flat-square&logo=instagram&logoColor=00e5ff&labelColor=050d1a)](https://instagram.com/intent_zach)

</div>
