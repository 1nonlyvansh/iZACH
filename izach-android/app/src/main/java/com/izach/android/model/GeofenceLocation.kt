package com.izach.android.model

data class GeofenceLocation(
    val id: String,
    val name: String,
    val lat: Double,
    val lng: Double,
    val radius: Float,
    val arriveCommand: String,
    val leaveCommand: String,
    val enabled: Boolean = true
)
