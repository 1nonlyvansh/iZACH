# Changelog

All notable changes to iZACH are documented here. See [README.md](README.md) for full feature descriptions and screenshots — this file is the terse, technical log.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are `YYYY-MM-DD`.

---

## [3.2.0] — 2026-07-28

### Added
- **macOS compatibility — full native port.** `modules/platform_utils.py` (new) provides `IS_WINDOWS`/`IS_MAC` + a shared `run_applescript()` helper. `modules/system_control.py` split into a thin dispatcher over `system_control_windows.py` / `system_control_mac.py` / `system_control_common.py` / `system_control_unsupported.py`, chosen at runtime. Windows behavior is unchanged; macOS gets real implementations, not stubs: AppleScript-driven volume/mute/brightness/Wi-Fi/theme, `.app` bundle scanning across `/Applications`, `~/Applications`, `/System/Applications` for app launch/detection, AVFoundation camera backend, CoreAudio mic handling with proper OS-level release on mute (previously the app kept a PortAudio session alive after mute, so macOS's own mic indicator kept showing the app as active), `osascript`-based notifications.
- **Dual-instance coordination** (`modules/instance_coordinator.py`, new) — a Mac and Windows instance of iZACH on the same LAN detect each other, negotiate Primary/Secondary via a pin/tie-break, support a "hand off to X" command, and an opt-in auto-promotion watchdog if the Primary goes offline (Task Scheduler on Windows, `launchd` on macOS).
- **Shared brain mirror** (`modules/shared_brain_mirror.py`, new) — Syncthing-based sync of the Obsidian memory vault between both machines, so context isn't stranded on whichever machine was Primary.
- **Settings UI — 15-tab reorganization** of Cortex UI's previously single-page Settings: Personalisation, Appearance, Device Connection, Notifications & Announcements, Connected Services, Security, Boot Settings, Others, Advanced. Tab bar scrolls horizontally instead of overflowing.
- **Boot Settings tab** — per-service enable/disable toggles wired into `launch_izach.py`, which now hides a disabled service's terminal window while still running it headless (an early draft skipped launching the service entirely — wrong, since disabling "backend" would've killed the whole app).
- **Android — multi-device profiles**: new `DevicesActivity`, `AddDeviceActivity`, `DeviceLauncherActivity`, `CommandQueueActivity`, `DeviceProfile`/`QueuedCommand` models, and a dedicated QR scanner (`QrCaptureActivity`/`QrViewfinderView`) as the primary pairing method.
- Platform self-awareness — iZACH can now answer "which OS/machine am I on?" correctly (`modules/personality.py`).

### Fixed
- **Calendar / Google Fit / Smart Home OAuth stuck at "Not Connected"** — all three used Google's `urn:ietf:wg:oauth:2.0:oob` redirect, which Google discontinued in 2022 (consent screen refuses to render). Rewritten to the standard local-server flow already used correctly by the Gmail/Calendar integration.
- **Spotify "device not found" / broken reconnect** — device discovery checked the last-known cached device before checking for a live active device; flipped the precedence.
- **Mic staying open after mute (macOS)** — the underlying `pyaudio.PyAudio()` instance kept the OS mic reservation alive across mute/unmute cycles even though individual stream open/close calls respected mute; now torn down entirely on mute.
- **Voice response latency** — tightened `pause_threshold` (2.5s → 1.0s) and `non_speaking_duration` (1.0s → 0.5s) for a snappier turnaround.
- **App detection false negatives** (e.g. "WhatsApp is not installed" when it was) — macOS lacked any app-detection implementation at all; added the `.app` bundle scan.
- **Android**: screenshot viewer showing solid black on a bitmap decode failure now shows a clear error instead; Save/Share buttons no longer overlap the status bar on devices with tall notches (fixed-height container swapped for `wrap_content` + `minHeight`); re-scanning a QR for one profile no longer corrupts a different, currently-active profile's saved connection.
- **`let` redeclaration `SyntaxError`** in `cortex-ui.html` that silently broke the *entire* inline script block (blank UI, zero console errors) — two independently-added timer variables shared the same name across two separate features.
- Assorted dead code and dead UI buttons removed following a full audit pass across backend, Cortex UI, and Android.

### Security
- **Purged 4 files with real leaked credentials from full git history** (not just current tree): `instagram_settings.json` (Instagram Graph API `app_secret` + `access_token`), `news_settings.json` (`newsapi_key`), plus `command_log.csv` and `file_manager_config.json`. These had been committed in early-2026 commits and later deleted from HEAD, but remained recoverable from history on the public repo. Rewritten via `git filter-repo` and force-pushed — all commit hashes and tags changed as a result. Both leaked credentials were rotated.
- `.gitignore` audit confirmed all 9 secret-shaped file categories (`.env`, `credentials.json`, `api_keys.json`, `token*.json`, `pairing_secret.json`, `browser_passwords.json`, `fitness_credentials.json`, `smart_home_credentials.json`) excluded on both Windows and macOS working copies before every push in this cycle.

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
