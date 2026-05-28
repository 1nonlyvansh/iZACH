import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
import re
import logging
import json
import threading
from rapidfuzz import process, fuzz
from dotenv import load_dotenv

_MOOD_MAP = {
    "chill": "chill lofi relaxing",
    "relaxing": "chill lofi relaxing",
    "lofi": "lofi hip hop study",
    "study": "study lofi concentration",
    "focus": "focus concentration deep work",
    "energetic": "energetic upbeat workout",
    "workout": "gym workout motivational",
    "happy": "happy feel good pop",
    "sad": "sad emotional ballad",
    "party": "party dance hits",
    "sleep": "sleep calm ambient",
    "morning": "morning upbeat fresh",
    "night": "night chill late night",
    "romantic": "romantic love songs",
    "jazz": "jazz smooth instrumental",
    "classical": "classical instrumental calm",
}


load_dotenv()

logger = logging.getLogger(__name__)


class SpotifyController:
    def __init__(self):
        self.last_device_id = None
        self.last_device_name = None
        self.client_id = os.getenv("SPOTIPY_CLIENT_ID", "")
        self.client_secret = os.getenv("SPOTIPY_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
        self.music_context = {
            "last_track": None,
            "last_artist": None
        }

        self.memory_file = "device_memory.json"

        try:
            with open(self.memory_file, "r") as f:
                data = json.load(f)
                self.last_device_id = data.get("id")
                self.last_device_name = data.get("name")
        except:
            self.last_device_id = None
            self.last_device_name = None

        self._sleep_timer = None

        self.scope = (
            "user-modify-playback-state "
            "user-read-playback-state "
            "playlist-read-private "
            "user-library-read "
            "user-read-recently-played"
        )

        try:
            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                cache_path=".cache",
                open_browser=True
            ))
            logger.info("[SPOTIFY] Controller online.")
        except Exception as e:
            logger.error(f"[SPOTIFY] Initialization Error: {e}")
            self.sp = None


    # ─────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────

    def _get_active_device(self):
        try:
            devices = self.sp.devices()
            if not devices or not devices['devices']:
                return None
            for d in devices['devices']:
                if d['is_active']:
                    self.last_device_id = d['id']
                    self.last_device_name = d['name']
                    return d['id']
            # No active device — use first available and update memory
            first = devices['devices'][0]
            self.last_device_id = first['id']
            self.last_device_name = first['name']
            try:
                with open(self.memory_file, "w") as f:
                    json.dump({"id": first['id'], "name": first['name']}, f)
            except Exception:
                pass
            return first['id']
        except Exception:
            return None

    @staticmethod
    def _normalize(text):
        """Strip all non-alphanumeric characters and lowercase."""
        return re.sub(r'[^\w]', '', text.lower())


    # ─────────────────────────────────────────────
    # TRACK PLAYBACK
    # ─────────────────────────────────────────────

    def play_track(self, query):
        """
        Build 7.5: Safe Search & Scoring.
        Searches Spotify and plays the best matching track.
        """
        if not self.sp:
            return "Spotify is not active right now."

        try:
            device_id = self.last_device_id or self._get_active_device()
            if not device_id:
                return "No active Spotify device."

            results = self.sp.search(q=query, limit=10, type='track')
            items = results.get('tracks', {}).get('items', [])

            if not items:
                return f"I couldn't find any tracks for '{query}'."

            best_match = None
            highest_score = -1

            for track in items:
                score = 0
                name = track['name'].lower()
                artist = track['artists'][0]['name'].lower()

                if query.lower() in name:
                    score += 50
                if query.lower() in artist:
                    score += 30

                if score > highest_score:
                    highest_score = score
                    best_match = track

            if not best_match:
                return f"I couldn't find a good match for '{query}'."

            track_uri = best_match['uri']
            track_name = best_match['name']
            artist_name = best_match['artists'][0]['name']

            self.sp.start_playback(device_id=device_id, uris=[track_uri])

            self.music_context["last_track"] = track_name
            self.music_context["last_artist"] = artist_name
            print(f"[CONTEXT] {self.music_context}")

            device_info = f" on {self.last_device_name}" if self.last_device_name else ""
            return f"Playing {track_name} by {artist_name}{device_info}"

        except Exception as e:
            logger.error(f"[SPOTIFY] Play Error: {e}")
            if "404" in str(e) or "Device not found" in str(e):
                self.last_device_id = None
                try:
                    import os
                    if os.path.exists(self.memory_file):
                        os.remove(self.memory_file)
                except Exception:
                    pass
                return "Spotify device not found. Make sure Spotify is open on your device and try again."
            return "I encountered an error while trying to play that track."


    # ─────────────────────────────────────────────
    # PLAYLIST FUNCTIONS
    # ─────────────────────────────────────────────

    def get_playlist_map(self):
        if not self.sp:
            return {}
        try:
            results = self.sp.current_user_playlists(limit=50)
            return {pl['name']: pl['uri'] for pl in results.get('items', [])}
        except Exception as e:
            logger.error(f"[SPOTIFY] Playlist Map Error: {e}")
            return {}


    def find_best_playlist(self, user_input, playlist_map):
        """
        Build 5.9: High-resilience fuzzy matching for Spotify playlists.
        Handles partial names, word reordering, punctuation, and speech errors.
        """
        if not playlist_map:
            return None, None

        clean_input = user_input.lower().strip()

        normalized_choices = {}
        for original_name in playlist_map.keys():
            norm = re.sub(r'\(.*?\)', '', original_name)
            norm = re.sub(r'[^\w\s]', '', norm)
            norm = norm.lower().strip()
            normalized_choices[norm] = original_name

        result = process.extractOne(
            clean_input,
            list(normalized_choices.keys()),
            scorer=fuzz.partial_ratio,
            score_cutoff=45
        )

        if result:
            matched_normalized = result[0]
            original_name = normalized_choices[matched_normalized]
            return playlist_map[original_name], original_name

        return None, None


    def play_specific_playlist_uri(self, uri):
        try:
            device_id = self.last_device_id or self._get_active_device()
            if not device_id:
                return "No active Spotify device."

            self.sp.start_playback(device_id=device_id, context_uri=uri)

            playlist_info = self.sp.playlist_items(uri, limit=1)
            if playlist_info['items']:
                first_track = playlist_info['items'][0]['track']
                self.music_context["last_track"] = first_track['name']
                self.music_context["last_artist"] = first_track['artists'][0]['name']
                print(f"[CONTEXT] {self.music_context}")

            return "Playing playlist."

        except Exception as e:
            return f"Playback Error: {e}"


    # ─────────────────────────────────────────────
    # PLAYBACK CONTROLS
    # ─────────────────────────────────────────────

    def pause_music(self):
        try:
            self.sp.pause_playback()
            return "Paused."
        except Exception:
            return "Failed to pause."

    def resume_music(self):
        try:
            self.sp.start_playback()
            return "Resumed."
        except Exception:
            return "Failed to resume."

    def next_track(self):
        try:
            self.sp.next_track()
            return "Skipped."
        except Exception:
            return "Failed to skip."

    def previous_track(self):
        try:
            self.sp.previous_track()
            return "Back."
        except Exception:
            return "Failed to go back."


    # ─────────────────────────────────────────────
    # NOW PLAYING / METADATA
    # ─────────────────────────────────────────────

    def get_current_track(self):
        """
        Build 6.0: Metadata retrieval.
        Returns the name and artist of the currently playing track.
        """
        if not self.sp:
            return "Spotify is not active right now."

        try:
            current_playback = self.sp.current_playback()

            if current_playback is None or not current_playback.get('is_playing'):
                return "Nothing is currently playing on Spotify."

            track_item = current_playback.get('item')
            if track_item:
                track_name = track_item.get('name')
                artist_names = ", ".join([a['name'] for a in track_item.get('artists', [])])
                return f"Now playing {track_name} by {artist_names}."

            return "Nothing is currently playing on Spotify."

        except Exception as e:
            logger.error(f"[SPOTIFY] Metadata Error: {e}")
            return "Spotify is not active right now."


    def get_current_playing(self):
        """
        Build 7.6: Live-First Playback Detection.
        Checks live Spotify status with a fallback to local context memory.
        """
        try:
            current = self.sp.current_playback()
            if current and current.get('item'):
                track_name = current['item']['name']
                artist_name = current['item']['artists'][0]['name']

                self.music_context["last_track"] = track_name
                self.music_context["last_artist"] = artist_name

                return f"Now playing {track_name} by {artist_name}."

        except Exception as e:
            logger.error(f"[SPOTIFY] Live check failed: {e}")

        ctx = self.music_context
        if ctx.get("last_track") and ctx.get("last_artist"):
            return f"Last played was {ctx['last_track']} by {ctx['last_artist']}."

        return "Nothing is currently playing."


    def get_music_context(self):
        """Returns the cached track and artist metadata."""
        return {
            "track": self.music_context["last_track"],
            "artist": self.music_context["last_artist"]
        }


    # ─────────────────────────────────────────────
    # LIKED SONGS
    # ─────────────────────────────────────────────

    def play_liked_songs(self):
        """
        Build 6.2: Direct Track Injection.
        Fetches Liked Songs and plays them in shuffle mode.
        """
        if not self.sp:
            return "Spotify is not active right now."

        try:
            device_id = self.last_device_id or self._get_active_device()
            if not device_id:
                return "No active Spotify device."

            results = self.sp.current_user_saved_tracks(limit=50)
            items = results.get('items', [])

            if not items:
                return "Your liked songs list is empty."

            track_uris = [item['track']['uri'] for item in items]

            self.sp.shuffle(True, device_id=device_id)
            self.sp.start_playback(device_id=device_id, uris=track_uris)

            return "Playing your liked songs in shuffle mode."

        except Exception as e:
            logger.error(f"[SPOTIFY] Liked Songs Fetch Error: {e}")
            return "I couldn't access your liked songs. Please check your connection."


    # ─────────────────────────────────────────────
    # QUEUE
    # ─────────────────────────────────────────────

    def add_track_to_queue(self, uri):
        """Adds a specific track URI to the user's current playback queue."""
        if not self.sp:
            return "Spotify is not connected."

        try:
            device_id = self.last_device_id or self._get_active_device()
            if not device_id:
                return "No active device found to queue tracks."

            self.sp.add_to_queue(uri, device_id=device_id)
            return True

        except Exception as e:
            logger.error(f"[SPOTIFY] Queue Error: {e}")
            return False


    # ─────────────────────────────────────────────
    # SIMILAR TRACKS / RADIO
    # ─────────────────────────────────────────────

    def play_similar_tracks(self, query=None):
        """
        Build 8.2: Strict Duplicate & Artist Filter.
        Uses context memory to exclude the current track/artist from the new radio queue.
        """
        if not self.sp:
            return "Spotify is not active right now."

        try:
            device_id = self.last_device_id or self._get_active_device()
            if not device_id:
                return "No active Spotify device."

            ctx = self.get_music_context()
            last_track = ctx.get("track")
            last_artist = ctx.get("artist")

            if not query and last_track:
                search_query = f"{last_track} {last_artist}"
            else:
                search_query = query

            if not search_query:
                return "I don't know what to base the similar songs on. Play something first!"

            results = self.sp.search(q=search_query, type='track', limit=10)
            raw_tracks = results.get('tracks', {}).get('items', [])

            if not raw_tracks:
                return f"I couldn't find any songs similar to '{search_query}'."

            filtered_tracks = []
            seen_names = set()

            if last_track and last_artist:
                target_track_lower = last_track.lower()
                target_artist_lower = last_artist.lower()

                for t in raw_tracks:
                    t_name = t['name'].lower()
                    t_artist = t['artists'][0]['name'].lower()

                    if target_track_lower in t_name or t_artist == target_artist_lower:
                        continue
                    if t_name not in seen_names:
                        filtered_tracks.append(t)
                        seen_names.add(t_name)
            else:
                filtered_tracks = raw_tracks

            final_selection = filtered_tracks if len(filtered_tracks) >= 2 else raw_tracks

            first_track_uri = final_selection[0]['uri']
            self.sp.start_playback(device_id=device_id, uris=[first_track_uri])

            for track in final_selection[1:11]:
                self.sp.add_to_queue(track['uri'], device_id=device_id)

            self.music_context["last_track"] = final_selection[0]['name']
            self.music_context["last_artist"] = final_selection[0]['artists'][0]['name']

            return f"Starting a discovery session based on {last_track if last_track else search_query}."

        except Exception as e:
            logger.error(f"[SPOTIFY] Filtered Radio Error: {e}")
            return "I encountered an error building your filtered radio."


    # ─────────────────────────────────────────────
    # DEVICE SWITCHER
    # ─────────────────────────────────────────────

    def switch_device(self, device_name):
        """
        Build 8.3: Fuzzy Device Switching.
        Transfers current playback to a target device (Phone, Laptop, TV, etc.)
        """
        if not self.sp:
            return "Spotify is not connected."

        try:
            # 1. Fetch available devices
            results = self.sp.devices()
            devices = results.get('devices', [])

            if not devices:
                return "I couldn't find any active Spotify devices. Make sure the app is open."

            # 2. Normalize input + apply speech corrections
            target = device_name.lower().strip()
            corrections = {
                "elite": "allied",
                "alight": "allied",
                "note": "node",
                "mode": "node",
                "road": "node"
            }
            for wrong, correct in corrections.items():
                target = target.replace(wrong, correct)

            # 3. Device aliases
            aliases = {
                "phone": "oneplus",
                "mobile": "oneplus",
                "tv": "samsung",
                "laptop": "allied",
                "pc": "allied",
            }
            for alias, real in aliases.items():
                if alias in target:
                    target = real

            normalized_target = self._normalize(target)
            device_map = {self._normalize(d['name']): d for d in devices}

            # 4. Fuzzy match
            result = process.extractOne(
                normalized_target,
                list(device_map.keys()),
                scorer=fuzz.ratio,
                score_cutoff=60
            )

            if not result:
                return f"I couldn't find a device matching '{device_name}'."

            matched_key = result[0]
            matched_device = device_map[matched_key]

            # 5. Transfer playback
            self.sp.transfer_playback(device_id=matched_device['id'], force_play=True)
            self.last_device_id = matched_device['id']
            self.last_device_name = matched_device['name']

            # 6. Save to memory file
            try:
                with open(self.memory_file, "w") as f:
                    json.dump({
                        "id": self.last_device_id,
                        "name": self.last_device_name
                    }, f)
            except Exception as e:
                print(f"[MEMORY SAVE ERROR]: {e}")

            return f"Switched playback to {matched_device['name']}."

        except Exception as e:
            logger.error(f"[SPOTIFY] Device Switch Error: {e}")
            return "I encountered an error while trying to switch devices."


    # ─────────────────────────────────────────────
    # DEVICE LIST
    # ─────────────────────────────────────────────

    def play_mood(self, mood: str) -> str:
        if not self.sp:
            return "Spotify is not active right now."
        try:
            device_id = self.last_device_id or self._get_active_device()
            if not device_id:
                return "No active Spotify device."
            query = _MOOD_MAP.get(mood.lower().strip(), mood)
            results = self.sp.search(q=query, limit=10, type='playlist')
            playlists = results.get('playlists', {}).get('items', [])
            if not playlists:
                return f"No playlists found for '{mood}'."
            playlist = playlists[0]
            self.sp.start_playback(device_id=device_id, context_uri=playlist['uri'])
            return f"Playing {playlist['name']} for a {mood} vibe."
        except Exception as e:
            logger.error(f"[SPOTIFY] Mood play error: {e}")
            return "Error starting mood playlist."

    def sleep_timer(self, minutes: int) -> str:
        if self._sleep_timer and self._sleep_timer.is_alive():
            self._sleep_timer.cancel()
        def _pause():
            self.pause_music()
        self._sleep_timer = threading.Timer(minutes * 60, _pause)
        self._sleep_timer.daemon = True
        self._sleep_timer.start()
        return f"Music will stop in {minutes} minute{'s' if minutes != 1 else ''}."

    def cancel_sleep_timer(self) -> str:
        if self._sleep_timer and self._sleep_timer.is_alive():
            self._sleep_timer.cancel()
            self._sleep_timer = None
            return "Sleep timer cancelled."
        return "No active sleep timer."

    def get_recently_played(self) -> str:
        if not self.sp:
            return "Spotify is not active right now."
        try:
            results = self.sp.current_user_recently_played(limit=5)
            items = results.get('items', [])
            if not items:
                return "No recently played tracks."
            names = [
                f"{i['track']['name']} by {i['track']['artists'][0]['name']}"
                for i in items
            ]
            return "Recently played: " + ", then ".join(names) + "."
        except Exception as e:
            logger.error(f"[SPOTIFY] Recently played error: {e}")
            return "Could not fetch recently played tracks."

    def list_devices(self):
        if not self.sp:
            return "Spotify not connected."

        try:
            devices = self.sp.devices().get('devices', [])

            if not devices:
                return "No active Spotify devices found."

            output = "Available devices:\n"
            for d in devices:
                output += f"  - {d['name']}\n"

            print(output)
            return output

        except Exception as e:
            return f"Error fetching devices: {e}"