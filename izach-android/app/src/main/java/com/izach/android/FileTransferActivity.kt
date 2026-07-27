package com.izach.android

import android.app.DownloadManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.izach.android.databinding.ActivityFilesBinding
import com.izach.android.model.FileInfo
import com.izach.android.network.IZACHApi
import com.izach.android.ui.FilesAdapter
import kotlinx.coroutines.launch

class FileTransferActivity : AppCompatActivity() {

    private lateinit var binding: ActivityFilesBinding
    private lateinit var api: IZACHApi
    private lateinit var adapter: FilesAdapter
    private var lastNotifiedPct = -1

    private val filePicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { uploadFile(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityFilesBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp12 = (12 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp12, bars.top, dp12, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)
        adapter = FilesAdapter { file -> downloadFile(file) }
        createTransferChannel()

        binding.rvFiles.layoutManager = LinearLayoutManager(this)
        binding.rvFiles.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnUpload.setOnClickListener { filePicker.launch(arrayOf("*/*")) }
        binding.btnRefresh.setOnClickListener { loadFiles() }

        loadFiles()
    }

    private fun loadFiles() {
        binding.progressFiles.visibility = View.VISIBLE
        lifecycleScope.launch {
            api.getFiles().onSuccess { files ->
                binding.progressFiles.visibility = View.GONE
                adapter.setFiles(files)
                binding.tvEmpty.visibility = if (files.isEmpty()) View.VISIBLE else View.GONE
            }.onFailure {
                binding.progressFiles.visibility = View.GONE
                toast("Failed to load files: ${it.message}")
            }
        }
    }

    private fun uploadFile(uri: Uri) {
        binding.progressUpload.visibility = View.VISIBLE
        binding.btnUpload.isEnabled = false
        val displayName = uri.lastPathSegment?.substringAfterLast('/') ?: "file"
        lastNotifiedPct = -1
        notifyUploadProgress(displayName, 0, -1)
        lifecycleScope.launch {
            api.uploadFile(uri, this@FileTransferActivity) { written, total ->
                notifyUploadProgress(displayName, written, total)
            }.onSuccess { filename ->
                binding.progressUpload.visibility = View.GONE
                binding.btnUpload.isEnabled = true
                toast("Uploaded: $filename")
                notifyUploadDone(filename, ok = true)
                loadFiles()
            }.onFailure {
                binding.progressUpload.visibility = View.GONE
                binding.btnUpload.isEnabled = true
                toast("Upload failed: ${it.message}")
                notifyUploadDone(displayName, ok = false, error = it.message)
            }
        }
    }

    // Throttled to once per whole percentage point so a fast LAN upload doesn't
    // hammer NotificationManager with dozens of updates per second.
    private fun notifyUploadProgress(filename: String, written: Long, total: Long) {
        val indeterminate = total <= 0
        val pct = if (indeterminate) 0 else ((written * 100) / total).toInt()
        if (!indeterminate && pct == lastNotifiedPct) return
        lastNotifiedPct = pct
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) return
        val notif = NotificationCompat.Builder(this, TRANSFER_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_tasks)
            .setContentTitle("Uploading $filename")
            .setContentText(if (indeterminate) "Uploading…" else "$pct%")
            .setProgress(100, pct, indeterminate)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(TRANSFER_NOTIF_ID, notif)
    }

    private fun notifyUploadDone(filename: String, ok: Boolean, error: String? = null) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) return
        val notif = NotificationCompat.Builder(this, TRANSFER_CHANNEL_ID)
            .setSmallIcon(if (ok) R.drawable.ic_task_done else R.drawable.ic_task_failed)
            .setContentTitle(if (ok) "Uploaded $filename" else "Upload failed")
            .setContentText(if (ok) "Sent to PC" else (error ?: "Unknown error"))
            .setOngoing(false)
            .setAutoCancel(true)
            .build()
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(TRANSFER_NOTIF_ID, notif)
    }

    private fun createTransferChannel() {
        val ch = NotificationChannel(TRANSFER_CHANNEL_ID, "iZACH File Transfers", NotificationManager.IMPORTANCE_LOW)
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
    }

    private fun downloadFile(file: FileInfo) {
        val url = api.downloadUrl(file.name)
        val req = DownloadManager.Request(Uri.parse(url)).apply {
            setTitle(file.name)
            setDescription("Downloading from iZACH")
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, file.name)
            setAllowedOverMetered(true)
        }
        val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        dm.enqueue(req)
        toast("Downloading ${file.name}…")
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    companion object {
        private const val TRANSFER_CHANNEL_ID = "izach_transfers"
        private const val TRANSFER_NOTIF_ID = 3001
    }
}
