"""Shared browser password vault.

Reads/writes the same browser_passwords.json file Cortex UI's Electron
password-store.cjs uses, so a login saved in one UI is available in the
other. Electron's safeStorage on Windows is DPAPI + AES-256-GCM: a random
AES-256 key is generated once, wrapped with DPAPI, and stored as
`os_crypt.encrypted_key` in Electron's "Local State" file (5-byte "DPAPI"
tag + the DPAPI blob). Each stored secret is `v10` + 12-byte nonce +
AES-GCM ciphertext, base64-encoded. Re-implemented here in pure Python
(pywin32's DPAPI unwrap + `cryptography`'s AESGCM) so no Node/Electron
process is needed to read the vault.
"""
import os
import json
import time
import base64
import datetime

import win32crypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_PATH = os.path.join(_REPO_ROOT, "browser_passwords.json")
WEBAUTHN_FILE = os.path.join(_REPO_ROOT, "browser_webauthn.json")

# Electron's default userData folder is named after package.json's "name"
# (dev) or "productName" (packaged) — both are checked since either may be
# the one actually in use on a given machine.
_LOCAL_STATE_CANDIDATES = [
    os.path.join(os.environ.get("APPDATA", ""), "izach-ui", "Local State"),
    os.path.join(os.environ.get("APPDATA", ""), "iZACH", "Local State"),
]


def _master_key():
    for path in _LOCAL_STATE_CANDIDATES:
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
        enc_key_b64 = (local_state.get("os_crypt") or {}).get("encrypted_key")
        if not enc_key_b64:
            continue
        enc_key = base64.b64decode(enc_key_b64)
        if enc_key[:5] != b"DPAPI":
            continue
        _, key = win32crypt.CryptUnprotectData(enc_key[5:], None, None, None, 0)
        return key
    raise RuntimeError(
        "Could not find Cortex's encryption key. Open Cortex UI at least once "
        "so it generates its encrypted-key file, then try again."
    )


def _decrypt(b64_ciphertext):
    raw = base64.b64decode(b64_ciphertext)
    prefix, nonce, ct = raw[:3], raw[3:15], raw[15:]
    if prefix not in (b"v10", b"v11"):
        raise ValueError(f"Unsupported ciphertext version tag: {prefix!r}")
    return AESGCM(_master_key()).decrypt(nonce, ct, None).decode("utf-8")


def _encrypt(plaintext):
    nonce = os.urandom(12)
    ct = AESGCM(_master_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(b"v10" + nonce + ct).decode("ascii")


def _read_vault():
    try:
        with open(VAULT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_vault(entries):
    with open(VAULT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def list_entries():
    """Metadata only — never returns decrypted passwords for a passive list."""
    return [
        {"id": e["id"], "site": e["site"], "username": e["username"], "createdAt": e.get("createdAt")}
        for e in _read_vault()
    ]


def find_for_site(hostname):
    hostname = (hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not hostname:
        return None
    for e in list_entries():
        site = (e.get("site") or "").lower()
        if site.startswith("www."):
            site = site[4:]
        if site and (site in hostname or hostname in site):
            return e
    return None


def reveal(entry_id):
    """Decrypts on an explicit reveal/fill action only — caller must have
    already run a local confirmation gate (e.g. Windows Hello) first."""
    entry = next((e for e in _read_vault() if e["id"] == entry_id), None)
    if not entry:
        raise KeyError("Entry not found.")
    return entry["username"], _decrypt(entry["password"])


def add(site, username, password):
    entries = _read_vault()
    entry_id = "pw" + format(int(time.time() * 1000), "x") + os.urandom(3).hex()
    entries.append({
        "id": entry_id,
        "site": site.strip(),
        "username": username.strip(),
        "password": _encrypt(password),
        "createdAt": datetime.datetime.utcnow().isoformat() + "Z",
    })
    _write_vault(entries)
    return entry_id


def remove(entry_id):
    _write_vault([e for e in _read_vault() if e["id"] != entry_id])


def is_webauthn_enrolled():
    try:
        with open(WEBAUTHN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("credentialId")
    except Exception:
        return None
