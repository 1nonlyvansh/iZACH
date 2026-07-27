package com.izach.android.model

// A command waiting to run on a specific saved device (Mac or Windows),
// independent of whichever connection is currently active on the phone.
// Order in the stored list IS execution priority — reordering the list
// reorders execution.
data class QueuedCommand(
    val id: String,
    val text: String,
    val targetProfileId: String,
    val targetProfileName: String,
    val addedAt: Long
)
