package com.izach.android

import android.os.Bundle
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.izach.android.databinding.ActivityAddDeviceBinding
import com.izach.android.network.IZACHApi
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject

/**
 * Dedicated "add a new PC" flow — separate from Settings, which edits the
 * connection this phone is currently using. This screen only ever creates a
 * new saved profile; it never touches the active connection, so scanning a
 * second PC here can't accidentally disturb whatever chat session is
 * already live.
 */
class AddDeviceActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAddDeviceBinding
    private lateinit var api: IZACHApi

    private val qrLauncher = registerForActivityResult(ScanContract()) { result ->
        if (result?.contents == null) return@registerForActivityResult
        try {
            val json = JSONObject(result.contents)
            val url = json.getString("backend_url")
            val host = json.getString("ws_host")
            val secret = json.optString("pairing_secret", "")
            promptNameAndSave(url, host, secret)
        } catch (e: Exception) {
            toast("Invalid QR code — not an iZACH QR")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityAddDeviceBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = IZACHApi(this)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            insets
        }

        binding.btnBack.setOnClickListener { finish() }

        binding.btnScanQr.setOnClickListener {
            val options = ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Scan iZACH QR code shown on the new PC")
                .setBeepEnabled(false)
                .setOrientationLocked(false)
                .setCaptureActivity(com.izach.android.ui.QrCaptureActivity::class.java)
            qrLauncher.launch(options)
        }

        binding.btnAddManual.setOnClickListener {
            val url = binding.etManualUrl.text.toString().trim()
            val secret = binding.etManualSecret.text.toString().trim()
            if (url.isBlank()) {
                toast("Enter a backend URL")
                return@setOnClickListener
            }
            val host = url.substringAfter("://").substringBefore(":").substringBefore("/")
            promptNameAndSave(url, host, secret)
        }
    }

    private fun promptNameAndSave(url: String, host: String, secret: String) {
        val input = EditText(this).apply {
            hint = "e.g. Mac or Windows"
            setTextColor(getColor(R.color.text_pri))
        }
        AlertDialog.Builder(this)
            .setTitle("Name this PC")
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("Save") { _, _ ->
                val name = input.text.toString().trim().ifBlank { "My PC" }
                api.addProfileFromScan(url, host, secret, name)
                toast("Added \"$name\"")
                finish()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
