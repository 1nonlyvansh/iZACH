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

Pair it with the Android companion app and your phone becomes a remote interface — send voice commands, transfer files, monitor your system, and control Spotify from anywhere on your network.

---

## Feature Matrix

<table>
<tr>
<td width="50%" valign="top">

**🎤 Voice & Language**
- Continuous wake-word detection
- Natural language command parsing
- Groq LLM (`llama-3.3-70b`) for intent resolution
- Gemini fallback (3 rotated keys)
- Context memory across sessions
- Disambiguation for ambiguous commands

**🖥️ System Control**
- Volume, brightness, Wi-Fi, dark/light mode
- Battery health, CPU temp, RAM usage
- Timer, alarm, reminder engine
- Drive management + eject by name
- Firewall & Windows Update status
- Network device discovery

**🤖 Automation**
- Web automation via Playwright (14 functions)
- PowerShell executor with safety block list
- File manager: open, find, rename, move, copy, delete, sort, organize
- Screenshot capture → phone transfer
- Screen reader (Tesseract OCR)

</td>
<td width="50%" valign="top">

**🧠 Intelligence**
- Behavioral pattern learner (Phase 5)
- Routine suggestions from usage history
- Short + long-term context memory
- MongoDB brain (falls back to local JSON)
- Proactive task suggestions
- Calendar event extraction from speech

**📱 Connectivity**
- WhatsApp bridge — read & reply hands-free
- Spotify — play, pause, skip, playlists, device switch
- Google Calendar sync
- Android companion app (Wi-Fi)
- Ngrok tunnel for remote access

**🔐 Security**
- Face authentication (dlib, 0.50 tolerance)
- Face-gated file deletion
- Pre-commit hook blocks secrets & large files
- PowerShell command safety block list
- OAuth tokens never committed

**📷 Vision**
- Camera object identification (Gemini Vision)
- Calorie estimation from food
- Brand/item recognition
- Screen element detection

</td>
</tr>
</table>

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       USER INPUT                            │
│    Voice Mic  ──  Chat UI  ──  PS> Terminal  ──  Android    │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│              ELECTRON DESKTOP UI  :5173                     │
│   React  •  WebSocket  •  Neural Orb  •  Right Panel        │
└─────────────────────────┬───────────────────────────────────┘
                          │  HTTP :5050  /  WS :5051
┌─────────────────────────▼───────────────────────────────────┐
│                  FLASK BACKEND  :5050                       │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ CommandChain│  │  IntentRouter│  │    TaskEngine     │  │
│  └──────┬──────┘  └──────┬───────┘  └─────────┬─────────┘  │
│         └───────────────┬┘──────────────────────┘          │
│                         │                                   │
│  ┌──────────┬───────────┼────────────┬──────────────────┐   │
│  │ AI Layer │  System   │   Vision   │   Automation     │   │
│  │Groq/Gem  │  Control  │   Camera   │  Web / Shell     │   │
│  └──────────┴───────────┴────────────┴──────────────────┘   │
└───────┬──────────────────────┬──────────────────────────────┘
        │                      │
┌───────▼──────┐      ┌────────▼────────┐      ┌─────────────┐
│  WhatsApp    │      │   MMA Agent     │      │   Android   │
│  Bridge      │      │   :6060         │      │   App       │
│  :3000       │      │   (Remote)      │      │  (Wi-Fi)    │
└──────────────┘      └─────────────────┘      └─────────────┘
```

---

## Android Companion App

<table>
<tr>
<td width="50%" valign="top">

**Features**
- Chat interface — send voice or text commands
- Floating mic overlay — trigger iZACH from any app
- File transfer — send files from phone → PC
- Spotify remote control
- System dashboard (CPU, RAM, battery)
- Screenshot viewer
- Quick command shortcuts
- Download monitor
- Clipboard sync
- Notification history

</td>
<td width="50%" valign="top">

**Requirements**
- Android 7.0+
- Same Wi-Fi network as PC
- iZACH backend running on PC (port 5050)

**Download**

[![Download APK](https://img.shields.io/badge/Download-iZACH.apk-00e5ff?style=for-the-badge&logo=android&logoColor=00e5ff&labelColor=050d1a)](https://github.com/1nonlyvansh/iZACH/releases/latest)

> **Note:** Enable *Install from unknown sources* in Android Settings → Security before installing.

</td>
</tr>
</table>

### Connecting the App to iZACH

**Both devices must be on the same Wi-Fi network.**

1. Find your PC's local IP address:
   ```
   ipconfig
   ```
   Look for `IPv4 Address` under your Wi-Fi adapter — e.g. `192.168.1.105`

2. Make sure iZACH backend is running (`python launch_izach.py`)

3. Open iZACH app → **Settings** (gear icon)

4. Enter your PC's IP and port:
   ```
   http://192.168.1.105:5050
   ```
   Or tap the QR scan button — iZACH desktop can display a QR code with the backend URL.

5. Tap **Save** — the app will test the connection and confirm online status.

> If connection fails: check Windows Firewall allows port 5050, and that both devices are on the same subnet (not guest Wi-Fi vs main Wi-Fi).

---

### Adding APK to a GitHub Release

To distribute your own build:

1. Build the APK in Android Studio:
   `Build → Generate Signed Bundle / APK → APK`

2. Create a GitHub Release:
   ```
   GitHub repo → Releases → Draft a new release
   Tag: v1.0.0
   Title: iZACH v1.0.0
   ```

3. Drag and drop the `.apk` file into the release assets

4. Publish release — the download badge above will auto-link to `releases/latest`

---

## Voice Command Examples

```
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

// Files
"Find my resume"
"Organize my Downloads folder"
"Delete project.zip"   ← triggers face auth

