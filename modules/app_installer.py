"""
app_installer.py
Registry-based app detection + official installer download for iZACH.
"""

import os
import re
import winreg
import platform
import subprocess
import threading
from pathlib import Path

# ── Windows info ───────────────────────────────────────────────

def get_windows_info() -> dict:
    ver_str = platform.version()          # e.g. "10.0.26200"
    build = 0
    try:
        build = int(ver_str.split(".")[-1])
    except Exception:
        pass
    is_64 = platform.machine().endswith("64")
    return {
        "version": "11" if build >= 22000 else "10",
        "build":   build,
        "arch":    "x64" if is_64 else "x86",
    }


# ── Registry scanner ───────────────────────────────────────────

_REGISTRY_PATHS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]
_installed_cache: set | None = None
_cache_lock = threading.Lock()


def _scan_registry() -> set:
    names: set = set()
    for hive, path in _REGISTRY_PATHS:
        try:
            with winreg.OpenKey(hive, path) as key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, sub) as sk:
                            try:
                                dn, _ = winreg.QueryValueEx(sk, "DisplayName")
                                if dn and isinstance(dn, str):
                                    names.add(dn.strip().lower())
                            except FileNotFoundError:
                                pass
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass
    return names


def get_installed_apps(refresh: bool = False) -> set:
    global _installed_cache
    with _cache_lock:
        if _installed_cache is None or refresh:
            _installed_cache = _scan_registry()
    return _installed_cache


# Built-in Windows apps — never offer to install these
_ALWAYS_INSTALLED = {
    "notepad", "paint", "calculator", "camera", "photos", "edge",
    "microsoft edge", "windows media player", "file explorer", "explorer",
    "cmd", "command prompt", "powershell", "task manager", "control panel",
    "settings", "microsoft store", "store", "snipping tool", "clock",
    "weather", "maps", "mail", "wordpad", "cortana", "search",
    "xbox", "xbox game bar", "your phone", "phone link", "calendar",
}

# Normalized app name → list of registry display name patterns
_APP_ALIASES: dict[str, list[str]] = {
    "chrome":          ["google chrome"],
    "firefox":         ["mozilla firefox"],
    "vscode":          ["visual studio code", "microsoft visual studio code"],
    "vs code":         ["visual studio code", "microsoft visual studio code"],
    "visual studio code": ["visual studio code", "microsoft visual studio code"],
    "vlc":             ["vlc media player"],
    "discord":         ["discord"],
    "steam":           ["steam"],
    "spotify":         ["spotify", "spotify music", "spotifyab.spotifymusic"],
    "telegram":        ["telegram desktop", "telegram"],
    "whatsapp":        ["whatsapp"],
    "zoom":            ["zoom"],
    "obs":             ["obs studio"],
    "obs studio":      ["obs studio"],
    "7zip":            ["7-zip"],
    "7-zip":           ["7-zip"],
    "winrar":          ["winrar"],
    "notepad++":       ["notepad++"],
    "git":             ["git", "git for windows"],
    "python":          ["python", "python 3"],
    "nodejs":          ["node.js"],
    "node":            ["node.js"],
    "postman":         ["postman"],
    "bitwarden":       ["bitwarden"],
    "anydesk":         ["anydesk"],
    "teamviewer":      ["teamviewer"],
    "skype":           ["skype"],
    "audacity":        ["audacity"],
    "gimp":            ["gimp"],
    "inkscape":        ["inkscape"],
    "handbrake":       ["handbrake"],
    "ccleaner":        ["ccleaner"],
    "malwarebytes":    ["malwarebytes"],
    "everything":      ["everything"],
    "powertoys":       ["microsoft powertoys", "powertoys"],
    "sharex":          ["sharex"],
    "putty":           ["putty"],
    "notion":          ["notion"],
    "figma":           ["figma"],
    "brave":           ["brave", "brave browser"],
    "docker":          ["docker desktop"],
    "virtualbox":      ["oracle vm virtualbox", "virtualbox"],
    "blender":         ["blender"],
    "pycharm":         ["pycharm community edition", "pycharm professional edition", "pycharm"],
    "android studio":  ["android studio"],
    "java":            ["java", "java se runtime environment", "java se development kit"],
    "adobe reader":    ["adobe acrobat reader", "adobe reader dc"],
    "acrobat":         ["adobe acrobat"],
    "potplayer":       ["potplayer", "daum potplayer"],
    "terminal":        ["windows terminal"],
    "winamp":          ["winamp"],
    "mongodb":         ["mongodb"],
    "mysql":           ["mysql server"],
    "xampp":           ["xampp"],
    "wampserver":      ["wampserver"],
}


