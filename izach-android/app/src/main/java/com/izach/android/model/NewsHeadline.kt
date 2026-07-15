package com.izach.android.model

data class NewsHeadline(
    val title: String,
    val source: String,
    val link: String,
    val published: String
)

data class MarketIndex(
    val label: String,
    val price: Double,
    val change: Double,
    val pct: Double
)
