package com.izach.android.network

import android.content.Context
import android.net.Uri
import android.os.Build
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.izach.android.model.Automation
import com.izach.android.model.Bookmark
import com.izach.android.model.BrowserHistoryEntry
import com.izach.android.model.BusyStatus
import com.izach.android.model.CalendarEvent
import com.izach.android.model.CommandResponse
import com.izach.android.model.DeviceProfile
import com.izach.android.model.DndAlert
import com.izach.android.model.DndStatus
import com.izach.android.model.FileEntry
import com.izach.android.model.FileInfo
import com.izach.android.model.GeofenceLocation
import com.izach.android.model.MarketIndex
import com.izach.android.model.MemoryEntry
import com.izach.android.model.Message
import com.izach.android.model.NewsHeadline
import com.izach.android.model.OpenTabEntry
import com.izach.android.model.Recording
import com.izach.android.model.SchedulerJob
import com.izach.android.model.SpotifyStatus
import com.izach.android.model.SystemStatus
import com.izach.android.model.WaChatSummary
import com.izach.android.model.WaThreadMessage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import okio.source
import java.util.concurrent.TimeUnit

// Thrown by sendCommand() specifically for an HTTP 401 (PC reachable, but
// rejected this device's pairing signature) — distinct from every other
// failure (timeout, connection refused) so callers know retrying is useless
// until the device is re-paired.
class PairingRejectedException(message: String) : Exception(message)

class IZACHApi(context: Context) {

    private val prefs = context.getSharedPreferences("izach_prefs", Context.MODE_PRIVATE)
    private val gson = Gson()

