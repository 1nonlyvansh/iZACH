package com.izach.android.ui

import android.graphics.Color
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
import com.izach.android.databinding.FragmentTaskStreamBinding

data class TaskEvent(
    val id: String,
    var name: String,
    var progress: Int = 0,
    var status: String = "running",  // running, completed, failed
    var message: String = ""
)

class TaskStreamBottomSheet : BottomSheetDialogFragment() {

    private var _binding: FragmentTaskStreamBinding? = null
    private val binding get() = _binding!!
    private val tasks = mutableListOf<TaskEvent>()
    private lateinit var taskAdapter: TaskAdapter

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
        _binding = FragmentTaskStreamBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        taskAdapter = TaskAdapter(tasks)
        binding.rvTasks.layoutManager = LinearLayoutManager(requireContext())
        binding.rvTasks.adapter = taskAdapter
        binding.btnCloseStream.setOnClickListener { dismiss() }
        updateEmpty()
    }

    fun preloadTasks(snapshot: Collection<TaskEvent>) {
        tasks.clear()
        tasks.addAll(snapshot)
        if (::taskAdapter.isInitialized) {
            taskAdapter.notifyDataSetChanged()
            updateEmpty()
        }
    }

    fun upsertTask(event: TaskEvent) {
        val idx = tasks.indexOfFirst { it.id == event.id }
        if (idx >= 0) {
            tasks[idx] = event
            taskAdapter.notifyItemChanged(idx)
        } else {
            tasks.add(0, event)
            taskAdapter.notifyItemInserted(0)
        }
        if (::taskAdapter.isInitialized) updateEmpty()
    }

    private fun updateEmpty() {
        if (!::taskAdapter.isInitialized) return
        binding.tvTasksEmpty.visibility = if (tasks.isEmpty()) View.VISIBLE else View.GONE
        binding.rvTasks.visibility = if (tasks.isEmpty()) View.GONE else View.VISIBLE
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    class TaskAdapter(private val items: List<TaskEvent>) : RecyclerView.Adapter<TaskAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvName: TextView = view.findViewById(R.id.tvTaskName)
            val tvStatus: TextView = view.findViewById(R.id.tvTaskStatus)
            val progressBar: ProgressBar = view.findViewById(R.id.taskProgressBar)
            val ivStatus: ImageView = view.findViewById(R.id.ivTaskStatus)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val v = LayoutInflater.from(parent.context).inflate(R.layout.item_task_event, parent, false)
            return VH(v)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val t = items[position]
            holder.tvName.text = t.name
            when (t.status) {
                "completed" -> {
                    holder.tvStatus.text = t.message.ifBlank { "Done" }
                    holder.tvStatus.setTextColor(0xFF1db954.toInt())
                    holder.progressBar.visibility = View.GONE
                    holder.ivStatus.setImageResource(R.drawable.ic_task_done)
                }
                "failed" -> {
                    holder.tvStatus.text = t.message.ifBlank { "Failed" }
                    holder.tvStatus.setTextColor(0xFFff3d3d.toInt())
                    holder.progressBar.visibility = View.GONE
                    holder.ivStatus.setImageResource(R.drawable.ic_task_failed)
                }
                else -> {
                    holder.tvStatus.text = if (t.message.isNotBlank()) t.message else "Running…"
                    holder.tvStatus.setTextColor(0xFF00e5ff.toInt())
                    holder.progressBar.visibility = View.VISIBLE
                    holder.progressBar.progress = t.progress
                    holder.ivStatus.setImageResource(R.drawable.ic_tasks)
                }
            }
        }

        override fun getItemCount() = items.size
    }
}
