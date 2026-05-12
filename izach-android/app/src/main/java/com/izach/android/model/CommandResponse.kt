package com.izach.android.model

data class CommandResponse(
    val text: String,
    val action: String? = null,
    val requiresConfirmation: Boolean = false,
    val confirmationToken: String? = null
)
