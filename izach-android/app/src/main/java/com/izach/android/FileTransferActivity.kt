package com.izach.android

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
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

    private val filePicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { uploadFile(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityFilesBinding.inflate(layoutInflater)
        setContentView(binding.root)

        api = IZACHApi(this)
        adapter = FilesAdapter { file -> downloadFile(file) }

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
        lifecycleScope.launch {
            api.uploadFile(uri, this@FileTransferActivity).onSuccess { filename ->
                binding.progressUpload.visibility = View.GONE
                binding.btnUpload.isEnabled = true
                toast("Uploaded: $filename")
                loadFiles()
            }.onFailure {
                binding.progressUpload.visibility = View.GONE
                binding.btnUpload.isEnabled = true
                toast("Upload failed: ${it.message}")
            }
        }
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
}
