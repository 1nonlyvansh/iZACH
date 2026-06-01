package com.izach.android

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.os.Bundle
import android.view.View
import android.widget.ImageButton
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Streams PC system audio to this device over local network.
 *
 * Backend: GET /audio/stream → raw PCM s16le 22050Hz mono
 * Uses AudioTrack in STREAM mode for low-latency playback.
 */
class AudioStreamActivity : AppCompatActivity() {

    private val SAMPLE_RATE  = 22050
    private val CHANNEL_CFG  = AudioFormat.CHANNEL_OUT_MONO
    private val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
    private val BUFFER_SIZE  = AudioTrack.getMinBufferSize(SAMPLE_RATE, CHANNEL_CFG, AUDIO_FORMAT)
        .coerceAtLeast(8192)

    private var audioTrack: AudioTrack? = null
    private var streamJob: Job? = null
    private var streaming = false

    private lateinit var btnToggle: ImageButton
    private lateinit var tvStatus:  TextView
    private lateinit var tvInfo:    TextView

    private val httpClient = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.SECONDS)   // infinite — streaming
        .connectTimeout(10, TimeUnit.SECONDS)
        .build()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_audio_stream)

        btnToggle = findViewById(R.id.btnAudioToggle)
        tvStatus  = findViewById(R.id.tvAudioStatus)
        tvInfo    = findViewById(R.id.tvAudioInfo)

        val api = IZACHApi(this)
        tvInfo.text = "PC: ${api.baseUrl()}\n22050 Hz · Mono · PCM"

        btnToggle.setOnClickListener {
            if (streaming) stopStream() else checkAndStartStream(api)
        }

        // Back button
        findViewById<View>(R.id.btnAudioBack).setOnClickListener { finish() }
    }

    private fun checkAndStartStream(api: IZACHApi) {
        tvStatus.text = "Checking backend…"
        lifecycleScope.launch {
            val info = api.getAudioStreamInfo()
            val available = info.getOrNull()?.get("available")?.toString()?.toBoolean() ?: false
            val hint      = info.getOrNull()?.get("install_hint")?.toString() ?: ""
            val backend   = info.getOrNull()?.get("backend")?.toString() ?: "none"
            if (!available) {
                tvStatus.text = "❌ No audio backend on PC"
                tvInfo.text   = "Run on PC:\nwinget install ffmpeg\n\n$hint"
                return@launch
            }
            tvInfo.text = "PC: ${api.baseUrl()}\n22050 Hz · Mono · PCM · $backend"
            startStream(api)
        }
    }

    private fun startStream(api: IZACHApi) {
        streaming = true
        btnToggle.setImageResource(R.drawable.ic_stop)
        tvStatus.text = "Connecting…"

        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(CHANNEL_CFG)
                    .setEncoding(AUDIO_FORMAT)
                    .build()
            )
            .setBufferSizeInBytes(BUFFER_SIZE)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()

        audioTrack?.play()

        streamJob = lifecycleScope.launch(Dispatchers.IO) {
            try {
                val url = "${api.baseUrl()}/audio/stream"
                val request = Request.Builder().url(url).build()
                val response = httpClient.newCall(request).execute()

                if (!response.isSuccessful) {
                    withContext(Dispatchers.Main) {
                        tvStatus.text = "Error: HTTP ${response.code}"
                        streaming = false
                        btnToggle.setImageResource(R.drawable.ic_play)
                    }
                    return@launch
                }

                withContext(Dispatchers.Main) {
                    tvStatus.text = "Streaming PC audio…"
                }

                val inputStream = response.body?.byteStream() ?: return@launch
                val buf = ByteArray(BUFFER_SIZE)

                while (isActive && streaming) {
                    val read = inputStream.read(buf, 0, buf.size)
                    if (read <= 0) break
                    audioTrack?.write(buf, 0, read)
                }

                inputStream.close()
                response.close()
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    if (streaming) tvStatus.text = "Disconnected: ${e.message?.take(40)}"
                }
            } finally {
                withContext(Dispatchers.Main) {
                    streaming = false
                    btnToggle.setImageResource(R.drawable.ic_play)
                    if (tvStatus.text == "Streaming PC audio…") tvStatus.text = "Stopped"
                }
                audioTrack?.stop()
                audioTrack?.release()
                audioTrack = null
            }
        }
    }

    private fun stopStream() {
        streaming = false
        streamJob?.cancel()
        streamJob = null
        // Tell backend to kill ffmpeg
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val api = IZACHApi(this@AudioStreamActivity)
                api.stopAudioStream()
            } catch (_: Exception) {}
        }
        tvStatus.text = "Stopped"
        btnToggle.setImageResource(R.drawable.ic_play)
    }

    override fun onDestroy() {
        super.onDestroy()
        stopStream()
    }
}
