package com.izach.android.network

import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.izach.android.model.DndAlert
import com.izach.android.model.DndStatus
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

class IZACHWebSocket(private val api: IZACHApi) {

    private val TAG = "iZACH-WS"
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build()
    private var webSocket: WebSocket? = null
    private val reconnectHandler = Handler(Looper.getMainLooper())
    private var reconnectScheduled = false
    private var shouldReconnect = true

    var isConnected = false
        private set

    var onChat: ((sender: String, text: String, ts: String) -> Unit)? = null
    var onNotification: ((text: String) -> Unit)? = null
    var onConnected: (() -> Unit)? = null
    var onDisconnected: (() -> Unit)? = null
    var onScreenshot: ((filename: String) -> Unit)? = null
    var onClipboard: ((text: String) -> Unit)? = null
    var onTaskEvent: ((type: String, id: String, name: String, progress: Int, message: String) -> Unit)? = null
    // New unified-event-bus callbacks
    var onPcNotification: ((title: String, body: String, category: String) -> Unit)? = null
    var onDownloadEvent: ((type: String, filename: String, size: Long, speedStr: String) -> Unit)? = null
    var onDndAlert: ((DndAlert) -> Unit)? = null
    var onDndStatus: ((DndStatus) -> Unit)? = null
    var onBusyStatus: ((active: Boolean, reason: String) -> Unit)? = null
    var onReminder:   ((title: String, body: String) -> Unit)?     = null
    var onBrowserHandoff: ((url: String, title: String) -> Unit)? = null

    private fun scheduleReconnect() {
        if (reconnectScheduled || !shouldReconnect) return
        reconnectScheduled = true
        reconnectHandler.postDelayed({
            reconnectScheduled = false
            if (shouldReconnect && !isConnected) connect()
        }, 3000L)
    }

    fun connect() {
        shouldReconnect = true
        val host = api.wsHost()
        val url = "ws://$host:5051"
        Log.d(TAG, "Connecting to $url")
        val req = Request.Builder().url(url).build()
        webSocket = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                isConnected = true
                Log.d(TAG, "Connected")
                // The WS port has no auth of its own, so the backend only
                // trusts this hello (and flips the phone-connected indicator)
                // if it proves possession of the pairing secret, the same way
                // every signed HTTP request does — otherwise any device on
                // the LAN could claim to be "android_device" and show as
                // connected without ever being paired.
                val secret = api.pairingSecret()
                val hello = if (secret.isBlank()) {
                    """{"type":"client_hello","name":"android_device","device_name":"${Build.MODEL}"}"""
                } else {
                    val ts = (System.currentTimeMillis() / 1000).toString()
                    val message = "ws_hello|$ts".toByteArray()
                    val mac = javax.crypto.Mac.getInstance("HmacSHA256")
                    mac.init(javax.crypto.spec.SecretKeySpec(secret.toByteArray(), "HmacSHA256"))
                    val sig = mac.doFinal(message).joinToString("") { "%02x".format(it) }
                    """{"type":"client_hello","name":"android_device","device_name":"${Build.MODEL}","ts":"$ts","sig":"$sig"}"""
                }
                ws.send(hello)
                onConnected?.invoke()
            }

