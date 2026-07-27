package com.izach.android

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.izach.android.databinding.ActivitySearchBinding
import com.izach.android.model.Bookmark
import com.izach.android.model.CalendarEvent
import com.izach.android.model.MemoryEntry
import com.izach.android.model.Message
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

/**
 * App-wide search across the four data sources that otherwise live in
 * separate siloed screens: chat history, bookmarks, memory entries and
 * calendar events. Loads each source once, then filters client-side as
 * the user types — no per-keystroke network calls.
 */
class SearchActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySearchBinding
    private lateinit var api: IZACHApi
    private lateinit var adapter: SearchAdapter

    private var history: List<Message> = emptyList()
    private var bookmarks: List<Bookmark> = emptyList()
    private var memoryEntries: List<MemoryEntry> = emptyList()
    private var calendarEvents: List<CalendarEvent> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivitySearchBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, maxOf(ime.bottom, bars.bottom))
            insets
        }

        api = IZACHApi(this)

        adapter = SearchAdapter(emptyList())
        binding.rvResults.layoutManager = LinearLayoutManager(this)
        binding.rvResults.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }

        binding.etQuery.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) = runSearch(s?.toString().orEmpty())
        })

        binding.etQuery.requestFocus()
        loadAllSources()
    }

    private fun loadAllSources() {
        lifecycleScope.launch { api.getHistory(200).onSuccess { history = it } }
        lifecycleScope.launch { api.getBookmarks().onSuccess { bookmarks = it } }
        lifecycleScope.launch { api.getMemoryEntries().onSuccess { memoryEntries = it } }
        lifecycleScope.launch { api.getCalendarEvents().onSuccess { calendarEvents = it } }
    }

    private fun runSearch(rawQuery: String) {
        val query = rawQuery.trim()
        if (query.isBlank()) {
            adapter.update(emptyList())
            binding.tvEmpty.text = "Type to search across chat, bookmarks, memory & calendar"
            binding.tvEmpty.visibility = View.VISIBLE
            return
        }

        val results = mutableListOf<SearchResult>()

        bookmarks.filter { it.title.contains(query, true) || it.url.contains(query, true) }
            .forEach { bm ->
                results.add(SearchResult("BOOKMARK", bm.title, bm.url) {
                    startActivity(Intent(this, BookmarksActivity::class.java))
                })
            }

        memoryEntries.filter { it.key.contains(query, true) || it.value.contains(query, true) }
            .forEach { entry ->
                results.add(SearchResult("MEMORY", entry.key, entry.value) {
                    startActivity(Intent(this, MemoryActivity::class.java))
                })
            }

        calendarEvents.filter { it.title.contains(query, true) }
            .forEach { event ->
                results.add(SearchResult("CALENDAR", event.title, event.startIso) {
                    startActivity(Intent(this, CalendarActivity::class.java))
                })
            }

        history.filter { it.text.contains(query, true) }
            .forEach { msg ->
                results.add(SearchResult("CHAT", "${msg.sender}: ${msg.text.take(60)}", msg.ts) {
                    startActivity(Intent(this, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
                })
            }

        adapter.update(results)
        binding.tvEmpty.text = "No results for \"$query\""
        binding.tvEmpty.visibility = if (results.isEmpty()) View.VISIBLE else View.GONE
    }

    private data class SearchResult(
        val category: String,
        val title: String,
        val subtitle: String,
        val onClick: () -> Unit
    )

    private class SearchAdapter(
        private var items: List<SearchResult>
    ) : RecyclerView.Adapter<SearchAdapter.VH>() {

        fun update(newItems: List<SearchResult>) {
            items = newItems
            notifyDataSetChanged()
        }

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
            val item = items[position]
            holder.tv1.text = "[${item.category}] ${item.title}"
            holder.tv1.setTextColor(0xFF00e5ff.toInt())
            holder.tv2.text = item.subtitle
            holder.tv2.setTextColor(0xFF3a6070.toInt())
            holder.itemView.setBackgroundColor(0xFF071020.toInt())
            holder.itemView.setOnClickListener { item.onClick() }
        }

        override fun getItemCount() = items.size
    }
}
