package com.izach.android.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.izach.android.R
import com.izach.android.databinding.FragmentDownloadMonitorBinding

data class DownloadEvent(
    val filename: String,
    var size: Long = 0L,
    var speedStr: String = "",
    var status: String = "downloading"  // downloading, completed, failed
)

class DownloadMonitorBottomSheet : BottomSheetDialogFragment() {

    private var _binding: FragmentDownloadMonitorBinding? = null
    private val binding get() = _binding!!
    private val downloads = mutableListOf<DownloadEvent>()
    private lateinit var dlAdapter: DlAdapter

    override fun onStart() {
        super.onStart()
        val sheet = dialog?.findViewById<View>(com.google.android.material.R.id.design_bottom_sheet)
        sheet?.let {
            val h = (resources.displayMetrics.heightPixels * 0.6).toInt()
            it.layoutParams.height = h
            val b = BottomSheetBehavior.from(it)
            b.peekHeight = h
            b.state = BottomSheetBehavior.STATE_EXPANDED
            b.skipCollapsed = true
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, saved: Bundle?): View {
        _binding = FragmentDownloadMonitorBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        dlAdapter = DlAdapter(downloads)
        binding.rvDownloads.layoutManager = LinearLayoutManager(requireContext())
        binding.rvDownloads.adapter = dlAdapter
        binding.btnCloseDl.setOnClickListener { dismiss() }
        updateEmpty()
    }

    fun preload(snapshot: Collection<DownloadEvent>) {
        downloads.clear()
        downloads.addAll(snapshot)
        if (::dlAdapter.isInitialized) {
            dlAdapter.notifyDataSetChanged()
            updateEmpty()
        }
    }

    fun upsertDownload(event: DownloadEvent) {
        val idx = downloads.indexOfFirst { it.filename == event.filename }
        if (idx >= 0) {
            downloads[idx] = event
            if (::dlAdapter.isInitialized) dlAdapter.notifyItemChanged(idx)
        } else {
            downloads.add(0, event)
            if (::dlAdapter.isInitialized) dlAdapter.notifyItemInserted(0)
        }
        if (::dlAdapter.isInitialized) updateEmpty()
    }

    private fun updateEmpty() {
        if (!::dlAdapter.isInitialized) return
        val b = _binding ?: return
        b.tvDlEmpty.visibility = if (downloads.isEmpty()) View.VISIBLE else View.GONE
        b.rvDownloads.visibility = if (downloads.isEmpty()) View.GONE else View.VISIBLE
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    class DlAdapter(private val items: List<DownloadEvent>) :
        RecyclerView.Adapter<DlAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val ivStatus: ImageView = view.findViewById(R.id.ivDlStatus)
            val tvFilename: TextView = view.findViewById(R.id.tvDlFilename)
            val progressBar: ProgressBar = view.findViewById(R.id.dlProgressBar)
            val tvSpeed: TextView = view.findViewById(R.id.tvDlSpeed)
            val tvSize: TextView = view.findViewById(R.id.tvDlSize)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context).inflate(R.layout.item_download, parent, false)
            return VH(v)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val d = items[position]
            holder.tvFilename.text = d.filename
            holder.tvSize.text = formatSize(d.size)

            when (d.status) {
                "completed" -> {
                    holder.progressBar.visibility = View.GONE
                    holder.tvSpeed.text = "Complete"
                    holder.tvSpeed.setTextColor(0xFF1db954.toInt())
                    holder.ivStatus.setColorFilter(0xFF1db954.toInt())
                }
                "failed" -> {
                    holder.progressBar.visibility = View.GONE
                    holder.tvSpeed.text = "Failed"
                    holder.tvSpeed.setTextColor(0xFFff3d3d.toInt())
                    holder.ivStatus.setColorFilter(0xFFff3d3d.toInt())
                }
                else -> {
                    holder.progressBar.visibility = View.VISIBLE
                    holder.progressBar.isIndeterminate = true
                    holder.tvSpeed.text = if (d.speedStr.isNotBlank()) d.speedStr else "Downloading…"
                    holder.tvSpeed.setTextColor(0xFF3a6070.toInt())
                    holder.ivStatus.clearColorFilter()
                }
            }
        }

        private fun formatSize(bytes: Long): String = when {
            bytes >= 1_000_000_000L -> "${bytes / 1_000_000_000.0f} GB"
            bytes >= 1_000_000L -> String.format("%.1f MB", bytes / 1_000_000.0)
            bytes >= 1_000L -> String.format("%.1f KB", bytes / 1_000.0)
            else -> "$bytes B"
        }

        override fun getItemCount() = items.size
    }
}
