package com.izach.android

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
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
import com.izach.android.databinding.ActivityNewsBinding
import com.izach.android.databinding.ItemNewsBinding
import com.izach.android.model.NewsHeadline
import kotlinx.coroutines.launch
import com.izach.android.network.IZACHApi

class NewsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityNewsBinding
    private lateinit var api: IZACHApi
    private val headlines = mutableListOf<NewsHeadline>()
    private lateinit var adapter: NewsAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityNewsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        adapter = NewsAdapter(headlines) { headline ->
            if (headline.link.isNotBlank()) {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(headline.link)))
                } catch (e: Exception) {
                    Toast.makeText(this, "Couldn't open link", Toast.LENGTH_SHORT).show()
                }
            }
        }
        binding.rvHeadlines.layoutManager = LinearLayoutManager(this)
        binding.rvHeadlines.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnRefresh.setOnClickListener { loadAll() }

        loadAll()
    }

    private fun loadAll() {
        lifecycleScope.launch {
            api.getNewsHeadlines().onSuccess { list ->
                headlines.clear()
                headlines.addAll(list)
                adapter.notifyDataSetChanged()
            }.onFailure {
                Toast.makeText(this@NewsActivity, "Couldn't load news: ${it.message}", Toast.LENGTH_SHORT).show()
            }
            api.getMarketIndices().onSuccess { indices -> renderMarket(indices) }
        }
    }

    private fun renderMarket(indices: List<com.izach.android.model.MarketIndex>) {
        binding.marketContainer.removeAllViews()
        val dp = resources.displayMetrics.density
        indices.forEach { idx ->
            val tv = TextView(this).apply {
                text = "${idx.label}\n${idx.price}  (${if (idx.pct >= 0) "+" else ""}${idx.pct}%)"
                setTextColor(if (idx.pct >= 0) 0xFF1db954.toInt() else 0xFFff3d3d.toInt())
                textSize = 11f
                typeface = android.graphics.Typeface.MONOSPACE
                setPadding((10 * dp).toInt(), (8 * dp).toInt(), (10 * dp).toInt(), (8 * dp).toInt())
                setBackgroundResource(R.drawable.bg_shortcut_tile)
            }
            val lp = android.widget.LinearLayout.LayoutParams(
                android.widget.LinearLayout.LayoutParams.WRAP_CONTENT,
                android.widget.LinearLayout.LayoutParams.WRAP_CONTENT
            )
            lp.marginEnd = (8 * dp).toInt()
            binding.marketContainer.addView(tv, lp)
        }
    }

    class NewsAdapter(
        private val items: List<NewsHeadline>,
        private val onTap: (NewsHeadline) -> Unit
    ) : RecyclerView.Adapter<NewsAdapter.VH>() {

        inner class VH(val b: ItemNewsBinding) : RecyclerView.ViewHolder(b.root)

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemNewsBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val headline = items[position]
            holder.b.tvTitle.text = headline.title
            holder.b.tvSource.text = "${headline.source} · ${headline.published}"
            holder.itemView.setOnClickListener { onTap(headline) }
        }

        override fun getItemCount() = items.size
    }
}
