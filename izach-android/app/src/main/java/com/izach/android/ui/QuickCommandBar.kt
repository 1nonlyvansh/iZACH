package com.izach.android.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.izach.android.R
import com.izach.android.databinding.FragmentQuickCommandsBinding
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class QuickCommandBar : BottomSheetDialogFragment() {

    private var _binding: FragmentQuickCommandsBinding? = null
    private val binding get() = _binding!!
    private lateinit var api: IZACHApi

    var onScreenshotTaken: ((filename: String) -> Unit)? = null

    override fun onStart() {
        super.onStart()
        val sheet = dialog?.findViewById<View>(com.google.android.material.R.id.design_bottom_sheet)
        sheet?.let {
            val b = BottomSheetBehavior.from(it)
            b.state = BottomSheetBehavior.STATE_EXPANDED
            b.skipCollapsed = true
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, saved: Bundle?): View {
        _binding = FragmentQuickCommandsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        api = IZACHApi(requireContext())

        binding.btnCloseQuick.setOnClickListener { dismiss() }

        val actions = listOf(
            binding.btnLockPc to "lock_pc",
            binding.btnQScreenshot to "screenshot",
            binding.btnVolUp to "volume_up",
            binding.btnVolDown to "volume_down",
            binding.btnMute to "mute",
            binding.btnPlayPause to "play_pause",
            binding.btnNextTrack to "next_track",
            binding.btnPrevTrack to "prev_track",
        )

        for ((btn, action) in actions) {
            btn.setOnClickListener { fire(action) }
        }
    }

    private fun fire(action: String) {
        lifecycleScope.launch {
            api.quickAction(action).onSuccess { msg ->
                Toast.makeText(requireContext(), msg, Toast.LENGTH_SHORT).show()
                if (action == "screenshot") {
                    // screenshot result comes via WS; just dismiss
                }
            }.onFailure {
                Toast.makeText(requireContext(), "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
