package com.izach.android.model

data class WaThreadMessage(
    val id: String,
    val sender: String,
    val number: String,
    val text: String,
    val timestamp: Long,
    val chat: String,
    val fromMe: Boolean = false
)

/** One row in the recent-chats list — the latest message per contact. */
data class WaChatSummary(
    val name: String,
    val number: String,
    val lastText: String,
    val timestamp: Long
)
