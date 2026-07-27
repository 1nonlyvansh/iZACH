package com.izach.android

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivityDeviceLauncherBinding
import com.izach.android.databinding.ItemLauncherDeviceBinding
import com.izach.android.model.DeviceProfile
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

/**
 * First screen on app open — a device picker, not the chat. Shows every
 * saved PC (Mac and Windows paired separately) as a card with live battery%
 * and reachability, dims/labels a card OFFLINE if it's paired but not
 * answering right now, and a "+" card to pair another PC. Tapping a card
 * switches the active connection to it and opens the chat (MainActivity).
 * Tapping a card's gear icon opens Settings scoped to that device.
 */
class DeviceLauncherActivity : AppCompatActivity() {

    private lateinit var binding: ActivityDeviceLauncherBinding
    private lateinit var api: IZACHApi

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityDeviceLauncherBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = IZACHApi(this)

        val prefs = getSharedPreferences("izach_prefs", MODE_PRIVATE)
        if (prefs.getBoolean("biometric_lock", false)) showBiometricPrompt()

        val dp4 = (4 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp4, bars.top, dp4, 0)
            insets
        }

        binding.cardAddDevice.setOnClickListener {
            startActivity(Intent(this, AddDeviceActivity::class.java))
        }
        binding.btnMenu.setOnClickListener { showSideMenu() }
    }

    private fun showSideMenu() {
        val popup = android.widget.PopupMenu(this, binding.btnMenu)
        popup.menu.add(0, 1, 0, "Command Queue")
        popup.menu.add(0, 2, 1, "Settings")
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                1 -> startActivity(Intent(this, CommandQueueActivity::class.java))
                2 -> startActivity(Intent(this, SettingsActivity::class.java))
            }
            true
        }
        popup.show()
    }

    // Moved here from MainActivity — this Activity is the actual app
    // launcher now (the device picker), so gating had to move with it.
    // Left in MainActivity, it no longer fired until AFTER a device was
    // already picked, silently leaving the picker itself (device names,
    // connection state) exposed with no lock on app open.
    private fun showBiometricPrompt() {
        val executor = ContextCompat.getMainExecutor(this)
        val prompt = BiometricPrompt(this, executor, object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {}
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) { finish() }
            override fun onAuthenticationFailed() {}
        })
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("iZACH")
            .setSubtitle("Authenticate to continue")
            .setNegativeButtonText("Cancel")
            .build()
        prompt.authenticate(info)
    }

    override fun onResume() {
        super.onResume()
        if (api.hasUnnamedActiveConnection()) {
            promptNameConnection()
        } else {
            renderDevices()
        }
    }

    private fun promptNameConnection() {
        val input = EditText(this).apply {
            hint = "e.g. Mac or Windows"
            setTextColor(getColor(R.color.text_pri))
        }
        AlertDialog.Builder(this)
            .setTitle("Name this PC")
            .setMessage("You just paired a new connection — give it a name so you can tell it apart later.")
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("Save") { _, _ ->
                val name = input.text.toString().trim().ifBlank { "My PC" }
                api.saveActiveConnectionAsProfile(name)
                renderDevices()
            }
            .show()
    }

    private fun renderDevices() {
        val profiles = api.getProfiles()
        binding.tvEmptyState.visibility = if (profiles.isEmpty()) View.VISIBLE else View.GONE
        binding.devicesContainer.removeAllViews()

        for (profile in profiles) {
            val row = ItemLauncherDeviceBinding.inflate(LayoutInflater.from(this), binding.devicesContainer, false)
            row.tvName.text = profile.name
            row.tvIcon.text = platformIcon(profile.platform)
            row.tvSubtitle.text = platformLabel(profile.platform)
            row.offlineOverlay.visibility = View.GONE
            row.tvBattery.text = ""

            row.cardRoot.setOnClickListener {
                api.switchToProfile(profile.id)
                startActivity(Intent(this, MainActivity::class.java))
            }
            row.cardRoot.setOnLongClickListener {
                showDeviceContextMenu(profile)
                true
            }
            row.btnSettings.setOnClickListener {
                api.switchToProfile(profile.id)
                startActivity(Intent(this, SettingsActivity::class.java))
            }

            binding.devicesContainer.addView(row.root)

            // Live reachability + battery, fetched per-card without touching
            // which profile is active — every card checks itself independently.
            lifecycleScope.launch {
                api.getStatusForProfile(profile).onSuccess { status ->
                    row.tvSubtitle.text = platformLabel(status.platform.ifBlank { profile.platform })
                    row.tvIcon.text = platformIcon(status.platform.ifBlank { profile.platform })
                    row.tvBattery.text = when {
                        status.batteryPct == null -> ""
                        status.batteryPlugged == true -> "⚡${status.batteryPct}%"
                        else -> "${status.batteryPct}%"
                    }
                    row.offlineOverlay.visibility = View.GONE
                }.onFailure {
                    row.offlineOverlay.visibility = View.VISIBLE
                }
            }
        }
    }

    private fun showDeviceContextMenu(profile: DeviceProfile) {
        val options = arrayOf("Rename", "Test connection now", "Remove")
        AlertDialog.Builder(this)
            .setTitle(profile.name)
            .setItems(options) { _, which ->
                when (which) {
                    0 -> promptRename(profile)
                    1 -> testConnectionNow(profile)
                    2 -> confirmRemove(profile)
                }
            }
            .show()
    }

    private fun promptRename(profile: DeviceProfile) {
        val input = EditText(this).apply {
            setText(profile.name)
            setTextColor(getColor(R.color.text_pri))
        }
        AlertDialog.Builder(this)
            .setTitle("Rename device")
            .setView(input)
            .setPositiveButton("Save") { _, _ ->
                val name = input.text.toString().trim().ifBlank { profile.name }
                api.renameProfile(profile.id, name)
                renderDevices()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun testConnectionNow(profile: DeviceProfile) {
        toast("Checking ${profile.name}…")
        lifecycleScope.launch {
            api.getStatusForProfile(profile)
                .onSuccess { toast("${profile.name}: online (${it.pcName.ifBlank { "reachable" }})") }
                .onFailure { toast("${profile.name}: unreachable right now") }
            renderDevices()
        }
    }

    private fun confirmRemove(profile: DeviceProfile) {
        AlertDialog.Builder(this)
            .setTitle("Remove ${profile.name}?")
            .setMessage("This only removes the saved shortcut on this phone — it won't affect the PC itself.")
            .setPositiveButton("Remove") { _, _ ->
                api.deleteProfile(profile.id)
                renderDevices()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun platformLabel(platform: String) = when (platform) {
        "mac" -> "macOS"
        "windows" -> "Windows"
        else -> "Tap to check"
    }

    private fun platformIcon(platform: String) = when (platform) {
        "mac" -> "🍎"
        "windows" -> "🪟"
        else -> "💻"
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
