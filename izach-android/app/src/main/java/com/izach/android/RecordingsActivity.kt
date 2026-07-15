package com.izach.android

import android.os.Bundle
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ActivityRecordingsBinding
import com.izach.android.databinding.ItemRecordingBinding
import com.izach.android.model.Recording
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class RecordingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityRecordingsBinding
    private lateinit var api: IZACHApi
    private val recordings = mutableListOf<Recording>()
    private lateinit var adapter: RecordingsAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityRecordingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        adapter = RecordingsAdapter(recordings,
            onPlay = { rec -> runRecording(rec) },
            onDelete = { rec -> confirmDelete(rec) }
        )
        binding.rvRecordings.layoutManager = LinearLayoutManager(this)
        binding.rvRecordings.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }

        loadRecordings()
    }

    private fun loadRecordings() {
        lifecycleScope.launch {
            api.getRecordings().onSuccess { list ->
                recordings.clear()
                recordings.addAll(list)
                adapter.notifyDataSetChanged()
                binding.tvEmpty.visibility = if (list.isEmpty()) android.view.View.VISIBLE else android.view.View.GONE
            }.onFailure {
                Toast.makeText(this@RecordingsActivity, "Couldn't load recordings: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun runRecording(rec: Recording) {
        Toast.makeText(this, "Replaying \"${rec.name}\"…", Toast.LENGTH_SHORT).show()
        lifecycleScope.launch {
            api.replayRecording(rec.name).onSuccess { (ok, summary) ->
                Toast.makeText(this@RecordingsActivity, summary, if (ok) Toast.LENGTH_SHORT else Toast.LENGTH_LONG).show()
            }.onFailure {
                Toast.makeText(this@RecordingsActivity, "Replay failed: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun confirmDelete(rec: Recording) {
        AlertDialog.Builder(this)
            .setTitle("Delete recording?")
            .setMessage(rec.name)
            .setPositiveButton("Delete") { _, _ ->
                lifecycleScope.launch {
                    api.deleteRecording(rec.name)
                    recordings.remove(rec)
                    adapter.notifyDataSetChanged()
                    binding.tvEmpty.visibility = if (recordings.isEmpty()) android.view.View.VISIBLE else android.view.View.GONE
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    class RecordingsAdapter(
        private val items: List<Recording>,
        private val onPlay: (Recording) -> Unit,
        private val onDelete: (Recording) -> Unit
    ) : RecyclerView.Adapter<RecordingsAdapter.VH>() {

        inner class VH(val b: ItemRecordingBinding) : RecyclerView.ViewHolder(b.root)

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemRecordingBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val rec = items[position]
            holder.b.tvName.text = rec.name
            val schedulePart = if (rec.scheduleCron.isNotBlank()) " · scheduled" else ""
            holder.b.tvMeta.text = "${rec.steps} steps$schedulePart"
            if (rec.triggerPhrases.isNotEmpty()) {
                holder.b.tvTriggers.visibility = android.view.View.VISIBLE
                holder.b.tvTriggers.text = rec.triggerPhrases.joinToString(", ") { "\"$it\"" }
            } else {
                holder.b.tvTriggers.visibility = android.view.View.GONE
            }
            holder.b.btnPlay.setOnClickListener { onPlay(rec) }
            holder.b.btnDelete.setOnClickListener { onDelete(rec) }
        }

        override fun getItemCount() = items.size
    }
}
