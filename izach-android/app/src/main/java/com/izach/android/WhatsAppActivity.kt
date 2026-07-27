package com.izach.android

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ActivityWhatsappBinding
import com.izach.android.databinding.ItemWaChatBinding
import com.izach.android.model.WaChatSummary
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class WhatsAppActivity : AppCompatActivity() {

    private lateinit var binding: ActivityWhatsappBinding
    private lateinit var api: IZACHApi
    private val chats = mutableListOf<WaChatSummary>()
    private lateinit var adapter: ChatsAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityWhatsappBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        adapter = ChatsAdapter(chats) { chat ->
            startActivity(
                Intent(this, WhatsAppThreadActivity::class.java)
                    .putExtra("number", chat.number)
                    .putExtra("name", chat.name)
            )
        }
        binding.rvChats.layoutManager = LinearLayoutManager(this)
        binding.rvChats.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnRefresh.setOnClickListener { loadChats() }

        loadChats()
    }

    override fun onResume() {
        super.onResume()
        loadChats()
    }

    private fun loadChats() {
        lifecycleScope.launch {
            api.getWaRecentChats().onSuccess { list ->
                chats.clear()
                chats.addAll(list)
                adapter.notifyDataSetChanged()
                binding.tvEmpty.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
            }.onFailure {
                Toast.makeText(this@WhatsAppActivity, "Couldn't load chats: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    class ChatsAdapter(
        private val items: List<WaChatSummary>,
        private val onTap: (WaChatSummary) -> Unit
    ) : RecyclerView.Adapter<ChatsAdapter.VH>() {

        inner class VH(val b: ItemWaChatBinding) : RecyclerView.ViewHolder(b.root)

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemWaChatBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val chat = items[position]
            holder.b.tvName.text = chat.name
            holder.b.tvLastText.text = chat.lastText
            holder.b.tvTime.text = if (chat.timestamp > 0) {
                SimpleDateFormat("h:mm a", Locale.getDefault()).format(Date(chat.timestamp * 1000))
            } else ""
            holder.itemView.setOnClickListener { onTap(chat) }
        }

        override fun getItemCount() = items.size
    }
}
