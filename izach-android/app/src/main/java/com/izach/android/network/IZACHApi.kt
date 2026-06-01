package com.izach.android.network

import android.content.Context
import android.net.Uri
import android.os.Build
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.izach.android.model.BusyStatus
import com.izach.android.model.CommandResponse
import com.izach.android.model.DndAlert
import com.izach.android.model.DndStatus
import com.izach.android.model.FileEntry
import com.izach.android.model.FileInfo
import com.izach.android.model.Message
import com.izach.android.model.SpotifyStatus
import com.izach.android.model.SystemStatus
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

class IZACHApi(context: Context) {

    private val prefs = context.getSharedPreferences("izach_prefs", Context.MODE_PRIVATE)
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.MINUTES)
        .callTimeout(15, TimeUnit.MINUTES)
        .build()

    fun baseUrl(): String =
        prefs.getString("backend_url", "http://192.168.1.100:5050")
            ?: "http://192.168.1.100:5050"

    fun wsHost(): String {
        val saved = prefs.getString("ws_host", "") ?: ""
        if (saved.isNotBlank()) return saved
        return baseUrl().substringAfter("://").substringBefore(":").substringBefore("/")
    }

    suspend fun sendCommand(text: String): Result<CommandResponse> = withContext(Dispatchers.IO) {
        runCatching {
            val deviceName = Build.MODEL
            val body = """{"text":${gson.toJson(text)},"source":"phone","device_name":${gson.toJson(deviceName)}}"""
                .toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url("${baseUrl()}/command").post(body).build()
            val resp = client.newCall(req).execute()
            val raw = resp.body?.string() ?: ""
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

    suspend fun uploadFile(uri: Uri, context: Context): Result<String> = withContext(Dispatchers.IO) {
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
                    cr.openInputStream(uri)?.use { sink.writeAll(it.source()) }
                        ?: error("Cannot open file")
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
                mma      = obj.get("mma")?.asBoolean ?: false
            )
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
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.get("message")?.asString ?: obj.get("response")?.asString ?: "Done."
        }
    }

    fun saveBackendUrl(url: String) = prefs.edit().putString("backend_url", url).apply()
    fun saveWsHost(host: String) = prefs.edit().putString("ws_host", host).apply()

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
            val obj  = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
            obj.get("message")?.asString ?: obj.get("response")?.asString ?: "Done."
        }
    }

    suspend fun alliedVolume(level: Int): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"text":"set volume to $level percent"}""".toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${alliedBaseUrl()}/command").post(body).build()).execute()
            Unit
        }
    }

    suspend fun alliedBrightness(level: Int): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = """{"text":"set brightness to $level percent"}""".toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder().url("${alliedBaseUrl()}/command").post(body).build()).execute()
            Unit
        }
    }

    suspend fun alliedScreenshot(): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val resp = client.newCall(
                Request.Builder().url("${alliedBaseUrl()}/screenshot/capture")
                    .post("".toRequestBody(null)).build()
            ).execute()
            val obj = gson.fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)
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
}
