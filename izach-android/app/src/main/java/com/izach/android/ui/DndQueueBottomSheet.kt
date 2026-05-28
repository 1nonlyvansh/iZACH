package com.izach.android.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.izach.android.R
import com.izach.android.databinding.FragmentDndQueueBinding
import com.izach.android.model.DndAlert
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class DndQueueBottomSheet : BottomSheetDialogFragment() {

    private var _binding: FragmentDndQueueBinding? = null
    private val binding get() = _binding!!
    private val alerts = mutableListOf<DndAlert>()
    private lateinit var alertAdapter: AlertAdapter

    var onHandle: ((alert: DndAlert, index: Int) -> Unit)? = null
    var onBusy: ((alert: DndAlert, index: Int) -> Unit)? = null
    var onRefresh: (() -> Unit)? = null

    override fun onStart() {
        super.onStart()
        val sheet = dialog?.findViewById<View>(com.google.android.material.R.id.design_bottom_sheet)
        sheet?.let {
            val h = (resources.displayMetrics.heightPixels * 0.72).toInt()
            it.layoutParams.height = h
            val b = BottomSheetBehavior.from(it)
            b.peekHeight = h
            b.state = BottomSheetBehavior.STATE_EXPANDED
            b.skipCollapsed = true
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, saved: Bundle?): View {
        _binding = FragmentDndQueueBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        alertAdapter = AlertAdapter(
            alerts,
            onHandle = { alert, idx -> onHandle?.invoke(alert, idx) },
            onBusy   = { alert, idx -> onBusy?.invoke(alert, idx) }
        )
        binding.rvDndAlerts.layoutManager = LinearLayoutManager(requireContext())
        binding.rvDndAlerts.adapter = alertAdapter
        binding.btnCloseDnd.setOnClickListener { dismiss() }
        binding.btnRefreshDnd.setOnClickListener { onRefresh?.invoke() }
        updateEmpty()
        updateHeader()
    }

    fun preload(snapshot: Collection<DndAlert>) {
        alerts.clear()
        alerts.addAll(snapshot)
        if (::alertAdapter.isInitialized) {
            alertAdapter.notifyDataSetChanged()
            updateEmpty()
            updateHeader()
        }
    }

    fun upsertAlert(alert: DndAlert) {
        val idx = alerts.indexOfFirst { it.id == alert.id }
        if (idx >= 0) {
            alerts[idx] = alert
            if (::alertAdapter.isInitialized) alertAdapter.notifyItemChanged(idx)
        } else {
            alerts.add(0, alert)
            if (::alertAdapter.isInitialized) {
                alertAdapter.notifyItemInserted(0)
                _binding?.rvDndAlerts?.scrollToPosition(0)
            }
        }
        updateEmpty()
        updateHeader()
    }

    private fun updateEmpty() {
        if (!::alertAdapter.isInitialized) return
        val empty = alerts.isEmpty()
        _binding?.tvDndEmpty?.visibility = if (empty) View.VISIBLE else View.GONE
        _binding?.rvDndAlerts?.visibility = if (empty) View.GONE else View.VISIBLE
    }

    private fun updateHeader() {
        if (_binding == null) return
        val unhandled = alerts.count { it.action == null }
        binding.tvDndTitle.text = if (unhandled > 0) "DND QUEUE ($unhandled)" else "DND QUEUE"
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    class AlertAdapter(
        private val items: MutableList<DndAlert>,
        private val onHandle: (DndAlert, Int) -> Unit,
        private val onBusy: (DndAlert, Int) -> Unit
    ) : RecyclerView.Adapter<AlertAdapter.VH>() {

        private val timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvType: TextView   = view.findViewById(R.id.tvAlertType)
            val tvFrom: TextView   = view.findViewById(R.id.tvAlertFrom)
            val tvText: TextView   = view.findViewById(R.id.tvAlertText)
            val tvTs: TextView     = view.findViewById(R.id.tvAlertTs)
            val btnHandle: Button  = view.findViewById(R.id.btnAlertHandle)
            val btnBusy: Button    = view.findViewById(R.id.btnAlertBusy)
            val tvAction: TextView = view.findViewById(R.id.tvAlertAction)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context).inflate(R.layout.item_dnd_alert, parent, false)
            return VH(v)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val a = items[position]
            val isCall = a.type == "phone_call"

            holder.tvType.text = if (isCall) "📞 CALL" else "💬 WA"
            holder.tvType.setTextColor(if (isCall) 0xFF00e5ff.toInt() else 0xFF25D366.toInt())

            holder.tvFrom.text = "${a.from}  ·  ${a.number}"
            if (isCall) {
                holder.tvText.text = "Incoming WhatsApp call"
                holder.tvText.visibility = View.VISIBLE
            } else if (a.text.isNotBlank()) {
                holder.tvText.text = a.text
                holder.tvText.visibility = View.VISIBLE
            } else {
                holder.tvText.visibility = View.GONE
            }
            holder.tvTs.text = timeFmt.format(Date(a.ts * 1000L))

            if (a.action == null) {
                holder.btnHandle.visibility = View.VISIBLE
                holder.btnBusy.visibility   = View.VISIBLE
                holder.tvAction.visibility  = View.GONE
                holder.btnHandle.setOnClickListener { onHandle(a, position) }
                holder.btnBusy.setOnClickListener   { onBusy(a, position) }
            } else {
                holder.btnHandle.visibility = View.GONE
                holder.btnBusy.visibility   = View.GONE
                holder.tvAction.visibility  = View.VISIBLE
                val (label, color) = when (a.action) {
                    "handle"     -> "✅ HANDLED"      to 0xFF00e5ff.toInt()
                    "busy"       -> "📵 BUSY SENT"    to 0xFFff8c00.toInt()
                    "unattended" -> "⚠ UNATTENDED"   to 0xFFff5555.toInt()
                    else         -> a.action.uppercase() to 0xFF3a6070.toInt()
                }
                holder.tvAction.text = label
                holder.tvAction.setTextColor(color)
            }
        }

        override fun getItemCount() = items.size
    }
}
