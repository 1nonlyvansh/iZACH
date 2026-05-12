import json
import threading
import asyncio
import time as _time

_clients = set()           # all connected WS clients
_extension_clients = set() # only chrome extension clients
_android_clients: dict = {}  # ws -> device_name
_loop = None

async def _handler(ws):
    _clients.add(ws)
    identified = False
    android_device_name = None

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
                        android_device_name = data.get("device_name", "Android")
                        _android_clients[ws] = android_device_name
                        identified = True
                        print(f"[WS] Android device connected: {android_device_name}")
                        _broadcast_nowait({"type": "device_connected", "device_name": android_device_name})

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
        if android_device_name:
            _android_clients.pop(ws, None)
            print(f"[WS] Android device disconnected: {android_device_name}")
            _broadcast_nowait({"type": "device_disconnected", "device_name": android_device_name})
        elif identified:
            print("[WS] Chrome extension disconnected.")


async def _server():
    try:
        from websockets.asyncio.server import serve
        async with serve(_handler, "0.0.0.0", 5051):
            print("[WS] Bridge running on port 5051")
            await asyncio.Future()
    except OSError as e:
        print(f"[WS] Port 5051 busy, retrying in 3s: {e}")
        await asyncio.sleep(3)
        await _server()
    except Exception as e:
        print(f"[WS] Bridge error: {e}")


def start_ws_bridge():
    global _loop
    if _loop and _loop.is_running():
        return
    _loop = asyncio.new_event_loop()
    t = threading.Thread(target=_loop.run_until_complete, args=(_server(),), daemon=True)
    t.start()


def has_clients() -> bool:
    return bool(_clients)

def get_android_devices() -> list:
    return list(_android_clients.values())

def _broadcast_nowait(event: dict):
    if not _loop or not _clients:
        return
    try:
        msg = json.dumps(event)
        asyncio.run_coroutine_threadsafe(_broadcast_all(msg), _loop)
    except Exception:
        pass

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
    except Exception:
        pass


def emit(event: str, source: str, payload: dict):
    """Broadcast standardized event envelope used by all new features."""
    broadcast({
        "event": event,
        "source": source,
        "timestamp": int(_time.time()),
        "payload": payload,
    })

async def _broadcast_all(msg: str):
    global _clients, _extension_clients
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead
    _extension_clients -= dead
