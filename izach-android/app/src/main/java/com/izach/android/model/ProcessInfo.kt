package com.izach.android.model

data class ProcessInfo(
    val pid: Int,
    val name: String,
    val cpu: Float,
    val memoryMb: Float
)
