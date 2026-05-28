"""
dnd_action.pyw — runs silently (no console window, .pyw extension).
Launched by Windows when user clicks a toast action button.

Handles:
  izach://dnd/action/handle/<id>     → /dnd/action/handle/<id>
  izach://dnd/action/busy/<id>       → /dnd/action/busy/<id>

Makes a silent HTTP GET to iZACH backend, then exits immediately.
"""
import sys
import urllib.request
import urllib.error


def main():
    if len(sys.argv) < 2:
        return

    arg  = sys.argv[1].strip()
    # Strip scheme
    path = arg.replace("izach://", "").rstrip("/")

    try:
        url = f"http://127.0.0.1:5050/{path}"
        urllib.request.urlopen(url, timeout=6)
    except Exception:
        pass


main()
