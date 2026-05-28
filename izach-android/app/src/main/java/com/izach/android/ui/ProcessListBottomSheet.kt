package com.izach.android.ui

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.izach.android.R
import com.izach.android.databinding.FragmentProcessListBinding
import com.izach.android.model.ProcessInfo
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class ProcessListBottomSheet : BottomSheetDialogFragment() {

    private var _binding: FragmentProcessListBinding? = null
    private val binding get() = _binding!!
    private var allProcesses = listOf<ProcessInfo>()
    private var filtered = mutableListOf<ProcessInfo>()
    private lateinit var procAdapter: ProcAdapter

    var api: IZACHApi? = null
    var baseUrlOverride: String? = null       // null → main PC, non-null → AlliedNode
    var title: String = "PROCESSES"

    override fun onStart() {
        super.onStart()
        val sheet = dialog?.findViewById<View>(com.google.android.material.R.id.design_bottom_sheet)
        sheet?.let {
            val h = (resources.displayMetrics.heightPixels * 0.85).toInt()
            it.layoutParams.height = h
            val b = BottomSheetBehavior.from(it)
            b.peekHeight = h
            b.state = BottomSheetBehavior.STATE_EXPANDED
            b.skipCollapsed = true
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, saved: Bundle?): View {
        _binding = FragmentProcessListBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        binding.tvProcessTitle.text = title
        procAdapter = ProcAdapter(filtered) { proc -> killProcess(proc) }
        binding.rvProcesses.layoutManager = LinearLayoutManager(requireContext())
        binding.rvProcesses.adapter = procAdapter

        binding.btnCloseProc.setOnClickListener { dismiss() }
        binding.btnRefreshProc.setOnClickListener { loadProcesses() }

        binding.etProcSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) { applyFilter(s?.toString() ?: "") }
        })

        loadProcesses()
    }

    private fun loadProcesses() {
        val api = api ?: return
        binding.progressProc.visibility = View.VISIBLE
        binding.tvProcEmpty.visibility = View.GONE
        lifecycleScope.launch {
            val url = baseUrlOverride ?: api.baseUrl()
            api.getProcesses(url)
                .onSuccess { procs ->
                    allProcesses = procs.sortedByDescending { it.memoryMb }
                    applyFilter(binding.etProcSearch.text?.toString() ?: "")
                    _binding?.tvProcCount?.text = "${procs.size} processes"
                    _binding?.progressProc?.visibility = View.GONE
                }
                .onFailure {
                    _binding?.progressProc?.visibility = View.GONE
                    _binding?.tvProcEmpty?.text = "Failed: ${it.message}"
                    _binding?.tvProcEmpty?.visibility = View.VISIBLE
                }
        }
    }

    private fun applyFilter(query: String) {
        val q = query.trim().lowercase()
        val result = if (q.isBlank()) allProcesses else allProcesses.filter { it.name.lowercase().contains(q) }
        filtered.clear()
        filtered.addAll(result)
        if (::procAdapter.isInitialized) procAdapter.notifyDataSetChanged()
        val empty = filtered.isEmpty()
        _binding?.tvProcEmpty?.text = if (q.isBlank()) "No processes found" else "No matches for \"$q\""
        _binding?.tvProcEmpty?.visibility = if (empty) View.VISIBLE else View.GONE
        _binding?.rvProcesses?.visibility = if (empty) View.GONE else View.VISIBLE
    }

    private fun killProcess(proc: ProcessInfo) {
        val api = api ?: return
        lifecycleScope.launch {
            val url = baseUrlOverride ?: api.baseUrl()
            api.killProcess(proc.pid, url)
                .onSuccess {
                    Toast.makeText(requireContext(), "Killed ${proc.name}", Toast.LENGTH_SHORT).show()
                    loadProcesses()
                }
                .onFailure {
                    Toast.makeText(requireContext(), "Kill failed: ${it.message}", Toast.LENGTH_SHORT).show()
                }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }

    class ProcAdapter(
        private val items: List<ProcessInfo>,
        private val onKill: (ProcessInfo) -> Unit
    ) : RecyclerView.Adapter<ProcAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvName: TextView  = view.findViewById(R.id.tvProcName)
            val tvPid: TextView   = view.findViewById(R.id.tvProcPid)
            val tvCpu: TextView   = view.findViewById(R.id.tvProcCpu)
            val tvMem: TextView   = view.findViewById(R.id.tvProcMem)
            val btnKill: Button   = view.findViewById(R.id.btnKillProc)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_process, parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val p = items[position]
            holder.tvName.text = p.name
            holder.tvPid.text  = "PID ${p.pid}"
            holder.tvCpu.text  = if (p.cpu > 0.05f) "CPU ${String.format("%.1f", p.cpu)}%" else ""
            holder.tvMem.text  = if (p.memoryMb >= 1024f)
                "%.1f GB".format(p.memoryMb / 1024f)
            else
                "${p.memoryMb.toInt()} MB"
            holder.btnKill.setOnClickListener { onKill(p) }
        }

        override fun getItemCount() = items.size
    }
}
