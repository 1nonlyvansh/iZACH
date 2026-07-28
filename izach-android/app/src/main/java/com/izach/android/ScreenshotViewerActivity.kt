package com.izach.android

import android.content.ContentValues
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.izach.android.databinding.ActivityScreenshotBinding
import androidx.lifecycle.lifecycleScope
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream

class ScreenshotViewerActivity : AppCompatActivity() {

    private lateinit var binding: ActivityScreenshotBinding
    private lateinit var api: IZACHApi
    private var filename: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityScreenshotBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.ssTopBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)
        filename = intent.getStringExtra("filename") ?: ""

        binding.btnBack.setOnClickListener { finish() }

        binding.btnSave.setOnClickListener {
            if (filename.isNotEmpty()) downloadScreenshot()
        }

        binding.btnShare.setOnClickListener {
            if (filename.isNotEmpty()) shareScreenshot()
        }

        if (filename.isNotEmpty()) loadImage()
    }

    private fun loadImage() {
        binding.progressImage.visibility = View.VISIBLE
        lifecycleScope.launch {
            try {
                val bytes = api.screenshotImageBytes(filename)
                if (bytes == null) {
                    binding.progressImage.visibility = View.GONE
                    Toast.makeText(this@ScreenshotViewerActivity, "Load failed — not paired or file missing", Toast.LENGTH_SHORT).show()
                    return@launch
                }
                val bmp = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                binding.progressImage.visibility = View.GONE
                if (bmp == null) {
                    Toast.makeText(this@ScreenshotViewerActivity, "Load failed — bad image data", Toast.LENGTH_SHORT).show()
                } else {
                    binding.ivScreenshot.setImageBitmap(bmp)
                }
            } catch (e: Exception) {
                binding.progressImage.visibility = View.GONE
                Toast.makeText(this@ScreenshotViewerActivity, "Load failed: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    // DownloadManager can't attach the per-request HMAC signature the backend
    // requires, so it always 401'd. Fetch through the signed api client
    // instead and write the bytes straight into MediaStore ourselves.
    private fun downloadScreenshot() {
        Toast.makeText(this, "Saving to Pictures…", Toast.LENGTH_SHORT).show()
        lifecycleScope.launch {
            val bytes = api.screenshotImageBytes(filename)
            if (bytes == null) {
                Toast.makeText(this@ScreenshotViewerActivity, "Save failed — not paired or file missing", Toast.LENGTH_SHORT).show()
                return@launch
            }
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val values = ContentValues().apply {
                        put(MediaStore.Images.Media.DISPLAY_NAME, filename)
                        put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
                        put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/iZACH")
                    }
                    val uri = contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                        ?: error("MediaStore insert failed")
                    contentResolver.openOutputStream(uri)?.use { it.write(bytes) } ?: error("Couldn't open output stream")
                } else {
                    @Suppress("DEPRECATION")
                    val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "iZACH")
                    dir.mkdirs()
                    File(dir, filename).writeBytes(bytes)
                }
                Toast.makeText(this@ScreenshotViewerActivity, "Saved to Pictures/iZACH", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@ScreenshotViewerActivity, "Save failed: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    // Same problem as the save button — the raw backend URL has no way to
    // carry the pairing signature once handed to a different app. Fetch the
    // bytes ourselves, cache them locally, and share a content:// URI via
    // FileProvider instead of the URL.
    private fun shareScreenshot() {
        lifecycleScope.launch {
            val bytes = api.screenshotImageBytes(filename)
            if (bytes == null) {
                Toast.makeText(this@ScreenshotViewerActivity, "Share failed — not paired or file missing", Toast.LENGTH_SHORT).show()
                return@launch
            }
            try {
                val dir = File(cacheDir, "shared").apply { mkdirs() }
                val file = File(dir, filename)
                FileOutputStream(file).use { it.write(bytes) }
                val uri = FileProvider.getUriForFile(this@ScreenshotViewerActivity, "$packageName.fileprovider", file)
                val intent = Intent(Intent.ACTION_SEND).apply {
                    type = "image/jpeg"
                    putExtra(Intent.EXTRA_STREAM, uri)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                startActivity(Intent.createChooser(intent, "Share screenshot"))
            } catch (e: Exception) {
                Toast.makeText(this@ScreenshotViewerActivity, "Share failed: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }
}
