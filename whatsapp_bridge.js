const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const fs = require('fs');
const path = require('path');

const SESSION_PATH = path.join(__dirname, '.wwebjs_auth');
const STARTUP_TIME = Math.floor(Date.now() / 1000); // Unix timestamp in seconds

const app = express();
app.use(express.json());

let isReady = false;
let activeClient = null;

// Gates outgoing sends until WhatsApp Web's internal chat/contact store has
// finished syncing after 'ready' — sending too early is a known trigger for
// whatsapp-web.js's "No LID for user" error (WhatsApp's identity-migration
// bug, see github.com/pedroslopez/whatsapp-web.js issues #3834/#5750/#3985).
// This can't fully eliminate that upstream bug — it still surfaces
// intermittently even in warmed-up sessions — but it removes the "bridge
// just started, fired a send immediately" case entirely.
let sendReady = false;
function _waitUntilSendReady(maxMs = 10000) {
    return new Promise((resolve) => {
        if (sendReady) return resolve(true);
        const start = Date.now();
        const iv = setInterval(() => {
            if (sendReady || Date.now() - start > maxMs) {
                clearInterval(iv);
                resolve(sendReady);
            }
        }, 250);
    });
}

// Only one recovery cycle should ever be in flight — whatsapp-web.js's own
// 'disconnected' event AND a failed /messages/* call can both notice the
// same broken session around the same time, and without this guard they'd
// each schedule their own destroy()+createClient(), racing two clients into
// existence.
let _recovering = false;
function _recoverFromStaleClient(client, reason) {
    if (_recovering) return;
    _recovering = true;
    isReady = false;
    sendReady = false;
    console.log(`[WHATSAPP] Recovering — ${reason}. Restarting...`);
    notifyIZACH('/whatsapp/status', { status: 'disconnected' });
    setTimeout(() => {
        client.destroy()
            .then(() => createClient())
            .catch(err => {
                console.log(`[BRIDGE] Destroy/restart error: ${err.message}`);
                createClient();
            })
            .finally(() => { _recovering = false; });
    }, 5000);
}

// A previous session's client can get stuck during initialize() — neither
// 'ready' nor 'qr' ever fires, no error either — most often because the
// LocalAuth session dir (.wwebjs_auth) itself is corrupted, e.g. from the
// Chromium profile being killed mid-write by an ungraceful process
// termination. Puppeteer/whatsapp-web.js don't time this out on their own,
// so without this watchdog it just hangs at "connecting" forever with no
// way to recover short of manually deleting the session directory by hand.
const INIT_TIMEOUT_MS = 90000;

function createClient() {
    const client = new Client({
        authStrategy: new LocalAuth(),
        puppeteer: {
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        }
    });
    activeClient = client;

    const initWatchdog = setTimeout(() => {
        console.log(`[WHATSAPP] Still not ready/QR after ${INIT_TIMEOUT_MS / 1000}s — session likely corrupted. Clearing and retrying fresh.`);
        // A prior session's isReady/sendReady could still be true here (this
        // watchdog fires on RE-init, not just first boot) — without resetting
        // them, callers keep seeing "connected" while the client is actually
        // being destroyed and rebuilt from scratch.
        isReady = false;
        sendReady = false;
        notifyIZACH('/whatsapp/status', { status: 'disconnected' });
        try {
            fs.rmSync(SESSION_PATH, { recursive: true, force: true });
            console.log('[BRIDGE] Session cleared.');
        } catch (e) {
            console.log(`[BRIDGE] Could not clear session: ${e.message}`);
        }
        client.destroy()
            .catch(() => {})
            .finally(() => createClient());
    }, INIT_TIMEOUT_MS);

    client.on('qr', qr => {
        clearTimeout(initWatchdog);
        console.log('[WHATSAPP] Scan QR code:');
        qrcode.generate(qr, { small: true });
        notifyIZACH('/whatsapp/qr', { qr });
    });

    let acceptMessages = false;

    client.on('ready', () => {
        clearTimeout(initWatchdog);
        isReady = true;
        console.log('[WHATSAPP] Bridge Online');
        notifyIZACH('/whatsapp/status', { status: 'connected' });
        setTimeout(() => {
            acceptMessages = true;
            sendReady = true;
            console.log('[BRIDGE] Now accepting new messages');
        }, 8000);
    });

    client.on('disconnected', (reason) => {
        _recoverFromStaleClient(client, `disconnected: ${reason}`);
    });

    client.on('incoming_call', async (call) => {
        try {
            const contact = await client.getContactById(call.from);
            const name = contact.pushname || contact.name || contact.number;
            console.log(`[BRIDGE] Incoming call from: ${name}`);
            // Notify iZACH — returns { decline: true } when DND is active
            const resp = await fetch('http://127.0.0.1:5050/whatsapp/call', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ caller: name, number: call.from, type: 'call' })
            });
            const data = await resp.json().catch(() => ({}));
            if (data.decline) {
                await call.reject();
                console.log(`[BRIDGE] Call from ${name} rejected (DND active)`);
            }
        } catch (e) {
            console.log(`[BRIDGE] Call event error: ${e.message}`);
        }
    });

    client.on('message', async (msg) => {
        if (msg.isStatus) return;
        if (msg.from === 'status@broadcast') return;
        if (msg.fromMe) return;
        if (!acceptMessages) return;
        // Skip group chats
        if (msg.from.endsWith('@g.us')) return;
        // Skip media messages (photos, video, audio, documents)
        if (msg.hasMedia) {
            console.log(`[BRIDGE] Skipping media message from ${msg.from}`);
            return;
        }
        // Skip empty body
        if (!msg.body || !msg.body.trim()) return;
        try {
            const contact = await msg.getContact();
            const name = contact.pushname || contact.name || contact.number || msg.from;
            console.log(`[BRIDGE] Message from: ${name} — ${msg.body}`);
            await notifyIZACH('/whatsapp/message', { sender: name, number: msg.from, text: msg.body, type: 'message' });
        } catch (e) {
            console.log(`[BRIDGE] Message event error: ${e.message}`);
        }
    });

    client.initialize().catch(err => {
        console.log(`[BRIDGE] Init error: ${err.message}`);
        if (err.message.includes('already running') || err.message.includes('Execution context')) {
            console.log('[BRIDGE] Clearing session and retrying in 5s...');
            try {
                fs.rmSync(SESSION_PATH, { recursive: true, force: true });
                console.log('[BRIDGE] Session cleared.');
            } catch (e) {
                console.log(`[BRIDGE] Could not clear session: ${e.message}`);
            }
            setTimeout(createClient, 5000);
        }
    });

    return client;
}

