package com.izach.android

import android.os.Bundle
import android.widget.SeekBar
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivitySpotifyRemoteBinding
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class SpotifyRemoteActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySpotifyRemoteBinding
    private lateinit var api: IZACHApi

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivitySpotifyRemoteBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            insets
        }

        api = IZACHApi(this)
        binding.btnBack.setOnClickListener { finish() }

        binding.btnPlayPause.setOnClickListener { control("playpause") }
        binding.btnNext.setOnClickListener { control("next") }
        binding.btnPrev.setOnClickListener { control("prev") }

        binding.seekVolume.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onProgressChanged(s: SeekBar?, p: Int, fromUser: Boolean) {}
            override fun onStopTrackingTouch(s: SeekBar?) {
                lifecycleScope.launch { api.spotifyVolume(s?.progress ?: 50) }
            }
        })

        startPolling()
    }

    private fun control(action: String) {
        lifecycleScope.launch {
            api.spotifyControl(action).onFailure {
                Toast.makeText(this@SpotifyRemoteActivity, "Error: ${it.message}", Toast.LENGTH_SHORT).show()
            }
            refreshStatus()
        }
    }

    private fun startPolling() {
        lifecycleScope.launch {
            while (isActive) {
                refreshStatus()
                delay(3000)
            }
        }
    }

    private suspend fun refreshStatus() {
        api.getSpotifyStatus().onSuccess { s ->
            runOnUiThread {
                binding.tvTitle.text = s.title
                binding.tvArtist.text = s.artist
                binding.tvDevice.text = s.device
                binding.btnPlayPause.setImageResource(
                    if (s.playing) R.drawable.ic_pause else R.drawable.ic_play
                )
                if (s.duration > 0) {
                    binding.seekProgress.max = s.duration
                    binding.seekProgress.progress = s.progress
                    binding.tvProgress.text = "${msToTime(s.progress)} / ${msToTime(s.duration)}"
                }
                binding.seekVolume.progress = s.volume
                binding.tvVolume.text = "${s.volume}%"
            }
        }
    }

    private fun msToTime(ms: Int): String {
        val s = ms / 1000
        return "%d:%02d".format(s / 60, s % 60)
    }
}
