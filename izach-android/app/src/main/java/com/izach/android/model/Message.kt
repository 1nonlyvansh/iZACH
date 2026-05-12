package com.izach.android.model

data class Message(
    val text: String,
    val sender: String,  // "YOU", "iZACH", "system"
    val ts: String = "",
    val epoch: Long = System.currentTimeMillis()
)
