"""
modules/location_engine.py
4-layer location:
  1. Phone GPS companion (browser page → POST /location/phone-ping) — highest accuracy
  2. WiFi SSID → named label (user-defined via label_ssid())
  3. IP geolocation fallback (city-level)

Refreshes PC-level every 5 min. Phone GPS expires after 10 min of no ping.
Provides get_location() for AI context + WS broadcast.
"""

import json
import os
import subprocess
import threading
import time

_cache: dict = {"ssid": "", "label": "", "city": "", "lat": 0.0, "lon": 0.0, "country": ""}
_lock  = threading.Lock()

# Phone GPS data (updated via /location/phone-ping endpoint)
_phone_loc: dict = {
    "active": False, "lat": 0.0, "lon": 0.0, "accuracy": 0.0,
    "ts": 0, "place_name": "", "place_type": "",
}
_phone_lock = threading.Lock()
_PHONE_EXPIRE_SEC = 600  # 10 min — after this, phone GPS considered stale

# Google Maps API key (optional — for rich reverse geocoding)
_GMAPS_KEY = ""  # set via set_gmaps_key()

# Simple place-type mapping from Google Places types
_PLACE_TYPE_MAP = {
    "gym": "gym", "health": "gym",
    "university": "college", "school": "college", "library": "college",
    "restaurant": "restaurant", "food": "restaurant", "cafe": "restaurant",
    "bar": "bar", "night_club": "bar",
    "hospital": "hospital", "doctor": "hospital", "pharmacy": "hospital",
    "shopping_mall": "mall", "store": "mall", "supermarket": "mall",
    "park": "park", "amusement_park": "park",
    "airport": "airport", "transit_station": "transit",
    "lodging": "hotel", "spa": "spa",
    "movie_theater": "cinema",
    "bank": "bank", "atm": "bank",
    "gas_station": "petrol station",
    "place_of_worship": "temple",
    "home": "home",  # user-labeled SSID
}

_LABELS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "location_labels.json")
_REFRESH_SEC = 300  # 5 min


# ── Label management ──────────────────────────────────────────

def _load_labels() -> dict:
    try:
        with open(_LABELS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_labels(labels: dict):
    with open(_LABELS_FILE, "w") as f:
        json.dump(labels, f, indent=2)


def label_ssid(ssid: str, label: str):
    labels = _load_labels()
    labels[ssid] = label
    _save_labels(labels)
    with _lock:
        if _cache["ssid"] == ssid:
            _cache["label"] = label


# ── Data sources ──────────────────────────────────────────────

def _get_wifi_ssid() -> str:
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        r = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=5, creationflags=flags
        )
        for line in r.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip()
    except Exception:
        pass
    return ""


def _get_ip_location() -> dict:
    try:
        import requests
        r = requests.get("http://ip-api.com/json/?fields=status,city,lat,lon,country",
                         timeout=5)
        d = r.json()
        if d.get("status") == "success":
            return {
                "city":    d.get("city", ""),
                "lat":     d.get("lat", 0.0),
                "lon":     d.get("lon", 0.0),
                "country": d.get("country", ""),
            }
    except Exception:
        pass
    return {"city": "", "lat": 0.0, "lon": 0.0, "country": ""}


# ── Public API ────────────────────────────────────────────────

def get_location() -> dict:
    with _lock:
        return dict(_cache)


def refresh():
    ssid   = _get_wifi_ssid()
    labels = _load_labels()
    label  = labels.get(ssid, "")
    ip_loc = _get_ip_location()
    with _lock:
        _cache.update({"ssid": ssid, "label": label, **ip_loc})
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "location_update", **get_location()})
    except Exception:
        pass


_running = False
_watch_thread: threading.Thread | None = None


def is_running() -> bool:
    return _running


def _watch_loop():
    global _running
    while _running:
        time.sleep(_REFRESH_SEC)
        if _running:
            refresh()
    print("[LOCATION] Engine stopped.")


def start():
    global _running, _watch_thread
    if _running:
        return  # already running
    _running = True
    refresh()  # immediate first read
    _watch_thread = threading.Thread(target=_watch_loop, daemon=True, name="LocationEngine")
    _watch_thread.start()
    print("[LOCATION] Engine started.")


def stop():
    global _running
    _running = False
    print("[LOCATION] Engine stopping…")


# ── Phone GPS companion ───────────────────────────────────────

def set_gmaps_key(key: str):
    global _GMAPS_KEY
    _GMAPS_KEY = key


