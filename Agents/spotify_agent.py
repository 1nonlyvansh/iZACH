"""
SpotifyAgent — full LLM-driven handler for all Spotify/music commands.

Replaces/consolidates in command_chain.py:
  Pause/resume/skip/previous blocks        (~lines 2461-2489)
  Device switch block                      (~lines 2491-2502)
  Mood play block                          (~lines 2504-2516)
  Sleep timer blocks                       (~lines 2518-2533)
  Recently played block                    (~lines 2535-2539)
  Queue / add-to-queue block               (~lines 2301-2314)
  Similar / radio block                    (~lines 2257-2299)
  Current track block                      (~lines 2228-2237)
  Device list block                        (~lines 2207-2217)
  Playlist handler                         (~line 1827)
  Device-aware play block                  (~lines 2329-2380)
  Platform choice state                    (~lines 2316-2327)

Intents handled:
  play_track         play a song / artist / album on Spotify
  play_playlist      play a named playlist
  play_liked         play liked songs (shuffled)
  play_mood          mood-based playlist (chill / study / workout / etc.)
  play_radio         radio / songs similar to X
  queue_track        add a track to the queue
  queue_current      queue the currently playing track again
  pause              pause playback
  resume             resume playback
  next_track         skip to next track
  previous_track     go back to previous track
  current_track      what song is playing now
  recently_played    last 5 tracks played
  switch_device      transfer playback to another device
  list_devices       list available Spotify devices
  sleep_timer        pause music after N minutes
  cancel_sleep_timer cancel the sleep timer
"""

from __future__ import annotations

import json
import re

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's Spotify command parser. Parse the user command into JSON.

Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "query": "<song/artist/album/playlist name or null>",
  "device_name": "<device name to switch to or null>",
  "timer_minutes": <int or null>,
  "mood": "<mood keyword or null>",
  "platform": "<spotify|youtube|null — null means Spotify by default>"
}}

Intents (pick exactly one):
- play_track        : play a specific song, artist, or album on Spotify
- play_playlist     : play a named playlist ("play my study playlist", "play Bollywood hits")
- play_liked        : play liked / saved songs ("play my liked songs", "play saved songs")
- play_mood         : mood-based play ("play chill music", "something relaxing", "workout music")
- play_radio        : songs like / similar to X ("songs like Believer", "radio for Arijit Singh")
- queue_track       : add a song to the play queue ("queue Levitating", "add Shape of You to queue")
- queue_current     : queue the current song again ("queue this", "add this to queue")
- pause             : pause music
- resume            : resume / continue music
- next_track        : skip / next song
- previous_track    : previous song / go back
- current_track     : what song is playing / what's this
- recently_played   : recently played / what was I listening to
- switch_device     : transfer playback to another device ("play on TV", "switch to phone")
- list_devices      : show all Spotify devices
- sleep_timer       : stop music after N minutes ("sleep timer 30 minutes")
- cancel_sleep_timer: cancel sleep timer

