package com.izach.android

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ActivityAutomationsBinding
import com.izach.android.databinding.ItemAutomationBinding
import com.izach.android.model.Automation
import com.izach.android.model.SchedulerJob
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class AutomationsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAutomationsBinding
    private lateinit var api: IZACHApi
    private val automations = mutableListOf<Automation>()
    private var jobs: List<SchedulerJob> = emptyList()
    private lateinit var adapter: AutomationsAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityAutomationsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        adapter = AutomationsAdapter(
            items = automations,
            jobsProvider = { jobs },
            onToggle = { automation, enabled -> toggleAutomation(automation, enabled) },
            onDelete = { automation -> confirmDelete(automation) }
        )
        binding.rvAutomations.layoutManager = LinearLayoutManager(this)
        binding.rvAutomations.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnAdd.setOnClickListener { showAddDialog() }

        loadAutomations()
    }

    private fun loadAutomations() {
        lifecycleScope.launch {
            api.getAutomations().onSuccess { list ->
                automations.clear()
                automations.addAll(list)
                adapter.notifyDataSetChanged()
                binding.tvEmpty.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
            }.onFailure {
                Toast.makeText(this@AutomationsActivity, "Couldn't load automations: ${it.message}", Toast.LENGTH_SHORT).show()
            }
            api.getSchedulerJobs().onSuccess { list ->
                jobs = list
                adapter.notifyDataSetChanged()
            }
        }
    }

    private fun showAddDialog() {
        val et = EditText(this).apply {
            hint = "e.g. remind me to drink water every day at 5pm"
            setPadding(48, 32, 48, 32)
        }
        AlertDialog.Builder(this)
            .setTitle("New automation")
            .setView(et)
            .setPositiveButton("SAVE") { _, _ ->
                val content = et.text.toString().trim()
                if (content.isNotEmpty()) {
                    lifecycleScope.launch {
                        api.addAutomation(content).onSuccess {
                            loadAutomations()
                        }.onFailure {
                            Toast.makeText(this@AutomationsActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun toggleAutomation(automation: Automation, enabled: Boolean) {
        lifecycleScope.launch {
            api.setAutomationEnabled(automation.id, enabled)
        }
    }

    private fun confirmDelete(automation: Automation) {
        AlertDialog.Builder(this)
            .setTitle("Delete automation?")
            .setMessage(automation.content)
            .setPositiveButton("Delete") { _, _ ->
                lifecycleScope.launch {
                    api.deleteAutomation(automation.id)
                    automations.remove(automation)
                    adapter.notifyDataSetChanged()
                    binding.tvEmpty.visibility = if (automations.isEmpty()) View.VISIBLE else View.GONE
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    class AutomationsAdapter(
        private val items: List<Automation>,
        private val jobsProvider: () -> List<SchedulerJob>,
        private val onToggle: (Automation, Boolean) -> Unit,
        private val onDelete: (Automation) -> Unit
    ) : RecyclerView.Adapter<AutomationsAdapter.VH>() {

        inner class VH(val b: ItemAutomationBinding) : RecyclerView.ViewHolder(b.root)

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemAutomationBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val automation = items[position]
            holder.b.tvContent.text = automation.content
            val job = jobsProvider().find { it.id == "mem_${automation.id}" }
            if (automation.cron.isNotBlank() || job != null) {
                holder.b.tvSchedule.visibility = View.VISIBLE
                holder.b.tvSchedule.text = if (job != null) "Next run: ${job.nextRun}" else "cron: ${automation.cron}"
            } else {
                holder.b.tvSchedule.visibility = View.GONE
            }
            holder.b.switchEnabled.setOnCheckedChangeListener(null)
            holder.b.switchEnabled.isChecked = automation.enabled
            holder.b.switchEnabled.setOnCheckedChangeListener { _, checked -> onToggle(automation, checked) }
            holder.b.btnDelete.setOnClickListener { onDelete(automation) }
        }

        override fun getItemCount() = items.size
    }
}