async function notifyIZACH(endpoint, data) {
    try {
        await fetch(`http://127.0.0.1:5050${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    } catch (e) {
        // iZACH not running yet, silently ignore
    }
}

// ── Routes ──────────────────────────────────────────────────────────────
// Registered once against the shared `app` instance. Handlers read
// `activeClient`, which is repointed at the current client on every
// reconnect/restart, instead of closing over a specific client instance.

// "No LID for user" (whatsapp-web.js issues #3834/#5750/#3985) is a race in
// the library's own identity-store resolution, not a permanent failure —
// retrying a few seconds later resolves it most of the time. Only this
// specific error is retried; anything else fails immediately as before.
const _LID_ERROR = /No LID for user/i;
async function _sendWithLidRetry(sendFn, maxRetries = 2, delayMs = 3000) {
    for (let attempt = 0; ; attempt++) {
        try {
            return await sendFn();
        } catch (e) {
            const msg = e.message || String(e);
            if (attempt >= maxRetries || !_LID_ERROR.test(msg)) throw e;
            console.log(`[BRIDGE] "No LID for user" — retrying in ${delayMs}ms (attempt ${attempt + 1}/${maxRetries})`);
            await new Promise(r => setTimeout(r, delayMs));
        }
    }
}

// Send message endpoint
app.post('/send-message', async (req, res) => {
    let { number, text } = req.body;
    if (!number || !text) {
        return res.json({ status: 'error', message: 'number and text are required' });
    }
    // Normalize to WA format. Only bare phone numbers get digit-stripped and
    // forced to @c.us — a number that's already a full JID (@c.us, @g.us
    // group, or @lid — WhatsApp's newer privacy-ID identity) is left as-is.
    // Some contacts are addressed by @lid, not a phone-number JID at all;
    // force-rewriting their real @lid JID into a nonexistent @c.us one is
    // what caused "No LID for user" to fail on every retry, not just once.
    number = number.toString().trim();
    if (!/@(c\.us|g\.us|lid)$/.test(number)) {
        number = number.replace(/[^0-9]/g, '') + '@c.us';
    }
    await _waitUntilSendReady();
    try {
        await _sendWithLidRetry(() => activeClient.sendMessage(number, text));
        res.json({ status: 'sent' });
    } catch (e) {
        const errMsg = e.message || String(e) || 'unknown bridge error';
        console.log(`[BRIDGE] Send failed to ${number}: ${errMsg}`);
        res.json({ status: 'error', message: errMsg });
    }
});

// Send voice note endpoint
app.post('/send-voice', async (req, res) => {
    const { number, audio_path } = req.body;
    if (!audio_path) return res.status(400).json({ status: 'error', message: 'audio_path required' });
    await _waitUntilSendReady();
    try {
        const resolved = path.resolve(audio_path);
        const allowed = path.resolve(__dirname);
        if (!resolved.startsWith(allowed + path.sep) && resolved !== allowed) {
            return res.status(403).json({ status: 'error', message: 'Path outside allowed directory' });
        }
        const media = MessageMedia.fromFilePath(resolved);
        await _sendWithLidRetry(() => activeClient.sendMessage(number, media, { sendAudioAsVoice: true }));
        res.json({ status: 'sent' });
    } catch (e) {
        res.json({ status: 'error', message: e.message });
    }
});

// Health check
app.get('/health', (req, res) => {
    res.json({ status: isReady ? 'connected' : 'connecting' });
});

// Fetch message history for past N hours (used by Phase 3 context engine)
app.get('/messages/history', async (req, res) => {
    const hours = parseInt(req.query.hours) || 24;
    const since = Date.now() - (hours * 60 * 60 * 1000);
    if (!isReady || !activeClient) {
        return res.status(503).json({ error: 'WhatsApp not connected — scan the QR code first.', messages: [] });
    }
    try {
        const chats = await activeClient.getChats();
        const messages = [];
        for (const chat of chats.slice(0, 30)) { // limit to 30 chats
            try {
                const chatMsgs = await chat.fetchMessages({ limit: 50 });
                for (const msg of chatMsgs) {
                    if (msg.fromMe) continue;
                    if (msg.isStatus) continue;
                    if ((msg.timestamp * 1000) < since) continue;
                    const contact = await msg.getContact();
                    const name = contact.pushname || contact.name || contact.number || msg.from;
                    messages.push({
                        id: msg.id._serialized,
                        sender: name,
                        number: msg.from,
                        text: msg.body,
                        timestamp: msg.timestamp,
                        chat: chat.name || name,
                    });
                }
            } catch (e) { /* skip unreadable chat */ }
        }
        messages.sort((a, b) => a.timestamp - b.timestamp);
        res.json({ messages, count: messages.length });
    } catch (e) {
        // getChats()/fetchMessages() failing here means the underlying
        // WhatsApp Web session is actually broken even though isReady was
        // still true (whatsapp-web.js's own 'disconnected' event doesn't
        // always fire for this — the page can go stale silently). The raw
        // error is whatsapp-web.js's own minified internal JS (e.g. a bare
        // "r" from a WhatsApp Web variable name), not useful to callers —
        // report the real problem instead, and kick off the same recovery
        // the 'disconnected' handler uses.
        console.log(`[BRIDGE] /messages/history failed against a client that claimed ready: ${e.message}`);
        _recoverFromStaleClient(activeClient, `stale client (${e.message})`);
        res.status(503).json({ error: 'WhatsApp session appears broken — reconnecting automatically, try again shortly.', messages: [] });
    }
});

// Fetch recent messages from a specific chat (for draft engine)
app.get('/messages/chat', async (req, res) => {
    const { number, limit = 10 } = req.query;
    if (!number) return res.status(400).json({ error: 'number required' });
    if (!isReady || !activeClient) {
        return res.status(503).json({ error: 'WhatsApp not connected — scan the QR code first.', messages: [] });
    }
    try {
        const chats = await activeClient.getChats();
        const chat = chats.find(c => c.id._serialized === number || c.id.user === number.replace('@c.us', ''));
        if (!chat) return res.json({ messages: [], count: 0 });
        const parsedLimit = parseInt(limit);
        const msgs = await chat.fetchMessages({ limit: Number.isNaN(parsedLimit) ? 10 : parsedLimit });
        const out = [];
        for (const msg of msgs) {
            if (msg.isStatus) continue;
            const contact = msg.fromMe ? null : await msg.getContact().catch(() => null);
            const name = msg.fromMe ? 'Me' : (contact?.pushname || contact?.name || number);
            out.push({ id: msg.id._serialized, sender: name, fromMe: msg.fromMe, text: msg.body, timestamp: msg.timestamp });
        }
        res.json({ messages: out, count: out.length });
    } catch (e) {
        console.log(`[BRIDGE] /messages/chat failed against a client that claimed ready: ${e.message}`);
        _recoverFromStaleClient(activeClient, `stale client (${e.message})`);
        res.status(503).json({ error: 'WhatsApp session appears broken — reconnecting automatically, try again shortly.', messages: [] });
    }
});

app.post('/logout', async (req, res) => {
    try {
        await activeClient.logout();
        res.json({ status: 'logged_out' });
    } catch (e) {
        res.json({ status: 'error', message: e.message });
    }
});

app.post('/restart', async (req, res) => {
    try {
        isReady = false;
        notifyIZACH('/whatsapp/status', { status: 'disconnected' });
        setTimeout(() => {
            activeClient.destroy()
                .then(() => createClient())
                .catch(err => {
                    console.log(`[BRIDGE] Restart error: ${err.message}`);
                    createClient();
                });
        }, 250);
        res.json({ status: 'restarting' });
    } catch (e) {
        res.json({ status: 'error', message: e.message });
    }
});

app.listen(3000, () => console.log('[BRIDGE] Running on port 3000'));
createClient();

process.on('SIGINT', async () => {
    console.log('[BRIDGE] Shutting down gracefully...');
    try { await activeClient.destroy(); } catch (e) {}
    process.exit(0);
});

process.on('SIGTERM', async () => {
    console.log('[BRIDGE] Shutting down gracefully...');
    try { await activeClient.destroy(); } catch (e) {}
    process.exit(0);
});
