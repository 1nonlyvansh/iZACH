iZACH — Intelligent Zenith Adaptive Cognitive Handler

A full-stack AI assistant that can listen, think, and act — combining voice input, real-time AI processing, and system-level automation in a single modular architecture.

---

🚀 What It Does

iZACH is not just a chatbot. It acts as a personal operating layer that can:

- Understand voice commands
- Process them using AI (Groq / Gemini)
- Execute real actions (Spotify, WhatsApp, system tasks)
- Maintain context and memory

---

⚡ Key Features

- 🎤 Voice → AI → Action pipeline
- 💬 Chat-based command interface
- 📱 WhatsApp automation bridge
- 🎵 Spotify playback control
- 🧠 Context-aware memory system
- ⚙️ Task orchestration engine
- 🖥️ Desktop UI (React + Electron)

---

🧠 Architecture Overview

User (Voice / UI)
        ↓
Electron UI (React)
        ↓
Flask Backend (Port 5050)
        ↓
Command Engine
        ↓
Modules:
  • AI Processing (Groq / Gemini)
  • Spotify Controller
  • WhatsApp Bridge
  • Task Engine

---

🖼️ Demo

«Screenshots and demo will be added after UI stabilization.»

---

🛠️ Setup

1. Clone the repo

git clone https://github.com/1nonlyvansh/iZACH-V1.git
cd iZACH-V1

---

2. Install backend dependencies

pip install -r requirements.txt

---

3. Install UI dependencies

cd izach-ui
npm install
cd ..

---

4. Setup environment variables

Create a ".env" file:

GROQ_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
SPOTIPY_CLIENT_ID=your_id
SPOTIPY_CLIENT_SECRET=your_secret

---

5. Run the system

python launch_izach.py

---

⚠️ Notes

- Do NOT run "main.py" directly
- Ensure all ports are free:
  - 5050 → Backend
  - 3000 → WhatsApp Bridge
  - 6060 → MMA Agent

---

🎯 Future Improvements

- Smarter context memory
- Better UI responsiveness
- Real-time system monitoring
- Multi-device sync

---

📌 Project Status

Actively under development — core system functional, UI being refined.
