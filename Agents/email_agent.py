"""
Agents/email_agent.py
Lightweight voice/chat command routing for the email agent (modules/email_agent.py).

Unlike calendar_agent.py's full LLM intent parser, this handles a small,
narrow set of fixed intents (order status, email agent status) via regex —
proportionate to the scope, not a general-purpose email command language.
"""
import re

_ORDER_RE = re.compile(
    r"\b(where\W+(?:is|are|s)|track(?:ing)?|status of|any update on)\b.*\b(order|package|parcel|delivery|shipment)\b",
    re.IGNORECASE,
)
_ORDERS_LIST_RE = re.compile(r'\b(my\s+)?(orders|packages|deliveries)\b', re.IGNORECASE)
_STATUS_RE = re.compile(r'\bemail\s*(agent)?\b.*\b(status|connected|enabled)\b', re.IGNORECASE)


def handle(query: str) -> str | None:
    """Returns a spoken reply if this query is email-agent-related, else None
    (caller should fall through to normal handling)."""
    q = query.strip()

    if _ORDER_RE.search(q) or _ORDERS_LIST_RE.search(q):
        from modules.email_agent import get_tracked_orders
        orders = get_tracked_orders()
        if not orders:
            return "No tracked orders yet."
        lines = []
        for o in orders[:5]:
            desc = o.get("description") or "package"
            carrier = o.get("carrier") or ""
            status = (o.get("status") or "").replace("_", " ")
            eta = f", expected {o['delivery_date']}" if o.get("delivery_date") else ""
            lines.append(f"{desc} via {carrier}: {status}{eta}" if carrier else f"{desc}: {status}{eta}")
        return " | ".join(lines)

    if _STATUS_RE.search(q):
        from modules.email_agent import get_auth_status
        status = get_auth_status()
        if status.get("connected"):
            return f"Email agent connected as {status.get('user')}."
        return "Email agent isn't connected — connect it in Settings."

    return None
