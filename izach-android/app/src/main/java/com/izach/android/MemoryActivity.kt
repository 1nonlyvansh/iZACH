package com.izach.android

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ActivityMemoryBinding
import com.izach.android.model.MemoryEntry
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class MemoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMemoryBinding
    private lateinit var api: IZACHApi
    private val entries = mutableListOf<MemoryEntry>()
    private lateinit var adapter: MemoryAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityMemoryBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        adapter = MemoryAdapter(entries) { entry -> confirmDelete(entry) }
        binding.rvMemory.layoutManager = LinearLayoutManager(this)
        binding.rvMemory.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnAdd.setOnClickListener { showAddDialog() }

        loadEntries()
    }

    private fun loadEntries() {
        lifecycleScope.launch {
            api.getMemoryEntries().onSuccess { list ->
                entries.clear()
                entries.addAll(list)
                adapter.notifyDataSetChanged()
                binding.tvEmpty.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
            }.onFailure {
                Toast.makeText(this@MemoryActivity, "Couldn't load memory: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun showAddDialog() {
        val view = layoutInflater.inflate(R.layout.dialog_memory_entry, null)
        val etKey = view.findViewById<EditText>(R.id.etKey)
        val etValue = view.findViewById<EditText>(R.id.etValue)
        AlertDialog.Builder(this)
            .setTitle("Remember something")
            .setView(view)
            .setPositiveButton("SAVE") { _, _ ->
                val key = etKey.text.toString().trim()
                val value = etValue.text.toString().trim()
                if (key.isNotEmpty() && value.isNotEmpty()) {
                    lifecycleScope.launch {
                        api.addMemoryEntry(key, value).onSuccess {
                            loadEntries()
                        }.onFailure {
                            Toast.makeText(this@MemoryActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun confirmDelete(entry: MemoryEntry) {
        AlertDialog.Builder(this)
            .setTitle("Forget this?")
            .setMessage("${entry.key}: ${entry.value}")
            .setPositiveButton("Forget") { _, _ ->
                lifecycleScope.launch {
                    api.deleteMemoryEntry(entry.key)
                    entries.remove(entry)
                    adapter.notifyDataSetChanged()
                    binding.tvEmpty.visibility = if (entries.isEmpty()) View.VISIBLE else View.GONE
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    class MemoryAdapter(
        private val items: List<MemoryEntry>,
        private val onLongPress: (MemoryEntry) -> Unit
    ) : RecyclerView.Adapter<MemoryAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tv1: TextView = view.findViewById(android.R.id.text1)
            val tv2: TextView = view.findViewById(android.R.id.text2)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(android.R.layout.simple_list_item_2, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val entry = items[position]
            holder.tv1.text = entry.key
            holder.tv1.setTextColor(0xFF00e5ff.toInt())
            holder.tv2.text = entry.value
            holder.tv2.setTextColor(0xFFc8e8f0.toInt())
            holder.itemView.setBackgroundColor(0xFF071020.toInt())
            holder.itemView.setOnLongClickListener { onLongPress(entry); true }
        }

        override fun getItemCount() = items.size
    }
}
