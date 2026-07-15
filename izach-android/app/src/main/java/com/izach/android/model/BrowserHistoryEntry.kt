package com.izach.android.model

data class BrowserHistoryEntry(
    val id: String,
    val url: String,
    val title: String,
    val device: String,
    val ts: String
)
