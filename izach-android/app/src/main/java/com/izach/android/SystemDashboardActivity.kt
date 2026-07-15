package com.izach.android

import android.app.AlertDialog
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivitySystemDashboardBinding
import com.izach.android.model.SystemStatus
import com.izach.android.network.IZACHApi
import com.izach.android.ui.ProcessListBottomSheet
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class SystemDashboardActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySystemDashboardBinding
    private lateinit var api: IZACHApi

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivitySystemDashboardBinding.inflate(layoutInflater)
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
        binding.btnViewProcesses.setOnClickListener {
            ProcessListBottomSheet().also {
                it.api = api
                it.title = "PROCESSES — THIS PC"
            }.show(supportFragmentManager, "procs")
        }
        startPolling()
    }

    private fun setupPowerButtons() {
        binding.btnPcLock.setOnClickListener {
            executePowerAction("lock", "Lock PC?", "PC will lock immediately.")
        }
        binding.btnPcSleep.setOnClickListener {
            executePowerAction("sleep", "Sleep PC?", "PC will go to sleep.")
        }
        binding.btnPcRestart.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Restart PC?")
                .setMessage("All unsaved work will be lost.")
                .setPositiveButton("RESTART") { _, _ -> runPowerAction("restart") }
                .setNegativeButton("CANCEL", null)
                .show()
        }
        binding.btnPcShutdown.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Shut Down PC?")
                .setMessage("All unsaved work will be lost. PC will turn off.")
                .setPositiveButton("SHUTDOWN") { _, _ -> runPowerAction("shutdown") }
                .setNegativeButton("CANCEL", null)
                .show()
        }
    }

    private fun executePowerAction(action: String, title: String, msg: String) {
        AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage(msg)
            .setPositiveButton("CONFIRM") { _, _ -> runPowerAction(action) }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun runPowerAction(action: String) {
        lifecycleScope.launch {
            api.pcPower(action)
                .onSuccess { Toast.makeText(this@SystemDashboardActivity, "✅ $action sent", Toast.LENGTH_SHORT).show() }
                .onFailure { Toast.makeText(this@SystemDashboardActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show() }
        }
    }

    private fun startPolling() {
        lifecycleScope.launch {
            while (isActive) {
                api.getSystemStatus().onSuccess { s -> runOnUiThread { updateUI(s) } }
                delay(2000)
            }
        }
    }

    private fun updateUI(s: SystemStatus) {
        binding.pbCpu.progress = s.cpu.toInt()
        binding.tvCpu.text = "${s.cpu.toInt()}%"

        binding.pbRam.progress = s.ram.toInt()
        binding.tvRam.text = "${s.ram.toInt()}%"

        binding.pbGpu.progress = s.gpu.toInt()
        binding.tvGpu.text = if (s.gpu > 0f) "${s.gpu.toInt()}%" else "N/A"

        binding.pbProcCpu.progress = s.procCpu.toInt()
        binding.tvProcCpu.text = "${s.procCpu}%"

        binding.pbProcMem.progress = s.procMem.toInt()
        binding.tvProcMem.text = "${s.procMem}%"

        val waConnected = s.whatsapp
        val mmaConnected = s.mma
        binding.dotWhatsapp.setBackgroundResource(
            if (waConnected) R.drawable.dot_connected else R.drawable.dot_disconnected
        )
        binding.dotMma.setBackgroundResource(
            if (mmaConnected) R.drawable.dot_connected else R.drawable.dot_disconnected
        )
        binding.tvWhatsapp.text = if (waConnected) "CONNECTED" else "OFFLINE"
        binding.tvWhatsapp.setTextColor(
            ContextCompat.getColor(this, if (waConnected) R.color.green_neon else R.color.red_neon)
        )
        binding.tvMma.text = if (mmaConnected) "CONNECTED" else "OFFLINE"
        binding.tvMma.setTextColor(
            ContextCompat.getColor(this, if (mmaConnected) R.color.green_neon else R.color.red_neon)
        )
    }
}