Rules:
- play_mood triggers: chill, lofi, lo-fi, study, focus, workout, gym, happy, sad, party, jazz, classical, romantic, morning, night, sleepy, energetic, relaxing, something, vibes
- play_radio triggers: "songs like", "similar to", "radio for", "play similar"
- play_playlist triggers: "playlist" keyword in command
- platform: "youtube" ONLY if user explicitly says "on YouTube"; otherwise null (= Spotify)
- query: strip filler like "on spotify", "for me", "please"; keep just the song/artist/topic
- timer_minutes: convert "30 minutes"→30, "1 hour"→60, "half hour"→30
- Output ONLY the JSON object
"""

_MOOD_WORDS = {
    "chill", "relaxing", "relax", "lofi", "lo-fi", "study", "focus",
    "energetic", "workout", "gym", "happy", "sad", "party", "sleepy",
    "morning", "night", "romantic", "jazz", "classical", "something",
    "vibes", "ambient", "meditation", "sleep",
}


class SpotifyAgent:
    """
    Handles all Spotify/music domain commands via LLM intent parsing.
    Stateful: manages platform-choice and playlist-disambiguation flows.
    """

    def __init__(self, speak_fn, raw_ai_fn, spotify_handler):
        self.speak          = speak_fn
        self._raw_ai        = raw_ai_fn
        self.spotify        = spotify_handler

        # Stateful flows (mirrors command_chain states but owned by agent)
        self._pending_platform: str | None = None   # song waiting for platform pick
        self._pending_playlists: dict       = {}     # name→uri map for disambiguation

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Parse and execute Spotify command.
        Returns True if handled, False to fall through.
        """
        # ── Stateful: playlist disambiguation ────────────────────
        if self._pending_playlists:
            return self._resolve_playlist_pick(cmd)

        # ── Stateful: platform choice (Spotify vs YouTube) ───────
        if self._pending_platform:
            return self._resolve_platform_choice(cmd)

        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        platform    = (intent_data.get("platform") or "").lower()

        # If user explicitly said YouTube → fall through to command_chain
        if platform == "youtube":
            return False

        print(f"[SPO_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "play_track":         self._play_track,
            "play_playlist":      self._play_playlist,
            "play_liked":         self._play_liked,
            "play_mood":          self._play_mood,
            "play_radio":         self._play_radio,
            "queue_track":        self._queue_track,
            "queue_current":      self._queue_current,
            "pause":              self._pause,
            "resume":             self._resume,
            "next_track":         self._next_track,
            "previous_track":     self._previous_track,
            "current_track":      self._current_track,
            "recently_played":    self._recently_played,
            "switch_device":      self._switch_device,
            "list_devices":       self._list_devices,
            "sleep_timer":        self._sleep_timer,
            "cancel_sleep_timer": self._cancel_sleep_timer,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        prompt   = _PARSE_PROMPT.format(cmd=cmd)
        response = ""
        try:
            response = self._raw_ai(prompt)
            clean    = re.sub(r'^```(?:json)?\s*', '', response.strip(), flags=re.IGNORECASE)
            clean    = re.sub(r'\s*```$', '', clean)
            m        = re.search(r'\{.*\}', clean, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            return data if "intent" in data else {"intent": "unknown"}
        except Exception as e:
            print(f"[SPO_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Stateful flow resolvers ───────────────────────────────────

    def _resolve_playlist_pick(self, cmd: str) -> bool:
        """User is disambiguating which playlist to play."""
        if cmd.strip() in {"cancel", "nevermind", "stop"}:
            self._pending_playlists = {}
            self.speak("Cancelled.")
            return True

        uri, name = self.spotify.find_best_playlist(cmd, self._pending_playlists)
        if uri:
            self._pending_playlists = {}
            self.speak(self.spotify.play_specific_playlist_uri(uri))
        else:
            names = ", ".join(list(self._pending_playlists.keys())[:4])
            self.speak(f"Couldn't match that. Choose from: {names}.")
        return True

    def _resolve_platform_choice(self, cmd: str) -> bool:
        """User chose Spotify or YouTube for a pending song."""
        song = self._pending_platform
        self._pending_platform = None

        if "youtube" in cmd:
            from modules.automation import play_specific_youtube
            play_specific_youtube(song)
        elif "spotify" in cmd or "spotify" not in cmd:
            self.speak(f"Playing {song}.")
            status = self.spotify.play_track(song)
            if any(w in status.lower() for w in ["couldn't", "error", "not found", "failed"]):
                self.speak(status)
        else:
            self.speak("Playing on Spotify.")
            self.spotify.play_track(song)
        return True

    # ── Helpers ───────────────────────────────────────────────────

    def _clean_playlist_name(self, cmd: str) -> str:
        keywords = ["play", "my", "playlist", "on", "spotify", "in", "youtube", "please"]
        pattern  = re.compile(r'\b(' + '|'.join(keywords) + r')\b', re.IGNORECASE)
        return pattern.sub('', cmd).strip()

    def _resolve_device(self, name: str) -> str:
        """Apply learned device aliases."""
        try:
            from modules.command_chain import _resolve_device_alias
            return _resolve_device_alias(name)
        except Exception:
            return name

    def _save_device(self, spoken: str, real: str) -> None:
        try:
            from modules.command_chain import _save_device_alias
            _save_device_alias(spoken, real)
        except Exception:
            pass

    # ── Handlers ─────────────────────────────────────────────────

    def _play_track(self, d: dict, cmd: str) -> bool:
        query = (d.get("query") or "").strip()
        if not query:
            self.speak("What should I play?")
            return True

        # Check if "on YouTube" mentioned → ask platform
        if "youtube" in cmd.lower():
            self._pending_platform = query
            self.speak(f"Play {query} on Spotify or YouTube?")
            return True

        self.speak(f"Playing {query}.")
        status = self.spotify.play_track(query)
        if any(w in status.lower() for w in ["couldn't", "error", "not found", "failed", "no active"]):
            self.speak(status)
        return True

    def _play_playlist(self, d: dict, cmd: str) -> bool:
        query    = (d.get("query") or "").strip()
        clean    = self._clean_playlist_name(query or cmd)
        playlists = self.spotify.get_playlist_map()

        if not playlists:
            self.speak("Couldn't fetch your playlists.")
            return True

        uri, name = self.spotify.find_best_playlist(clean, playlists)
        if uri:
            self.speak(self.spotify.play_specific_playlist_uri(uri))
        else:
            # Ambiguous → ask user to pick
            self._pending_playlists = playlists
            top_names = ", ".join(list(playlists.keys())[:5])
            self.speak(f"I couldn't find that playlist. Which one? {top_names}.")
        return True

    def _play_liked(self, d: dict, cmd: str) -> bool:
        self.speak("Playing your liked songs.")
        status = self.spotify.play_liked_songs()
        if status and any(w in status.lower() for w in ["error", "failed", "couldn't"]):
            self.speak(status)
        return True

    def _play_mood(self, d: dict, cmd: str) -> bool:
        mood = (d.get("mood") or d.get("query") or "").strip()
        if not mood:
            # Extract mood word from command directly
            words = cmd.lower().split()
            for w in words:
                if w in _MOOD_WORDS:
                    mood = w
                    break
            if not mood:
                mood = cmd.replace("play", "").replace("something", "").strip() or "chill"
        # Strip filler suffixes
        for filler in [" music", " songs", " tracks", " vibes", " playlist", " beats"]:
            mood = mood.replace(filler, "").strip()
        status = self.spotify.play_mood(mood)
        self.speak(status)
        return True

    def _play_radio(self, d: dict, cmd: str) -> bool:
        query = (d.get("query") or "").strip()
        if not query:
            # Strip radio trigger phrases
            for pfx in ["play songs like", "songs like", "similar to",
                        "play similar songs to", "play similar to", "radio for",
                        "play similar", "on spotify", "in spotify"]:
                query = re.sub(pfx, "", cmd, flags=re.IGNORECASE).strip()
                if query and query != cmd:
                    break
        if not query:
            self.speak("Tell me which song or artist to base it on.")
            return True
        status = self.spotify.play_similar_tracks(query)
        self.speak(status)
        return True

    def _queue_track(self, d: dict, cmd: str) -> bool:
        query = (d.get("query") or "").strip()
        if not query:
            # Strip queue verbs
            query = re.sub(r'\b(queue|add|to|next|play)\b', '', cmd, flags=re.IGNORECASE).strip()
        if not query:
            self.speak("Which song should I add to the queue?")
            return True
        try:
            results = self.spotify.sp.search(q=query, limit=1, type='track')
            tracks  = results.get('tracks', {}).get('items', [])
            if tracks:
                uri  = tracks[0]['uri']
                name = tracks[0]['name']
                self.spotify.add_track_to_queue(uri)
                self.speak(f"Added {name} to your queue.")
            else:
                self.speak(f"Couldn't find {query} on Spotify.")
        except Exception as e:
            self.speak(f"Queue error: {e}")
        return True

    def _queue_current(self, d: dict, cmd: str) -> bool:
        try:
            ctx = self.spotify.get_music_context()
            track  = ctx.get("track", "")
            artist = ctx.get("artist", "")
            if not track:
                self.speak("No song in memory to queue.")
                return True
            results = self.spotify.sp.search(q=f"{track} {artist}", limit=1, type='track')
            items   = results.get('tracks', {}).get('items', [])
            if items:
                uri = items[0]['uri']
                self.spotify.add_track_to_queue(uri)
                self.speak(f"Added {track} to your queue.")
            else:
                self.speak("Couldn't find that song in the Spotify catalog.")
        except Exception as e:
            self.speak(f"Queue error: {e}")
        return True

    def _pause(self, d: dict, cmd: str) -> bool:
        try:
            from modules.response_generator import get_response_generator
            rg = get_response_generator()
            if rg:
                rg.instant("pause")
        except Exception:
            pass
        self.spotify.pause_music()
        return True

    def _resume(self, d: dict, cmd: str) -> bool:
        try:
            from modules.response_generator import get_response_generator
            rg = get_response_generator()
            if rg:
                rg.instant("resume")
        except Exception:
            pass
        self.spotify.resume_music()
        return True

    def _next_track(self, d: dict, cmd: str) -> bool:
        try:
            from modules.response_generator import get_response_generator
            rg = get_response_generator()
            if rg:
                rg.instant("next")
        except Exception:
            pass
        self.spotify.next_track()
        return True

    def _previous_track(self, d: dict, cmd: str) -> bool:
        try:
            from modules.response_generator import get_response_generator
            rg = get_response_generator()
            if rg:
                rg.instant("previous")
        except Exception:
            pass
        self.spotify.previous_track()
        return True

    def _current_track(self, d: dict, cmd: str) -> bool:
        self.speak(self.spotify.get_current_track())
        return True

    def _recently_played(self, d: dict, cmd: str) -> bool:
        self.speak(self.spotify.get_recently_played())
        return True

    def _switch_device(self, d: dict, cmd: str) -> bool:
        device = (d.get("device_name") or "").strip()
        if not device:
            # Extract from command: "switch to X", "play on X", "move to X"
            m = re.search(
                r'(?:switch|transfer|move|change|play)\s+(?:playback|spotify|music|audio|the music)?\s*(?:to|on)\s+(?:my\s+)?(.+)',
                cmd, re.IGNORECASE
            )
            device = m.group(1).strip() if m else ""
        if not device:
            self.speak("Which device should I switch to?")
            return True
        resolved = self._resolve_device(device)
        status   = self.spotify.switch_device(resolved)
        self._save_device(device, resolved)
        self.speak(status)
        return True

    def _list_devices(self, d: dict, cmd: str) -> bool:
        self.speak(self.spotify.list_devices())
        return True

    def _sleep_timer(self, d: dict, cmd: str) -> bool:
        minutes = d.get("timer_minutes")
        if minutes is None:
            m = re.search(
                r'(\d+)\s*(minute|min|hour|hr)s?',
                cmd, re.IGNORECASE
            )
            if m:
                n    = int(m.group(1))
                unit = m.group(2).lower()
                minutes = n * 60 if unit.startswith("hour") or unit == "hr" else n
        if not minutes:
            self.speak("How many minutes for the sleep timer?")
            return True
        self.speak(self.spotify.sleep_timer(int(minutes)))
        return True

    def _cancel_sleep_timer(self, d: dict, cmd: str) -> bool:
        self.speak(self.spotify.cancel_sleep_timer())
        return True
