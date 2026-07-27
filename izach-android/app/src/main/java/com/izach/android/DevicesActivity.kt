package com.izach.android

import android.os.Bundle
import android.view.LayoutInflater
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivityDevicesBinding
import com.izach.android.databinding.ItemDeviceProfileBinding
import com.izach.android.model.DeviceProfile
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.launch

/**
 * "Which device is this phone talking to, and what's its peer?" — shows this
 * connection's platform + role, the paired peer's platform + role (via
 * /peer/local), a one-tap handoff button, and the saved-connections list so
 * the phone can be paired to Mac and Windows separately and switch between
 * them without re-scanning a QR code each time.
 */
class DevicesActivity : AppCompatActivity() {

    private lateinit var binding: ActivityDevicesBinding
    private lateinit var api: IZACHApi
    private var peerPlatform: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityDevicesBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = IZACHApi(this)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            insets
        }

        binding.btnBack.setOnClickListener { finish() }
        binding.btnHandoff.setOnClickListener { confirmHandoff() }
        binding.btnSaveCurrentAsProfile.setOnClickListener { promptSaveProfile() }

        refresh()
    }

    override fun onResume() {
        super.onResume()
        renderProfiles()
    }

    private fun refresh() {
        lifecycleScope.launch {
            api.getSystemStatus().onSuccess { status ->
                binding.tvThisDeviceName.text = status.pcName.ifBlank { "This PC" }
                binding.tvThisDevicePlatform.text = platformLabel(status.platform)
                binding.tvThisDeviceIcon.text = platformIcon(status.platform)
            }.onFailure {
                binding.tvThisDevicePlatform.text = "Unreachable"
            }

            api.getPeerLocal().onSuccess { peer ->
                peerPlatform = peer.peerPlatform
                binding.tvThisDeviceRole.text = peer.role.uppercase()
                binding.tvThisDeviceRole.setTextColor(
                    getColor(if (peer.role == "primary") R.color.green_neon else R.color.amber)
                )
                if (!peer.configured || peer.peerHostname == null) {
                    binding.tvPeerName.text = "No peer configured"
                    binding.tvPeerPlatform.text = ""
                    binding.tvPeerRole.text = ""
                    binding.btnHandoff.isEnabled = false
                    binding.btnHandoff.alpha = 0.4f
                } else {
                    binding.tvPeerName.text = peer.peerHostname
                    binding.tvPeerPlatform.text = platformLabel(peer.peerPlatform ?: "")
                    binding.tvPeerIcon.text = platformIcon(peer.peerPlatform ?: "")
                    binding.tvPeerRole.text = (peer.peerRole ?: "").uppercase()
                    binding.btnHandoff.isEnabled = true
                    binding.btnHandoff.alpha = 1f
                    binding.btnHandoff.text = "HAND OFF TO ${(peer.peerPlatform ?: "PEER").uppercase()}"
                }
            }.onFailure {
                binding.tvPeerName.text = "Couldn't check — dual-instance not set up?"
                binding.btnHandoff.isEnabled = false
                binding.btnHandoff.alpha = 0.4f
            }
        }
    }

    private fun platformLabel(platform: String) = when (platform) {
        "mac" -> "macOS"
        "windows" -> "Windows"
        else -> "Unknown"
    }

    private fun platformIcon(platform: String) = when (platform) {
        "mac" -> "🍎"
        "windows" -> "🪟"
        else -> "💻"
    }

    private fun confirmHandoff() {
        val target = peerPlatform ?: return
        AlertDialog.Builder(this)
            .setTitle("Hand off?")
            .setMessage("This will make ${platformLabel(target)} the primary device. Restart iZACH there to finish.")
            .setPositiveButton("Hand Off") { _, _ ->
                lifecycleScope.launch {
                    api.triggerHandoff(target)
                        .onSuccess { toast("Handoff sent") }
                        .onFailure { toast("Failed: ${it.message}") }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ── Saved connections ──────────────────────────────────────────
    private fun renderProfiles() {
        binding.profilesContainer.removeAllViews()
        val activeId = api.activeProfileId()
        for (profile in api.getProfiles()) {
            val row = ItemDeviceProfileBinding.inflate(LayoutInflater.from(this), binding.profilesContainer, false)
            row.tvProfileIcon.text = platformIcon(profile.platform)
            row.tvProfileName.text = profile.name
            row.tvProfileUrl.text = profile.backendUrl
            val isActive = profile.id == activeId
            row.tvProfileActive.visibility = if (isActive) android.view.View.VISIBLE else android.view.View.GONE
            row.btnProfileConnect.isEnabled = !isActive
            row.btnProfileConnect.text = if (isActive) "CONNECTED" else "CONNECT"
            row.btnProfileConnect.setOnClickListener {
                api.switchToProfile(profile.id)
                toast("Switched to ${profile.name}. Restart app to fully apply.")
                renderProfiles()
                refresh()
            }
            row.btnProfileDelete.setOnClickListener {
                AlertDialog.Builder(this)
                    .setTitle("Remove ${profile.name}?")
                    .setMessage("This only removes the saved shortcut — it won't affect the PC itself.")
                    .setPositiveButton("Remove") { _, _ ->
                        api.deleteProfile(profile.id)
                        renderProfiles()
                    }
                    .setNegativeButton("Cancel", null)
                    .show()
            }
            binding.profilesContainer.addView(row.root)
        }
    }

    private fun promptSaveProfile() {
        val input = android.widget.EditText(this).apply {
            hint = "e.g. Mac or Windows"
            setTextColor(getColor(R.color.text_pri))
        }
        AlertDialog.Builder(this)
            .setTitle("Save current connection as…")
            .setView(input)
            .setPositiveButton("Save") { _, _ ->
                val name = input.text.toString().trim().ifBlank { "My PC" }
                api.saveActiveConnectionAsProfile(name)
                toast("Saved \"$name\"")
                renderProfiles()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
