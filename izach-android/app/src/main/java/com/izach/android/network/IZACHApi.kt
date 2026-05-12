package com.izach.android.network

import android.content.Context
import android.net.Uri
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.izach.android.model.CommandResponse
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
            val body = """{"text":${gson.toJson(text)}}"""
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

    fun saveBackendUrl(url: String) = prefs.edit().putString("backend_url", url).apply()
    fun saveWsHost(host: String) = prefs.edit().putString("ws_host", host).apply()
}