            override fun onMessage(ws: WebSocket, text: String) {
                try {
                    val json = gson.fromJson(text, JsonObject::class.java)

                    // New unified event format: {"event":..., "source":..., "payload":{}}
                    val eventKey = json.get("event")?.asString
                    if (eventKey != null) {
                        val payload = json.getAsJsonObject("payload") ?: JsonObject()
                        handleUnifiedEvent(eventKey, payload)
                        return
                    }

                    // Legacy type-based format
                    when (json.get("type")?.asString) {
                        "chat" -> {
                            val sender = json.get("sender")?.asString ?: "iZACH"
                            val msg = json.get("text")?.asString ?: return
                            val ts = json.get("ts")?.asString ?: ""
                            if (msg.isNotBlank()) onChat?.invoke(sender, msg, ts)
                        }
                        "notification" -> {
                            val msg = json.get("text")?.asString ?: return
                            if (msg.isNotBlank()) onNotification?.invoke(msg)
                        }
                        "screenshot_ready" -> {
                            val filename = json.get("filename")?.asString ?: return
                            onScreenshot?.invoke(filename)
                        }
                        "clipboard" -> {
                            val clip = json.get("text")?.asString ?: return
                            if (clip.isNotBlank()) onClipboard?.invoke(clip)
                        }
                        "dnd_alert" -> {
                            val id     = json.get("id")?.asInt ?: return
                            val from   = json.get("from")?.asString ?: return
                            val number = json.get("number")?.asString ?: return
                            val text   = json.get("text")?.asString ?: ""
                            val type   = json.get("alert_type")?.asString
                                ?: json.get("type")?.asString ?: ""
                            val ts     = json.get("ts")?.asLong ?: (System.currentTimeMillis() / 1000L)
                            val action     = if (json.has("action") && !json.get("action").isJsonNull)
                                json.get("action").asString else null
                            val isPriority = json.get("is_priority")?.asBoolean ?: false
                            onDndAlert?.invoke(DndAlert(id, from, number, text, type, ts, action, isPriority))
                        }
                        "dnd_status" -> {
                            val active     = json.get("active")?.asBoolean ?: return
                            val reason     = json.get("reason")?.asString ?: ""
                            val queueCount = json.get("queue_count")?.asInt ?: 0
                            onDndStatus?.invoke(DndStatus(active, reason, queueCount))
                        }
                        "busy_status" -> {
                            val active = json.get("active")?.asBoolean ?: return
                            val reason = json.get("reason")?.asString ?: "manual"
                            onBusyStatus?.invoke(active, reason)
                        }
                        "reminder_alert" -> {
                            val title = json.get("title")?.asString ?: return
                            val body  = json.get("body")?.asString  ?: title
                            onReminder?.invoke(title, body)
                        }
                        "task_started", "task_progress", "task_completed", "task_failed" -> {
                            val type = json.get("type")?.asString ?: return
                            val id = json.get("id")?.asString ?: return
                            val name = json.get("name")?.asString ?: json.get("message")?.asString ?: ""
                            val prog = json.get("progress")?.asInt ?: 0
                            val msg = json.get("message")?.asString ?: json.get("error")?.asString ?: ""
                            onTaskEvent?.invoke(type, id, name, prog, msg)
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Parse error: $e")
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                isConnected = false
                Log.w(TAG, "Disconnected: $t")
                onDisconnected?.invoke()
                scheduleReconnect()
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                isConnected = false
                onDisconnected?.invoke()
                if (code != 1000) scheduleReconnect()
            }
        })
    }

    private fun handleUnifiedEvent(event: String, payload: JsonObject) {
        when (event) {
            "clipboard_changed" -> {
                val clipText = payload.get("text")?.asString ?: return
                if (clipText.isNotBlank()) onClipboard?.invoke(clipText)
            }
            "notification" -> {
                val title = payload.get("title")?.asString ?: return
                val body = payload.get("body")?.asString ?: ""
                val category = payload.get("category")?.asString ?: "system"
                onPcNotification?.invoke(title, body, category)
            }
            "dnd_alert" -> {
                val id     = payload.get("id")?.asInt ?: return
                val from   = payload.get("from")?.asString ?: return
                val number = payload.get("number")?.asString ?: return
                val text   = payload.get("text")?.asString ?: ""
                val type   = payload.get("type")?.asString ?: ""
                val ts     = payload.get("ts")?.asLong ?: (System.currentTimeMillis() / 1000L)
                val action     = if (payload.has("action") && !payload.get("action").isJsonNull)
                    payload.get("action").asString else null
                val isPriority = payload.get("is_priority")?.asBoolean ?: false
                onDndAlert?.invoke(DndAlert(id, from, number, text, type, ts, action, isPriority))
            }
            "dnd_status" -> {
                val active     = payload.get("active")?.asBoolean ?: return
                val reason     = payload.get("reason")?.asString ?: ""
                val queueCount = payload.get("queue_count")?.asInt ?: 0
                onDndStatus?.invoke(DndStatus(active, reason, queueCount))
            }
            "busy_status" -> {
                val active = payload.get("active")?.asBoolean ?: return
                val reason = payload.get("reason")?.asString ?: "manual"
                onBusyStatus?.invoke(active, reason)
            }
            "reminder_alert" -> {
                val title = payload.get("title")?.asString ?: return
                val body  = payload.get("body")?.asString  ?: title
                onReminder?.invoke(title, body)
            }
            "download_started", "download_progress", "download_completed", "download_failed" -> {
                val filename = payload.get("filename")?.asString ?: return
                val size = payload.get("size")?.asLong ?: 0L
                val speedStr = payload.get("speed_str")?.asString ?: ""
                onDownloadEvent?.invoke(event, filename, size, speedStr)
            }
            "browser_handoff" -> {
                val url = payload.get("url")?.asString ?: return
                val title = payload.get("title")?.asString ?: url
                onBrowserHandoff?.invoke(url, title)
            }
        }
    }

    fun disconnect() {
        shouldReconnect = false
        reconnectHandler.removeCallbacksAndMessages(null)
        webSocket?.close(1000, "App closed")
        webSocket = null
        isConnected = false
    }
}
