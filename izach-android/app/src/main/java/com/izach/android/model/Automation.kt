package com.izach.android.model

data class Automation(
    val id: String,
    val content: String,
    val enabled: Boolean,
    val created: String,
    val cron: String = ""
)

data class SchedulerJob(
    val id: String,
    val nextRun: String
)
