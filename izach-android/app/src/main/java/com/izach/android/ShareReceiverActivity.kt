package com.izach.android

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

/**
 * Handles Android's share sheet: links/text -> save as an iZACH bookmark,
 * files -> upload to the PC. Renders as a floating dialog (see
 * Theme.MaterialComponents.DayNight.Dialog in the manifest) so it doesn't
 * feel like a full app switch from whatever app the user shared from.
 */
class ShareReceiverActivity : AppCompatActivity() {

    private lateinit var api: IZACHApi

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = IZACHApi(this)

        when (intent?.action) {
            Intent.ACTION_SEND -> handleSingleShare()
            Intent.ACTION_SEND_MULTIPLE -> handleMultipleFiles()
            else -> finish()
        }
    }

    private fun handleSingleShare() {
        val stream = getStreamExtra()
        if (stream != null) {
            confirmUpload(listOf(stream))
            return
        }
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()
        if (text.isNullOrBlank()) {
            finish()
            return
        }
        showBookmarkDialog(text)
    }

    private fun handleMultipleFiles() {
        val uris = getStreamListExtra()
        if (uris.isNullOrEmpty()) {
            finish()
            return
        }
        confirmUpload(uris)
    }

    @Suppress("DEPRECATION")
    private fun getStreamExtra(): Uri? =
        if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun getStreamListExtra(): List<Uri>? =
        if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM)

    private fun showBookmarkDialog(sharedText: String) {
        val url = Regex("""https?://\S+""").find(sharedText)?.value ?: sharedText
        val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)?.trim()

        val dp = resources.displayMetrics.density
        val pad = (20 * dp).toInt()
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
        }
        val titleInput = EditText(this).apply {
            hint = "Title"
            setText(subject ?: url)
        }
        val urlInput = EditText(this).apply {
            hint = "URL"
            setText(url)
        }
        val folderInput = EditText(this).apply {
            hint = "Folder"
            setText("General")
        }
        container.addView(titleInput)
        container.addView(urlInput)
        container.addView(folderInput)

        AlertDialog.Builder(this)
            .setTitle("Save to iZACH Bookmarks")
            .setView(container)
            .setPositiveButton("SAVE") { _, _ ->
                val title = titleInput.text.toString().trim().ifBlank { url }
                val finalUrl = urlInput.text.toString().trim()
                val folder = folderInput.text.toString().trim().ifBlank { "General" }
                if (finalUrl.isBlank()) {
                    toast("URL required")
                    finish()
                    return@setPositiveButton
                }
                lifecycleScope.launch {
                    api.addBookmark(title, finalUrl, folder)
                        .onSuccess { toast("Bookmarked!") }
                        .onFailure { toast("Failed: ${it.message}") }
                    finish()
                }
            }
            .setNegativeButton("CANCEL") { _, _ -> finish() }
            .setNeutralButton("OPEN IN BROWSER") { _, _ ->
                startActivity(Intent(this, BrowserActivity::class.java).putExtra(BrowserActivity.EXTRA_URL, url))
                finish()
            }
            .setOnCancelListener { finish() }
            .show()
    }

    private fun confirmUpload(uris: List<Uri>) {
        val label = if (uris.size == 1) "1 file" else "${uris.size} files"
        AlertDialog.Builder(this)
            .setTitle("Send to PC")
            .setMessage("Send $label to your PC via iZACH?")
            .setPositiveButton("SEND") { _, _ ->
                lifecycleScope.launch {
                    var okCount = 0
                    uris.forEach { uri ->
                        api.uploadFile(uri, this@ShareReceiverActivity).onSuccess { okCount++ }
                    }
                    toast(if (okCount == uris.size) "Sent to PC!" else "Sent $okCount/${uris.size}")
                    finish()
                }
            }
            .setNegativeButton("CANCEL") { _, _ -> finish() }
            .setOnCancelListener { finish() }
            .show()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