// Communication
"What did she say on WhatsApp?"
"Reply: I'll be there in 10 minutes"

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
| ngrok | any | ngrok.com (free account) |
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

`dlib` (face recognition) requires prebuilt wheel to avoid cmake hell:

```bash
# Install dlib first — pick wheel matching your Python version
# Python 3.12:
pip install https://github.com/z-mahmud22/Dlib_Windows_Python3.x/raw/main/dlib-19.24.99-cp312-cp312-win_amd64.whl

# Then everything else
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

---

### 3 — Node dependencies

```bash
# WhatsApp bridge (project root)
npm install

# Electron UI
cd izach-ui && npm install && cd ..
```

---

### 4 — API keys

```bash
copy .env.example .env
# Edit .env with your keys
```

| Variable | Source |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free tier |
| `GEMINI_KEY_1/2/3` | [aistudio.google.com](https://aistudio.google.com) — free |
| `SPOTIPY_CLIENT_ID` | [developer.spotify.com](https://developer.spotify.com) → create app |
| `SPOTIPY_CLIENT_SECRET` | same app |
| `SPOTIPY_REDIRECT_URI` | set `http://127.0.0.1:8888/callback` in Spotify dashboard |

**Google Calendar** (optional):
1. Google Cloud Console → enable Calendar API
2. OAuth 2.0 credentials → download as `credentials.json` → place in project root

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
● MMA Agent      :6060   remote agent
● WhatsApp       :3000   Node.js bridge
● Ngrok Tunnel   ——      exposes :5050 publicly
● Electron UI    :5173   React desktop app
```

**First-run notes:**
- **WhatsApp** — bridge window shows QR. Scan in WhatsApp → Linked Devices.
- **Spotify** — first command opens browser OAuth. Approve it.
- **Face auth** — say *"enroll my face"* to register biometrics.

---

## Port Reference

| Port | Service |
|---|---|
| `5050` | iZACH Flask backend (REST) |
| `5051` | WebSocket — real-time UI events |
| `3000` | WhatsApp bridge |
| `6060` | MMA remote agent |
| `5678` | n8n workflow engine |
| `4040` | ngrok local dashboard |
| `5173` | Vite dev server (Electron) |

---

## Project Structure

```
iZACH/
├── main.py                  # Backend entry point
├── launch_izach.py          # System launcher (all services)
├── modules/
│   ├── command_chain.py     # Central command router
│   ├── ai_handler.py        # Groq / Gemini inference
│   ├── system_control.py    # Volume, brightness, WiFi, drives
│   ├── web_automation.py    # Playwright browser automation
│   ├── shell_executor.py    # PowerShell executor + safety
│   ├── face_auth.py         # Face enrollment & verification
│   ├── file_manager.py      # File operations
│   ├── calendar_agent.py    # Google Calendar sync
│   ├── pattern_learner.py   # Behavioral pattern engine
│   ├── spotify_controller.py
│   ├── whatsapp_handler.py
│   ├── camera_vision.py     # Gemini Vision integration
│   ├── ws_bridge.py         # WebSocket broadcast hub
│   └── ui_api.py            # Flask REST endpoints
├── izach-ui/                # Electron + React desktop app
│   └── src/
│       ├── App.jsx
│       ├── components/      # NeuralOrb, ChatPanel, RightPanel…
│       └── hooks/useIZACH.js
├── izach-android/           # Android companion app (Kotlin)
├── chrome_extension/        # Browser extension
├── whatsapp_bridge.js       # WhatsApp Web.js bridge
└── .env.example             # API key template
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq (`llama-3.3-70b-versatile`) + Google Gemini |
| Speech | `SpeechRecognition` + `edge-tts` (Microsoft voices) |
| Backend | Python 3.12 · Flask · WebSockets |
| UI | React 18 · Electron · Vite · Tailwind |
| Browser | Playwright (Chromium) |
| Vision | OpenCV · face_recognition (dlib) · Gemini Vision |
| Automation | PyAutoGUI · pywin32 · psutil |
| Memory | MongoDB · JSON fallback |
| Android | Kotlin · OkHttp · Wi-Fi (HTTP to Flask :5050) |

---

## Common Issues

| Problem | Fix |
|---|---|
| `dlib` install fails | Use prebuilt wheel (see step 2) |
| Mic not detected | Windows Settings → Privacy → Microphone → allow |
| Port 5050 in use | `netstat -ano \| findstr :5050` → kill that PID |
| Electron blank screen | Backend not up — check `http://localhost:5050/health` |
| `playwright install` fails | Activate `.venv` first |
| WhatsApp QR not showing | Run `node whatsapp_bridge.js` manually in that window |
| Android app can't connect | Check firewall allows port 5050; both devices on same Wi-Fi subnet |

---

<div align="center">

**iZACH** is actively developed. Core system functional across all 5 phases.

*Voice → AI → Action.*

<br>

[![GitHub](https://img.shields.io/badge/GitHub-1nonlyvansh%2FiZACH-00e5ff?style=flat-square&logo=github&logoColor=00e5ff&labelColor=050d1a)](https://github.com/1nonlyvansh/iZACH)
&nbsp;
[![Instagram](https://img.shields.io/badge/Instagram-%401nonlyvansh-00e5ff?style=flat-square&logo=instagram&logoColor=00e5ff&labelColor=050d1a)](https://instagram.com/1nonlyvansh)
&nbsp;
[![iZACH Instagram](https://img.shields.io/badge/Instagram-%40intent__zach-00e5ff?style=flat-square&logo=instagram&logoColor=00e5ff&labelColor=050d1a)](https://instagram.com/intent_zach)

</div>
