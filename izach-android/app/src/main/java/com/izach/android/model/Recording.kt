package com.izach.android.model

data class Recording(
    val name: String,
    val startUrl: String,
    val steps: Int,
    val triggerPhrases: List<String>,
    val scheduleCron: String,
    val createdAt: String
)
