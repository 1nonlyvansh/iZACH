package com.izach.android

import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle
import android.widget.SeekBar
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivityAlliedNodeBinding
import com.izach.android.network.IZACHApi
import com.izach.android.ui.ProcessListBottomSheet
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class AlliedNodeActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAlliedNodeBinding
    private lateinit var api: IZACHApi
    private var isOnline = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityAlliedNodeBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            insets
        }

        api = IZACHApi(this)
        binding.btnBack.setOnClickListener { finish() }

        setupPowerButtons()
        setupSliders()
        setupActions()
        startPolling()
    }

    private fun setupPowerButtons() {
        fun confirmPower(action: String, title: String, msg: String) {
            AlertDialog.Builder(this)
                .setTitle(title).setMessage(msg)
                .setPositiveButton(action.uppercase()) { _, _ -> runAlliedCommand(action) }
                .setNegativeButton("CANCEL", null).show()
        }
        binding.btnAlliedLock.setOnClickListener     { confirmPower("lock", "Lock AlliedNode 2?", "PC will lock.") }
        binding.btnAlliedSleep.setOnClickListener    { confirmPower("sleep", "Sleep AlliedNode 2?", "PC will sleep.") }
        binding.btnAlliedRestart.setOnClickListener  { confirmPower("restart", "Restart AlliedNode 2?", "All unsaved work will be lost.") }
        binding.btnAlliedShutdown.setOnClickListener { confirmPower("shutdown", "Shut Down AlliedNode 2?", "All unsaved work will be lost.") }
    }

    private fun runAlliedCommand(action: String) {
        lifecycleScope.launch {
            api.alliedPower(action)
                .onSuccess { Toast.makeText(this@AlliedNodeActivity, "✅ $action sent to AlliedNode 2", Toast.LENGTH_SHORT).show() }
                .onFailure { Toast.makeText(this@AlliedNodeActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show() }
        }
    }

    private fun setupSliders() {
        binding.seekVolume.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                binding.tvVolumeVal.text = "$progress%"
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) {}
        })
        binding.btnSetVolume.setOnClickListener {
            val vol = binding.seekVolume.progress
            lifecycleScope.launch {
                api.alliedVolume(vol)
                    .onSuccess { Toast.makeText(this@AlliedNodeActivity, "Volume → $vol%", Toast.LENGTH_SHORT).show() }
                    .onFailure { Toast.makeText(this@AlliedNodeActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show() }
            }
        }

        binding.seekBrightness.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                binding.tvBrightnessVal.text = "$progress%"
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) {}
        })
        binding.btnSetBrightness.setOnClickListener {
            val bri = binding.seekBrightness.progress
            lifecycleScope.launch {
                api.alliedBrightness(bri)
                    .onSuccess { Toast.makeText(this@AlliedNodeActivity, "Brightness → $bri%", Toast.LENGTH_SHORT).show() }
                    .onFailure { Toast.makeText(this@AlliedNodeActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show() }
            }
        }
    }

    private fun setupActions() {
        binding.btnAlliedScreenshot.setOnClickListener {
            lifecycleScope.launch {
                api.alliedScreenshot()
                    .onSuccess { filename ->
                        startActivity(
                            Intent(this@AlliedNodeActivity, ScreenshotViewerActivity::class.java)
                                .putExtra("filename", filename)
                                .putExtra("allied_base_url", api.alliedBaseUrl())
                        )
                    }
                    .onFailure { Toast.makeText(this@AlliedNodeActivity, "Screenshot failed: ${it.message}", Toast.LENGTH_SHORT).show() }
            }
        }

        binding.btnAlliedProcesses.setOnClickListener {
            val sheet = ProcessListBottomSheet().also {
                it.api = api
                it.baseUrlOverride = api.alliedBaseUrl()
                it.title = "ALLIEDNODE 2 — PROCESSES"
            }
            sheet.show(supportFragmentManager, "allied_procs")
        }

        binding.btnAlliedTerminal.setOnClickListener {
            startActivity(
                Intent(this, TerminalActivity::class.java)
                    .putExtra("allied_base_url", api.alliedBaseUrl())
                    .putExtra("terminal_title", "AlliedNode 2 Terminal")
            )
        }
    }

    private fun startPolling() {
        lifecycleScope.launch {
            while (isActive) {
                api.getAlliedStatus()
                    .onSuccess { s ->
                        isOnline = true
                        runOnUiThread {
                            binding.alliedDot.setBackgroundResource(R.drawable.dot_connected)
                            binding.tvAlliedStatus.text = "ONLINE"
                            binding.tvAlliedStatus.setTextColor(ContextCompat.getColor(this@AlliedNodeActivity, R.color.green_neon))
                            binding.pbAlliedCpu.progress = s.cpu.toInt()
                            binding.tvAlliedCpu.text = "${s.cpu.toInt()}%"
                            binding.pbAlliedRam.progress = s.ram.toInt()
                            binding.tvAlliedRam.text = "${s.ram.toInt()}%"
                            binding.pbAlliedGpu.progress = s.gpu.toInt()
                            binding.tvAlliedGpu.text = if (s.gpu > 0f) "${s.gpu.toInt()}%" else "N/A"
                        }
                    }
                    .onFailure {
                        if (isOnline) runOnUiThread {
                            isOnline = false
                            binding.alliedDot.setBackgroundResource(R.drawable.dot_disconnected)
                            binding.tvAlliedStatus.text = "OFFLINE"
                            binding.tvAlliedStatus.setTextColor(ContextCompat.getColor(this@AlliedNodeActivity, R.color.red_neon))
                        }
                    }
                delay(3000)
            }
        }
    }
}
