package com.izach.android.model

data class SpotifyStatus(
    val playing: Boolean,
    val title: String,
    val artist: String,
    val device: String,
    val albumArt: String,
    val progress: Int,
    val duration: Int,
    val volume: Int,
    val shuffle: Boolean,
    val repeat: String
)
