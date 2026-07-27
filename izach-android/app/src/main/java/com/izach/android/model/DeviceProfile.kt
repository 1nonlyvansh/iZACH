package com.izach.android.model

// A saved PC pairing — lets the phone hold separate connections for Mac and
// Windows iZACH installs and switch between them without re-scanning the QR
// each time. "platform" is cached from the last successful /status call
// against this profile ("mac" / "windows" / "" if never connected).
data class DeviceProfile(
    val id: String,
    val name: String,
    val backendUrl: String,
    val wsHost: String,
    val pairingSecret: String,
    val platform: String = ""
)
