package com.izach.android.ui

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ItemFileBinding
import com.izach.android.model.FileInfo

class FilesAdapter(
    private val onDownload: (FileInfo) -> Unit
) : RecyclerView.Adapter<FilesAdapter.VH>() {

    private val items = mutableListOf<FileInfo>()

    fun setFiles(files: List<FileInfo>) {
        items.clear()
        items.addAll(files)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val b = ItemFileBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return VH(b)
    }

    override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(items[position])
    override fun getItemCount() = items.size

    inner class VH(private val b: ItemFileBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(file: FileInfo) {
            b.tvFilename.text = file.name
            b.tvFileSize.text = formatSize(file.size)
            b.btnDownload.setOnClickListener { onDownload(file) }
        }

        private fun formatSize(bytes: Long): String = when {
            bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
            bytes >= 1024 -> "%.1f KB".format(bytes / 1024.0)
            else -> "$bytes B"
        }
    }
}
