package com.izach.android.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.izach.android.R
import com.izach.android.databinding.FragmentNotificationHistoryBinding
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class NotificationEntry(
    val title: String,
    val category: String,
    val body: String,
    val epochMs: Long = System.currentTimeMillis()
)

class NotificationHistoryBottomSheet : BottomSheetDialogFragment() {

    private var _binding: FragmentNotificationHistoryBinding? = null
    private val binding get() = _binding!!
    private val notifications = mutableListOf<NotificationEntry>()
    private lateinit var notifAdapter: NotifAdapter

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
        _binding = FragmentNotificationHistoryBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        notifAdapter = NotifAdapter(notifications)
        binding.rvNotifications.layoutManager = LinearLayoutManager(requireContext())
        binding.rvNotifications.adapter = notifAdapter
        binding.btnCloseNotif.setOnClickListener { dismiss() }
        updateEmpty()
    }

    fun preload(snapshot: Collection<NotificationEntry>) {
        notifications.clear()
        notifications.addAll(snapshot)
        if (::notifAdapter.isInitialized) {
            notifAdapter.notifyDataSetChanged()
            updateEmpty()
        }
    }

    fun addNotification(entry: NotificationEntry) {
        notifications.add(0, entry)
        if (::notifAdapter.isInitialized) {
            notifAdapter.notifyItemInserted(0)
            binding.rvNotifications.scrollToPosition(0)
            updateEmpty()
        }
    }

    private fun updateEmpty() {
        if (!::notifAdapter.isInitialized) return
        binding.tvNotifEmpty.visibility = if (notifications.isEmpty()) View.VISIBLE else View.GONE
        binding.rvNotifications.visibility = if (notifications.isEmpty()) View.GONE else View.VISIBLE
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    class NotifAdapter(private val items: List<NotificationEntry>) :
        RecyclerView.Adapter<NotifAdapter.VH>() {

        private val timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvCategory: TextView = view.findViewById(R.id.tvNotifCategory)
            val tvTitle: TextView = view.findViewById(R.id.tvNotifTitle)
            val tvBody: TextView = view.findViewById(R.id.tvNotifBody)
            val tvTs: TextView = view.findViewById(R.id.tvNotifTs)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context).inflate(R.layout.item_notification, parent, false)
            return VH(v)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val n = items[position]
            holder.tvCategory.text = n.category.uppercase()
            holder.tvTitle.text = n.title
            holder.tvTs.text = timeFmt.format(Date(n.epochMs))
            if (n.body.isNotBlank()) {
                holder.tvBody.text = n.body
                holder.tvBody.visibility = View.VISIBLE
            } else {
                holder.tvBody.visibility = View.GONE
            }
            val categoryColor = when (n.category) {
                "downloads"   -> 0xFF1db954.toInt()
                "transfers"   -> 0xFF00e5ff.toInt()
                "automation"  -> 0xFFffb300.toInt()
                "alerts"      -> 0xFFff3d3d.toInt()
                else          -> 0xFF3a6070.toInt()
            }
            holder.tvCategory.setTextColor(categoryColor)
        }

        override fun getItemCount() = items.size
    }
}
