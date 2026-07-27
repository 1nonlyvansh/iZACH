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
import com.izach.android.databinding.ActivityCalendarBinding
import com.izach.android.model.CalendarEvent
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

class CalendarActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCalendarBinding
    private lateinit var api: IZACHApi
    private val events = mutableListOf<CalendarEvent>()
    private lateinit var adapter: EventsAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityCalendarBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        adapter = EventsAdapter(events) { event -> confirmDelete(event) }
        binding.rvEvents.layoutManager = LinearLayoutManager(this)
        binding.rvEvents.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnRefresh.setOnClickListener { loadEvents() }

        loadEvents()
    }

    private fun loadEvents() {
        lifecycleScope.launch {
            api.getCalendarEvents().onSuccess { list ->
                events.clear()
                events.addAll(list)
                adapter.notifyDataSetChanged()
                binding.tvEmpty.visibility = if (list.isEmpty()) android.view.View.VISIBLE else android.view.View.GONE
            }.onFailure {
                Toast.makeText(this@CalendarActivity, "Couldn't load calendar: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun confirmDelete(event: CalendarEvent) {
        AlertDialog.Builder(this)
            .setTitle("Cancel event?")
            .setMessage(event.title)
            .setPositiveButton("Cancel event") { _, _ ->
                lifecycleScope.launch {
                    api.deleteCalendarEvent(event.id).onSuccess { ok ->
                        if (ok) {
                            events.remove(event)
                            adapter.notifyDataSetChanged()
                        } else {
                            Toast.makeText(this@CalendarActivity, "Failed to cancel", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
            .setNegativeButton("Keep", null)
            .show()
    }

    companion object {
        fun formatEvent(event: CalendarEvent): Pair<String, String> {
            return if (event.allDay) {
                val date = try { LocalDate.parse(event.startIso) } catch (_: DateTimeParseException) { null }
                Pair(event.title, date?.format(DateTimeFormatter.ofPattern("EEE, MMM d")) ?: "All day")
            } else {
                val dt = try { OffsetDateTime.parse(event.startIso) } catch (_: DateTimeParseException) { null }
                val formatted = dt?.format(DateTimeFormatter.ofPattern("EEE, MMM d · h:mm a")) ?: event.startIso
                Pair(event.title, formatted)
            }
        }
    }

    class EventsAdapter(
        private val items: List<CalendarEvent>,
        private val onLongPress: (CalendarEvent) -> Unit
    ) : RecyclerView.Adapter<EventsAdapter.VH>() {

        inner class VH(view: android.view.View) : RecyclerView.ViewHolder(view) {
            val tv1: android.widget.TextView = view.findViewById(android.R.id.text1)
            val tv2: android.widget.TextView = view.findViewById(android.R.id.text2)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(android.R.layout.simple_list_item_2, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val event = items[position]
            val (title, subtitle) = formatEvent(event)
            holder.tv1.text = title
            holder.tv1.setTextColor(0xFFc8e8f0.toInt())
            holder.tv2.text = subtitle
            holder.tv2.setTextColor(0xFF00e5ff.toInt())
            holder.itemView.setBackgroundColor(0xFF071020.toInt())
            holder.itemView.setOnLongClickListener { onLongPress(event); true }
        }

        override fun getItemCount() = items.size
    }
}
