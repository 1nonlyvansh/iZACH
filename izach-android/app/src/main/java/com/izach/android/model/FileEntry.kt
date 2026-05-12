package com.izach.android.model

data class FileEntry(
    val name: String,
    val path: String,   // absolute PC path — never shown in chat UI
    val isDir: Boolean,
    val size: Long = 0L
)