    // Every request is signed with the per-install pairing secret (obtained via
    // QR scan or manual entry in Settings) so the backend can tell this phone
    // apart from any other device on the same network. Requests made before
    // pairing (empty secret) go out unsigned and the backend will simply
    // reject anything sensitive until the phone is paired.
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.MINUTES)
        .callTimeout(15, TimeUnit.MINUTES)
        .addInterceptor { chain ->
            val original = chain.request()
            val secret = pairingSecret()
            if (secret.isBlank()) {
                chain.proceed(original)
            } else {
                val bodyBytes = original.body?.let { body ->
                    val buffer = okio.Buffer()
                    body.writeTo(buffer)
                    buffer.readByteArray()
                } ?: ByteArray(0)
                val path = original.url.encodedPath
                val ts = (System.currentTimeMillis() / 1000).toString()
                val message = "${original.method}|$path|$ts".toByteArray() + byteArrayOf('|'.code.toByte()) + bodyBytes
                val mac = javax.crypto.Mac.getInstance("HmacSHA256")
                mac.init(javax.crypto.spec.SecretKeySpec(secret.toByteArray(), "HmacSHA256"))
                val sig = mac.doFinal(message).joinToString("") { "%02x".format(it) }
                val signed = original.newBuilder()
                    .addHeader("X-iZACH-Signature", sig)
                    .addHeader("X-iZACH-Timestamp", ts)
                    .build()
                chain.proceed(signed)
            }
        }
        .build()

    fun baseUrl(): String =
        prefs.getString("backend_url", "http://192.168.1.100:5050")
            ?: "http://192.168.1.100:5050"

    fun wsHost(): String {
        val saved = prefs.getString("ws_host", "") ?: ""
        if (saved.isNotBlank()) return saved
        return baseUrl().substringAfter("://").substringBefore(":").substringBefore("/")
    }

    fun pairingSecret(): String = prefs.getString("pairing_secret", "") ?: ""
    fun savePairingSecret(secret: String) {
        prefs.edit().putString("pairing_secret", secret).apply()
        updateActiveProfileFields(pairingSecret = secret)
    }

    // ── Saved device profiles — Mac and Windows iZACH installs saved as
    // separate named connections. The flat backend_url/ws_host/pairing_secret
    // keys above remain the single "currently active connection" that every
    // existing call site already reads; profiles are a layer on top that lets
    // the user switch which connection is active without re-scanning a QR
    // code each time. ──────────────────────────────────────────────
    private val profilesKey = "device_profiles"
    private val activeProfileIdKey = "active_profile_id"

    fun getProfiles(): List<DeviceProfile> {
        val raw = prefs.getString(profilesKey, null) ?: return emptyList()
        return runCatching {
            gson.fromJson(raw, Array<DeviceProfile>::class.java).toList()
        }.getOrDefault(emptyList())
    }

    private fun saveProfiles(profiles: List<DeviceProfile>) {
        prefs.edit().putString(profilesKey, gson.toJson(profiles)).apply()
    }

    fun activeProfileId(): String? = prefs.getString(activeProfileIdKey, null)

    // True when there's a live connection (freshly QR-paired, or from before
    // saved profiles existed) that no saved profile owns yet — the device
    // picker uses this to prompt "name this connection" instead of either
    // silently swallowing it into an unnamed profile or showing an empty
    // screen after a fresh pairing.
    fun hasUnnamedActiveConnection(): Boolean =
        pairingSecret().isNotBlank() && activeProfileId() == null

    // Snapshots the CURRENT active connection (whatever's in the flat keys
    // right now — freshly QR-paired or otherwise) into a new named saved
    // profile, and marks it active. This is how "Mac" and "Windows" become
    // two independently switchable saved connections.
    fun saveActiveConnectionAsProfile(name: String): DeviceProfile {
        val profile = DeviceProfile(
            id = java.util.UUID.randomUUID().toString(),
            name = name,
            backendUrl = baseUrl(),
            wsHost = wsHost(),
            pairingSecret = pairingSecret()
        )
        val updated = getProfiles() + profile
        saveProfiles(updated)
        prefs.edit().putString(activeProfileIdKey, profile.id).apply()
        return profile
    }

    // Copies a saved profile's connection details into the flat active keys
    // — every existing screen (Settings, widget, all API calls) picks this up
    // immediately since they all read the flat keys, not the profile itself.
    fun switchToProfile(id: String) {
        val profile = getProfiles().firstOrNull { it.id == id } ?: return
        prefs.edit()
            .putString("backend_url", profile.backendUrl)
            .putString("ws_host", profile.wsHost)
            .putString("pairing_secret", profile.pairingSecret)
            .putString(activeProfileIdKey, profile.id)
            .apply()
    }

    fun deleteProfile(id: String) {
        saveProfiles(getProfiles().filterNot { it.id == id })
        if (activeProfileId() == id) {
            prefs.edit().remove(activeProfileIdKey).apply()
        }
    }

    fun renameProfile(id: String, newName: String) {
        saveProfiles(getProfiles().map { if (it.id == id) it.copy(name = newName) else it })
    }

    // Adds a freshly-scanned PC as its own new profile WITHOUT touching the
    // flat active-connection keys or active_profile_id at all — whatever the
    // phone is currently connected to (and its chat session) stays completely
    // undisturbed. This is what the dedicated "Connect Another PC" flow uses,
    // as opposed to Settings' QR scan (which intentionally replaces the
    // active connection).
    fun addProfileFromScan(backendUrl: String, wsHost: String, secret: String, name: String): DeviceProfile {
        val profile = DeviceProfile(
            id = java.util.UUID.randomUUID().toString(),
            name = name,
            backendUrl = backendUrl,
            wsHost = wsHost,
            pairingSecret = secret
        )
        saveProfiles(getProfiles() + profile)
        return profile
    }

    // Keeps the active saved profile (if any) in sync when its connection
    // details change from underneath it — e.g. editing the URL in Settings,
    // or re-pairing with a fresh secret via QR while that profile is active.
    private fun updateActiveProfileFields(
        backendUrl: String? = null,
        wsHost: String? = null,
        pairingSecret: String? = null,
        platform: String? = null
    ) {
        val id = activeProfileId() ?: return
        saveProfiles(getProfiles().map {
            if (it.id != id) it else it.copy(
                backendUrl = backendUrl ?: it.backendUrl,
                wsHost = wsHost ?: it.wsHost,
                pairingSecret = pairingSecret ?: it.pairingSecret,
                platform = platform ?: it.platform
            )
        })
    }

    // Severs the active-profile link if the host about to become active
    // doesn't match whatever profile currently holds that link. Without
    // this, scanning (or manually entering) a DIFFERENT PC's connection
    // details while a saved profile was active — e.g. re-scanning in
    // Settings while "Windows" was the active profile, actually pointing
    // at a Mac — silently overwrote that profile's own backendUrl/wsHost/
    // pairingSecret via updateActiveProfileFields() (called from
    // saveBackendUrl/saveWsHost/savePairingSecret below), corrupting it
    // in place: still named/labeled "Windows" (stale cached platform) but
    // now actually pointing at the Mac's IP and secret. The launcher then
    // shows a "Windows" card that's really the Mac (wrong label, and
    // reachability checks against the WRONG expectations), and if the
    // user also saves the new connection under its own name via
    // "Connect Another PC" or "+ SAVE CURRENT CONNECTION", a second,
    // duplicate entry for the same physical machine appears too.
    // Clearing the link here instead lets hasUnnamedActiveConnection()
    // correctly detect "this is an unclaimed connection" and prompt to
    // name it as a brand-new profile — leaving the old one untouched.
    // A matching host is treated as "re-pairing the same machine" (new
    // secret, same box) and keeps syncing that profile as before.
    fun clearActiveProfileLinkIfDifferentHost(newHost: String) {
        val activeId = activeProfileId() ?: return
        val activeProfile = getProfiles().firstOrNull { it.id == activeId } ?: return
        if (activeProfile.wsHost.isNotBlank() && activeProfile.wsHost != newHost) {
            prefs.edit().remove(activeProfileIdKey).apply()
        }
    }

    // Applies a freshly scanned connection to the flat active-connection
    // keys, guarding against the corruption described above. Used by
    // Settings' QR-scan flow. secret is left untouched if blank (the QR
    // didn't carry one — keep whatever secret is already stored).
    fun applyConnection(url: String, host: String, secret: String) {
        clearActiveProfileLinkIfDifferentHost(host)
        saveBackendUrl(url)
        saveWsHost(host)
        if (secret.isNotBlank()) savePairingSecret(secret)
    }

    // Called after a successful /status fetch to cache which platform this
    // connection is — lets Devices screen and tile-hiding work without
    // requiring a fresh round-trip every time.
    fun cacheActiveProfilePlatform(platform: String) {
        if (platform.isBlank()) return
        updateActiveProfileFields(platform = platform)
    }

    // Best-effort platform of whatever's currently active — empty string if
    // never successfully connected yet (caller should treat that as "unknown,
    // assume full feature set" rather than hiding anything).
    fun activePlatform(): String {
        val id = activeProfileId() ?: return ""
        return getProfiles().firstOrNull { it.id == id }?.platform ?: ""
    }

    // Plain client with no signing interceptor — used only for one-off
    // per-profile peeks below, where the request must be signed with THAT
    // profile's own secret rather than whatever's currently active.
    private val plainClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()

    // Fetches /status for a SAVED profile without switching the active
    // connection — lets the device-picker screen show live battery% / online
    // state for every saved PC at once, side by side, none of them becoming
    // "active" just by being glanced at. /status is exempt from signature
    // verification server-side (see getSystemStatus's comment above), so no
    // signing is actually needed here — this mirrors that, deliberately not
    // reusing the signed `client`.
    suspend fun getStatusForProfile(profile: DeviceProfile): Result<SystemStatus> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp = plainClient.newCall(Request.Builder().url("${profile.backendUrl}/status").build()).execute()
                val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
                SystemStatus(
                    cpu = obj.get("cpu")?.asFloat ?: 0f,
                    ram = obj.get("ram")?.asFloat ?: 0f,
                    gpu = obj.get("gpu")?.asFloat ?: 0f,
                    procCpu = obj.get("proc_cpu")?.asFloat ?: 0f,
                    procMem = obj.get("proc_mem")?.asFloat ?: 0f,
                    ramUsedGb = obj.get("ram_used_gb")?.asFloat ?: 0f,
                    ramTotalGb = obj.get("ram_total_gb")?.asFloat ?: 0f,
                    whatsapp = obj.get("whatsapp")?.asBoolean ?: false,
                    mma = obj.get("mma")?.asBoolean ?: false,
                    pcName = obj.get("pc_name")?.asString ?: "",
                    batteryPct = obj.get("battery_pct")?.takeIf { !it.isJsonNull }?.asInt,
                    batteryPlugged = obj.get("battery_plugged")?.takeIf { !it.isJsonNull }?.asBoolean,
                    platform = obj.get("platform")?.takeIf { !it.isJsonNull }?.asString ?: ""
                )
            }
        }

    // Signs and sends a command to a SAVED profile that may not be the
    // active connection — mirrors the interceptor's exact HMAC scheme above,
    // built manually here since the interceptor always signs with whatever
    // pairingSecret() (the active connection's) currently returns.
    suspend fun sendCommandToProfile(profile: DeviceProfile, text: String): Result<CommandResponse> =
        withContext(Dispatchers.IO) {
            runCatching {
                val deviceName = Build.MODEL
                val bodyStr = """{"text":${gson.toJson(text)},"source":"phone","device_name":${gson.toJson(deviceName)}}"""
                val bodyBytes = bodyStr.toByteArray()
                val body = bodyStr.toRequestBody("application/json".toMediaType())
                val path = "/command"
                val ts = (System.currentTimeMillis() / 1000).toString()
                var reqBuilder = Request.Builder().url("${profile.backendUrl}$path").post(body)
                if (profile.pairingSecret.isNotBlank()) {
                    val message = "POST|$path|$ts".toByteArray() + byteArrayOf('|'.code.toByte()) + bodyBytes
                    val mac = javax.crypto.Mac.getInstance("HmacSHA256")
                    mac.init(javax.crypto.spec.SecretKeySpec(profile.pairingSecret.toByteArray(), "HmacSHA256"))
                    val sig = mac.doFinal(message).joinToString("") { "%02x".format(it) }
                    reqBuilder = reqBuilder
                        .addHeader("X-iZACH-Signature", sig)
                        .addHeader("X-iZACH-Timestamp", ts)
                }
                val resp = plainClient.newCall(reqBuilder.build()).execute()
                val raw = resp.body?.string() ?: ""
                if (resp.code == 401) throw PairingRejectedException(raw)
                if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
                val obj = gson.fromJson(raw, JsonObject::class.java)
                CommandResponse(
                    text = obj.get("message")?.asString ?: obj.get("response")?.asString ?: "Done.",
                    action = obj.get("action")?.asString,
                    requiresConfirmation = obj.get("requires_confirmation")?.asBoolean ?: false,
                    confirmationToken = obj.get("confirmation_token")?.asString
                )
            }
        }

    // ── Cross-device command queue — add a command targeted at a specific
    // saved PC (Mac or Windows), independent of whichever is currently the
    // active connection. Order in the list is execution priority. ──
    private val commandQueueKey = "cross_device_command_queue"

    fun getCommandQueue(): List<com.izach.android.model.QueuedCommand> {
        val raw = prefs.getString(commandQueueKey, null) ?: return emptyList()
        return runCatching {
            gson.fromJson(raw, Array<com.izach.android.model.QueuedCommand>::class.java).toList()
        }.getOrDefault(emptyList())
    }

    private fun saveCommandQueue(queue: List<com.izach.android.model.QueuedCommand>) {
        prefs.edit().putString(commandQueueKey, gson.toJson(queue)).apply()
    }

    fun addToCommandQueue(text: String, targetProfile: DeviceProfile) {
        val entry = com.izach.android.model.QueuedCommand(
            id = java.util.UUID.randomUUID().toString(),
            text = text,
            targetProfileId = targetProfile.id,
            targetProfileName = targetProfile.name,
            addedAt = System.currentTimeMillis()
        )
        saveCommandQueue(getCommandQueue() + entry)
    }

    fun removeFromCommandQueue(id: String) {
        saveCommandQueue(getCommandQueue().filterNot { it.id == id })
    }

    fun reorderCommandQueue(newOrder: List<com.izach.android.model.QueuedCommand>) {
        saveCommandQueue(newOrder)
    }

    // Walks the queue front-to-back once; fires every command whose target
    // profile answers right now (not just the very first item) so a command
    // queued for an offline Mac doesn't block a Windows-targeted command
    // behind it once Windows comes online — each command still only ever
    // runs after everything queued earlier FOR THE SAME TARGET has already
    // fired, since removal preserves relative order. Returns how many sent.
    suspend fun drainCommandQueue(): Int {
        var sent = 0
        val remaining = getCommandQueue().toMutableList()
        var i = 0
        while (i < remaining.size) {
            val cmd = remaining[i]
            val profile = getProfiles().firstOrNull { it.id == cmd.targetProfileId }
            if (profile == null) {
                // Target profile was deleted — drop the orphaned command.
                remaining.removeAt(i)
                continue
            }
            val reachable = getStatusForProfile(profile).isSuccess
            if (!reachable) {
                i++
                continue
            }
            val result = sendCommandToProfile(profile, cmd.text)
            if (result.isSuccess) {
                remaining.removeAt(i)
                sent++
            } else {
                i++
            }
        }
        if (sent > 0) saveCommandQueue(remaining)
        return sent
    }

    // ── Offline command queue — persisted so typed commands survive the app
    // being killed while the PC is unreachable; flushed on WS reconnect. ──
    private val offlineQueueKey = "offline_command_queue"

    fun getQueuedCommands(): List<String> {
        val raw = prefs.getString(offlineQueueKey, null) ?: return emptyList()
        return runCatching { gson.fromJson(raw, Array<String>::class.java).toList() }.getOrDefault(emptyList())
    }

    fun enqueueOfflineCommand(text: String) {
        val updated = (getQueuedCommands() + text).takeLast(50)
        prefs.edit().putString(offlineQueueKey, gson.toJson(updated)).apply()
    }

    fun removeQueuedCommand(text: String) {
        val updated = getQueuedCommands().toMutableList()
        updated.remove(text)
        prefs.edit().putString(offlineQueueKey, gson.toJson(updated)).apply()
    }

    // Registers this device's FCM token so the PC can push notifications
    // (DND alerts, reminders, handoffs) even when the WebSocket connection
    // is down or the app has been killed. No-op server-side until Firebase
    // is actually configured — see FcmService.kt / build.gradle.kts.
    suspend fun registerFcmToken(token: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("token" to token, "device_name" to Build.MODEL))
                .toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/phone/fcm-token").post(body).build()).execute()
            Unit
        }
    }

    // ── Geofenced automations — stored locally on the phone only, since
    // the geofence transitions fire entirely on-device via Play Services. ──
    private val geofenceKey = "geofence_locations"

    fun getGeofences(): List<GeofenceLocation> {
        val raw = prefs.getString(geofenceKey, null) ?: return emptyList()
        return runCatching { gson.fromJson(raw, Array<GeofenceLocation>::class.java).toList() }.getOrDefault(emptyList())
    }

    fun saveGeofences(list: List<GeofenceLocation>) {
        prefs.edit().putString(geofenceKey, gson.toJson(list)).apply()
    }

    suspend fun sendCommand(text: String): Result<CommandResponse> = withContext(Dispatchers.IO) {
        runCatching {
            val deviceName = Build.MODEL
            val body = """{"text":${gson.toJson(text)},"source":"phone","device_name":${gson.toJson(deviceName)}}"""
                .toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url("${baseUrl()}/command").post(body).build()
            val resp = client.newCall(req).execute()
            val raw = resp.body?.string() ?: ""
            // A 401 means the PC WAS reached and rejected this device's
            // signature — retrying with the same (rejected) secret will just
            // 401 forever, so this must never be treated the same as a real
            // network failure (which genuinely is worth queuing/retrying).
            if (resp.code == 401) throw PairingRejectedException(raw)
            if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
            val obj = gson.fromJson(raw, JsonObject::class.java)
            CommandResponse(
                text = obj.get("message")?.asString ?: obj.get("response")?.asString ?: "Done.",
                action = obj.get("action")?.asString,
                requiresConfirmation = obj.get("requires_confirmation")?.asBoolean ?: false,
                confirmationToken = obj.get("confirmation_token")?.asString
            )
        }
    }

    suspend fun confirmCommand(token: String): Result<CommandResponse> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"token":${gson.toJson(token)}}"""
                .toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url("${baseUrl()}/confirm_command").post(body).build()
            val resp = client.newCall(req).execute()
            val raw = resp.body?.string() ?: ""
            if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
            val obj = gson.fromJson(raw, JsonObject::class.java)
            CommandResponse(text = obj.get("response")?.asString ?: "Done.")
        }
    }

    suspend fun quickAction(action: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"action":${gson.toJson(action)}}"""
                .toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url("${baseUrl()}/quick_action").post(body).build()
            val resp = client.newCall(req).execute()
            val raw = resp.body?.string() ?: ""
            if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
            val obj = gson.fromJson(raw, JsonObject::class.java)
            obj.get("msg")?.asString ?: "Done"
        }
    }

    suspend fun getFilePreview(path: String): Result<JsonObject> = withContext(Dispatchers.IO) {
        runCatching {
            val url = "${baseUrl()}/file_preview?path=${Uri.encode(path)}"
            val resp = client.newCall(Request.Builder().url(url).build()).execute()
            val raw = resp.body?.string() ?: "{}"
            val obj = gson.fromJson(raw, JsonObject::class.java)
            if (obj.get("ok")?.asBoolean != true) error(obj.get("error")?.asString ?: "Preview failed")
            obj
        }
    }

    suspend fun getNotificationHistory(): Result<List<Triple<String, String, String>>> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${baseUrl()}/notifications/history").build()
            val resp = client.newCall(req).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("notifications")?.map { el ->
                val o = el.asJsonObject
                Triple(
                    o.get("title")?.asString ?: "",
                    o.get("category")?.asString ?: "system",
                    o.get("body")?.asString ?: ""
                )
            } ?: emptyList()
        }
    }

    suspend fun getHistory(n: Int = 50): Result<List<Message>> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${baseUrl()}/history?n=$n").get().build()
            val resp = client.newCall(req).execute()
            val raw = resp.body?.string() ?: "[]"
            val obj = gson.fromJson(raw, JsonObject::class.java)
            val arr = obj.getAsJsonArray("messages") ?: return@runCatching emptyList()
            arr.map { el ->
                val o = el.asJsonObject
                Message(
                    text = o.get("text")?.asString ?: "",
                    sender = o.get("sender")?.asString ?: "iZACH",
                    ts = o.get("ts")?.asString ?: "",
                    epoch = o.get("epoch")?.asLong ?: 0L
                )
            }
        }
    }

    suspend fun checkStatus(): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${baseUrl()}/status").get().build()
            client.newCall(req).execute().isSuccessful
        }.getOrDefault(false)
    }

    // onProgress reports (bytesWritten, totalBytes) as the file streams — used to
    // drive a real upload-progress notification instead of an indeterminate spinner.
    // totalBytes is -1 if the content provider couldn't report a size.
    suspend fun uploadFile(uri: Uri, context: Context, onProgress: ((Long, Long) -> Unit)? = null): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val cr = context.contentResolver
            val name = cr.query(uri, null, null, null, null)?.use { c ->
                val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                c.moveToFirst()
                if (idx >= 0) c.getString(idx) else "upload"
            } ?: "upload"
            val fileSize = cr.query(uri, arrayOf(android.provider.OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val idx = c.getColumnIndex(android.provider.OpenableColumns.SIZE)
                    if (idx >= 0) c.getLong(idx) else -1L
                } else -1L
            } ?: -1L
            val reqBody = object : RequestBody() {
                override fun contentType() = "application/octet-stream".toMediaType()
                override fun contentLength() = fileSize
                override fun writeTo(sink: BufferedSink) {
                    cr.openInputStream(uri)?.use { input ->
                        val buffer = ByteArray(8192)
                        var totalWritten = 0L
                        var read: Int
                        while (input.read(buffer).also { read = it } != -1) {
                            sink.write(buffer, 0, read)
                            totalWritten += read
                            onProgress?.invoke(totalWritten, fileSize)
                        }
                    } ?: error("Cannot open file")
                }
            }
            val multipart = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", name, reqBody)
                .build()
            val req = Request.Builder().url("${baseUrl()}/upload").post(multipart).build()
            val resp = client.newCall(req).execute()
            val raw = resp.body?.string() ?: ""
            if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
            val obj = gson.fromJson(raw, JsonObject::class.java)
            obj.get("filename")?.asString ?: name
        }
    }

    suspend fun getFiles(): Result<List<FileInfo>> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${baseUrl()}/files").get().build()
            val resp = client.newCall(req).execute()
            val raw = resp.body?.string() ?: "{}"
            val obj = gson.fromJson(raw, JsonObject::class.java)
            val arr = obj.getAsJsonArray("files") ?: return@runCatching emptyList()
            arr.map { el ->
                val o = el.asJsonObject
                FileInfo(
                    name = o.get("name")?.asString ?: "",
                    size = o.get("size")?.asLong ?: 0L,
                    modified = o.get("modified")?.asDouble ?: 0.0
                )
            }
        }
    }

    fun downloadUrl(filename: String) = "${baseUrl()}/download/$filename"

    suspend fun listDirs(path: String? = null): Result<List<FileEntry>> = withContext(Dispatchers.IO) {
        runCatching {
            val url = if (path != null)
                "${baseUrl()}/list_dirs?path=${Uri.encode(path)}"
            else
                "${baseUrl()}/list_dirs"
            val resp = client.newCall(Request.Builder().url(url).build()).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("entries")?.map { el ->
                val o = el.asJsonObject
                FileEntry(
                    name = o.get("name")?.asString ?: "",
                    path = o.get("path")?.asString ?: "",
                    isDir = o.get("is_dir")?.asBoolean ?: true
                )
            } ?: emptyList()
        }
    }

    suspend fun listFiles(path: String): Result<List<FileEntry>> = withContext(Dispatchers.IO) {
        runCatching {
            val url = "${baseUrl()}/list_files?path=${Uri.encode(path)}"
            val resp = client.newCall(Request.Builder().url(url).build()).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("entries")?.map { el ->
                val o = el.asJsonObject
                FileEntry(
                    name = o.get("name")?.asString ?: "",
                    path = o.get("path")?.asString ?: "",
                    isDir = false,
                    size = o.get("size")?.asLong ?: 0L
                )
            } ?: emptyList()
        }
    }

    fun fetchFileUrl(path: String): String = "${baseUrl()}/fetch_file?path=${Uri.encode(path)}"

    fun screenshotImageUrl(filename: String): String = "${baseUrl()}/screenshot/image/$filename"

    suspend fun captureScreenshot(): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${baseUrl()}/screenshot/capture")
                .post("".toRequestBody(null)).build()
            val resp = client.newCall(req).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.get("filename")?.asString ?: error("No filename")
        }
    }

    suspend fun getClipboardHistory(): Result<List<Pair<String, String>>> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${baseUrl()}/clipboard/history").get().build()
            val resp = client.newCall(req).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("entries")?.map { el ->
                val o = el.asJsonObject
                Pair(o.get("text")?.asString ?: "", o.get("ts")?.asString ?: "")
            } ?: emptyList()
        }
    }

    suspend fun setClipboard(text: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"text":${gson.toJson(text)}}"""
                .toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url("${baseUrl()}/clipboard").post(body).build()
            client.newCall(req).execute()
            Unit
        }
    }

    suspend fun getSystemStatus(): Result<SystemStatus> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/status").build()).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            SystemStatus(
                cpu      = obj.get("cpu")?.asFloat ?: 0f,
                ram      = obj.get("ram")?.asFloat ?: 0f,
                gpu      = obj.get("gpu")?.asFloat ?: 0f,
                procCpu  = obj.get("proc_cpu")?.asFloat ?: 0f,
                procMem  = obj.get("proc_mem")?.asFloat ?: 0f,
                ramUsedGb  = obj.get("ram_used_gb")?.asFloat ?: 0f,
                ramTotalGb = obj.get("ram_total_gb")?.asFloat ?: 0f,
                whatsapp = obj.get("whatsapp")?.asBoolean ?: false,
                mma      = obj.get("mma")?.asBoolean ?: false,
                pcName   = obj.get("pc_name")?.asString ?: "",
                batteryPct = obj.get("battery_pct")?.takeIf { !it.isJsonNull }?.asInt,
                batteryPlugged = obj.get("battery_plugged")?.takeIf { !it.isJsonNull }?.asBoolean,
                platform = obj.get("platform")?.takeIf { !it.isJsonNull }?.asString ?: ""
            ).also { cacheActiveProfilePlatform(it.platform) }
        }
    }

    // ── Dual-instance peer info — this device's own role plus whatever it
    // last heard from its paired peer machine (platform/hostname/role), for
    // the phone's Devices screen. Read-only, safe to poll. ──────────
    data class PeerLocalInfo(
        val configured: Boolean,
        val role: String,
        val peerPlatform: String?,
        val peerHostname: String?,
        val peerRole: String?
    )

    suspend fun getPeerLocal(): Result<PeerLocalInfo> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/peer/local").build()).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            val peer = obj.getAsJsonObject("peer")
            PeerLocalInfo(
                configured = obj.get("configured")?.asBoolean ?: false,
                role = obj.get("role")?.asString ?: "primary",
                peerPlatform = peer?.get("platform")?.takeIf { !it.isJsonNull }?.asString,
                peerHostname = peer?.get("hostname")?.takeIf { !it.isJsonNull }?.asString,
                peerRole = peer?.get("role")?.takeIf { !it.isJsonNull }?.asString
            )
        }
    }

    // Sends the handoff as a normal authenticated text command — reuses the
    // already-built, already-tested command_chain.py parser end to end
    // instead of a new endpoint (the machine-to-machine /peer/handoff route
    // uses a different auth scheme the phone isn't signed for).
    suspend fun triggerHandoff(targetPlatform: String): Result<CommandResponse> {
        val phrase = if (targetPlatform == "mac") "hands off to mac" else "hands off to windows"
        return sendCommand(phrase)
    }

    // Verifies the stored pairing_secret is actually accepted by the PC —
    // /status is intentionally exempt from the signature check (so basic
    // reachability testing works pre-pairing), so it can't be used to confirm
    // pairing. /dnd/vip is a lightweight, non-exempt, read-only route that is.
    // Returns Result.success(true/false) when the PC actually answered (false
    // meaning the stored secret was rejected — genuinely not paired), or
    // Result.failure when the PC couldn't be reached at all — callers must not
    // collapse the latter into "not paired": the phone may be perfectly paired
    // with the PC simply offline/asleep/off-network right now.
    suspend fun verifyPairing(): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/dnd/vip").build()).execute()
            resp.isSuccessful
        }
    }

    suspend fun getSpotifyStatus(): Result<SpotifyStatus> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/spotify").build()).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            SpotifyStatus(
                playing   = obj.get("playing")?.asBoolean ?: false,
                title     = obj.get("title")?.asString ?: "—",
                artist    = obj.get("artist")?.asString ?: "—",
                device    = obj.get("device")?.asString ?: "—",
                albumArt  = obj.get("album_art")?.asString ?: "",
                progress  = obj.get("progress")?.asInt ?: 0,
                duration  = obj.get("duration")?.asInt ?: 0,
                volume    = obj.get("volume")?.asInt ?: 0,
                shuffle   = obj.get("shuffle")?.asBoolean ?: false,
                repeat    = obj.get("repeat")?.asString ?: "off"
            )
        }
    }

    suspend fun spotifyControl(action: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"action":${gson.toJson(action)}}"""
                .toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/spotify/control").post(body).build()).execute()
            Unit
        }
    }

    suspend fun spotifyVolume(vol: Int): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"volume":$vol}"""
                .toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/spotify/volume").post(body).build()).execute()
            Unit
        }
    }

    suspend fun getActiveDownloads(): Result<Set<String>> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${baseUrl()}/downloads/active").get().build()
            val resp = client.newCall(req).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("downloads")
                ?.mapNotNull { it.asJsonObject.get("filename")?.asString?.takeIf { s -> s.isNotBlank() } }
                ?.toSet() ?: emptySet()
        }
    }

    // ── N8N token header (used for WA send + AI respond) ──────────
    private val n8nToken: String get() = prefs.getString("n8n_token", "izach-n8n-2024") ?: "izach-n8n-2024"
    private fun Request.Builder.withN8nToken() = header("X-N8N-Token", n8nToken)

    // ── DND ────────────────────────────────────────────────────────
    suspend fun getDndStatus(): Result<DndStatus> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/dnd").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            DndStatus(
                active     = obj.get("active")?.asBoolean ?: false,
                reason     = obj.get("reason")?.asString ?: "",
                queueCount = obj.get("queue_count")?.asInt ?: 0,
            )
        }
    }

    suspend fun toggleDnd(action: String, reason: String = "manual"): Result<DndStatus> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("action" to action, "reason" to reason))
                .toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/dnd").post(body).build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            DndStatus(
                active     = obj.get("active")?.asBoolean ?: false,
                reason     = obj.get("reason")?.asString ?: "",
                queueCount = obj.get("queue_count")?.asInt ?: 0,
            )
        }
    }

    suspend fun getDndQueue(): Result<List<DndAlert>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/dnd/queue").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("queue")?.map { el ->
                val o = el.asJsonObject
                DndAlert(
                    id     = o.get("id")?.asInt ?: 0,
                    from   = o.get("from")?.asString ?: "Unknown",
                    number = o.get("number")?.asString ?: "",
                    text   = o.get("text")?.asString ?: "",
                    type   = o.get("type")?.asString ?: "alert",
                    ts     = o.get("ts")?.asLong ?: 0L,
                    action = o.get("action")?.asString,
                )
            } ?: emptyList()
        }
    }

    suspend fun dndHandle(index: Int): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"index":$index}""".toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/dnd/handle").post(body).build()).execute()
            gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java).get("ok")?.asBoolean ?: false
        }
    }

    suspend fun dndBusy(index: Int): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"index":$index}""".toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/dnd/busy").post(body).build()).execute()
            gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java).get("ok")?.asBoolean ?: false
        }
    }

    // ── Busy mode ──────────────────────────────────────────────────
    suspend fun getBusyStatus(): Result<BusyStatus> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/busy").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            BusyStatus(
                active  = obj.get("active")?.asBoolean ?: false,
                reason  = obj.get("reason")?.asString ?: "",
                persona = obj.get("persona")?.asString ?: "",
            )
        }
    }

    suspend fun toggleBusy(action: String, reason: String = "manual"): Result<BusyStatus> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("action" to action, "reason" to reason, "duration_min" to 60))
                .toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/busy").post(body).build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            BusyStatus(
                active  = obj.get("active")?.asBoolean ?: false,
                reason  = obj.get("reason")?.asString ?: "",
                persona = obj.get("persona")?.asString ?: "",
            )
        }
    }

    // ── WhatsApp quick reply (via iZACH bridge) ────────────────────
    suspend fun waSendMessage(number: String, text: String, name: String = ""): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("number" to number, "text" to text, "name" to name))
                .toRequestBody("application/json".toMediaType())
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/whatsapp/send").post(body).withN8nToken().build()
            ).execute()
            gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java).get("ok")?.asBoolean ?: false
        }
    }

    suspend fun waAiDraft(from: String, message: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("from" to from, "message" to message, "lang_hint" to "hinglish"))
                .toRequestBody("application/json".toMediaType())
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/ai/respond").post(body).withN8nToken().build()
            ).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.get("reply")?.asString ?: ""
        }
    }

    // ── PC power actions (Phase 2) ─────────────────────────────────
    suspend fun pcPower(action: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            // Map action → natural language command
            val cmd = when (action) {
                "lock"     -> "lock the pc"
                "sleep"    -> "sleep the pc"
                "shutdown" -> "shutdown the pc"
                "restart"  -> "restart the pc"
                else       -> action
            }
            val body = """{"text":${gson.toJson(cmd)}}""".toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/command").post(body).build()).execute()
            val raw  = resp.body?.string() ?: ""
            if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
            val obj  = gson.fromJson(raw, JsonObject::class.java)
            obj.get("message")?.asString ?: obj.get("response")?.asString ?: "Done."
        }
    }

    fun saveBackendUrl(url: String) {
        prefs.edit().putString("backend_url", url).apply()
        updateActiveProfileFields(backendUrl = url)
    }
    fun saveWsHost(host: String) {
        prefs.edit().putString("ws_host", host).apply()
        updateActiveProfileFields(wsHost = host)
    }

    // ── VIP contacts ──────────────────────────────────────────
    suspend fun getVipContacts(): Result<List<String>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/dnd/vip").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("vip")?.map { it.asString } ?: emptyList()
        }
    }

    suspend fun setVipContacts(list: List<String>): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("vip" to list))
                .toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/dnd/vip").post(body).build()).execute()
            Unit
        }
    }

    // ── Audio streaming ────────────────────────────────────────
    fun audioStreamUrl(): String = "${baseUrl()}/audio/stream"

    suspend fun getAudioStreamInfo(): Result<Map<String, Any?>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/audio/info").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            mapOf(
                "available"    to (obj.get("available")?.asBoolean ?: false),
                "backend"      to (obj.get("backend")?.asString ?: "none"),
                "install_hint" to (obj.get("install_hint")?.asString ?: ""),
            )
        }
    }

    suspend fun stopAudioStream(): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            client.newCall(
                Request.Builder().url("${baseUrl()}/audio/stop")
                    .post("".toRequestBody(null)).build()
            ).execute()
            Unit
        }
    }

    // ── Process manager ────────────────────────────────────────────
    suspend fun getProcesses(baseUrl: String = baseUrl()): Result<List<com.izach.android.model.ProcessInfo>> =
        withContext(Dispatchers.IO) {
            runCatching {
                val resp    = client.newCall(Request.Builder().url("$baseUrl/processes").build()).execute()
                val bodyStr = resp.body?.string() ?: "[]"
                // Backend may return a raw JSON array OR {"processes":[...]}
                val arr: JsonArray = try {
                    val obj = gson.fromJson(bodyStr, JsonObject::class.java)
                    obj.getAsJsonArray("processes") ?: JsonArray()
                } catch (_: Exception) {
                    try { gson.fromJson(bodyStr, JsonArray::class.java) } catch (_: Exception) { JsonArray() }
                }
                arr.map { el ->
                    val o = el.asJsonObject
                    com.izach.android.model.ProcessInfo(
                        pid      = o.get("pid")?.asInt ?: 0,
                        name     = o.get("name")?.asString ?: "unknown",
                        cpu      = o.get("cpu")?.asFloat ?: 0f,
                        memoryMb = o.get("memory_mb")?.asFloat ?: 0f,
                    )
                }
            }
        }

    suspend fun killProcess(pid: Int, baseUrl: String = baseUrl()): Result<Unit> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = """{"pid":$pid}""".toRequestBody("application/json".toMediaType())
                client.newCall(Request.Builder().url("$baseUrl/kill_process").post(body).build()).execute()
                Unit
            }
        }

    // ── AlliedNode 2 (secondary PC, separate iZACH instance) ──────
    fun alliedBaseUrl(): String =
        prefs.getString("allied_url", "http://192.168.1.101:5050") ?: "http://192.168.1.101:5050"

    fun saveAlliedUrl(url: String) = prefs.edit().putString("allied_url", url).apply()

    suspend fun getAlliedStatus(): Result<com.izach.android.model.SystemStatus> =
        withContext(Dispatchers.IO) {
            runCatching {
                val url = alliedBaseUrl()
                val resp = client.newCall(Request.Builder().url("$url/status").build()).execute()
                val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
                com.izach.android.model.SystemStatus(
                    cpu        = obj.get("cpu")?.asFloat ?: 0f,
                    ram        = obj.get("ram")?.asFloat ?: 0f,
                    gpu        = obj.get("gpu")?.asFloat ?: 0f,
                    procCpu    = obj.get("proc_cpu")?.asFloat ?: 0f,
                    procMem    = obj.get("proc_mem")?.asFloat ?: 0f,
                    ramUsedGb  = obj.get("ram_used_gb")?.asFloat ?: 0f,
                    ramTotalGb = obj.get("ram_total_gb")?.asFloat ?: 0f,
                    whatsapp   = obj.get("whatsapp")?.asBoolean ?: false,
                    mma        = obj.get("mma")?.asBoolean ?: false,
                )
            }
        }

    suspend fun alliedPower(action: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val cmd = when (action) {
                "lock"     -> "lock the pc"
                "sleep"    -> "sleep the pc"
                "shutdown" -> "shutdown the pc"
                "restart"  -> "restart the pc"
                else       -> action
            }
            val body = """{"text":${gson.toJson(cmd)}}""".toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${alliedBaseUrl()}/command").post(body).build()).execute()
            val raw  = resp.body?.string() ?: ""
            if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
            val obj  = gson.fromJson(raw, JsonObject::class.java)
            obj.get("message")?.asString ?: obj.get("response")?.asString ?: "Done."
        }
    }

    suspend fun alliedVolume(level: Int): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"text":"set volume to $level percent"}""".toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${alliedBaseUrl()}/command").post(body).build()).execute()
            if (!resp.isSuccessful) error("HTTP ${resp.code}: ${resp.body?.string() ?: ""}")
            Unit
        }
    }

    suspend fun alliedBrightness(level: Int): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"text":"set brightness to $level percent"}""".toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${alliedBaseUrl()}/command").post(body).build()).execute()
            if (!resp.isSuccessful) error("HTTP ${resp.code}: ${resp.body?.string() ?: ""}")
            Unit
        }
    }

    suspend fun alliedScreenshot(): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${alliedBaseUrl()}/screenshot/capture")
                    .post("".toRequestBody(null)).build()
            ).execute()
            val raw = resp.body?.string() ?: ""
            if (!resp.isSuccessful) error("HTTP ${resp.code}: $raw")
            val obj = gson.fromJson(raw, JsonObject::class.java)
            obj.get("filename")?.asString ?: error("No filename")
        }
    }

    suspend fun alliedTerminalCmd(cmd: String, baseUrl: String = alliedBaseUrl()): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val body = """{"text":${gson.toJson(cmd)}}""".toRequestBody("application/json".toMediaType())
                val resp = client.newCall(Request.Builder().url("$baseUrl/command").post(body).build()).execute()
                val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
                obj.get("message")?.asString ?: obj.get("response")?.asString ?: "Done."
            }
        }

    // ── Background Mode ───────────────────────────────────────────
    /** GET /settings — returns current ui mode */
    suspend fun getUiMode(): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/settings").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonObject("settings")?.get("ui")?.asString ?: "classic"
        }
    }

    /** POST /background-mode  — switches PC to headless background mode */
    suspend fun activateBackgroundMode(): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/background-mode")
                    .post("".toRequestBody(null)).build()
            ).execute()
            gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
                .get("ok")?.asBoolean ?: false
        }
    }

    /** Restore UI mode to given value (e.g. "classic" or "scifi") */
    suspend fun setUiMode(mode: String): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("ui" to mode))
                .toRequestBody("application/json".toMediaType())
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/settings").post(body).build()
            ).execute()
            gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
                .get("ok")?.asBoolean ?: false
        }
    }

    // ── Auto-DND schedule ──────────────────────────────────────────
    suspend fun pushDndSchedule(enabled: Boolean, startHour: Int, startMin: Int, endHour: Int, endMin: Int): Result<Unit> =
        withContext(Dispatchers.IO) {
            runCatching {
                val start = "%02d:%02d".format(startHour, startMin)
                val end   = "%02d:%02d".format(endHour, endMin)
                val body  = gson.toJson(mapOf("enabled" to enabled, "start" to start, "end" to end))
                    .toRequestBody("application/json".toMediaType())
                client.newCall(Request.Builder().url("${baseUrl()}/dnd/schedule").post(body).build()).execute()
                Unit
            }
        }

    // ── Calendar ─────────────────────────────────────────────────
    suspend fun getCalendarEvents(): Result<List<CalendarEvent>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/calendar/events").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            if (obj.get("ok")?.asBoolean != true) error(obj.get("error")?.asString ?: "Failed to load events")
            obj.getAsJsonArray("events")?.mapNotNull { el ->
                val o = el.asJsonObject
                val start = o.getAsJsonObject("start") ?: return@mapNotNull null
                val dateTime = start.get("dateTime")?.asString
                val allDay   = dateTime == null
                CalendarEvent(
                    id       = o.get("id")?.asString ?: return@mapNotNull null,
                    title    = o.get("summary")?.asString ?: "(no title)",
                    startIso = dateTime ?: start.get("date")?.asString ?: "",
                    allDay   = allDay,
                    link     = o.get("hangoutLink")?.asString ?: o.get("htmlLink")?.asString ?: ""
                )
            }?.sortedBy { it.startIso } ?: emptyList()
        }
    }

    suspend fun deleteCalendarEvent(eventId: String): Result<Boolean> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/calendar/events/$eventId").delete().build()
            ).execute()
            gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java).get("ok")?.asBoolean ?: false
        }
    }

    // ── Browser recordings ────────────────────────────────────────
    suspend fun getRecordings(): Result<List<Recording>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/browser/recordings").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            if (obj.get("ok")?.asBoolean != true) error(obj.get("error")?.asString ?: "Failed to load recordings")
            obj.getAsJsonArray("recordings")?.map { el ->
                val o = el.asJsonObject
                Recording(
                    name           = o.get("name")?.asString ?: "",
                    startUrl       = o.get("start_url")?.asString ?: "",
                    steps          = o.get("steps")?.asInt ?: 0,
                    triggerPhrases = o.getAsJsonArray("trigger_phrases")?.map { it.asString } ?: emptyList(),
                    scheduleCron   = o.get("schedule_cron")?.asString ?: "",
                    createdAt      = o.get("created_at")?.asString ?: ""
                )
            } ?: emptyList()
        }
    }

    suspend fun replayRecording(name: String): Result<Pair<Boolean, String>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/browser/recordings/${Uri.encode(name)}/replay")
                    .post("".toRequestBody(null)).build()
            ).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            val ok = obj.get("ok")?.asBoolean ?: false
            val completed = obj.get("completed")?.asInt ?: 0
            val total = obj.get("total")?.asInt ?: 0
            val summary = if (ok) "Replay finished — $completed/$total steps."
            else "Replay stopped — $completed/$total steps completed."
            Pair(ok, summary)
        }
    }

    suspend fun deleteRecording(name: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            client.newCall(
                Request.Builder().url("${baseUrl()}/browser/recordings/${Uri.encode(name)}").delete().build()
            ).execute()
            Unit
        }
    }

    // ── Memory (key/value personal facts) ──────────────────────────
    suspend fun getMemoryEntries(): Result<List<MemoryEntry>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/memory").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            if (obj.get("ok")?.asBoolean != true) error(obj.get("error")?.asString ?: "Failed to load memory")
            obj.getAsJsonArray("data")?.map { el ->
                val o = el.asJsonObject
                MemoryEntry(
                    key   = o.get("key")?.asString ?: "",
                    value = o.get("value")?.asString ?: "",
                    added = o.get("added")?.asString ?: ""
                )
            } ?: emptyList()
        }
    }

    suspend fun addMemoryEntry(key: String, value: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("key" to key, "value" to value))
                .toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/memory").post(body).build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            if (obj.get("ok")?.asBoolean != true) error(obj.get("error")?.asString ?: "Failed to save")
            Unit
        }
    }

    suspend fun deleteMemoryEntry(key: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            client.newCall(
                Request.Builder().url("${baseUrl()}/memory/${Uri.encode(key)}").delete().build()
            ).execute()
            Unit
        }
    }

    // ── Automations & scheduler ─────────────────────────────────────
    suspend fun getAutomations(): Result<List<Automation>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/smart-memory?category=automation").build()
            ).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            if (obj.get("ok")?.asBoolean != true) error(obj.get("error")?.asString ?: "Failed to load automations")
            obj.getAsJsonArray("data")?.map { el ->
                val o = el.asJsonObject
                val sched = o.getAsJsonObject("auto_schedule")
                Automation(
                    id      = o.get("id")?.asString ?: "",
                    content = o.get("content")?.asString ?: "",
                    enabled = o.get("enabled")?.asBoolean ?: true,
                    created = o.get("created")?.asString ?: "",
                    cron    = sched?.get("cron")?.asString ?: ""
                )
            } ?: emptyList()
        }
    }

    suspend fun getSchedulerJobs(): Result<List<SchedulerJob>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/smart-memory/jobs").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("jobs")?.map { el ->
                val o = el.asJsonObject
                SchedulerJob(id = o.get("id")?.asString ?: "", nextRun = o.get("next_run")?.asString ?: "—")
            } ?: emptyList()
        }
    }

    suspend fun addAutomation(content: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("category" to "automation", "content" to content))
                .toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/smart-memory").post(body).build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            if (obj.get("ok")?.asBoolean != true) error(obj.get("error")?.asString ?: "Failed to add automation")
            Unit
        }
    }

    suspend fun setAutomationEnabled(id: String, enabled: Boolean): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("enabled" to enabled))
                .toRequestBody("application/json".toMediaType())
            client.newCall(
                Request.Builder().url("${baseUrl()}/smart-memory/$id")
                    .patch(body).build()
            ).execute()
            Unit
        }
    }

    suspend fun deleteAutomation(id: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            client.newCall(Request.Builder().url("${baseUrl()}/smart-memory/$id").delete().build()).execute()
            Unit
        }
    }

    // ── Bookmarks (full-list replace semantics, matches desktop) ────
    suspend fun getBookmarks(): Result<List<Bookmark>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/api/custom_links").build()).execute()
            val arr  = gson.fromJson(resp.body?.string() ?: "[]", JsonArray::class.java)
            arr.map { el ->
                val o = el.asJsonObject
                Bookmark(
                    title  = o.get("title")?.asString ?: "",
                    url    = o.get("url")?.asString ?: "",
                    folder = o.get("folder")?.asString ?: "General"
                )
            }
        }
    }

    private suspend fun saveBookmarks(list: List<Bookmark>): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(list).toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/api/custom_links").post(body).build()).execute()
            Unit
        }
    }

    suspend fun addBookmark(title: String, url: String, folder: String): Result<Unit> {
        val current = getBookmarks().getOrDefault(emptyList())
        return saveBookmarks(current + Bookmark(title, url, folder))
    }

    suspend fun deleteBookmark(bookmark: Bookmark): Result<Unit> {
        val current = getBookmarks().getOrDefault(emptyList())
        return saveBookmarks(current.filterNot { it.title == bookmark.title && it.url == bookmark.url })
    }

    // ── Browser history (shared with the desktop Electron browser) ─
    suspend fun getBrowserHistory(query: String = "", limit: Int = 200): Result<List<BrowserHistoryEntry>> =
        withContext(Dispatchers.IO) {
            runCatching {
                val url = "${baseUrl()}/browser/history?limit=$limit" +
                    if (query.isNotBlank()) "&q=${Uri.encode(query)}" else ""
                val resp = client.newCall(Request.Builder().url(url).build()).execute()
                val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
                obj.getAsJsonArray("entries")?.map { el ->
                    val o = el.asJsonObject
                    BrowserHistoryEntry(
                        id = o.get("id")?.asString ?: "",
                        url = o.get("url")?.asString ?: "",
                        title = o.get("title")?.asString ?: "",
                        device = o.get("device")?.asString ?: "pc",
                        ts = o.get("ts")?.asString ?: ""
                    )
                } ?: emptyList()
            }
        }

    suspend fun addBrowserHistoryEntry(url: String, title: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("url" to url, "title" to title, "device" to Build.MODEL))
                .toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/browser/history").post(body).build()).execute()
            Unit
        }
    }

    // ── Open-tab sync (shared with the desktop Electron browser) ────
    // Pushes the FULL current tab list every time it changes (not an append —
    // closing/reordering tabs needs to be reflected too), so the PC's "Tabs
    // from Phone" picker always matches what's actually open right now.
    suspend fun pushOpenTabs(tabs: List<Pair<String, String>>): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(
                mapOf("device" to Build.MODEL, "tabs" to tabs.map { mapOf("url" to it.first, "title" to it.second) })
            ).toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/browser/tabs").post(body).build()).execute()
            Unit
        }
    }

    suspend fun getOtherDeviceTabs(): Result<List<OpenTabEntry>> = withContext(Dispatchers.IO) {
        runCatching {
            val url = "${baseUrl()}/browser/tabs?exclude=${Uri.encode(Build.MODEL)}"
            val resp = client.newCall(Request.Builder().url(url).build()).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            val devices = obj.getAsJsonObject("devices") ?: JsonObject()
            val result = mutableListOf<OpenTabEntry>()
            devices.keySet().forEach { device ->
                devices.getAsJsonObject(device)?.getAsJsonArray("tabs")?.forEach { el ->
                    val o = el.asJsonObject
                    result.add(
                        OpenTabEntry(
                            device = device,
                            url = o.get("url")?.asString ?: "",
                            title = o.get("title")?.asString ?: ""
                        )
                    )
                }
            }
            result
        }
    }

    // Asks the PC to autofill a saved login for this URL. Only the URL crosses
    // the network — the PC looks up the credential, re-verifies with Windows
    // Hello, and injects it locally; the decrypted password never reaches the
    // phone or travels over this connection.
    suspend fun requestAutofillOnPc(url: String): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf("url" to url)).toRequestBody("application/json".toMediaType())
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/browser/autofill-request").post(body).build()).execute()
            if (!resp.isSuccessful) error("HTTP ${resp.code}")
            Unit
        }
    }

    // ── WhatsApp conversation browser ────────────────────────────────
    suspend fun getWaRecentChats(hours: Int = 24): Result<List<WaChatSummary>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/whatsapp/messages/history?hours=$hours").build()
            ).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            val msgs = obj.getAsJsonArray("messages") ?: JsonArray()
            // Bucket by number, keep only the latest message per contact.
            val byNumber = LinkedHashMap<String, WaChatSummary>()
            msgs.forEach { el ->
                val o = el.asJsonObject
                val number = o.get("number")?.asString ?: return@forEach
                val ts = o.get("timestamp")?.asLong ?: 0L
                val existing = byNumber[number]
                if (existing == null || ts > existing.timestamp) {
                    byNumber[number] = WaChatSummary(
                        name      = o.get("sender")?.asString ?: number,
                        number    = number,
                        lastText  = o.get("text")?.asString ?: "",
                        timestamp = ts
                    )
                }
            }
            byNumber.values.sortedByDescending { it.timestamp }
        }
    }

    suspend fun getWaThread(number: String, limit: Int = 30): Result<List<WaThreadMessage>> = withContext(Dispatchers.IO) {
        runCatching {
            val url = "${baseUrl()}/whatsapp/messages/chat?number=${Uri.encode(number)}&limit=$limit"
            val resp = client.newCall(Request.Builder().url(url).build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("messages")?.map { el ->
                val o = el.asJsonObject
                WaThreadMessage(
                    id        = o.get("id")?.asString ?: "",
                    sender    = o.get("sender")?.asString ?: "",
                    number    = number,
                    text      = o.get("text")?.asString ?: "",
                    timestamp = o.get("timestamp")?.asLong ?: 0L,
                    chat      = o.get("chat")?.asString ?: "",
                    fromMe    = o.get("fromMe")?.asBoolean ?: false
                )
            } ?: emptyList()
        }
    }

    // ── News / quick brief ───────────────────────────────────────────
    suspend fun getNewsHeadlines(topic: String = "india", count: Int = 8): Result<List<NewsHeadline>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${baseUrl()}/news/headlines?topic=$topic&count=$count").build()
            ).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonArray("items")?.map { el ->
                val o = el.asJsonObject
                NewsHeadline(
                    title     = o.get("title")?.asString ?: "",
                    source    = o.get("source")?.asString ?: "",
                    link      = o.get("link")?.asString ?: "",
                    published = o.get("published")?.asString ?: ""
                )
            } ?: emptyList()
        }
    }

    suspend fun getMarketIndices(): Result<List<MarketIndex>> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/news/market").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            val indices = obj.getAsJsonObject("indices") ?: JsonObject()
            indices.entrySet().map { (label, el) ->
                val o = el.asJsonObject
                MarketIndex(
                    label  = label,
                    price  = o.get("price")?.asDouble ?: 0.0,
                    change = o.get("change")?.asDouble ?: 0.0,
                    pct    = o.get("pct")?.asDouble ?: 0.0
                )
            }
        }
    }

    // ── Proactive agent settings (reuses generic /settings GET/POST) ─
    suspend fun getProactiveSettings(): Result<JsonObject> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(Request.Builder().url("${baseUrl()}/settings").build()).execute()
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.getAsJsonObject("settings") ?: JsonObject()
        }
    }

    suspend fun setSetting(key: String, value: Any): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(mapOf(key to value)).toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${baseUrl()}/settings").post(body).build()).execute()
            Unit
        }
    }
}
