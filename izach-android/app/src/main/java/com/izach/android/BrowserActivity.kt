package com.izach.android

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.text.Editable
import android.text.TextUtils
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivityBrowserBinding
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch
import java.net.URLEncoder

/**
 * In-app multi-tab browser. Bookmarks and "open on PC" both hit the same
 * backend endpoints the desktop Electron browser already uses, so they're
 * cross-device from day one — no separate mobile bookmark store.
 */
class BrowserActivity : AppCompatActivity() {

    private lateinit var binding: ActivityBrowserBinding
    private lateinit var api: IZACHApi

    private class Tab(val id: Long, val webView: WebView) {
        var title: String = "New Tab"
        var url: String = ""
    }

    private val tabs = mutableListOf<Tab>()
    private var activeTabId: Long = -1
    private var nextTabId = 1L
    private var findBarVisible = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityBrowserBinding.inflate(layoutInflater)
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

        binding.btnBack.setOnClickListener {
            val tab = activeTab()
            if (tab != null && tab.webView.canGoBack()) tab.webView.goBack() else finish()
        }
        binding.btnForward.setOnClickListener {
            activeTab()?.webView?.let { wv -> if (wv.canGoForward()) wv.goForward() }
        }
        binding.btnReload.setOnClickListener { activeTab()?.webView?.reload() }
        binding.btnMenu.setOnClickListener { showMenu(it) }
        binding.btnNewTab.setOnClickListener { openTab(DEFAULT_URL, select = true) }

