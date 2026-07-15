package com.izach.android.model

data class CalendarEvent(
    val id: String,
    val title: String,
    val startIso: String,   // may be a dateTime or an all-day date
    val allDay: Boolean,
    val link: String = ""
)
