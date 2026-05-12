package com.izach.android.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.izach.android.databinding.FragmentFilePickerBinding
import com.izach.android.model.FileEntry
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class FilePickerBottomSheet : BottomSheetDialogFragment() {

    var onFileSelected: ((FileEntry) -> Unit)? = null

    private var _binding: FragmentFilePickerBinding? = null
    private val binding get() = _binding!!

    private lateinit var api: IZACHApi
    private lateinit var pickerAdapter: FilePickerAdapter

    // Stack of (displayName, absolutePath?) — null path = roots view
    private val pathStack = ArrayDeque<Pair<String, String?>>()

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, saved: Bundle?): View {
        _binding = FragmentFilePickerBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onStart() {
        super.onStart()
        val sheet = dialog?.findViewById<android.view.View>(
            com.google.android.material.R.id.design_bottom_sheet
        )
        sheet?.let {
            val h = (resources.displayMetrics.heightPixels * 0.85).toInt()
            it.layoutParams.height = h
            val behavior = BottomSheetBehavior.from(it)
            behavior.peekHeight = h
            behavior.state = BottomSheetBehavior.STATE_EXPANDED
            behavior.skipCollapsed = true
        }
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        api = IZACHApi(requireContext())
        pickerAdapter = FilePickerAdapter { entry ->
            if (entry.isDir) {
                navigateTo(entry.name, entry.path)
            } else {
                onFileSelected?.invoke(entry)
                dismiss()
            }
        }

        binding.rvPicker.layoutManager = LinearLayoutManager(requireContext())
        binding.rvPicker.adapter = pickerAdapter

        binding.btnPickerBack.setOnClickListener {
            if (pathStack.size > 1) {
                pathStack.removeLast()
                val (name, path) = pathStack.last()
                binding.tvPickerPath.text = name
                loadEntries(path)
            } else {
                dismiss()
            }
        }

        binding.btnPickerClose.setOnClickListener { dismiss() }

        // Initial: show roots
        pathStack.addLast("Sources" to null)
        loadEntries(null)
    }

    private fun navigateTo(displayName: String, path: String) {
        pathStack.addLast(displayName to path)
        binding.tvPickerPath.text = displayName
        loadEntries(path)
    }

    private fun loadEntries(path: String?) {
        binding.progressPicker.visibility = View.VISIBLE
        binding.tvPickerEmpty.visibility = View.GONE

        viewLifecycleOwner.lifecycleScope.launch {
            val dirs = if (path == null)
                api.listDirs(null).getOrDefault(emptyList())
            else
                api.listDirs(path).getOrDefault(emptyList())

            val files = if (path != null)
                api.listFiles(path).getOrDefault(emptyList())
            else
                emptyList()

            binding.progressPicker.visibility = View.GONE
            val all = dirs + files

            if (all.isEmpty()) {
                binding.tvPickerEmpty.visibility = View.VISIBLE
            } else {
                pickerAdapter.setEntries(all)
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
