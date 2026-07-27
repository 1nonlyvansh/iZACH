package com.izach.android.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import com.journeyapps.barcodescanner.ViewfinderView

/**
 * Stock zxing-android-embedded draws only a dimmed mask with a plain
 * rectangular hole for the scan area — no visible border, no way to turn
 * off the red laser sweep without a subclass. This draws a clean bordered
 * square with rounded corners over the same framing rect the library
 * already computes, closer to how WhatsApp's own linked-device QR scanner
 * looks, and disables the laser line entirely (WhatsApp doesn't have one
 * either — it isn't needed, the camera autofocuses continuously).
 */
class QrViewfinderView(context: Context, attrs: AttributeSet?) : ViewfinderView(context, attrs) {

    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 6f
        color = Color.parseColor("#FF00E5FF") // iZACH cyan
    }
    private val cornerRadius = 24f

    init {
        setLaserVisibility(false)
        setMaskColor(Color.parseColor("#B0050D1A")) // iZACH bg_deep, ~69% opaque
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val rect = framingRect ?: return
        canvas.drawRoundRect(RectF(rect), cornerRadius, cornerRadius, borderPaint)
    }
}
