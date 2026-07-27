package com.izach.android

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.Spinner
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivityCommandQueueBinding
import com.izach.android.databinding.ItemQueuedCommandBinding
import com.izach.android.model.QueuedCommand
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

/**
 * Queue commands for a specific saved PC (Mac or Windows) to run whenever
 * that PC is next reachable — independent of which connection is currently
 * active. Actual execution happens in StatusNotificationService's poll loop
 * so it keeps working with this screen closed; this Activity is just the
 * add/reorder/remove UI plus a manual "drain now" on open.
 */
class CommandQueueActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCommandQueueBinding
    private lateinit var api: IZACHApi

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityCommandQueueBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = IZACHApi(this)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            insets
        }

        binding.btnBack.setOnClickListener { finish() }
        binding.btnAddQueued.setOnClickListener { promptAddCommand() }

        render()
        // Best-effort immediate attempt in case something's already
        // reachable — the periodic background drain covers the rest.
        lifecycleScope.launch {
            if (api.drainCommandQueue() > 0) render()
        }
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    private fun render() {
        val queue = api.getCommandQueue()
        binding.tvEmptyQueue.visibility = if (queue.isEmpty()) View.VISIBLE else View.GONE
        binding.queueContainer.removeAllViews()

        queue.forEachIndexed { index, cmd ->
            val row = ItemQueuedCommandBinding.inflate(LayoutInflater.from(this), binding.queueContainer, false)
            row.tvCommandText.text = cmd.text
            row.tvCommandTarget.text = "→ ${cmd.targetProfileName.uppercase()}"

            row.btnMoveUp.isEnabled = index > 0
            row.btnMoveUp.alpha = if (index > 0) 1f else 0.3f
            row.btnMoveDown.isEnabled = index < queue.size - 1
            row.btnMoveDown.alpha = if (index < queue.size - 1) 1f else 0.3f

            row.btnMoveUp.setOnClickListener { moveCommand(queue, index, index - 1) }
            row.btnMoveDown.setOnClickListener { moveCommand(queue, index, index + 1) }
            row.btnDeleteQueued.setOnClickListener {
                api.removeFromCommandQueue(cmd.id)
                render()
            }

            binding.queueContainer.addView(row.root)
        }
    }

    private fun moveCommand(queue: List<QueuedCommand>, from: Int, to: Int) {
        if (to < 0 || to >= queue.size) return
        val mutable = queue.toMutableList()
        val item = mutable.removeAt(from)
        mutable.add(to, item)
        api.reorderCommandQueue(mutable)
        render()
    }

    private fun promptAddCommand() {
        val profiles = api.getProfiles()
        if (profiles.isEmpty()) {
            toast("Pair at least one PC first (Settings → Scan QR).")
            return
        }

        val layout = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        val input = EditText(this).apply {
            hint = "Command, e.g. \"lock the pc\""
            setTextColor(getColor(R.color.text_pri))
        }
        val spinner = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@CommandQueueActivity,
                android.R.layout.simple_spinner_dropdown_item,
                profiles.map { "${platformIcon(it.platform)} ${it.name}" }
            )
        }
        layout.addView(input)
        layout.addView(spinner)

        AlertDialog.Builder(this)
            .setTitle("Queue a command")
            .setView(layout)
            .setPositiveButton("Add") { _, _ ->
                val text = input.text.toString().trim()
                if (text.isBlank()) return@setPositiveButton
                val target = profiles[spinner.selectedItemPosition]
                api.addToCommandQueue(text, target)
                render()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun platformIcon(platform: String) = when (platform) {
        "mac" -> "🍎"
        "windows" -> "🪟"
        else -> "💻"
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
