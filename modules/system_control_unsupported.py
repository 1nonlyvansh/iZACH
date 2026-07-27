"""Fallback stubs for platforms that are neither Windows nor macOS (e.g. Linux).
Not a target platform for iZACH today — this exists so modules/system_control.py
degrades cleanly instead of raising ImportError if it's ever run there."""

__all__ = [
    "set_volume", "adjust_volume", "mute", "unmute", "set_wifi", "toggle_wifi",
    "get_wifi_signal", "set_theme", "get_battery_health", "get_cpu_temperature",
    "get_firewall_status", "get_update_status", "get_network_devices",
    "eject_drive", "kill_app", "set_process_priority", "schedule_shutdown",
    "schedule_restart", "cancel_shutdown", "_get_drive_map",
    "_get_connected_bluetooth_devices", "adjust_brightness", "set_brightness",
]

_UNSUPPORTED = (False, "This feature isn't supported on this platform yet.")


def set_volume(target): return _UNSUPPORTED
def adjust_volume(delta): return _UNSUPPORTED
def mute(): return _UNSUPPORTED
def unmute(): return _UNSUPPORTED
def set_wifi(enable): return _UNSUPPORTED
def toggle_wifi(): return _UNSUPPORTED
def get_wifi_signal(): return _UNSUPPORTED
def set_theme(mode): return _UNSUPPORTED
def get_battery_health(): return _UNSUPPORTED
def get_cpu_temperature(): return _UNSUPPORTED
def get_firewall_status(): return _UNSUPPORTED
def get_update_status(): return _UNSUPPORTED
def get_network_devices(): return _UNSUPPORTED
def eject_drive(identifier): return _UNSUPPORTED
def kill_app(name): return _UNSUPPORTED
def set_process_priority(app_name, level="high"): return _UNSUPPORTED
def schedule_shutdown(seconds): return _UNSUPPORTED
def schedule_restart(seconds): return _UNSUPPORTED
def cancel_shutdown(): return _UNSUPPORTED
def adjust_brightness(delta): return _UNSUPPORTED
def set_brightness(level): return _UNSUPPORTED
def _get_drive_map(): return {}
def _get_connected_bluetooth_devices(): return set()
