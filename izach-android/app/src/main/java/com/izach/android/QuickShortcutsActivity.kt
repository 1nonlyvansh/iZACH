package com.izach.android

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.izach.android.databinding.ActivityQuickShortcutsBinding
import com.izach.android.databinding.ItemShortcutBinding
import com.izach.android.model.Shortcut

class QuickShortcutsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityQuickShortcutsBinding
    private val shortcuts = mutableListOf<Shortcut>()
    private lateinit var adapter: ShortcutsAdapter
    private val gson = Gson()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityQuickShortcutsBinding.inflate(layoutInflater)
        setContentView(binding.root)

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
