package com.izach.android

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivitySystemDashboardBinding
import com.izach.android.model.SystemStatus
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class SystemDashboardActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySystemDashboardBinding
    private lateinit var api: IZACHApi

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
        startPolling()
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
