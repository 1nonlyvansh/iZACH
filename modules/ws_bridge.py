import json
import threading
import asyncio
import time as _time
import hmac as _hmac
import hashlib as _hashlib

_clients = set()           # all connected WS clients
_extension_clients = set() # only chrome extension clients
_android_clients = set()   # only Android app clients
_loop = None

# ── UI ready notification ─────────────────────────────────────
import threading as _threading
_ui_ready_event = _threading.Event()
_ui_ready_callbacks: list = []


def on_ui_connect(callback):
    """Register a callback fired once when first Electron/React client connects."""
    _ui_ready_callbacks.append(callback)

def _verify_ws_hello_signature(data) -> bool:
    """The WS accept path (port 5051) has no auth of its own — anything that
    connects and sends {"type":"client_hello","name":"android_device"} used
    to be trusted instantly, flipping the desktop's phone-connected indicator
    to "connected" for ANY device on the LAN regardless of pairing. Requires
    the same HMAC-over-secret proof the HTTP /command route already demands,
    just over a fixed "ws_hello|<ts>" message instead of method|path|body."""
    ts = data.get("ts")
    sig = data.get("sig")
    if not ts or not sig:
        return False
    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return False
    if abs(_time.time() - ts_int) > 300:
        return False
    try:
        from modules import ui_api as _uapi
        secret = _uapi._get_or_create_pairing_secret()
    except Exception:
        return False
    if not secret:
        return False
    message = f"ws_hello|{ts}".encode()
    expected = _hmac.new(secret.encode(), message, _hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, sig)


async def _send_state_snapshot(ws):
    try:
        snapshot: dict = {"type": "state_snapshot"}

        try:
            import psutil as _ps
            ram = _ps.virtual_memory()
            snapshot["vitals"] = {
                "cpu": round(_ps.cpu_percent(interval=0.1), 1),
                "ram": round(ram.percent, 1),
            }
        except Exception:
            pass

        try:
            from modules.window_watcher import get_active_window
            snapshot["active_window"] = get_active_window()
        except Exception:
            pass

        try:
            from modules.location_engine import get_location
            snapshot["location"] = get_location()
        except Exception:
            pass

        try:
            from modules.ui_api import _message_log
            snapshot["last_messages"] = _message_log[-5:]
        except Exception:
            pass

        await ws.send(json.dumps(snapshot))
    except Exception:
        pass


async def _handler(ws):
    _clients.add(ws)
    identified = False

    # Fire UI ready on first non-extension connection
    if not _ui_ready_event.is_set():
        _ui_ready_event.set()
        for _cb in _ui_ready_callbacks:
            try:
                _threading.Thread(target=_cb, daemon=True).start()
            except Exception:
                pass

    # Send current state to new client immediately
    await _send_state_snapshot(ws)

    try:
        async for msg in ws:
            try:
                data = json.loads(msg)

                if data.get("type") == "client_hello":
                    if data.get("name") == "chrome_extension":
                        _extension_clients.add(ws)
                        identified = True
                        print("[WS] Chrome extension connected.")
                    elif data.get("name") == "android_device":
                        device_name = data.get("device_name", "Android")
                        if not _verify_ws_hello_signature(data):
                            # Don't add to _android_clients (it would then also
                            # receive every broadcast meant for the paired
                            # phone — DND alerts, notifications, screenshots)
                            # and don't flip the connected indicator.
                            print(f"[WS] Rejected android_device hello (bad/missing pairing signature): {device_name}")
                        else:
                            _android_clients.add(ws)
                            identified = True
                            print(f"[WS] Android device connected: {device_name}")
                            # Update phone status in ui_api
                            try:
                                from modules import ui_api as _uapi
                                _uapi._phone_connected = True
                                if device_name:
                                    _uapi._phone_device_name = device_name
                            except Exception:
                                pass
                            # Broadcast phone_status: connected to cortex-ui (all non-android clients)
                            _broadcast_to_non_android({"type": "phone_status", "connected": True, "device_name": device_name, "qr": None})

                elif data.get("type") == "fill_result":
                    filled = data.get("filled", 0)
                    input_count = data.get("inputCount", -1)
                    from modules.command_chain import _chain_ref
                    if _chain_ref and hasattr(_chain_ref, 'speak'):
                        if filled > 0:
                            _chain_ref.speak(f"Filled {filled} field{'s' if filled != 1 else ''}. Review before submitting.")
                        elif input_count == 0:
                            _chain_ref.speak("No form inputs found on this page. Navigate to a form first, then say fill my details.")
                        else:
                            _chain_ref.speak("Found the form but couldn't match your saved details to the fields. Make sure your profile is saved in memory.")

                elif data.get("type") == "command":
                    from modules.command_chain import _chain_ref
                    if _chain_ref:
                        threading.Thread(
                            target=_chain_ref.process,
                            args=(data["text"],),
                            daemon=True
                        ).start()
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _clients.discard(ws)
        _extension_clients.discard(ws)
        was_android = ws in _android_clients
        _android_clients.discard(ws)
        if was_android:
            device_name = ""
            try:
                from modules import ui_api as _uapi
                device_name = _uapi._phone_device_name
            except Exception:
                pass
            if not _android_clients:
                # Last Android client disconnected
                try:
                    from modules import ui_api as _uapi
                    _uapi._phone_connected = False
                except Exception:
                    pass
                _broadcast_to_non_android({"type": "phone_status", "connected": False, "device_name": device_name, "qr": None})
            print(f"[WS] Android device disconnected: {device_name}")
        elif identified:
            print("[WS] Chrome extension disconnected.")


