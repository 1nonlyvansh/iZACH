package com.izach.android

import android.os.Bundle
import android.view.Gravity
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ActivityWhatsappThreadBinding
import com.izach.android.databinding.ItemWaMessageBinding
import com.izach.android.model.WaThreadMessage
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class WhatsAppThreadActivity : AppCompatActivity() {

    private lateinit var binding: ActivityWhatsappThreadBinding
    private lateinit var api: IZACHApi
    private val messages = mutableListOf<WaThreadMessage>()
    private lateinit var adapter: MessagesAdapter
    private var number: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityWhatsappThreadBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime  = insets.getInsets(WindowInsetsCompat.Type.ime())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.replyBar.setPadding(dp8, dp8, dp8, dp8 + maxOf(ime.bottom, bars.bottom))
            insets
        }

        api = IZACHApi(this)

        number = intent.getStringExtra("number") ?: ""
        val name = intent.getStringExtra("name") ?: number
        binding.tvContactName.text = name

        adapter = MessagesAdapter(messages)
        binding.rvMessages.layoutManager = LinearLayoutManager(this)
        binding.rvMessages.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnSend.setOnClickListener { sendReply(name) }

        loadThread()
    }

    private fun loadThread() {
        if (number.isEmpty()) return
        lifecycleScope.launch {
            api.getWaThread(number).onSuccess { list ->
                messages.clear()
                messages.addAll(list.sortedBy { it.timestamp })
                adapter.notifyDataSetChanged()
                if (messages.isNotEmpty()) binding.rvMessages.scrollToPosition(messages.size - 1)
            }.onFailure {
                Toast.makeText(this@WhatsAppThreadActivity, "Couldn't load thread: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun sendReply(name: String) {
        val text = binding.etReply.text.toString().trim()
        if (text.isEmpty() || number.isEmpty()) return
        binding.etReply.setText("")
        lifecycleScope.launch {
            api.waSendMessage(number, text, name).onSuccess { ok ->
                if (ok) {
                    loadThread()
                } else {
                    Toast.makeText(this@WhatsAppThreadActivity, "Send failed.", Toast.LENGTH_SHORT).show()
                }
            }.onFailure {
                Toast.makeText(this@WhatsAppThreadActivity, "Send failed: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    class MessagesAdapter(
        private val items: List<WaThreadMessage>
    ) : RecyclerView.Adapter<MessagesAdapter.VH>() {

        inner class VH(val b: ItemWaMessageBinding) : RecyclerView.ViewHolder(b.root)

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemWaMessageBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val msg = items[position]
            holder.b.tvMessage.text = msg.text
            val params = holder.b.tvMessage.layoutParams as FrameLayout.LayoutParams
            if (msg.fromMe) {
                params.gravity = Gravity.END
                holder.b.tvMessage.setBackgroundResource(R.drawable.bg_input)
                holder.b.tvMessage.setTextColor(0xFF00e5ff.toInt())
            } else {
                params.gravity = Gravity.START
                holder.b.tvMessage.setBackgroundResource(R.drawable.bg_shortcut_tile)
                holder.b.tvMessage.setTextColor(0xFFc8e8f0.toInt())
            }
            holder.b.tvMessage.layoutParams = params
        }

        override fun getItemCount() = items.size
    }
}
