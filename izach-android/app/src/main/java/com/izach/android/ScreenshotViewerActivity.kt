package com.izach.android

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.izach.android.databinding.ActivityScreenshotBinding
import androidx.lifecycle.lifecycleScope
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

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
        val url = api.screenshotImageUrl(filename)
        binding.progressImage.visibility = View.VISIBLE
        lifecycleScope.launch {
            withContext(Dispatchers.IO) {
                try {
                    val client = okhttp3.OkHttpClient()
                    val req = okhttp3.Request.Builder().url(url).build()
                    val resp = client.newCall(req).execute()
                    val bytes = resp.body?.bytes() ?: return@withContext
                    val bmp = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    runOnUiThread {
                        binding.progressImage.visibility = View.GONE
                        binding.ivScreenshot.setImageBitmap(bmp)
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        binding.progressImage.visibility = View.GONE
                        Toast.makeText(this@ScreenshotViewerActivity, "Load failed: ${e.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
    }

    private fun downloadScreenshot() {
        val url = api.screenshotImageUrl(filename)
        val req = DownloadManager.Request(Uri.parse(url)).apply {
            setTitle(filename)
            setDescription("iZACH Screenshot")
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            setDestinationInExternalPublicDir(Environment.DIRECTORY_PICTURES, filename)
            setAllowedOverMetered(true)
        }
        val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        dm.enqueue(req)
        Toast.makeText(this, "Saving to Pictures…", Toast.LENGTH_SHORT).show()
    }

    private fun shareScreenshot() {
        val url = api.screenshotImageUrl(filename)
        val intent = android.content.Intent(android.content.Intent.ACTION_VIEW, Uri.parse(url))
        startActivity(android.content.Intent.createChooser(intent, "Share screenshot"))
    }
}
