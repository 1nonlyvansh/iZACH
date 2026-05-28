package com.izach.android.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.lifecycle.lifecycleScope
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.izach.android.databinding.FragmentWaQuickReplyBinding
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class WaQuickReplyBottomSheet : BottomSheetDialogFragment() {

    private var _binding: FragmentWaQuickReplyBinding? = null
    private val binding get() = _binding!!

    var api: IZACHApi? = null
    var from: String = ""
    var number: String = ""
    var originalText: String = ""
    var onSend: ((number: String, text: String, name: String) -> Unit)? = null

    companion object {
        fun newInstance(
            from: String,
            number: String,
            originalText: String,
            api: IZACHApi
        ): WaQuickReplyBottomSheet = WaQuickReplyBottomSheet().also {
            it.from         = from
            it.number       = number
            it.originalText = originalText
            it.api          = api
        }
    }

    override fun onStart() {
        super.onStart()
        val sheet = dialog?.findViewById<View>(com.google.android.material.R.id.design_bottom_sheet)
        sheet?.let {
            val h = (resources.displayMetrics.heightPixels * 0.65).toInt()
            it.layoutParams.height = h
            val b = BottomSheetBehavior.from(it)
            b.peekHeight = h
            b.state = BottomSheetBehavior.STATE_EXPANDED
            b.skipCollapsed = true
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, saved: Bundle?): View {
        _binding = FragmentWaQuickReplyBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        binding.tvWaTo.text = "To: $from  •  $number"

        if (originalText.isNotBlank()) {
            binding.tvWaOriginal.text = "\"$originalText\""
            binding.tvWaOriginal.visibility = View.VISIBLE
        } else {
            binding.tvWaOriginal.visibility = View.GONE
        }

        binding.btnCloseWaReply.setOnClickListener { dismiss() }

        binding.btnSendWaReply.setOnClickListener {
            val text = binding.etWaReply.text?.toString()?.trim() ?: return@setOnClickListener
            if (text.isBlank()) return@setOnClickListener
            binding.btnSendWaReply.isEnabled = false
            onSend?.invoke(number, text, from)
            dismiss()
        }

        loadAiDraft()
    }

    private fun loadAiDraft() {
        val api = api ?: return
        _binding?.progressWaDraft?.visibility = View.VISIBLE
        _binding?.etWaReply?.hint = "Loading AI draft…"

        lifecycleScope.launch {
            api.waAiDraft(from, originalText)
                .onSuccess { draft ->
                    _binding?.let {
                        it.progressWaDraft.visibility = View.GONE
                        it.etWaReply.setText(draft)
                        it.etWaReply.setSelection(draft.length)
                        it.etWaReply.hint = "Edit reply…"
                    }
                }
                .onFailure {
                    _binding?.let {
                        it.progressWaDraft.visibility = View.GONE
                        it.etWaReply.hint = "Type your reply…"
                    }
                }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
