package com.izach.android.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.R
import com.izach.android.databinding.ItemFileEntryBinding
import com.izach.android.model.FileEntry

class FilePickerAdapter(
    private val onClick: (FileEntry) -> Unit
) : RecyclerView.Adapter<FilePickerAdapter.VH>() {

    private val items = mutableListOf<FileEntry>()

    fun setEntries(entries: List<FileEntry>) {
        items.clear()
        // Dirs first, then files — both alphabetical
        items.addAll(entries.sortedWith(compareBy({ !it.isDir }, { it.name.lowercase() })))
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val b = ItemFileEntryBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return VH(b)
    }

    override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(items[position])
    override fun getItemCount() = items.size

    inner class VH(private val b: ItemFileEntryBinding) : RecyclerView.ViewHolder(b.root) {
        init {
            b.root.setOnClickListener {
                val pos = adapterPosition
                if (pos != RecyclerView.NO_ID.toInt()) onClick(items[pos])
            }
        }

        fun bind(entry: FileEntry) {
            b.tvEntryName.text = entry.name

            if (entry.isDir) {
                b.ivEntryIcon.setImageResource(R.drawable.ic_folder)
                b.ivEntryIcon.setColorFilter(ContextCompat.getColor(b.root.context, R.color.cyan_dim))
                b.ivChevron.visibility = View.VISIBLE
                b.tvEntrySize.visibility = View.GONE
            } else {
                b.ivEntryIcon.setImageResource(R.drawable.ic_file)
                val ext = entry.name.substringAfterLast('.', "").lowercase()
                val colorRes = when (ext) {
                    "jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "heic" -> R.color.cyan
                    "mp4", "mkv", "avi", "mov", "wmv", "webm", "flv", "m4v" -> R.color.amber
                    "mp3", "flac", "wav", "aac", "ogg", "m4a", "opus", "wma" -> R.color.green_neon
                    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "odt" -> R.color.text_pri
                    "apk", "exe", "msi", "dmg", "deb", "rpm" -> R.color.red_neon
                    "zip", "rar", "7z", "tar", "gz", "bz2", "xz" -> R.color.amber
                    else -> R.color.text_sec
                }
                b.ivEntryIcon.setColorFilter(ContextCompat.getColor(b.root.context, colorRes))
                b.ivChevron.visibility = View.GONE
                b.tvEntrySize.text = formatSize(entry.size)
                b.tvEntrySize.visibility = View.VISIBLE
            }
        }

        private fun formatSize(bytes: Long) = when {
            bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
            bytes >= 1024 -> "%.1f KB".format(bytes / 1024.0)
            else -> "$bytes B"
        }
    }
}
