"""
modules/smart_home_engine.py
iZACH Smart Home Control — Phase 4

Supports:
  1. Google SDM API  — Nest Thermostat (AC): temp, mode, fan, status
  2. pychromecast    — Google TV / Chromecast: on/off, volume, play/pause, cast

Setup:
  • pip install google-auth google-auth-oauthlib requests pychromecast
  • Download smart_home_credentials.json from Google Cloud Console
    (enable "Smart Device Management API", create OAuth2 Desktop client)
  • Put Project ID from SDM console into smart_home_settings.json
"""

import os
import json
import time
import logging
import re
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("iZACH.SmartHome")

_BASE_DIR     = os.path.dirname(os.path.dirname(__file__))
_TOKEN_FILE   = os.path.join(_BASE_DIR, "smart_home_token.json")
_CREDS_FILE   = os.path.join(_BASE_DIR, "smart_home_credentials.json")
_SETTINGS_FILE = os.path.join(_BASE_DIR, "smart_home_settings.json")

_SCOPES = ["https://www.googleapis.com/auth/sdm.service"]
_SDM_BASE = "https://smartdevicemanagement.googleapis.com/v1"

_settings: dict = {}
_creds    = None
_auth_state = {"status": "not_connected", "error": ""}
_pending_flow = None

# Device cache: {device_id: {...}}
_device_cache: dict = {}
_cache_ts: float = 0
_CACHE_TTL = 120  # 2 min


# =============================================================================
# Settings
# =============================================================================

def _load_settings() -> dict:
    global _settings
    try:
        with open(_SETTINGS_FILE) as f:
            _settings = json.load(f)
    except FileNotFoundError:
        _settings = {"project_id": "", "cast_friendly_name": ""}
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(_settings, f, indent=2)
    return _settings


def get_settings() -> dict:
    if not _settings:
        _load_settings()
    return dict(_settings)


def update_settings(updates: dict) -> dict:
    global _settings
    if not _settings:
        _load_settings()
    _settings.update(updates)
    with open(_SETTINGS_FILE, "w") as f:
        json.dump(_settings, f, indent=2)
    return dict(_settings)


# =============================================================================
# OAuth2 — SDM API
# =============================================================================