        binding.etAddress.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_GO || actionId == EditorInfo.IME_ACTION_SEARCH ||
                actionId == EditorInfo.IME_ACTION_DONE
            ) {
                loadFromAddressBar()
                true
            } else false
        }

        binding.btnFindClose.setOnClickListener { toggleFindBar(false) }
        binding.btnFindUp.setOnClickListener { activeTab()?.webView?.findNext(false) }
        binding.btnFindDown.setOnClickListener { activeTab()?.webView?.findNext(true) }
        binding.etFind.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                activeTab()?.webView?.findAllAsync(s?.toString().orEmpty())
            }
        })

        val startUrl = intent.getStringExtra(EXTRA_URL)?.takeIf { it.isNotBlank() } ?: DEFAULT_URL
        openTab(startUrl, select = true)
    }

    private fun activeTab(): Tab? = tabs.find { it.id == activeTabId }

    @SuppressLint("SetJavaScriptEnabled")
    private fun openTab(url: String, select: Boolean) {
        val webView = WebView(this)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = true
            displayZoomControls = false
            safeBrowsingEnabled = true
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        val tab = Tab(nextTabId++, webView)

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url.toString()
                if (!u.startsWith("http://") && !u.startsWith("https://")) {
                    return try {
                        startActivity(Intent(Intent.ACTION_VIEW, request.url))
                        true
                    } catch (e: ActivityNotFoundException) {
                        true
                    }
                }
                return false
            }

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                tab.url = url ?: tab.url
                if (tab.id == activeTabId) {
                    binding.progressBar.visibility = View.VISIBLE
                    binding.etAddress.setText(tab.url)
                    if (findBarVisible) toggleFindBar(false)
                }
                refreshTabStrip()
            }

            override fun onPageFinished(view: WebView, url: String?) {
                tab.url = url ?: tab.url
                if (tab.id == activeTabId) {
                    binding.progressBar.visibility = View.GONE
                    binding.etAddress.setText(tab.url)
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                if (tab.id == activeTabId) binding.progressBar.progress = newProgress
            }

            override fun onReceivedTitle(view: WebView, title: String?) {
                tab.title = title?.takeIf { it.isNotBlank() } ?: tab.url
                refreshTabStrip()
                logHistory(tab.url, tab.title)
            }
        }

        webView.setFindListener { activeMatchOrdinal, numberOfMatches, isDoneCounting ->
            if (isDoneCounting) {
                binding.tvFindCount.text = if (numberOfMatches == 0) "0/0" else "${activeMatchOrdinal + 1}/$numberOfMatches"
            }
        }

        webView.setDownloadListener { dUrl, _, contentDisposition, mimeType, _ ->
            try {
                val request = DownloadManager.Request(Uri.parse(dUrl))
                request.addRequestHeader("cookie", CookieManager.getInstance().getCookie(dUrl))
                val fileName = URLUtil.guessFileName(dUrl, contentDisposition, mimeType)
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName)
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(request)
                toast("Downloading $fileName…")
            } catch (e: Exception) {
                toast("Download failed: ${e.message}")
            }
        }

        webView.loadUrl(url)
        tab.url = url
        tabs.add(tab)
        if (select) selectTab(tab.id)
        refreshTabStrip()
    }

    private fun selectTab(id: Long) {
        if (findBarVisible) toggleFindBar(false)
        activeTabId = id
        val tab = activeTab() ?: return
        (tab.webView.parent as? ViewGroup)?.removeView(tab.webView)
        binding.webContainer.removeAllViews()
        binding.webContainer.addView(
            tab.webView,
            FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
        )
        binding.etAddress.setText(tab.url)
        refreshTabStrip()
    }

    private fun closeTab(id: Long) {
        val idx = tabs.indexOfFirst { it.id == id }
        if (idx < 0) return
        val tab = tabs.removeAt(idx)
        (tab.webView.parent as? ViewGroup)?.removeView(tab.webView)
        tab.webView.destroy()
        if (tabs.isEmpty()) {
            finish()
            return
        }
        if (activeTabId == id) {
            selectTab(tabs[idx.coerceAtMost(tabs.size - 1)].id)
        } else {
            refreshTabStrip()
        }
    }

    private fun refreshTabStrip() {
        pushTabsSnapshot()
        binding.tabStrip.removeAllViews()
        val dp = resources.displayMetrics.density
        tabs.forEach { tab ->
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding((10 * dp).toInt(), (4 * dp).toInt(), (4 * dp).toInt(), (4 * dp).toInt())
                setBackgroundColor(if (tab.id == activeTabId) 0xFF0a1628.toInt() else 0xFF071020.toInt())
                setOnClickListener { selectTab(tab.id) }
            }
            val tv = TextView(this).apply {
                text = tab.title.take(18)
                setTextColor(if (tab.id == activeTabId) 0xFF00e5ff.toInt() else 0xFFc8e8f0.toInt())
                textSize = 12f
                typeface = Typeface.MONOSPACE
                maxWidth = (120 * dp).toInt()
                ellipsize = TextUtils.TruncateAt.END
                setSingleLine()
            }
            val close = ImageButton(this).apply {
                setImageResource(R.drawable.ic_task_failed)
                background = null
                layoutParams = LinearLayout.LayoutParams((26 * dp).toInt(), (26 * dp).toInt()).apply {
                    marginStart = (6 * dp).toInt()
                }
                contentDescription = "Close tab"
                setOnClickListener { closeTab(tab.id) }
            }
            row.addView(tv)
            row.addView(close)
            binding.tabStrip.addView(row)
        }
    }

    private fun loadFromAddressBar() {
        val input = binding.etAddress.text.toString().trim()
        if (input.isBlank()) return
        val url = normalizeUrl(input)
        val tab = activeTab()
        if (tab != null) tab.webView.loadUrl(url) else openTab(url, select = true)
        binding.etAddress.clearFocus()
        hideKeyboard()
    }

    private fun normalizeUrl(input: String): String {
        val looksLikeUrl = input.contains(".") && !input.contains(" ")
        return when {
            input.startsWith("http://") || input.startsWith("https://") -> input
            looksLikeUrl -> "https://$input"
            else -> "https://www.google.com/search?q=" + URLEncoder.encode(input, "UTF-8")
        }
    }

    private fun hideKeyboard() {
        val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(binding.etAddress.windowToken, 0)
    }

    private fun toggleFindBar(show: Boolean) {
        findBarVisible = show
        binding.findBar.visibility = if (show) View.VISIBLE else View.GONE
        if (show) {
            binding.etFind.requestFocus()
        } else {
            binding.etFind.setText("")
            activeTab()?.webView?.clearMatches()
        }
    }

    private fun showMenu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menu.add(0, 1, 0, "Find in page")
        popup.menu.add(0, 2, 1, "Bookmark this page")
        popup.menu.add(0, 3, 2, "Open on PC")
        popup.menu.add(0, 4, 3, "Share link")
        popup.menu.add(0, 5, 4, "History")
        popup.menu.add(0, 6, 5, "Autofill on PC")
        popup.menu.add(0, 7, 6, "Tabs from PC")
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                1 -> toggleFindBar(true)
                2 -> bookmarkCurrentPage()
                3 -> openOnPc()
                4 -> shareCurrentPage()
                5 -> showHistory()
                6 -> requestAutofillOnPc()
                7 -> showTabsFromPc()
            }
            true
        }
        popup.show()
    }

    private fun bookmarkCurrentPage() {
        val tab = activeTab() ?: return
        val title = tab.title.ifBlank { tab.url }
        val url = tab.url
        if (url.isBlank()) return
        lifecycleScope.launch {
            api.addBookmark(title, url, "Mobile Browser")
                .onSuccess { toast("Bookmarked!") }
                .onFailure { toast("Failed: ${it.message}") }
        }
    }

    private fun openOnPc() {
        val url = activeTab()?.url?.takeIf { it.isNotBlank() } ?: return
        lifecycleScope.launch {
            api.sendCommand("open $url in the browser")
                .onSuccess { toast("Opening on PC…") }
                .onFailure { toast("Failed: ${it.message}") }
        }
    }

    // Only the URL is sent — the PC looks up the saved login, re-verifies with
    // the OS's platform authenticator (Windows Hello / Touch ID), and fills
    // the page itself. No credential ever reaches this phone or crosses the
    // network.
    private fun requestAutofillOnPc() {
        val url = activeTab()?.url?.takeIf { it.isNotBlank() } ?: return
        val authName = if (api.activePlatform() == "mac") "Touch ID" else "Windows Hello"
        lifecycleScope.launch {
            api.requestAutofillOnPc(url)
                .onSuccess { toast("Requested — approve with $authName on your PC") }
                .onFailure { toast("Failed: ${it.message}") }
        }
    }

    private fun shareCurrentPage() {
        val url = activeTab()?.url?.takeIf { it.isNotBlank() } ?: return
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, url)
        }, "Share via"))
    }

    private fun logHistory(url: String, title: String) {
        if (url.isBlank() || url == "about:blank") return
        lifecycleScope.launch { api.addBrowserHistoryEntry(url, title) }
    }

    // Pushes the FULL current tab list (not an append) every time it changes,
    // so the PC's "Tabs from Phone" picker always matches what's actually open.
    private fun pushTabsSnapshot() {
        val snapshot = tabs
            .map { it.url to it.title }
            .filter { (url, _) -> url.isNotBlank() && url != "about:blank" }
        lifecycleScope.launch { api.pushOpenTabs(snapshot) }
    }

    private fun showHistory() {
        lifecycleScope.launch {
            api.getBrowserHistory().onSuccess { entries ->
                if (entries.isEmpty()) {
                    toast("No browsing history yet")
                    return@onSuccess
                }
                val labels = entries.map { e ->
                    val deviceTag = if (e.device == "pc") "PC" else e.device
                    "[$deviceTag] ${e.title.ifBlank { e.url }}"
                }.toTypedArray()
                AlertDialog.Builder(this@BrowserActivity)
                    .setTitle("History (synced with PC)")
                    .setItems(labels) { _, which -> openTab(entries[which].url, select = true) }
                    .setNegativeButton("CLOSE", null)
                    .show()
            }.onFailure { toast("Couldn't load history: ${it.message}") }
        }
    }

    private fun showTabsFromPc() {
        lifecycleScope.launch {
            api.getOtherDeviceTabs().onSuccess { entries ->
                if (entries.isEmpty()) {
                    toast("No open tabs on other devices right now")
                    return@onSuccess
                }
                val labels = entries.map { e -> "[${e.device}] ${e.title.ifBlank { e.url }}" }.toTypedArray()
                AlertDialog.Builder(this@BrowserActivity)
                    .setTitle("Continue a tab from PC")
                    .setItems(labels) { _, which -> openTab(entries[which].url, select = true) }
                    .setNegativeButton("CLOSE", null)
                    .show()
            }.onFailure { toast("Couldn't load PC tabs: ${it.message}") }
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    override fun onBackPressed() {
        if (findBarVisible) {
            toggleFindBar(false)
            return
        }
        val tab = activeTab()
        if (tab != null && tab.webView.canGoBack()) tab.webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        super.onDestroy()
        tabs.forEach { it.webView.destroy() }
    }

    companion object {
        const val EXTRA_URL = "url"
        private const val DEFAULT_URL = "https://www.google.com"
    }
}
