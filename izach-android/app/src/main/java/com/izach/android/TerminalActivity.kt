package com.izach.android

import android.os.Bundle
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivityTerminalBinding
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class TerminalActivity : AppCompatActivity() {

    private lateinit var binding: ActivityTerminalBinding
    private lateinit var api: IZACHApi
    private var alliedBaseUrl: String? = null
    private val history = mutableListOf<String>()
    private var historyIdx = -1

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityTerminalBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            insets
        }

        alliedBaseUrl = intent.getStringExtra("allied_base_url")
        val titleText = intent.getStringExtra("terminal_title") ?: ">_ TERMINAL"
        binding.topBar.findViewById<android.widget.TextView>(android.R.id.text1)?.text

        api = IZACHApi(this)
        binding.btnBack.setOnClickListener { finish() }

        binding.btnClearTerm.setOnClickListener {
            binding.tvTermOutput.text = "iZACH Terminal — type a command below\n"
        }

        binding.btnSendTerm.setOnClickListener { sendCommand() }

        binding.etTermInput.setOnEditorActionListener { _, actionId, event ->
            if (actionId == EditorInfo.IME_ACTION_SEND ||
                (event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN)) {
                sendCommand(); true
            } else false
        }

        append("Connected to: ${alliedBaseUrl ?: api.baseUrl()}\n")
    }

    private fun sendCommand() {
        val cmd = binding.etTermInput.text?.toString()?.trim() ?: return
        if (cmd.isBlank()) return
        binding.etTermInput.text?.clear()
        history.add(0, cmd)
        historyIdx = -1
        append("\n\$ $cmd\n")
        binding.btnSendTerm.isEnabled = false

        lifecycleScope.launch {
            val url = alliedBaseUrl
            val result = if (url != null) api.alliedTerminalCmd(cmd, url) else api.alliedTerminalCmd(cmd)
            result
                .onSuccess { response ->
                    append(response.trimEnd())
                    append("\n")
                }
                .onFailure { err ->
                    append("[ERROR] ${err.message}\n")
                }
            binding.btnSendTerm.isEnabled = true
            scrollBottom()
        }
    }

    private fun append(text: String) {
        binding.tvTermOutput.append(text)
        scrollBottom()
    }

    private fun scrollBottom() {
        binding.termScrollView.post {
            binding.termScrollView.fullScroll(android.view.View.FOCUS_DOWN)
        }
    }
}
