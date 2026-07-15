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

function createClient() {
    const client = new Client({
        authStrategy: new LocalAuth(),
        puppeteer: {
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        }
    });
    activeClient = client;

    client.on('qr', qr => {
        console.log('[WHATSAPP] Scan QR code:');
        qrcode.generate(qr, { small: true });
        notifyIZACH('/whatsapp/qr', { qr });
    });

    let acceptMessages = false;

    client.on('ready', () => {
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
        isReady = false;
        sendReady = false;
        console.log(`[WHATSAPP] Disconnected: ${reason}. Restarting...`);
        notifyIZACH('/whatsapp/status', { status: 'disconnected' });
        setTimeout(() => {
            client.destroy()
                .then(() => createClient())
                .catch(err => {
                    console.log(`[BRIDGE] Destroy/restart error: ${err.message}`);
                    createClient();
                });
        }, 5000);
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

// Send message endpoint
app.post('/send-message', async (req, res) => {
    let { number, text } = req.body;
    if (!number || !text) {
        return res.json({ status: 'error', message: 'number and text are required' });
    }
    // Normalize number to WA format: strip non-digits, ensure @c.us suffix
    number = number.toString().replace(/[^0-9]/g, '');
    if (!number.endsWith('@c.us')) number = number + '@c.us';
    await _waitUntilSendReady();
    try {
        await activeClient.sendMessage(number, text);
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
    await _waitUntilSendReady();
    try {
        const resolved = path.resolve(audio_path);
        const allowed = path.resolve(__dirname);
        if (!resolved.startsWith(allowed + path.sep) && resolved !== allowed) {
            return res.status(403).json({ status: 'error', message: 'Path outside allowed directory' });
        }
        const media = MessageMedia.fromFilePath(resolved);
        await activeClient.sendMessage(number, media, { sendAudioAsVoice: true });
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
        res.status(500).json({ error: e.message });
    }
});

// Fetch recent messages from a specific chat (for draft engine)
app.get('/messages/chat', async (req, res) => {
    const { number, limit = 10 } = req.query;
    if (!number) return res.status(400).json({ error: 'number required' });
    try {
        const chats = await activeClient.getChats();
        const chat = chats.find(c => c.id._serialized === number || c.id.user === number.replace('@c.us', ''));
        if (!chat) return res.json({ messages: [], count: 0 });
        const msgs = await chat.fetchMessages({ limit: parseInt(limit) });
        const out = [];
        for (const msg of msgs) {
            if (msg.isStatus) continue;
            const contact = msg.fromMe ? null : await msg.getContact().catch(() => null);
            const name = msg.fromMe ? 'Me' : (contact?.pushname || contact?.name || number);
            out.push({ id: msg.id._serialized, sender: name, fromMe: msg.fromMe, text: msg.body, timestamp: msg.timestamp });
        }
        res.json({ messages: out, count: out.length });
    } catch (e) {
        res.status(500).json({ error: e.message });
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
