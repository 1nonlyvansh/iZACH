package com.izach.android.ui

import com.izach.android.R
import com.journeyapps.barcodescanner.CaptureActivity
import com.journeyapps.barcodescanner.DecoratedBarcodeView

/**
 * Only override point needed to get a WhatsApp-style bordered square scan
 * frame everywhere in the app that scans a QR code — points at our own
 * outer/inner layouts (qr_capture_outer.xml → qr_scanner_view_inner.xml)
 * instead of the library's stock ones. ScanOptions.setCaptureActivity(...)
 * targets this class directly; no manifest intent-filter needed for that,
 * just the activity declaration itself.
 */
class QrCaptureActivity : CaptureActivity() {
    override fun initializeContent(): DecoratedBarcodeView {
        setContentView(R.layout.qr_capture_outer)
        return findViewById(R.id.zxing_barcode_scanner)
    }
}
