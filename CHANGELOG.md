# Changelog

All notable changes to iZACH are documented here. See [README.md](README.md) for full feature descriptions and screenshots — this file is the terse, technical log.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are `YYYY-MM-DD`.

---

## [2.2.0] — 2026-07-16

### Added
- **Forge UI standalone browser** — full rewrite of Forge's embedded browser into a standalone, multi-tab (`tk.Toplevel`) window built on `tkwebview2`/Edge WebView2.
  - Shares live cookies/sessions with Cortex UI's Electron browser via a shared Chromium profile directory.
  - Shares the same encrypted password vault (`browser_passwords.json`) as Cortex — same DPAPI/AES-256-GCM scheme as Electron's `safeStorage`, gated behind the same Windows Hello enrollment.
  - Bookmarks, history, find-in-page, zoom, DevTools, Phone Tabs, Send to Phone — full parity with Cortex's browser.
  - Tab count capped at 6 as a RAM guardrail (each tab is a full WebView2 process).
- **Nickname** — user-configurable additional wake word/trigger (`modules/wake_word.py`, `modules/personality.py`); settings in both Cortex and Forge.
- **Email agent** (`modules/email_agent.py`, `Agents/email_agent.py`) — off by default, own read-only Gmail OAuth (separate token from Calendar's):
  - OTP detection (regex, no LLM) with instant delivery.
  - Reply and configurable keyword/sender watch.
  - Order/shipment tracking — carrier/description/ETA extraction (Groq), deduplicated across status updates, stored in `tracked_orders.json`.
- **Calendar-driven auto-DND** (`modules/calendar_dnd.py`) — auto-enables DND N minutes before a calendar event and disables it at event end; does not interfere with manually-enabled or app-detected (Zoom/Teams/Meet) DND sessions.
- **Pattern-to-automation suggestions** — confirming a learned pattern (`modules/pattern_learner.py`) now creates a real `smart_memory` automation (visible in Android's Automations screen, fired by the shared scheduler) instead of a private, invisible routine.
- **Screen-aware assistance** (`modules/screen_awareness.py`) — off by default, per-app exclusion list (password managers by default) plus a fixed sensitive-title-keyword safety net:
  - Stack-trace detection on the active window (OCR + regex, no LLM/network call).
  - Idle-browser-tab nudge (pure timing signal, no OCR).
- **Unified notification triage** (`modules/notification_system.py`) — WhatsApp and Calendar reminders now feed into the same notification history as system/email alerts (previously invisible to it entirely); new `GET /notifications/feed` ranks everything by category weight + VIP-sender bonus.
- Settings UI (Cortex + Forge) for all of the above.

### Fixed
- **Phone pairing over WebSocket** — the WS port (5051) trusted any device claiming to be the Android app with zero verification; now requires an HMAC proof over the pairing secret before marking a phone "connected" or relaying broadcasts to it.
- **Pairing-secret file handling** — a transient file-read error used to silently mint and persist a brand-new pairing secret, invalidating every already-paired device; now only a genuinely missing file creates one, everything else fails closed.
- **Android offline command queue** — an HTTP 401 (rejected pairing signature) was queued and retried forever as if the PC were merely unreachable; now surfaces "not paired — re-scan the QR" and stops retrying.
- **Android "ONLINE" status accuracy** — the in-app connection indicator was driven by an unauthenticated reachability check; now verifies real pairing via a signed request.
- **RAG memory bleeding into greetings** — a bare "hi" could retrieve and echo an unrelated stored reply from a past conversation; greetings now skip memory retrieval entirely.
- **`browserPlayYouTube` reusing the last-played video** — always opens a fresh tab and navigates directly to the search URL now (previously raced a `dom-ready` event and silently stuck on `about:blank`).
- **Browser-window playback handoff** — "Open in Browser Window" now carries over the current timestamp/pause state instead of restarting playback.
- **Android silent-failure bugs** — `pcPower`, `alliedPower`, `alliedVolume`, `alliedBrightness`, `alliedScreenshot` no longer report success on an HTTP error response.
- **QR code load latency** — removed an unconditional Tailscale-IP subprocess call that added up to 3s to every QR render even in LAN mode.
- Missing dependencies pinned that the app silently relied on being installed: `apscheduler`, `google-auth-oauthlib`, `tkwebview2==3.5.0`, `pywebview==4.4.1` (pinned below latest — newer `pywebview` breaks `tkwebview2`'s API).
- Browser tab RAM growth — both Cortex's and Forge's browsers now cap open tabs at 6 (neither previously freed anything on tab-switch, only on explicit close).

### Security
- `.gitignore` audit — added `pairing_secret.json`, `token_gmail.json`, `tracked_orders.json`, `email_agent_state.json`, `custom_links.json`, `browser_tabs.json`, `api_usage.json`, `owner_voice.json`/`.npy`, `voice_profiles/`, `speaker_profiles/`, `firebase_service_account.json`, `google-services.json`, and the Spotipy `.cache` token file (previously only the `.cache/` *directory* pattern existed, missing the literal file Spotipy actually writes). Verified none of these were ever committed to history.

---

## [2.1.1] — prior to this log's start

Log rotation `WinError 32` fix, audio-stream backend check, download monitor fix. See commit `e398770`.

## [2.1.0] — prior to this log's start

Skills system (`#skill-id` activation, DeepSeek routing, multi-skill chaining), modular widget UI with API usage monitor, Android v2.1 (PC audio stream, DND inline reply, Quick Tiles, App Shortcuts), assorted crash fixes. See [README.md § What's New in v2.1.0](README.md#whats-new-in-v210) for full detail.

## [2.0.0] — prior to this log's start

Smart Memory system, Cortex UI rewrite, Android WebSocket connection + phone mirroring, automation scheduler, `.env`/`.gitignore` security pass. See [README.md § What's New in v2.0.0](README.md#whats-new-in-v200).

---

*This file starts its detailed entries at 2.2.0 — earlier versions are summarized from commit history and the README's own changelog sections rather than reconstructed in full.*
