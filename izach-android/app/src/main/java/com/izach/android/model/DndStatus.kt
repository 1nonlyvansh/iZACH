package com.izach.android.model

data class DndStatus(
    val active: Boolean,
    val reason: String,
    val queueCount: Int,
)
