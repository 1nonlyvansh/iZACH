package com.izach.android.model

data class DndAlert(
    val id: Int,
    val from: String,
    val number: String,
    val text: String,
    val type: String,         // "whatsapp_message" | "phone_call"
    val ts: Long,
    val action: String?,      // null | "handle" | "busy" | "unattended"
    val isPriority: Boolean = false,
)
