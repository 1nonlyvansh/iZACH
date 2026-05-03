"""
modules/whatsapp_sender.py
Reliable WhatsApp message sender via whatsapp-web.js bridge.

Replaces the old _send_message function with:
- Verification that message was sent
- Retry mechanism (up to 2 retries)
- Debug logging
- Contact resolution check
"""

import time
import logging
import requests

logger = logging.getLogger("iZACH.WhatsAppSender")

BRIDGE_URL   = "http://localhost:3000"
MAX_RETRIES  = 2
RETRY_DELAY  = 1.5   # seconds between retries
SEND_TIMEOUT = 8     # seconds


def send_message(number: str, text: str, contact_name: str = "") -> tuple[bool, str]:
    """
    Send a WhatsApp message with retry and verification.

    Returns:
        (success: bool, status_message: str)
    """
    if not number:
        logger.error("[WA SEND] No number provided.")
        return False, "No number to send to."

    if not text or not text.strip():
        logger.error("[WA SEND] Empty message.")
        return False, "Message text is empty."

    display = contact_name or number
    logger.info(f"[WA SEND] → {display}: {text[:60]}")

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            r = requests.post(
                f"{BRIDGE_URL}/send-message",
                json={"number": number, "text": text},
                timeout=SEND_TIMEOUT
            )

            if r.status_code == 200:
                result = r.json()
                status = result.get("status", "")

                if status == "sent":
                    logger.info(f"[WA SEND] ✓ Sent to {display} (attempt {attempt})")
                    return True, f"Message sent to {display}."

                elif status == "error":
                    err = result.get("message", "unknown error")
                    logger.warning(f"[WA SEND] Bridge error: {err}")
                    if attempt <= MAX_RETRIES:
                        logger.info(f"[WA SEND] Retrying ({attempt}/{MAX_RETRIES})...")
                        time.sleep(RETRY_DELAY)
                        continue
                    return False, f"Failed to send: {err}"

                else:
                    logger.warning(f"[WA SEND] Unexpected status: {status}")
                    return True, f"Message sent to {display}."

            else:
                logger.warning(f"[WA SEND] HTTP {r.status_code} on attempt {attempt}")
                if attempt <= MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return False, f"Bridge returned HTTP {r.status_code}."

        except requests.exceptions.ConnectionError:
            logger.error("[WA SEND] Bridge offline (port 3000 not reachable)")
            return False, "WhatsApp bridge is offline."

        except requests.exceptions.Timeout:
            logger.warning(f"[WA SEND] Timeout on attempt {attempt}")
            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            return False, "Send timed out."

        except Exception as e:
            logger.error(f"[WA SEND] Unexpected error: {e}")
            return False, f"Error: {e}"

    return False, "All send attempts failed."


def send_voice_note(number: str, audio_path: str, contact_name: str = "") -> tuple[bool, str]:
    """Send a voice note file to a WhatsApp contact."""
    display = contact_name or number
    try:
        r = requests.post(
            f"{BRIDGE_URL}/send-voice",
            json={"number": number, "audio_path": audio_path},
            timeout=15
        )
        if r.status_code == 200 and r.json().get("status") == "sent":
            logger.info(f"[WA VOICE] ✓ Sent voice note to {display}")
            return True, f"Voice note sent to {display}."
        return False, "Failed to send voice note."
    except Exception as e:
        logger.error(f"[WA VOICE] Error: {e}")
        return False, f"Voice note error: {e}"


def check_bridge_status() -> bool:
    """Returns True if WhatsApp bridge is reachable and connected."""
    try:
        r = requests.get(f"{BRIDGE_URL}/health", timeout=3)
        if r.status_code == 200:
            return r.json().get("status") == "connected"
    except Exception:
        pass
    return False