async def _server():
    while True:
        try:
            from websockets.asyncio.server import serve
            async with serve(_handler, "0.0.0.0", 5051):
                print("[WS] Bridge running on port 5051")
                await asyncio.Future()
        except OSError as e:
            print(f"[WS] Port 5051 busy, retrying in 3s: {e}")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[WS] Bridge error: {e}")
            break


def start_ws_bridge():
    global _loop
    if _loop and _loop.is_running():
        return
    # Silence noisy handshake tracebacks: bare TCP probes (port scanners, a
    # client that connects then drops before the WS upgrade) make the websockets
    # server log a full "did not receive a valid HTTP request" traceback. Benign.
    import logging as _logging
    _logging.getLogger("websockets.server").setLevel(_logging.CRITICAL)
    _loop = asyncio.new_event_loop()
    t = threading.Thread(target=_loop.run_until_complete, args=(_server(),), daemon=True)
    t.start()


def has_clients() -> bool:
    return bool(_clients)

def _broadcast_nowait(event: dict):
    if not _loop or not _clients:
        return
    try:
        msg = json.dumps(event)
        asyncio.run_coroutine_threadsafe(_broadcast_all(msg), _loop)
    except Exception as e:
        print(f"[WS] _broadcast_nowait failed: {e}")

def has_extension_client() -> bool:
    return bool(_extension_clients)

def send_notification(text: str):
    broadcast({"type": "notification", "text": text, "ts": _time.strftime("%H:%M")})

def broadcast(event: dict):
    if not _loop or not _clients:
        return
    try:
        msg = json.dumps(event)
        asyncio.run_coroutine_threadsafe(_broadcast_all(msg), _loop)
    except Exception as e:
        print(f"[WS] broadcast failed: {e}")


def emit(event: str, source: str, payload: dict):
    """Broadcast standardized event envelope used by all new features."""
    broadcast({
        "event": event,
        "source": source,
        "timestamp": int(_time.time()),
        "payload": payload,
    })

async def _broadcast_all(msg: str):
    global _clients, _extension_clients, _android_clients
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead
    _extension_clients -= dead
    _android_clients -= dead


def _broadcast_to_non_android(event: dict):
    """Broadcast to all clients except Android devices (e.g., phone_status events for cortex-ui)."""
    if not _loop or not _clients:
        return
    try:
        msg = json.dumps(event)
        targets = _clients - _android_clients
        if targets:
            asyncio.run_coroutine_threadsafe(_broadcast_subset(msg, targets), _loop)
    except Exception as e:
        print(f"[WS] _broadcast_to_non_android failed: {e}")


async def _broadcast_subset(msg: str, targets: set):
    dead = set()
    for ws in list(targets):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    global _clients, _extension_clients, _android_clients
    _clients -= dead
    _extension_clients -= dead
    _android_clients -= dead
