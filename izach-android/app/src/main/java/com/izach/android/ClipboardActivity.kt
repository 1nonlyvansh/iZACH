package com.izach.android

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ActivityClipboardBinding
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class ClipboardActivity : AppCompatActivity() {

    private lateinit var binding: ActivityClipboardBinding
    private lateinit var api: IZACHApi
    private val entries = mutableListOf<Pair<String, String>>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityClipboardBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.clipTopBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        val adapter = ClipAdapter(entries) { text ->
            // Copy to phone clipboard
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("iZACH clipboard", text))
            Toast.makeText(this, "Copied to phone clipboard", Toast.LENGTH_SHORT).show()
        }

        binding.rvClipboard.layoutManager = LinearLayoutManager(this)
        binding.rvClipboard.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }

        binding.btnSendToPC.setOnClickListener {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val text = cm.primaryClip?.getItemAt(0)?.text?.toString() ?: ""
            if (text.isNotBlank()) {
                lifecycleScope.launch {
                    api.setClipboard(text).onSuccess {
                        Toast.makeText(this@ClipboardActivity, "Sent to PC clipboard", Toast.LENGTH_SHORT).show()
                    }.onFailure {
                        Toast.makeText(this@ClipboardActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            } else {
                Toast.makeText(this, "Phone clipboard is empty", Toast.LENGTH_SHORT).show()
            }
        }

        loadHistory()
    }

    private fun loadHistory() {
        lifecycleScope.launch {
            api.getClipboardHistory().onSuccess { list ->
                entries.clear()
                entries.addAll(list)
                binding.rvClipboard.adapter?.notifyDataSetChanged()
                binding.tvEmpty.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
            }
        }
    }

    class ClipAdapter(
        private val items: List<Pair<String, String>>,
        private val onCopy: (String) -> Unit
    ) : RecyclerView.Adapter<ClipAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvText: TextView = view.findViewById(android.R.id.text1)
            val tvTs: TextView = view.findViewById(android.R.id.text2)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(android.R.layout.simple_list_item_2, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val (text, ts) = items[position]
            holder.tvText.text = text.take(120)
            holder.tvText.setTextColor(0xFFc8e8f0.toInt())
            holder.tvTs.text = ts
            holder.tvTs.setTextColor(0xFF3a6070.toInt())
            holder.itemView.setBackgroundColor(0xFF071020.toInt())
            holder.itemView.setOnClickListener { onCopy(text) }
        }

        override fun getItemCount() = items.size
    }
}
