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
import com.izach.android.databinding.ActivityBookmarksBinding
import com.izach.android.databinding.ItemBookmarkBinding
import com.izach.android.model.Bookmark
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class BookmarksActivity : AppCompatActivity() {

    private lateinit var binding: ActivityBookmarksBinding
    private lateinit var api: IZACHApi
    private val bookmarks = mutableListOf<Bookmark>()
    private lateinit var adapter: BookmarksAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityBookmarksBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        adapter = BookmarksAdapter(bookmarks,
            onOpen = { bm -> openOnPc(bm) },
            onDelete = { bm -> confirmDelete(bm) }
        )
        binding.rvBookmarks.layoutManager = LinearLayoutManager(this)
        binding.rvBookmarks.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnAdd.setOnClickListener { showAddDialog() }

        loadBookmarks()
    }

    private fun loadBookmarks() {
        lifecycleScope.launch {
            api.getBookmarks().onSuccess { list ->
                bookmarks.clear()
                bookmarks.addAll(list.sortedBy { it.folder + it.title })
                adapter.notifyDataSetChanged()
                binding.tvEmpty.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
            }.onFailure {
                Toast.makeText(this@BookmarksActivity, "Couldn't load bookmarks: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun showAddDialog() {
        val view = layoutInflater.inflate(R.layout.dialog_bookmark, null)
        val etTitle = view.findViewById<EditText>(R.id.etTitle)
        val etUrl = view.findViewById<EditText>(R.id.etUrl)
        val etFolder = view.findViewById<EditText>(R.id.etFolder)
        AlertDialog.Builder(this)
            .setTitle("Add bookmark")
            .setView(view)
            .setPositiveButton("SAVE") { _, _ ->
                val title = etTitle.text.toString().trim()
                var url = etUrl.text.toString().trim()
                val folder = etFolder.text.toString().trim().ifEmpty { "General" }
                if (title.isNotEmpty() && url.isNotEmpty()) {
                    if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://$url"
                    lifecycleScope.launch {
                        api.addBookmark(title, url, folder).onSuccess {
                            loadBookmarks()
                        }.onFailure {
                            Toast.makeText(this@BookmarksActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun openOnPc(bookmark: Bookmark) {
        lifecycleScope.launch {
            api.sendCommand("open ${bookmark.url} in the browser").onSuccess {
                Toast.makeText(this@BookmarksActivity, "Opening on PC…", Toast.LENGTH_SHORT).show()
            }.onFailure {
                Toast.makeText(this@BookmarksActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun confirmDelete(bookmark: Bookmark) {
        AlertDialog.Builder(this)
            .setTitle("Delete bookmark?")
            .setMessage(bookmark.title)
            .setPositiveButton("Delete") { _, _ ->
                lifecycleScope.launch {
                    api.deleteBookmark(bookmark)
                    bookmarks.remove(bookmark)
                    adapter.notifyDataSetChanged()
                    binding.tvEmpty.visibility = if (bookmarks.isEmpty()) View.VISIBLE else View.GONE
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    class BookmarksAdapter(
        private val items: List<Bookmark>,
        private val onOpen: (Bookmark) -> Unit,
        private val onDelete: (Bookmark) -> Unit
    ) : RecyclerView.Adapter<BookmarksAdapter.VH>() {

        inner class VH(val b: ItemBookmarkBinding) : RecyclerView.ViewHolder(b.root)

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemBookmarkBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val bookmark = items[position]
            holder.b.tvTitle.text = bookmark.title
            holder.b.tvUrl.text = "${bookmark.folder} · ${bookmark.url}"
            holder.b.btnOpen.setOnClickListener { onOpen(bookmark) }
            holder.b.btnDelete.setOnClickListener { onDelete(bookmark) }
        }

        override fun getItemCount() = items.size
    }
}