def _check_appx(name_lower: str) -> bool:
    """Check if app is installed as an AppX/MSIX (Microsoft Store) package."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-AppxPackage -Name '*{name_lower}*' -ErrorAction SilentlyContinue | Select-Object -First 1 Name"],
            capture_output=True, text=True, timeout=8
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def is_app_installed(name: str) -> bool:
    name_lower = name.lower().strip()
    if name_lower in _ALWAYS_INSTALLED:
        return True

    apps = get_installed_apps()
    # resolve through aliases
    candidates = _APP_ALIASES.get(name_lower, [name_lower])

    for candidate in candidates:
        if candidate in apps:
            return True
        for app in apps:
            if candidate in app:
                return True

    # exe check in common install dirs
    exe_stem = name_lower.replace(" ", "")
    for base in [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("APPDATA", ""),
    ]:
        if base and Path(base, exe_stem + ".exe").exists():
            return True

    # AppX (Microsoft Store) check — covers Spotify, WhatsApp, etc.
    for candidate in candidates:
        if _check_appx(candidate):
            return True

    return False


# ── Installer knowledge base ───────────────────────────────────

def get_installer_info(app_name: str) -> dict | None:
    win = get_windows_info()
    arch = win["arch"]

    db = {
        "chrome":          {"url": "https://dl.google.com/chrome/install/ChromeSetup.exe",          "filename": "ChromeSetup.exe"},
        "firefox":         {"url": f"https://download.mozilla.org/?product=firefox-latest&os=win{'64' if arch=='x64' else '32'}&lang=en-US", "filename": "FirefoxSetup.exe"},
        "vscode":          {"url": f"https://code.visualstudio.com/sha/download?build=stable&os=win32-{'x64' if arch=='x64' else 'ia32'}-user", "filename": "VSCodeSetup.exe"},
        "vs code":         {"url": f"https://code.visualstudio.com/sha/download?build=stable&os=win32-{'x64' if arch=='x64' else 'ia32'}-user", "filename": "VSCodeSetup.exe"},
        "vlc":             {"url": f"https://get.videolan.org/vlc/last/win{'64' if arch=='x64' else '32'}/", "filename": "VLCSetup.exe", "redirect": True},
        "discord":         {"url": "https://discord.com/api/downloads/distributions/app/installers/latest?channel=stable&platform=win&arch=x86", "filename": "DiscordSetup.exe"},
        "steam":           {"url": "https://cdn.akamai.steamstatic.com/client/installer/SteamSetup.exe",    "filename": "SteamSetup.exe"},
        "spotify":         {"url": "https://download.scdn.co/SpotifySetup.exe",                            "filename": "SpotifySetup.exe"},
        "zoom":            {"url": "https://zoom.us/client/latest/ZoomInstallerFull.exe",                  "filename": "ZoomSetup.exe"},
        "telegram":        {"url": "https://telegram.org/dl/desktop/win64" if arch == "x64" else "https://telegram.org/dl/desktop/win", "filename": "TelegramSetup.exe"},
        "whatsapp":        {"url": "https://web.whatsapp.com/desktop/windows/release/x64/WhatsAppSetup.exe", "filename": "WhatsAppSetup.exe"},
        "obs":             {"url": "https://github.com/obsproject/obs-studio/releases/download/30.2.3/OBS-Studio-30.2.3-Windows-Installer.exe", "filename": "OBSStudioSetup.exe"},
        "obs studio":      {"url": "https://github.com/obsproject/obs-studio/releases/download/30.2.3/OBS-Studio-30.2.3-Windows-Installer.exe", "filename": "OBSStudioSetup.exe"},
        "7zip":            {"url": f"https://www.7-zip.org/a/7z2406-{'x64' if arch=='x64' else ''}.exe",  "filename": "7ZipSetup.exe"},
        "7-zip":           {"url": f"https://www.7-zip.org/a/7z2406-{'x64' if arch=='x64' else ''}.exe",  "filename": "7ZipSetup.exe"},
        "winrar":          {"url": f"https://www.win-rar.com/fileadmin/winrar-versions/winrar/winrar-{'x64' if arch=='x64' else 'x32'}-701.exe", "filename": "WinRARSetup.exe"},
        "notepad++":       {"url": f"https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v8.6.8/npp.8.6.8.Installer.{'x64' if arch=='x64' else ''}.exe", "filename": "NotepadPlusPlusSetup.exe"},
        "git":             {"url": f"https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-{'64' if arch=='x64' else '32'}-bit.exe", "filename": "GitSetup.exe"},
        "python":          {"url": f"https://www.python.org/ftp/python/3.12.4/python-3.12.4-{'amd64' if arch=='x64' else ''}.exe", "filename": "PythonSetup.exe"},
        "nodejs":          {"url": f"https://nodejs.org/dist/v20.15.0/node-v20.15.0-x{'64' if arch=='x64' else '86'}.msi", "filename": "NodeJSSetup.msi"},
        "node":            {"url": f"https://nodejs.org/dist/v20.15.0/node-v20.15.0-x{'64' if arch=='x64' else '86'}.msi", "filename": "NodeJSSetup.msi"},
        "postman":         {"url": f"https://dl.pstmn.io/download/latest/win{'64' if arch=='x64' else '32'}", "filename": "PostmanSetup.exe"},
        "bitwarden":       {"url": "https://vault.bitwarden.com/download/?app=desktop&platform=windows", "filename": "BitwardenSetup.exe"},
        "anydesk":         {"url": "https://download.anydesk.com/AnyDesk.exe",                            "filename": "AnyDeskSetup.exe"},
        "teamviewer":      {"url": "https://download.teamviewer.com/download/TeamViewer_Setup.exe",        "filename": "TeamViewerSetup.exe"},
        "skype":           {"url": "https://go.skype.com/windows.desktop.download",                        "filename": "SkypeSetup.exe"},
        "audacity":        {"url": f"https://github.com/audacity/audacity/releases/download/Audacity-3.6.4/audacity-win-3.6.4-{'x64' if arch=='x64' else 'x86'}.exe", "filename": "AudacitySetup.exe"},
        "gimp":            {"url": "https://download.gimp.org/mirror/pub/gimp/v2.10/windows/gimp-2.10.38-setup-3.exe", "filename": "GIMPSetup.exe"},
        "handbrake":       {"url": "https://handbrake.fr/rotation.php?file=HandBrake-1.8.1-x86_64-Win_GUI.exe", "filename": "HandBrakeSetup.exe"},
        "ccleaner":        {"url": "https://download.ccleaner.com/ccsetup627.exe",                         "filename": "CClearerSetup.exe"},
        "malwarebytes":    {"url": "https://downloads.malwarebytes.com/file/mb4_offline",                  "filename": "MalwarebytesSetup.exe"},
        "everything":      {"url": f"https://www.voidtools.com/Everything-1.4.1.1026.{'x64' if arch=='x64' else 'x86'}-Setup.exe", "filename": "EverythingSetup.exe"},
        "powertoys":       {"url": f"https://github.com/microsoft/PowerToys/releases/download/v0.82.1/PowerToysSetup-0.82.1-{'x64' if arch=='x64' else 'x86'}.exe", "filename": "PowerToysSetup.exe"},
        "sharex":          {"url": "https://github.com/ShareX/ShareX/releases/download/v16.1.0/ShareX-16.1.0-setup.exe", "filename": "ShareXSetup.exe"},
        "putty":           {"url": f"https://the.earth.li/~sgtatham/putty/latest/w{'64' if arch=='x64' else '32'}/putty-{'64bit-' if arch=='x64' else ''}0.81-installer.msi", "filename": "PuTTYSetup.msi"},
        "notion":          {"url": "https://www.notion.so/desktop/windows/download",                       "filename": "NotionSetup.exe"},
        "figma":           {"url": "https://desktop.figma.com/win/FigmaSetup.exe",                         "filename": "FigmaSetup.exe"},
        "brave":           {"url": "https://laptop-updates.brave.com/latest/winx64",                       "filename": "BraveBrowserSetup.exe"},
        "docker":          {"url": "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe", "filename": "DockerDesktopInstaller.exe"},
        "virtualbox":      {"url": "https://download.virtualbox.org/virtualbox/7.0.18/VirtualBox-7.0.18-162988-Win.exe", "filename": "VirtualBoxSetup.exe"},
        "blender":         {"url": "https://www.blender.org/download/release/Blender4.2/blender-4.2.0-windows-x64.msi" if arch == "x64" else "", "filename": "BlenderSetup.msi"},
        "pycharm":         {"url": "https://download.jetbrains.com/python/pycharm-community-2024.1.3.exe", "filename": "PyCharmSetup.exe"},
        "potplayer":       {"url": f"https://t1.daumcdn.net/potplayer/PotPlayer/Version/Latest/PotPlayerSetup{'64' if arch=='x64' else ''}.exe", "filename": "PotPlayerSetup.exe"},
        "winamp":          {"url": "https://www.winamp.com/player/latest",                                 "filename": "WinampSetup.exe"},
        "android studio":  {"url": "https://redirector.gvt1.com/edgedl/android/studio/install/2024.1.1.11/android-studio-2024.1.1.11-windows.exe", "filename": "AndroidStudioSetup.exe"},
        "java":            {"url": "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.exe" if arch == "x64" else "", "filename": "JavaJDKSetup.exe"},
        "mongodb":         {"url": "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.11-signed.msi" if arch == "x64" else "", "filename": "MongoDBSetup.msi"},
        "xampp":           {"url": "https://sourceforge.net/projects/xampp/files/XAMPP%20Windows/8.2.12/xampp-windows-x64-8.2.12-0-VS17-installer.exe/download", "filename": "XAMPPSetup.exe"},
        "inkscape":        {"url": "https://inkscape.org/gallery/item/44616/inkscape-1.3.2_2023-11-25_091e20e-x64.exe" if arch == "x64" else "", "filename": "InkscapeSetup.exe"},
        "telegram desktop":{"url": "https://telegram.org/dl/desktop/win64" if arch == "x64" else "https://telegram.org/dl/desktop/win", "filename": "TelegramSetup.exe"},
    }

    return db.get(app_name.lower().strip())


# ── Download installer ─────────────────────────────────────────

def download_installer(app_name: str, speak_fn=None) -> tuple[bool, str]:
    info = get_installer_info(app_name)
    if not info or not info.get("url"):
        return False, f"No installer info for {app_name}. Search manually on Google."

    url      = info["url"]
    filename = info.get("filename") or f"{app_name.replace(' ', '_')}_setup.exe"
    dest     = Path.home() / "Downloads" / filename

    if speak_fn:
        speak_fn(f"Downloading {app_name} installer. I'll tell you when it's ready.")

    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, stream=True, timeout=30, allow_redirects=True, headers=headers)
        r.raise_for_status()

        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        size_mb = downloaded / (1024 * 1024)
        return True, f"{app_name.title()} installer saved to Downloads. {size_mb:.1f} MB. Run it to install."
    except Exception as e:
        return False, f"Download failed: {e}"
