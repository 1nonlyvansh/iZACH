package com.izach.android

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.izach.android.databinding.ActivityQuickShortcutsBinding
import com.izach.android.databinding.ItemShortcutBinding
import com.izach.android.model.Shortcut
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

class QuickShortcutsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityQuickShortcutsBinding
    private val shortcuts = mutableListOf<Shortcut>()
    private lateinit var adapter: ShortcutsAdapter
    private val gson = Gson()
    private lateinit var api: IZACHApi
    private var isBackground = false   // current PC ui mode

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityQuickShortcutsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = IZACHApi(this)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime  = insets.getInsets(WindowInsetsCompat.Type.ime())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, maxOf(ime.bottom, bars.bottom))
            insets
        }

        loadShortcuts()

        adapter = ShortcutsAdapter(shortcuts,
            onTap = { s ->
                startActivity(
                    Intent(this, MainActivity::class.java).apply {
                        putExtra("shortcut_command", s.command)
                        flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                    }
                )
            },
            onLongPress = { s -> showEditDialog(s) }
        )

        binding.rvShortcuts.layoutManager = GridLayoutManager(this, 3)
        binding.rvShortcuts.adapter = adapter
        binding.btnBack.setOnClickListener { finish() }
        binding.btnAdd.setOnClickListener { showAddDialog() }

        // ── System tiles ──────────────────────────────────────────
        loadBgModeState()

        binding.tileBgMode.setOnClickListener { toggleBgMode() }

        binding.tileForge.setOnClickListener {
            lifecycleScope.launch {
                binding.tvBgModeStatus.text = "SWITCHING…"
                api.setUiMode("classic").onSuccess {
                    Toast.makeText(this@QuickShortcutsActivity,
                        "Forge UI set — restart iZACH to open", Toast.LENGTH_SHORT).show()
                    isBackground = false
                    updateBgTile()
                }.onFailure {
                    Toast.makeText(this@QuickShortcutsActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }

        binding.tileCortex.setOnClickListener {
            lifecycleScope.launch {
                api.setUiMode("scifi").onSuccess {
                    Toast.makeText(this@QuickShortcutsActivity,
                        "Cortex UI set — restart iZACH to open", Toast.LENGTH_SHORT).show()
                    isBackground = false
                    updateBgTile()
                }.onFailure {
                    Toast.makeText(this@QuickShortcutsActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun loadBgModeState() {
        lifecycleScope.launch {
            api.getUiMode().onSuccess { mode ->
                isBackground = (mode == "background")
                updateBgTile()
            }
        }
    }

    private fun updateBgTile() {
        binding.tvBgModeLabel.text = if (isBackground) "BACKGROUND" else "BACKGROUND"
        binding.tvBgModeStatus.text = if (isBackground) "ACTIVE · TAP TO RESTORE" else "TAP TO ACTIVATE"
        val tileColor = if (isBackground) 0xFF00e5ff.toInt() else 0xFF3a6070.toInt()
        val bgAlpha   = if (isBackground) 0x22 else 0x0D
        binding.tvBgModeLabel.setTextColor(tileColor)
        binding.tileBgMode.setBackgroundColor(
            android.graphics.Color.argb(bgAlpha, 0x00, 0xe5, 0xff)
        )
    }

    private fun toggleBgMode() {
        if (isBackground) {
            // Already background — ask which UI to restore
            AlertDialog.Builder(this)
                .setTitle("Restore UI")
                .setMessage("Open which UI on next launch?")
                .setPositiveButton("Forge UI") { _, _ ->
                    lifecycleScope.launch {
                        api.setUiMode("classic")
                        isBackground = false
                        updateBgTile()
                        Toast.makeText(this@QuickShortcutsActivity,
                            "Forge UI set — restart iZACH to apply", Toast.LENGTH_SHORT).show()
                    }
                }
                .setNeutralButton("Cortex UI") { _, _ ->
                    lifecycleScope.launch {
                        api.setUiMode("scifi")
                        isBackground = false
                        updateBgTile()
                        Toast.makeText(this@QuickShortcutsActivity,
                            "Cortex UI set — restart iZACH to apply", Toast.LENGTH_SHORT).show()
                    }
                }
                .setNegativeButton("Cancel", null)
                .show()
        } else {
            AlertDialog.Builder(this)
                .setTitle("Activate Background Mode?")
                .setMessage("iZACH will close its window and run headless.\nVoice commands + tray icon stay active. Saves RAM.")
                .setPositiveButton("ACTIVATE") { _, _ ->
                    lifecycleScope.launch {
                        binding.tvBgModeStatus.text = "ACTIVATING…"
                        api.activateBackgroundMode().onSuccess {
                            isBackground = true
                            updateBgTile()
                            Toast.makeText(this@QuickShortcutsActivity,
                                "Background Mode activated", Toast.LENGTH_SHORT).show()
                        }.onFailure {
                            binding.tvBgModeStatus.text = "FAILED"
                            Toast.makeText(this@QuickShortcutsActivity,
                                "Error: ${it.message}", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun loadShortcuts() {
        val json = getSharedPreferences("izach_prefs", MODE_PRIVATE).getString("shortcuts", null)
        if (json != null) {
            val type = object : TypeToken<List<Shortcut>>() {}.type
            shortcuts.addAll(gson.fromJson(json, type))
        }
    }

    private fun saveShortcuts() {
        getSharedPreferences("izach_prefs", MODE_PRIVATE)
            .edit().putString("shortcuts", gson.toJson(shortcuts)).apply()
    }

    private fun showAddDialog() = showShortcutDialog(null) { label, cmd ->
        shortcuts.add(Shortcut(label, cmd))
        adapter.notifyItemInserted(shortcuts.size - 1)
        saveShortcuts()
    }

    private fun showEditDialog(s: Shortcut) {
        val idx = shortcuts.indexOf(s)
        AlertDialog.Builder(this)
            .setTitle("Shortcut")
            .setItems(arrayOf("Edit", "Delete")) { _, which ->
                if (which == 0) {
                    showShortcutDialog(s) { label, cmd ->
                        shortcuts[idx] = Shortcut(label, cmd)
                        adapter.notifyItemChanged(idx)
                        saveShortcuts()
                    }
                } else {
                    shortcuts.removeAt(idx)
                    adapter.notifyItemRemoved(idx)
                    saveShortcuts()
                }
            }.show()
    }

    private fun showShortcutDialog(existing: Shortcut?, onSave: (String, String) -> Unit) {
        val view = layoutInflater.inflate(R.layout.dialog_shortcut, null)
        val etLabel = view.findViewById<android.widget.EditText>(R.id.etLabel)
        val etCmd   = view.findViewById<android.widget.EditText>(R.id.etCommand)
        existing?.let { etLabel.setText(it.label); etCmd.setText(it.command) }
        AlertDialog.Builder(this)
            .setTitle(if (existing == null) "Add Shortcut" else "Edit Shortcut")
            .setView(view)
            .setPositiveButton("SAVE") { _, _ ->
                val label = etLabel.text.toString().trim()
                val cmd   = etCmd.text.toString().trim()
                if (label.isNotEmpty() && cmd.isNotEmpty()) onSave(label, cmd)
            }
            .setNegativeButton("CANCEL", null)
            .show()
    }
}

class ShortcutsAdapter(
    private val items: List<Shortcut>,
    private val onTap: (Shortcut) -> Unit,
    private val onLongPress: (Shortcut) -> Unit
) : RecyclerView.Adapter<ShortcutsAdapter.VH>() {

    inner class VH(val b: ItemShortcutBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(ItemShortcutBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun onBindViewHolder(holder: VH, position: Int) {
        val s = items[position]
        holder.b.tvLabel.text   = s.label
        holder.b.tvCommand.text = s.command
        holder.itemView.setOnClickListener { onTap(s) }
        holder.itemView.setOnLongClickListener { onLongPress(s); true }
    }

    override fun getItemCount() = items.size
}
