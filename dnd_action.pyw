"""
dnd_action.pyw — runs silently (no console window, .pyw extension).
Launched by Windows when user clicks a toast action button.

Handles:
  izach://dnd/action/handle/<id>     → POST /dnd/action/handle/<id>
  izach://dnd/action/busy/<id>       → POST /dnd/action/busy/<id>
  izach://meeting/join/<event_id>    → POST /meeting/join/<event_id>
  izach://meeting/skip/<event_id>    → POST /meeting/skip/<event_id>

Makes a silent HTTP request to iZACH backend, then exits immediately.
"""
import sys
import urllib.request
import urllib.parse


def main():
    if len(sys.argv) < 2:
        return

    arg  = sys.argv[1].strip()
    path = arg.replace("izach://", "").rstrip("/")

    # All actions use POST
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:5050/{path}",
            data=b"",
            method="POST",
        )
        urllib.request.urlopen(req, timeout=6)
    except Exception:
        pass


main()