def _reverse_geocode(lat: float, lon: float) -> dict:
    """
    Reverse-geocode lat/lon → place name + place type.
    Uses Google Maps Geocoding API if key set, else Nominatim (free, no key).
    Returns {"place_name": str, "place_type": str}
    """
    place_name = ""
    place_type = ""
    try:
        import requests as _req
        if _GMAPS_KEY:
            # Google Maps Geocoding API
            r = _req.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{lat},{lon}", "key": _GMAPS_KEY},
                timeout=6,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    place_name = results[0].get("formatted_address", "")
                    types = results[0].get("types", [])
                    for t in types:
                        if t in _PLACE_TYPE_MAP:
                            place_type = _PLACE_TYPE_MAP[t]
                            break
        else:
            # Nominatim (OpenStreetMap) — no key needed
            r = _req.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json"},
                headers={"User-Agent": "iZACH/1.4"},
                timeout=6,
            )
            if r.status_code == 200:
                d = r.json()
                addr = d.get("address", {})
                # Build a short readable name
                parts = [
                    addr.get("amenity") or addr.get("shop") or addr.get("building") or "",
                    addr.get("suburb") or addr.get("neighbourhood") or addr.get("city_district") or "",
                    addr.get("city") or addr.get("town") or addr.get("village") or "",
                ]
                place_name = ", ".join(p for p in parts if p) or d.get("display_name", "")
                # Infer type from Nominatim category
                cat = d.get("category", "")
                node = d.get("type", "")
                raw_type = f"{cat}_{node}"
                place_type = _infer_nominatim_type(addr, cat, node)
    except Exception:
        pass
    return {"place_name": place_name, "place_type": place_type}


def _infer_nominatim_type(addr: dict, cat: str, node: str) -> str:
    amenity = addr.get("amenity", "").lower()
    shop    = addr.get("shop", "").lower()
    combined = f"{amenity} {shop} {cat} {node}".lower()
    for kw, label in [
        ("gym", "gym"), ("fitness", "gym"), ("sport", "gym"),
        ("university", "college"), ("college", "college"), ("school", "college"), ("library", "college"),
        ("restaurant", "restaurant"), ("cafe", "restaurant"), ("fast_food", "restaurant"), ("food", "restaurant"),
        ("bar", "bar"), ("pub", "bar"), ("nightclub", "bar"),
        ("hospital", "hospital"), ("clinic", "hospital"), ("pharmacy", "hospital"),
        ("mall", "mall"), ("supermarket", "mall"), ("shop", "mall"),
        ("park", "park"),
        ("airport", "airport"), ("train", "transit"), ("bus", "transit"),
        ("hotel", "hotel"), ("spa", "spa"),
        ("cinema", "cinema"), ("theatre", "cinema"),
        ("bank", "bank"), ("atm", "bank"),
        ("petrol", "petrol station"), ("fuel", "petrol station"),
        ("place_of_worship", "temple"), ("temple", "temple"), ("mosque", "temple"), ("church", "temple"),
        ("home", "home"), ("residential", "home"),
    ]:
        if kw in combined:
            return label
    return ""


def update_phone_location(lat: float, lon: float, accuracy: float = 0.0) -> dict:
    """
    Called by /location/phone-ping endpoint.
    Updates _phone_loc with new GPS data + async reverse geocode.
    """
    global _phone_loc
    with _phone_lock:
        _phone_loc.update({
            "active": True,
            "lat": lat, "lon": lon,
            "accuracy": accuracy,
            "ts": int(time.time()),
        })
    # Async reverse geocode — don't block the HTTP response
    def _geo():
        result = _reverse_geocode(lat, lon)
        with _phone_lock:
            _phone_loc.update(result)
        # Check if place-type changed → announce
        _maybe_announce_location(result.get("place_type", ""), result.get("place_name", ""))
        try:
            from modules.ws_bridge import broadcast
            broadcast({"type": "phone_location", **get_phone_location()})
        except Exception:
            pass
    threading.Thread(target=_geo, daemon=True, name="PhoneGeo").start()
    return {"received": True}


_last_announced_type = ""

def _maybe_announce_location(place_type: str, place_name: str):
    """Announce to user if they arrived somewhere new."""
    global _last_announced_type
    if not place_type or place_type == _last_announced_type:
        return
    _last_announced_type = place_type
    try:
        from modules.ws_bridge import broadcast
        broadcast({"type": "location_announce", "place_type": place_type, "place_name": place_name})
    except Exception:
        pass


def get_phone_location() -> dict:
    with _phone_lock:
        loc = dict(_phone_loc)
    # Mark stale if no ping in 10 min
    if loc["active"] and (time.time() - loc["ts"]) > _PHONE_EXPIRE_SEC:
        loc["active"] = False
        loc["place_type"] = ""
    return loc


def get_location_context() -> str:
    """
    Returns AI-friendly location string combining phone GPS + WiFi SSID label.
    Priority: phone GPS place > SSID label > city.
    """
    phone = get_phone_location()
    pc    = get_location()
    if phone["active"] and phone["place_name"]:
        place  = phone["place_name"]
        ptype  = f" ({phone['place_type']})" if phone["place_type"] else ""
        return f"User is at {place}{ptype}"
    if pc.get("label"):
        return f"User is at {pc['label']} (home WiFi network: {pc['ssid']})"
    if pc.get("city"):
        return f"User is in {pc['city']}, {pc.get('country', '')}"
    return ""


def get_full_location() -> dict:
    """Combined PC + phone location for REST API."""
    return {
        "pc":    get_location(),
        "phone": get_phone_location(),
        "context": get_location_context(),
    }