def _save_token(creds):
    try:
        with open(_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    except Exception as e:
        logger.error(f"[SMARTHOME] Save token: {e}")


def _get_credentials():
    global _creds, _auth_state
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if _creds and _creds.valid:
            return _creds

        if os.path.exists(_TOKEN_FILE):
            _creds = Credentials.from_authorized_user_file(_TOKEN_FILE, _SCOPES)
            if _creds and _creds.expired and _creds.refresh_token:
                _creds.refresh(Request())
                _save_token(_creds)
            if _creds and _creds.valid:
                _auth_state["status"] = "connected"
                return _creds

        _auth_state["status"] = "not_connected"
        return None
    except ImportError:
        _auth_state["status"] = "missing_deps"
        _auth_state["error"] = "Run: pip install google-auth google-auth-oauthlib"
        return None
    except Exception as e:
        _auth_state["status"] = "error"
        _auth_state["error"] = str(e)
        return None


def start_auth_flow() -> dict:
    global _pending_flow
    if not os.path.exists(_CREDS_FILE):
        return {
            "error": (
                "smart_home_credentials.json not found. "
                "Go to Google Cloud Console → Smart Device Management API → "
                "Credentials → Create OAuth2 Desktop client → Download JSON → "
                "save as smart_home_credentials.json"
            )
        }
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(_CREDS_FILE, _SCOPES)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(
            prompt="consent",
            access_type="offline",
        )
        _pending_flow = flow
        return {
            "url": auth_url,
            "instructions": (
                "Open URL in browser → sign in → allow → copy the code. "
                "Then POST to /smarthome/auth/complete with {\"code\": \"...\"}"
            ),
        }
    except ImportError:
        return {"error": "Run: pip install google-auth-oauthlib"}
    except Exception as e:
        return {"error": str(e)}


def complete_auth(code: str) -> dict:
    global _creds, _pending_flow, _auth_state
    if not _pending_flow:
        return {"error": "No pending flow. Call /smarthome/auth/start first."}
    try:
        _pending_flow.fetch_token(code=code.strip())
        _creds = _pending_flow.credentials
        _save_token(_creds)
        _auth_state = {"status": "connected", "error": ""}
        _pending_flow = None
        return {"success": True, "message": "Google Smart Home connected!"}
    except Exception as e:
        return {"error": str(e)}


def disconnect() -> dict:
    global _creds, _auth_state
    _creds = None
    _auth_state = {"status": "not_connected", "error": ""}
    try:
        if os.path.exists(_TOKEN_FILE):
            os.remove(_TOKEN_FILE)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


def get_auth_status() -> dict:
    c = _get_credentials()
    return {
        "status":      "connected" if (c and c.valid) else _auth_state.get("status", "not_connected"),
        "token_valid": bool(c and c.valid),
        "error":       _auth_state.get("error", ""),
    }


# =============================================================================
# SDM Device discovery
# =============================================================================

def _sdm_get(path: str) -> Optional[dict]:
    c = _get_credentials()
    if not c:
        return None
    try:
        import requests as _req
        r = _req.get(
            f"{_SDM_BASE}/{path}",
            headers={"Authorization": f"Bearer {c.token}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        logger.debug(f"[SMARTHOME] GET {path} → {r.status_code}: {r.text[:120]}")
        return None
    except Exception as e:
        logger.debug(f"[SMARTHOME] GET {path}: {e}")
        return None


def _sdm_post(path: str, body: dict) -> Optional[dict]:
    c = _get_credentials()
    if not c:
        return None
    try:
        import requests as _req
        r = _req.post(
            f"{_SDM_BASE}/{path}",
            json=body,
            headers={"Authorization": f"Bearer {c.token}", "Content-Type": "application/json"},
            timeout=10,
        )
        if r.status_code in (200, 201):
            return r.json() if r.text else {}
        logger.debug(f"[SMARTHOME] POST {path} → {r.status_code}: {r.text[:120]}")
        return None
    except Exception as e:
        logger.debug(f"[SMARTHOME] POST {path}: {e}")
        return None


def _device_type_label(dtype: str) -> str:
    MAP = {
        "sdm.devices.types.THERMOSTAT":  "Thermostat",
        "sdm.devices.types.DISPLAY":     "Display",
        "sdm.devices.types.CAMERA":      "Camera",
        "sdm.devices.types.DOORBELL":    "Doorbell",
        "sdm.devices.types.SPEAKER":     "Speaker",
    }
    return MAP.get(dtype, dtype.split(".")[-1].title())


def list_sdm_devices(force: bool = False) -> list[dict]:
    """List all Nest/SDM devices with traits summary."""
    global _device_cache, _cache_ts
    if not force and time.time() - _cache_ts < _CACHE_TTL and _device_cache:
        return list(_device_cache.values())

    s = get_settings()
    project_id = s.get("project_id", "").strip()
    if not project_id:
        return []

    data = _sdm_get(f"enterprises/{project_id}/devices")
    if not data:
        return []

    devices = []
    for d in data.get("devices", []):
        device_id = d.get("name", "").split("/")[-1]
        dtype     = d.get("type", "")
        traits    = d.get("traits", {})
        info      = traits.get("sdm.devices.traits.Info", {})
        conn      = traits.get("sdm.devices.traits.Connectivity", {})
        temp_trait = traits.get("sdm.devices.traits.Temperature", {})
        humid_trait = traits.get("sdm.devices.traits.Humidity", {})
        mode_trait  = traits.get("sdm.devices.traits.ThermostatMode", {})
        sp_trait    = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
        eco_trait   = traits.get("sdm.devices.traits.ThermostatEco", {})

        device = {
            "id":           device_id,
            "full_name":    d.get("name", ""),
            "type":         _device_type_label(dtype),
            "raw_type":     dtype,
            "label":        info.get("customName", device_id[:8]),
            "online":       conn.get("status", "") == "ONLINE",
            "status":       conn.get("status", "UNKNOWN"),
            "current_temp": round(temp_trait.get("ambientTemperatureCelsius", 0), 1),
            "humidity":     round(humid_trait.get("ambientHumidityPercent", 0), 1),
            "mode":         mode_trait.get("mode", ""),
            "available_modes": mode_trait.get("availableModes", []),
            "cool_setpoint": round(sp_trait.get("coolCelsius", 0), 1),
            "heat_setpoint": round(sp_trait.get("heatCelsius", 0), 1),
            "eco_mode":     eco_trait.get("mode", ""),
        }
        devices.append(device)
        _device_cache[device_id] = device

    _cache_ts = time.time()
    return devices


# =============================================================================
# SDM Commands — Thermostat / AC
# =============================================================================

def set_temperature(device_id: str, temp_c: float, mode: str = "COOL") -> dict:
    """
    Set thermostat temperature setpoint.
    mode: "COOL" | "HEAT"
    temp_c: target temperature in Celsius
    """
    s = get_settings()
    project_id = s.get("project_id", "").strip()
    if not project_id:
        return {"success": False, "error": "project_id not configured"}

    cmd_map = {
        "COOL": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool",
        "HEAT": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat",
    }
    param_map = {
        "COOL": "coolCelsius",
        "HEAT": "heatCelsius",
    }
    mode_upper = mode.upper()
    command = cmd_map.get(mode_upper, cmd_map["COOL"])
    param   = param_map.get(mode_upper, param_map["COOL"])

    path = f"enterprises/{project_id}/devices/{device_id}:executeCommand"
    result = _sdm_post(path, {"command": command, "params": {param: float(temp_c)}})
    if result is not None:
        _cache_ts = 0  # invalidate cache
        return {"success": True, "message": f"Temperature set to {temp_c}°C ({mode_upper})"}
    return {"success": False, "error": "Command failed — check device ID and connection"}


def set_thermostat_mode(device_id: str, mode: str) -> dict:
    """
    Set thermostat operating mode.
    mode: "COOL" | "HEAT" | "HEATCOOL" | "OFF"
    """
    s = get_settings()
    project_id = s.get("project_id", "").strip()
    if not project_id:
        return {"success": False, "error": "project_id not configured"}

    valid_modes = {"COOL", "HEAT", "HEATCOOL", "OFF"}
    mode_upper = mode.upper()
    if mode_upper not in valid_modes:
        return {"success": False, "error": f"Invalid mode. Use: {', '.join(valid_modes)}"}

    path   = f"enterprises/{project_id}/devices/{device_id}:executeCommand"
    result = _sdm_post(path, {
        "command": "sdm.devices.commands.ThermostatMode.SetMode",
        "params":  {"mode": mode_upper},
    })
    if result is not None:
        _cache_ts = 0
        labels = {"COOL": "cooling", "HEAT": "heating", "HEATCOOL": "auto", "OFF": "off"}
        return {"success": True, "message": f"AC set to {labels.get(mode_upper, mode_upper)}"}
    return {"success": False, "error": "Command failed"}


def set_fan_timer(device_id: str, duration_sec: int = 900) -> dict:
    """Start fan for given duration (seconds). Default 15 min."""
    s = get_settings()
    project_id = s.get("project_id", "").strip()
    if not project_id:
        return {"success": False, "error": "project_id not configured"}

    path   = f"enterprises/{project_id}/devices/{device_id}:executeCommand"
    result = _sdm_post(path, {
        "command": "sdm.devices.commands.Fan.SetTimer",
        "params":  {"timerMode": "ON", "duration": f"{duration_sec}s"},
    })
    if result is not None:
        _cache_ts = 0
        return {"success": True, "message": f"Fan running for {duration_sec // 60} min"}
    return {"success": False, "error": "Command failed"}


def stop_fan(device_id: str) -> dict:
    s = get_settings()
    project_id = s.get("project_id", "").strip()
    if not project_id:
        return {"success": False, "error": "project_id not configured"}

    path   = f"enterprises/{project_id}/devices/{device_id}:executeCommand"
    result = _sdm_post(path, {
        "command": "sdm.devices.commands.Fan.SetTimer",
        "params":  {"timerMode": "OFF"},
    })
    if result is not None:
        _cache_ts = 0
        return {"success": True, "message": "Fan stopped"}
    return {"success": False, "error": "Command failed"}


# =============================================================================
# Chromecast / Google TV
# =============================================================================

_cast_device  = None
_cast_lock    = threading.Lock()


def _get_cast(friendly_name: str = "") -> Optional[object]:
    global _cast_device
    try:
        import pychromecast
        with _cast_lock:
            if _cast_device and not friendly_name:
                return _cast_device
            chromecasts, browser = pychromecast.get_listed_chromecasts(
                friendly_names=[friendly_name] if friendly_name else None,
                timeout=5,
            )
            pychromecast.discovery.stop_discovery(browser)
            if not chromecasts:
                return None
            cast = chromecasts[0]
            cast.wait(timeout=5)
            _cast_device = cast
            return cast
    except ImportError:
        logger.warning("[SMARTHOME] pychromecast not installed: pip install pychromecast")
        return None
    except Exception as e:
        logger.debug(f"[SMARTHOME] Chromecast discovery: {e}")
        return None


def list_cast_devices() -> list[dict]:
    try:
        import pychromecast
        chromecasts, browser = pychromecast.get_chromecasts(timeout=6)
        pychromecast.discovery.stop_discovery(browser)
        result = []
        for cc in chromecasts:
            result.append({
                "name":       cc.name,
                "model":      cc.model_name,
                "host":       cc.host,
                "status":     "online",
                "is_idle":    cc.status.is_idle if cc.status else True,
                "volume":     round((cc.status.volume_level or 0) * 100) if cc.status else 0,
                "is_muted":   cc.status.volume_muted if cc.status else False,
            })
        return result
    except ImportError:
        return []
    except Exception as e:
        logger.debug(f"[SMARTHOME] list_cast_devices: {e}")
        return []


def cast_play_pause(friendly_name: str = "") -> dict:
    cast = _get_cast(friendly_name or get_settings().get("cast_friendly_name", ""))
    if not cast:
        return {"success": False, "error": "No Chromecast found"}
    try:
        mc = cast.media_controller
        if mc.status and mc.status.player_is_playing:
            mc.pause()
            return {"success": True, "message": "Paused"}
        else:
            mc.play()
            return {"success": True, "message": "Playing"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cast_volume(level: float, friendly_name: str = "") -> dict:
    """Set volume 0.0–1.0"""
    cast = _get_cast(friendly_name or get_settings().get("cast_friendly_name", ""))
    if not cast:
        return {"success": False, "error": "No Chromecast found"}
    try:
        cast.set_volume(max(0.0, min(1.0, level)))
        return {"success": True, "message": f"Volume set to {int(level * 100)}%"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cast_volume_up(step: float = 0.1, friendly_name: str = "") -> dict:
    cast = _get_cast(friendly_name or get_settings().get("cast_friendly_name", ""))
    if not cast:
        return {"success": False, "error": "No Chromecast found"}
    try:
        current = cast.status.volume_level if cast.status else 0.5
        cast.set_volume(min(1.0, current + step))
        return {"success": True, "message": f"Volume up to {int(min(1.0, current + step) * 100)}%"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cast_volume_down(step: float = 0.1, friendly_name: str = "") -> dict:
    cast = _get_cast(friendly_name or get_settings().get("cast_friendly_name", ""))
    if not cast:
        return {"success": False, "error": "No Chromecast found"}
    try:
        current = cast.status.volume_level if cast.status else 0.5
        cast.set_volume(max(0.0, current - step))
        return {"success": True, "message": f"Volume down to {int(max(0.0, current - step) * 100)}%"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cast_mute_toggle(friendly_name: str = "") -> dict:
    cast = _get_cast(friendly_name or get_settings().get("cast_friendly_name", ""))
    if not cast:
        return {"success": False, "error": "No Chromecast found"}
    try:
        muted = cast.status.volume_muted if cast.status else False
        cast.set_volume_muted(not muted)
        return {"success": True, "message": "Unmuted" if muted else "Muted"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cast_stop(friendly_name: str = "") -> dict:
    cast = _get_cast(friendly_name or get_settings().get("cast_friendly_name", ""))
    if not cast:
        return {"success": False, "error": "No Chromecast found"}
    try:
        cast.media_controller.stop()
        return {"success": True, "message": "Playback stopped"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cast_media_url(url: str, title: str = "", content_type: str = "video/mp4",
                   friendly_name: str = "") -> dict:
    """Cast a direct media URL to Chromecast."""
    cast = _get_cast(friendly_name or get_settings().get("cast_friendly_name", ""))
    if not cast:
        return {"success": False, "error": "No Chromecast found"}
    try:
        cast.media_controller.play_media(url, content_type, title=title)
        cast.media_controller.block_until_active(timeout=10)
        return {"success": True, "message": f"Casting: {title or url[:40]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Unified command dispatcher (called from command_chain / voice)
# =============================================================================

def execute_voice_command(command: str, context: dict = None) -> dict:
    """
    Parse natural-language smart home command and execute it.
    Returns {success, message, action}.
    """
    import re
    cmd = command.lower().strip()
    ctx = context or {}

    # ── AC / Thermostat ──────────────────────────────────────────
    # Set temperature: "set ac to 22", "set temperature 24 degrees", "24 degrees cool"
    temp_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:degrees?|°|celsius|°c)?', cmd)
    if temp_match and any(k in cmd for k in ("temperature", "temp", "degree", "ac to", "cool to", "heat to", "set to")):
        temp = float(temp_match.group(1))
        mode = "HEAT" if "heat" in cmd else "COOL"
        devices = list_sdm_devices()
        thermostats = [d for d in devices if "THERMOSTAT" in d.get("raw_type", "")]
        if thermostats:
            dev_id = ctx.get("device_id") or thermostats[0]["id"]
            result = set_temperature(dev_id, temp, mode)
            result["action"] = "set_temperature"
            return result
        return {"success": False, "error": "No thermostat found", "action": "set_temperature"}

    # Mode: "turn off ac", "set ac to cool", "heat mode", "auto mode"
    if any(k in cmd for k in ("turn off ac", "switch off ac", "ac off", "stop ac")):
        devices = list_sdm_devices()
        thermostats = [d for d in devices if "THERMOSTAT" in d.get("raw_type", "")]
        if thermostats:
            dev_id = ctx.get("device_id") or thermostats[0]["id"]
            result = set_thermostat_mode(dev_id, "OFF")
            result["action"] = "ac_off"
            return result
        return {"success": False, "error": "No thermostat found", "action": "ac_off"}

    if any(k in cmd for k in ("turn on ac", "switch on ac", "ac on", "start ac", "cool mode")):
        devices = list_sdm_devices()
        thermostats = [d for d in devices if "THERMOSTAT" in d.get("raw_type", "")]
        if thermostats:
            dev_id = ctx.get("device_id") or thermostats[0]["id"]
            mode = "HEAT" if "heat" in cmd else "COOL"
            result = set_thermostat_mode(dev_id, mode)
            result["action"] = "ac_on"
            return result
        return {"success": False, "error": "No thermostat found", "action": "ac_on"}

    # Fan
    fan_dur_match = re.search(r'fan.*?(\d+)\s*(?:min|minute)', cmd)
    if "fan" in cmd:
        devices = list_sdm_devices()
        thermostats = [d for d in devices if "THERMOSTAT" in d.get("raw_type", "")]
        if thermostats:
            dev_id = ctx.get("device_id") or thermostats[0]["id"]
            if "off" in cmd or "stop" in cmd:
                result = stop_fan(dev_id)
            else:
                dur = int(fan_dur_match.group(1)) * 60 if fan_dur_match else 900
                result = set_fan_timer(dev_id, dur)
            result["action"] = "fan_control"
            return result

    # ── TV / Chromecast ──────────────────────────────────────────
    fn = ctx.get("cast_name") or get_settings().get("cast_friendly_name", "")

    if any(k in cmd for k in ("pause", "resume", "play")):
        result = cast_play_pause(fn)
        result["action"] = "cast_play_pause"
        return result

    if any(k in cmd for k in ("stop tv", "stop video", "stop casting")):
        result = cast_stop(fn)
        result["action"] = "cast_stop"
        return result

    if "mute" in cmd:
        result = cast_mute_toggle(fn)
        result["action"] = "cast_mute"
        return result

    vol_match = re.search(r'volume\s*(?:to\s*)?(\d+)', cmd)
    if vol_match:
        vol = int(vol_match.group(1))
        result = cast_volume(vol / 100.0, fn)
        result["action"] = "cast_volume"
        return result

    if "volume up" in cmd or "louder" in cmd:
        result = cast_volume_up(friendly_name=fn)
        result["action"] = "cast_volume_up"
        return result

    if "volume down" in cmd or "quieter" in cmd or "lower volume" in cmd:
        result = cast_volume_down(friendly_name=fn)
        result["action"] = "cast_volume_down"
        return result

    return {"success": False, "error": "Command not recognized", "action": "unknown"}


# =============================================================================
# Samsung SmartThings — REST API (free, Personal Access Token)
# =============================================================================

_ST_BASE = "https://api.smartthings.com/v1"


def _st_headers() -> dict:
    # Prefer env var; fall back to settings file (legacy)
    token = (
        os.getenv("SMARTTHINGS_TOKEN", "")
        or get_settings().get("smartthings_token", "")
    ).strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _st_get(path: str) -> Optional[dict]:
    hdrs = _st_headers()
    if not hdrs:
        return None
    try:
        import requests as _req
        r = _req.get(f"{_ST_BASE}/{path}", headers=hdrs, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.debug(f"[SMARTHOME/ST] GET {path}: {e}")
        return None


def _st_post(path: str, body: dict) -> Optional[dict]:
    hdrs = _st_headers()
    if not hdrs:
        return None
    try:
        import requests as _req
        r = _req.post(f"{_ST_BASE}/{path}", json=body, headers=hdrs, timeout=10)
        return r.json() if r.status_code in (200, 201, 204) else None
    except Exception as e:
        logger.debug(f"[SMARTHOME/ST] POST {path}: {e}")
        return None


def list_smartthings_devices() -> list[dict]:
    """List all SmartThings devices with status summary."""
    token = get_settings().get("smartthings_token", "").strip()
    if not token:
        logger.debug("[SMARTHOME] No SmartThings token configured.")
        return []
    data = _st_get("devices")
    if not data:
        logger.warning("[SMARTHOME] _st_get('devices') returned empty — check token or quota.")
        return []

    raw_items = data.get("items", [])
    logger.info(f"[SMARTHOME] SmartThings returned {len(raw_items)} raw devices.")

    # Skip these noise device types
    _SKIP_TYPES = {"LightSensor", "MobilePresence"}

    devices = []
    for d in raw_items:
        device_id   = d.get("deviceId", "")
        label       = d.get("label", d.get("name", device_id[:10]))
        device_type = d.get("deviceTypeName", "")
        components  = d.get("components", [])

        # Collect all capabilities across all components
        capabilities = []
        # Collect manufacturer category names
        mfr_cats = []
        for comp in components:
            for cap in comp.get("capabilities", []):
                capabilities.append(cap.get("id", ""))
            for cat in comp.get("categories", []):
                mfr_cats.append(cat.get("name", ""))

        # Skip noise devices
        if any(c in _SKIP_TYPES for c in mfr_cats):
            continue
        if d.get("type") == "MOBILE":
            continue

        # Debug: log every device so user can see why AC is/isn't detected
        logger.info(
            f"[SMARTHOME] dev: label={label!r}  type={device_type!r}  "
            f"mfr_cats={mfr_cats}  caps={capabilities[:6]}{'…' if len(capabilities)>6 else ''}"
        )

        # Category — use manufacturer categories first (most accurate)
        category = "other"
        mfr_lower = [c.lower() for c in mfr_cats]
        label_low = label.lower()
        type_low  = device_type.lower()

        # AC detection — broaden coverage for Samsung Bespoke / WindFree / etc.
        if "airconditioner" in mfr_lower:
            category = "ac"
        elif "television" in mfr_lower:
            category = "tv"
        elif "thermostat" in mfr_lower:
            category = "ac"
        # Capability-based fallback (Samsung AC always exposes airConditionerMode)
        elif "airConditionerMode" in capabilities or "airConditionerFanMode" in capabilities:
            category = "ac"
        elif "samsungce.airConditionerOptionalMode" in capabilities:
            category = "ac"
        elif "tvChannel" in capabilities or "audioVolume" in capabilities:
            category = "tv"
        # Device-type fallback — Samsung deviceTypeName e.g. "Samsung OCF Air Conditioner"
        elif "air" in type_low and ("condition" in type_low or "ac" in type_low):
            category = "ac"
        elif "tv" in type_low or "television" in type_low:
            category = "tv"
        # Label keyword fallback (last resort, word-boundary)
        elif re.search(r'\b(ac|hvac|aircon|air[\s\-_]?conditioner|climate)\b', label_low):
            category = "ac"
        elif re.search(r'\b(tv|television)\b', label_low):
            category = "tv"

        devices.append({
            "id":           device_id,
            "label":        label,
            "type":         device_type,
            "category":     category,
            "capabilities": capabilities,
            "mfr_cats":     mfr_cats,
            "online":       True,
        })
    return devices


def get_smartthings_device_status(device_id: str) -> dict:
    """Fetch live status of a SmartThings device (AC or TV)."""
    data = _st_get(f"devices/{device_id}/status")
    if not data:
        return {}
    main = data.get("components", {}).get("main", {})
    result = {}

    def _val(cap, key):
        return main.get(cap, {}).get(key, {}).get("value")

    # ── Common ──────────────────────────────────────────
    power = _val("switch", "switch")
    if power is not None:
        result["power"] = power  # "on" / "off"

    # ── AC-specific ──────────────────────────────────────
    ac_mode = _val("airConditionerMode", "airConditionerMode")
    if ac_mode:
        result["ac_mode"] = ac_mode

    th_mode = _val("thermostatMode", "thermostatMode")
    if th_mode:
        result["thermostat_mode"] = th_mode

    cool_sp = main.get("thermostatCoolingSetpoint", {}).get("coolingSetpoint", {})
    if cool_sp:
        result["cool_setpoint"] = cool_sp.get("value", 0)
        result["temp_unit"]     = cool_sp.get("unit", "C")

    heat_sp = main.get("thermostatHeatingSetpoint", {}).get("heatingSetpoint", {})
    if heat_sp:
        result["heat_setpoint"] = heat_sp.get("value", 0)

    temp = main.get("temperatureMeasurement", {}).get("temperature", {})
    if temp:
        result["current_temp"] = temp.get("value", 0)
        result["temp_unit"]    = temp.get("unit", "C")

    fan = _val("airConditionerFanMode", "fanMode")
    if fan:
        result["fan_speed"] = fan

    fan_mode = _val("thermostatFanMode", "thermostatFanMode")
    if fan_mode:
        result["fan_mode"] = fan_mode

    humidity = _val("relativeHumidityMeasurement", "humidity")
    if humidity is not None:
        result["humidity"] = humidity

    # ── TV-specific ──────────────────────────────────────
    volume = _val("audioVolume", "volume")
    if volume is not None:
        result["volume"] = volume

    muted = _val("audioMute", "mute")
    if muted is not None:
        result["muted"] = muted  # "muted" / "unmuted"

    channel = _val("tvChannel", "tvChannel")
    if channel is not None:
        result["channel"] = channel

    channel_name = _val("tvChannel", "tvChannelName")
    if channel_name:
        result["channel_name"] = channel_name

    playback = _val("mediaPlayback", "playbackStatus")
    if playback:
        result["playback"] = playback  # "playing" / "paused" / "stopped"

    return result


def smartthings_command(device_id: str, capability: str, command: str,
                         args: list = None, component: str = "main") -> dict:
    """Send any command to a SmartThings device."""
    body = {
        "commands": [{
            "component":  component,
            "capability": capability,
            "command":    command,
            "arguments":  args or [],
        }]
    }
    result = _st_post(f"devices/{device_id}/commands", body)
    if result is not None:
        return {"success": True, "message": f"{command} sent"}
    return {"success": False, "error": "Command failed — check token and device ID"}


# ── SmartThings AC convenience wrappers ──────────────────────────────────────

def st_ac_on(device_id: str) -> dict:
    return smartthings_command(device_id, "switch", "on")

def st_ac_off(device_id: str) -> dict:
    return smartthings_command(device_id, "switch", "off")

def st_ac_set_temp(device_id: str, temp_c: float, mode: str = "cool") -> dict:
    """Set AC temperature. mode: cool | heat"""
    if mode.lower() == "heat":
        return smartthings_command(device_id, "thermostatHeatingSetpoint",
                                    "setHeatingSetpoint", [temp_c])
    return smartthings_command(device_id, "thermostatCoolingSetpoint",
                                "setCoolingSetpoint", [temp_c])

def st_ac_set_mode(device_id: str, mode: str) -> dict:
    """
    mode options:
      airConditionerMode: cool | heat | auto | dry | wind | fanOnly
      thermostatMode:     cool | heat | auto | off
    """
    mode_l = mode.lower()
    # Try Samsung AC mode first, fall back to thermostat mode
    result = smartthings_command(device_id, "airConditionerMode",
                                  "setAirConditionerMode", [mode_l])
    if not result.get("success"):
        result = smartthings_command(device_id, "thermostatMode",
                                      "setThermostatMode", [mode_l])
    result["message"] = f"AC mode → {mode_l}"
    return result

def st_ac_set_fan_speed(device_id: str, speed: str) -> dict:
    """speed: auto | low | medium | high | turbo"""
    speed_l = speed.lower()
    result = smartthings_command(device_id, "airConditionerFanMode",
                                  "setFanMode", [speed_l])
    if not result.get("success"):
        result = smartthings_command(device_id, "thermostatFanMode",
                                      "setThermostatFanMode", [speed_l])
    result["message"] = f"Fan speed → {speed_l}"
    return result


# =============================================================================
# Samsung TV — SmartThings cloud control (primary)
# =============================================================================

def st_tv_on(device_id: str) -> dict:
    r = smartthings_command(device_id, "switch", "on")
    r["message"] = "TV turned on"
    return r

def st_tv_off(device_id: str) -> dict:
    r = smartthings_command(device_id, "switch", "off")
    r["message"] = "TV turned off"
    return r

def st_tv_volume_up(device_id: str) -> dict:
    r = smartthings_command(device_id, "audioVolume", "volumeUp")
    r["message"] = "Volume up"
    return r

def st_tv_volume_down(device_id: str) -> dict:
    r = smartthings_command(device_id, "audioVolume", "volumeDown")
    r["message"] = "Volume down"
    return r

def st_tv_set_volume(device_id: str, level: int) -> dict:
    """level: 0–100"""
    level = max(0, min(100, int(level)))
    r = smartthings_command(device_id, "audioVolume", "setVolume", [level])
    r["message"] = f"Volume → {level}"
    return r

def st_tv_mute(device_id: str) -> dict:
    r = smartthings_command(device_id, "audioMute", "mute")
    r["message"] = "TV muted"
    return r

def st_tv_unmute(device_id: str) -> dict:
    r = smartthings_command(device_id, "audioMute", "unmute")
    r["message"] = "TV unmuted"
    return r

def st_tv_mute_toggle(device_id: str) -> dict:
    """Toggle mute by checking current status."""
    status = get_smartthings_device_status(device_id)
    muted  = status.get("muted", "unmuted") == "muted"
    if muted:
        return st_tv_unmute(device_id)
    return st_tv_mute(device_id)

def st_tv_set_channel(device_id: str, channel: str) -> dict:
    """channel: channel number as string e.g. '5'"""
    r = smartthings_command(device_id, "tvChannel", "setTvChannel", [str(channel)])
    r["message"] = f"Channel → {channel}"
    return r

def st_tv_channel_up(device_id: str) -> dict:
    r = smartthings_command(device_id, "tvChannel", "channelUp")
    r["message"] = "Channel up"
    return r

def st_tv_channel_down(device_id: str) -> dict:
    r = smartthings_command(device_id, "tvChannel", "channelDown")
    r["message"] = "Channel down"
    return r

def st_tv_play(device_id: str) -> dict:
    r = smartthings_command(device_id, "mediaPlayback", "play")
    r["message"] = "Playing"
    return r

def st_tv_pause(device_id: str) -> dict:
    r = smartthings_command(device_id, "mediaPlayback", "pause")
    r["message"] = "Paused"
    return r

def st_tv_stop(device_id: str) -> dict:
    r = smartthings_command(device_id, "mediaPlayback", "stop")
    r["message"] = "Stopped"
    return r

def st_tv_launch_app(device_id: str, app_id: str) -> dict:
    """
    Common Samsung app IDs:
      Netflix:  11101200001
      YouTube:  111299001912
      Prime:    3201512006785
      Disney+:  3201907018807
      Hotstar:  3201601007230
    """
    r = smartthings_command(device_id, "custom.launchapp", "launchApp", [app_id])
    r["message"] = f"Launching app {app_id}"
    return r

# Known Samsung app IDs
SAMSUNG_APPS = {
    "netflix":    "11101200001",
    "youtube":    "111299001912",
    "prime":      "3201512006785",
    "amazon":     "3201512006785",
    "disney":     "3201907018807",
    "hotstar":    "3201601007230",
    "zee5":       "3201806016034",
    "sonyliv":    "3201606009684",
    "jio":        "3201606009684",
}

def st_tv_launch_app_by_name(device_id: str, app_name: str) -> dict:
    app_id = SAMSUNG_APPS.get(app_name.lower().strip())
    if not app_id:
        return {"success": False, "error": f"Unknown app '{app_name}'. Known: {', '.join(SAMSUNG_APPS)}"}
    return st_tv_launch_app(device_id, app_id)


# =============================================================================
# Samsung TV — direct local WebSocket via samsungtvws (fallback for key presses)
# =============================================================================

def _get_samsung_tv(ip: str = ""):
    tv_ip = ip or get_settings().get("samsung_tv_ip", "").strip()
    if not tv_ip:
        return None, "No Samsung TV IP configured"
    try:
        from samsungtvws import SamsungTVWS
        tv = SamsungTVWS(host=tv_ip, timeout=5)
        return tv, None
    except ImportError:
        return None, "Run: pip install samsungtvws"
    except Exception as e:
        return None, str(e)


def samsung_tv_send_key(key: str, ip: str = "") -> dict:
    """Send any Samsung TV key. e.g. KEY_VOLUMEUP, KEY_MUTE, KEY_POWER"""
    tv, err = _get_samsung_tv(ip)
    if not tv:
        return {"success": False, "error": err}
    try:
        tv.send_key(key)
        return {"success": True, "message": f"Key sent: {key}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def samsung_tv_power(ip: str = "") -> dict:
    return samsung_tv_send_key("KEY_POWER", ip)

def samsung_tv_volume_up(ip: str = "") -> dict:
    return samsung_tv_send_key("KEY_VOLUMEUP", ip)

def samsung_tv_volume_down(ip: str = "") -> dict:
    return samsung_tv_send_key("KEY_VOLUMEDOWN", ip)

def samsung_tv_mute(ip: str = "") -> dict:
    return samsung_tv_send_key("KEY_MUTE", ip)

def samsung_tv_channel_up(ip: str = "") -> dict:
    return samsung_tv_send_key("KEY_CHUP", ip)

def samsung_tv_channel_down(ip: str = "") -> dict:
    return samsung_tv_send_key("KEY_CHDOWN", ip)

def samsung_tv_set_channel(channel: int, ip: str = "") -> dict:
    """Dial channel number digit by digit."""
    tv, err = _get_samsung_tv(ip)
    if not tv:
        return {"success": False, "error": err}
    try:
        for digit in str(channel):
            tv.send_key(f"KEY_{digit}")
            time.sleep(0.3)
        tv.send_key("KEY_ENTER")
        return {"success": True, "message": f"Channel → {channel}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def samsung_tv_get_info(ip: str = "") -> dict:
    """Get basic TV info (model, name) — works without auth."""
    tv_ip = ip or get_settings().get("samsung_tv_ip", "").strip()
    if not tv_ip:
        return {"error": "No Samsung TV IP configured"}
    try:
        import requests as _req
        r = _req.get(f"http://{tv_ip}:8001/api/v2/", timeout=4)
        if r.status_code == 200:
            d = r.json()
            device = d.get("device", {})
            return {
                "name":        device.get("name", "Samsung TV"),
                "model":       device.get("modelName", ""),
                "ip":          tv_ip,
                "wlan_mac":    device.get("wifiMac", ""),
                "os_version":  device.get("OS", ""),
                "connected":   True,
            }
    except Exception as e:
        logger.debug(f"[SMARTHOME/TV] info: {e}")
    return {"ip": tv_ip, "connected": False, "error": "Cannot reach TV"}


# Samsung TV key map for common actions
_TV_KEY_MAP = {
    "home":       "KEY_HOME",
    "back":       "KEY_RETURN",
    "menu":       "KEY_MENU",
    "settings":   "KEY_MENU",
    "source":     "KEY_SOURCE",
    "info":       "KEY_INFO",
    "guide":      "KEY_GUIDE",
    "up":         "KEY_UP",
    "down":       "KEY_DOWN",
    "left":       "KEY_LEFT",
    "right":      "KEY_RIGHT",
    "enter":      "KEY_ENTER",
    "ok":         "KEY_ENTER",
    "play":       "KEY_PLAY",
    "pause":      "KEY_PAUSE",
    "stop":       "KEY_STOP",
    "rewind":     "KEY_REWIND",
    "forward":    "KEY_FF",
    "next":       "KEY_FF",
    "previous":   "KEY_REWIND",
    "hdmi1":      "KEY_HDMI1",
    "hdmi2":      "KEY_HDMI2",
    "hdmi":       "KEY_HDMI1",
    "netflix":    "KEY_NETFLIX",
    "youtube":    "KEY_YOUTUBE",
    "amazon":     "KEY_PRIME_VIDEO",
}


# =============================================================================
# Extended voice command dispatcher (Samsung + Google)
# =============================================================================

def execute_voice_command(command: str, context: dict = None) -> dict:
    """
    Parse natural-language smart home command and execute it.
    Handles: Samsung AC (SmartThings), Samsung TV (direct), Google Chromecast, Nest SDM.
    """
    import re
    cmd = command.lower().strip()
    ctx = context or {}
    fn  = ctx.get("cast_name") or get_settings().get("cast_friendly_name", "")

    s = get_settings()

    # ── Samsung AC (SmartThings) ─────────────────────────────────
    _has_st  = bool(s.get("smartthings_token", "").strip())
    _st_devs = []
    if _has_st:
        _st_devs = [d for d in list_smartthings_devices() if d["category"] == "ac"]

    def _st_ac_id():
        return ctx.get("st_device_id") or (_st_devs[0]["id"] if _st_devs else "")

    # Normalize brand-prefixed AC/TV: "turn off samsung ac" → "turn off ac"
    _brand_re = re.compile(
        r'\b(samsung|lg|panasonic|daikin|hitachi|voltas|carrier|whirlpool|haier|'
        r'sony|toshiba|sharp|mitsubishi|midea|tcl|hisense|oneplus|mi|xiaomi)\s+',
        re.IGNORECASE,
    )
    cmd_normalized = _brand_re.sub('', cmd).strip()

    # Turn on AC
    if any(k in cmd_normalized for k in ("turn on ac", "ac on", "start ac", "switch on ac", "on karo ac")):
        dev = _st_ac_id()
        if dev:
            r = st_ac_on(dev); r["action"] = "ac_on"; return r
        return {"success": False, "error": "No AC in SmartThings", "action": "ac_on"}

    # Turn off AC
    if any(k in cmd_normalized for k in ("turn off ac", "ac off", "stop ac", "switch off ac", "band karo ac")):
        dev = _st_ac_id()
        if dev:
            r = st_ac_off(dev); r["action"] = "ac_off"; return r
        return {"success": False, "error": "No AC in SmartThings", "action": "ac_off"}

    # Set temperature
    temp_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:degrees?|°|celsius|°c)?', cmd_normalized)
    if temp_m and any(k in cmd_normalized for k in ("temperature", "temp", "degree", "ac to", "cool to", "heat to", "set to", "set ac")):
        temp  = float(temp_m.group(1))
        mode  = "heat" if "heat" in cmd_normalized else "cool"
        dev   = _st_ac_id()
        if dev:
            r = st_ac_set_temp(dev, temp, mode); r["action"] = "set_temperature"; return r
        # Fallback to SDM
        devices = list_sdm_devices()
        therms = [d for d in devices if "THERMOSTAT" in d.get("raw_type", "")]
        if therms:
            r = set_temperature(therms[0]["id"], temp, mode.upper())
            r["action"] = "set_temperature"; return r
        return {"success": False, "error": "No AC device found", "action": "set_temperature"}

    # AC mode
    _ac_mode_map = {
        "cool mode":   "cool", "cooling":      "cool",
        "heat mode":   "heat", "heating":      "heat",
        "auto mode":   "auto", "dry mode":     "dry",
        "fan mode":    "wind", "fan only":     "wind",
    }
    for phrase, mode in _ac_mode_map.items():
        if phrase in cmd:
            dev = _st_ac_id()
            if dev:
                r = st_ac_set_mode(dev, mode); r["action"] = "ac_mode"; return r

    # Fan speed
    _fan_speed_map = {
        "fan low":     "low",  "low speed":   "low",
        "fan medium":  "medium", "medium speed": "medium",
        "fan high":    "high", "high speed":  "high",
        "fan auto":    "auto", "fan turbo":   "turbo",
        "turbo mode":  "turbo",
    }
    for phrase, speed in _fan_speed_map.items():
        if phrase in cmd:
            dev = _st_ac_id()
            if dev:
                r = st_ac_set_fan_speed(dev, speed); r["action"] = "fan_speed"; return r

    # ── Samsung TV (SmartThings cloud — primary; local WebSocket fallback) ────
    # Find TV device from SmartThings
    _st_tvs = [d for d in list_smartthings_devices() if d["category"] == "tv"] if _has_st else []

    def _st_tv_id():
        return ctx.get("st_tv_id") or (_st_tvs[0]["id"] if _st_tvs else "")

    if "tv" in cmd_normalized or "television" in cmd_normalized or "channel" in cmd_normalized or "tv" in cmd:
        tv_id = _st_tv_id()

        if any(k in cmd_normalized for k in ("turn off tv", "tv off", "switch off tv", "band karo tv")):
            if tv_id:
                r = st_tv_off(tv_id); r["action"] = "tv_off"; return r

        if any(k in cmd_normalized for k in ("turn on tv", "tv on", "switch on tv", "chalo tv")):
            if tv_id:
                r = st_tv_on(tv_id); r["action"] = "tv_on"; return r

        if "volume up" in cmd or "tv louder" in cmd:
            if tv_id:
                r = st_tv_volume_up(tv_id); r["action"] = "tv_vol_up"; return r

        if "volume down" in cmd or "tv quieter" in cmd:
            if tv_id:
                r = st_tv_volume_down(tv_id); r["action"] = "tv_vol_down"; return r

        vol_tv_m = re.search(r'(?:tv|television).*volume\s*(?:to\s*)?(\d+)|volume\s*(?:to\s*)?(\d+).*(?:tv|television)', cmd)
        if vol_tv_m:
            vol = int(vol_tv_m.group(1) or vol_tv_m.group(2))
            if tv_id:
                r = st_tv_set_volume(tv_id, vol); r["action"] = "tv_vol_set"; return r

        if "mute" in cmd and "tv" in cmd:
            if tv_id:
                r = st_tv_mute_toggle(tv_id); r["action"] = "tv_mute"; return r

        ch_m = re.search(r'channel\s*(\d+)', cmd)
        if ch_m:
            if tv_id:
                r = st_tv_set_channel(tv_id, ch_m.group(1)); r["action"] = "tv_channel"; return r

        if "channel up" in cmd or "next channel" in cmd:
            if tv_id:
                r = st_tv_channel_up(tv_id); r["action"] = "tv_ch_up"; return r

        if "channel down" in cmd or "previous channel" in cmd:
            if tv_id:
                r = st_tv_channel_down(tv_id); r["action"] = "tv_ch_down"; return r

        if "pause tv" in cmd or "pause the tv" in cmd:
            if tv_id:
                r = st_tv_pause(tv_id); r["action"] = "tv_pause"; return r

        if "play tv" in cmd or "resume tv" in cmd:
            if tv_id:
                r = st_tv_play(tv_id); r["action"] = "tv_play"; return r

        # App launch
        for app_name in SAMSUNG_APPS:
            if app_name in cmd:
                if tv_id:
                    r = st_tv_launch_app_by_name(tv_id, app_name)
                    r["action"] = "tv_app"; return r

        # Fallback: local WebSocket key presses (needs samsung_tv_ip set)
        tv_ip = ctx.get("tv_ip", "") or s.get("samsung_tv_ip", "")
        if tv_ip:
            for phrase, key in _TV_KEY_MAP.items():
                if phrase in cmd:
                    r = samsung_tv_send_key(key, tv_ip)
                    r["action"] = "tv_key"; return r

    # ── Google Chromecast fallback ───────────────────────────────
    if any(k in cmd for k in ("pause", "resume", "play media", "stop casting")):
        if "stop" in cmd:
            r = cast_stop(fn); r["action"] = "cast_stop"; return r
        r = cast_play_pause(fn); r["action"] = "cast_play_pause"; return r

    if "cast mute" in cmd or ("mute" in cmd and "tv" not in cmd):
        r = cast_mute_toggle(fn); r["action"] = "cast_mute"; return r

    vol_m = re.search(r'volume\s*(?:to\s*)?(\d+)', cmd)
    if vol_m and "tv" not in cmd:
        r = cast_volume(int(vol_m.group(1)) / 100.0, fn)
        r["action"] = "cast_volume"; return r

    if "cast volume up" in cmd or ("louder" in cmd and "tv" not in cmd):
        r = cast_volume_up(friendly_name=fn); r["action"] = "cast_volume_up"; return r

    if "cast volume down" in cmd or ("quieter" in cmd and "tv" not in cmd):
        r = cast_volume_down(friendly_name=fn); r["action"] = "cast_volume_down"; return r

    # ── Nest SDM fallback (if connected) ────────────────────────
    if temp_m and not _has_st:
        temp  = float(temp_m.group(1))
        mode  = "HEAT" if "heat" in cmd else "COOL"
        devs  = list_sdm_devices()
        therms = [d for d in devs if "THERMOSTAT" in d.get("raw_type", "")]
        if therms:
            r = set_temperature(therms[0]["id"], temp, mode)
            r["action"] = "set_temperature"; return r

    return {"success": False, "error": "Command not recognized", "action": "unknown"}


# =============================================================================
# Unified status
# =============================================================================

def get_all_status() -> dict:
    s = get_settings()
    creds_ok = bool(_get_credentials())

    # SmartThings — list devices, fetch live status for TV + AC
    st_devices = []
    st_tv_status = {}
    if s.get("smartthings_token"):
        try:
            st_devices = list_smartthings_devices()
            # Fetch live TV status if found
            tvs = [d for d in st_devices if d["category"] == "tv"]
            if tvs:
                try:
                    tv_status = get_smartthings_device_status(tvs[0]["id"])
                    tvs[0].update(tv_status)  # merge status into device dict
                    st_tv_status = tv_status
                except Exception:
                    pass
        except Exception:
            pass

    # Local Samsung TV info (only if IP configured and no ST TV found)
    tv_info = {}
    if s.get("samsung_tv_ip"):
        tv_info = samsung_tv_get_info()
    # Merge ST TV status into tv_info if richer
    if st_tv_status:
        tv_info.update(st_tv_status)
        tv_info["connected"] = True

    return {
        "sdm": {
            "connected": creds_ok,
            "status":    _auth_state.get("status", "not_connected"),
            "devices":   list_sdm_devices() if creds_ok else [],
        },
        "cast": {
            "devices": list_cast_devices(),
        },
        "samsung_tv": tv_info,
        "smartthings": {
            "connected": bool(s.get("smartthings_token")),
            "devices":   st_devices,
        },
        "settings": s,
    }


# =============================================================================
# Init
# =============================================================================

def init():
    _load_settings()
    _get_credentials()
    logger.info(f"[SMARTHOME] Engine ready. SDM: {_auth_state['status']}")


try:
    init()
except Exception as _sh_init_err:
    logger.warning(f"[SMARTHOME] Module-level init() failed: {_sh_init_err}")
