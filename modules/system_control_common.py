"""Pure helpers with no platform-specific OS calls, imported directly by both
system_control_windows.py and system_control_mac.py (kept separate from
modules/system_control.py itself to avoid a circular import — the platform
modules are imported BY system_control.py, so they can't import back from it)."""


def _get_local_subnet():
    """Return subnet prefix e.g. '192.168.0' from local IP."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ".".join(ip.split(".")[:3])
    except Exception:
        return None
