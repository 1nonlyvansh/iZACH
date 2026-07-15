package com.izach.android.model

data class SystemStatus(
    val cpu: Float,
    val ram: Float,
    val gpu: Float,
    val procCpu: Float,
    val procMem: Float,
    val ramUsedGb: Float,
    val ramTotalGb: Float,
    val whatsapp: Boolean,
    val mma: Boolean,
    val pcName: String = "",
    val batteryPct: Int? = null,
    val batteryPlugged: Boolean? = null
)
