import json
import threading
import asyncio

_clients = set()
_loop = None

async def _handler(ws):
    _clients.add(ws)
    
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
                if data.get("type") == "command":
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

async def _server():
    try:
        from websockets.asyncio.server import serve
        async with serve(_handler, "127.0.0.1", 5051):
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

def broadcast(event: dict):
    if not _loop or not _clients:
        return
    try:
        msg = json.dumps(event)
        try:
            future = asyncio.run_coroutine_threadsafe(_broadcast_all(msg), _loop)
            future.result(timeout=0.2)
        except Exception:
            pass
    except Exception:
        pass

async def _broadcast_all(msg: str):
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients -= dead