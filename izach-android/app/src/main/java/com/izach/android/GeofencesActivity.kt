package com.izach.android

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.izach.android.databinding.ActivityGeofencesBinding
import com.izach.android.model.GeofenceLocation
import com.izach.android.network.IZACHApi
import java.util.UUID

class GeofencesActivity : AppCompatActivity() {

    private lateinit var binding: ActivityGeofencesBinding
    private lateinit var api: IZACHApi
    private val locations = mutableListOf<GeofenceLocation>()
    private lateinit var adapter: GeofenceAdapter
    private var cancellationTokenSource: CancellationTokenSource? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityGeofencesBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            binding.topBar.setPadding(dp8, bars.top, dp8, 0)
            binding.root.setPadding(0, 0, 0, bars.bottom)
            insets
        }

        api = IZACHApi(this)
        adapter = GeofenceAdapter(locations, { loc -> confirmDelete(loc) }, { loc -> toggleEnabled(loc) })
        binding.rvGeofences.layoutManager = LinearLayoutManager(this)
        binding.rvGeofences.adapter = adapter

        binding.btnBack.setOnClickListener { finish() }
        binding.btnAdd.setOnClickListener { requestLocationThenAdd() }

        loadLocations()
    }

    private fun loadLocations() {
        locations.clear()
        locations.addAll(api.getGeofences())
        adapter.notifyDataSetChanged()
        binding.tvEmpty.visibility = if (locations.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun persistAndReregister() {
        api.saveGeofences(locations)
        GeofenceManager.registerAll(this, locations)
        adapter.notifyDataSetChanged()
        binding.tvEmpty.visibility = if (locations.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun hasFineLocation() = ContextCompat.checkSelfPermission(
        this, Manifest.permission.ACCESS_FINE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED

    private fun hasBackgroundLocation(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true
        return ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_BACKGROUND_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestLocationThenAdd() {
        if (!hasFineLocation()) {
            ActivityCompat.requestPermissions(
                this, arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                REQ_FINE_LOCATION
            )
            return
        }
        if (!hasBackgroundLocation()) {
            AlertDialog.Builder(this)
                .setTitle("Background location needed")
                .setMessage("For arrive/leave automations to fire while the app isn't open, choose \"Allow all the time\" on the next screen.")
                .setPositiveButton("CONTINUE") { _, _ ->
                    ActivityCompat.requestPermissions(
                        this, arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION), REQ_BACKGROUND_LOCATION
                    )
                }
                .setNegativeButton("SKIP FOR NOW") { _, _ -> showAddDialog() }
                .show()
            return
        }
        showAddDialog()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            REQ_FINE_LOCATION -> if (hasFineLocation()) requestLocationThenAdd() else toast("Location permission required to add a geofence")
            REQ_BACKGROUND_LOCATION -> showAddDialog()
        }
    }

    @Suppress("MissingPermission")
    private fun showAddDialog() {
        val fused = LocationServices.getFusedLocationProviderClient(this)
        toast("Getting current location…")
        fused.lastLocation.addOnSuccessListener { loc ->
            if (loc != null) {
                showAddForm(loc.latitude, loc.longitude)
            } else {
                requestFreshLocation(fused)
            }
        }.addOnFailureListener {
            requestFreshLocation(fused)
        }
    }

    @Suppress("MissingPermission")
    private fun requestFreshLocation(fused: com.google.android.gms.location.FusedLocationProviderClient) {
        val cts = CancellationTokenSource()
        cancellationTokenSource = cts
        fused.getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, cts.token)
            .addOnSuccessListener { loc ->
                if (loc == null) {
                    toast("Couldn't get current location — make sure location is on")
                } else {
                    showAddForm(loc.latitude, loc.longitude)
                }
            }
            .addOnFailureListener {
                toast("Couldn't get current location: ${it.message}")
            }
    }

    override fun onDestroy() {
        cancellationTokenSource?.cancel()
        super.onDestroy()
    }

    private fun showAddForm(lat: Double, lng: Double) {
        val dp = resources.displayMetrics.density
        val pad = (20 * dp).toInt()
        val container = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
        }
        val etName = EditText(this).apply { hint = "Name (e.g. Home, Office)" }
        val etRadius = EditText(this).apply {
            hint = "Radius in meters (default 150)"
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
        }
        val etArrive = EditText(this).apply { hint = "Command on arrive (e.g. \"turn off dnd\")" }
        val etLeave = EditText(this).apply { hint = "Command on leave (e.g. \"lock the pc\")" }
        container.addView(etName)
        container.addView(etRadius)
        container.addView(etArrive)
        container.addView(etLeave)

        AlertDialog.Builder(this)
            .setTitle("New Geofence (current location)")
            .setView(container)
            .setPositiveButton("SAVE") { _, _ ->
                val name = etName.text.toString().trim().ifBlank { "Location" }
                val radius = etRadius.text.toString().trim().toFloatOrNull() ?: 150f
                val arrive = etArrive.text.toString().trim()
                val leave = etLeave.text.toString().trim()
                locations.add(
                    GeofenceLocation(
                        id = UUID.randomUUID().toString(),
                        name = name, lat = lat, lng = lng, radius = radius,
                        arriveCommand = arrive, leaveCommand = leave, enabled = true
                    )
                )
                persistAndReregister()
                toast("Saved \"$name\"")
            }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun toggleEnabled(loc: GeofenceLocation) {
        val idx = locations.indexOfFirst { it.id == loc.id }
        if (idx < 0) return
        locations[idx] = loc.copy(enabled = !loc.enabled)
        persistAndReregister()
    }

    private fun confirmDelete(loc: GeofenceLocation) {
        AlertDialog.Builder(this)
            .setTitle("Remove \"${loc.name}\"?")
            .setPositiveButton("Remove") { _, _ ->
                locations.removeAll { it.id == loc.id }
                persistAndReregister()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    companion object {
        private const val REQ_FINE_LOCATION = 201
        private const val REQ_BACKGROUND_LOCATION = 202
    }

    class GeofenceAdapter(
        private val items: List<GeofenceLocation>,
        private val onLongPress: (GeofenceLocation) -> Unit,
        private val onTap: (GeofenceLocation) -> Unit
    ) : RecyclerView.Adapter<GeofenceAdapter.VH>() {

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
            val loc = items[position]
            val status = if (loc.enabled) "ON" else "OFF"
            holder.tv1.text = "[$status] ${loc.name} (${loc.radius.toInt()}m)"
            holder.tv1.setTextColor(if (loc.enabled) 0xFF00e5ff.toInt() else 0xFF3a6070.toInt())
            holder.tv2.text = "Arrive: ${loc.arriveCommand.ifBlank { "—" }} · Leave: ${loc.leaveCommand.ifBlank { "—" }}"
            holder.tv2.setTextColor(0xFFc8e8f0.toInt())
            holder.itemView.setBackgroundColor(0xFF071020.toInt())
            holder.itemView.setOnClickListener { onTap(loc) }
            holder.itemView.setOnLongClickListener { onLongPress(loc); true }
        }

        override fun getItemCount() = items.size
    }
}
