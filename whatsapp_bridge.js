const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Kill any leftover Chrome processes before starting
try {
    execSync('taskkill /F /IM chrome.exe /T 2>nul', { stdio: 'ignore' });
} catch (e) {}

const SESSION_PATH = path.join(__dirname, '.wwebjs_auth');
const STARTUP_TIME = Math.floor(Date.now() / 1000); // Unix timestamp in seconds

const app = express();
app.use(express.json());

let isReady = false;

function createClient() {
    const client = new Client({
        authStrategy: new LocalAuth(),
        puppeteer: {
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        }
    });

    client.on('qr', qr => {
        console.log('[WHATSAPP] Scan QR code:');
        qrcode.generate(qr, { small: true });
    });

    let acceptMessages = false;

    client.on('ready', () => {
        isReady = true;
        console.log('[WHATSAPP] Bridge Online');
        notifyIZACH('/whatsapp/status', { status: 'connected' });
        setTimeout(() => {
            acceptMessages = true;
            console.log('[BRIDGE] Now accepting new messages');
        }, 8000);
    });

    client.on('disconnected', (reason) => {
        isReady = false;
        console.log(`[WHATSAPP] Disconnected: ${reason}. Restarting...`);
        notifyIZACH('/whatsapp/status', { status: 'disconnected' });
        setTimeout(() => {
            client.destroy().then(() => createClient());
        }, 5000);
    });

    client.on('incoming_call', async (call) => {
        try {
            const contact = await client.getContactById(call.from);
            const name = contact.pushname || contact.name || contact.number;
            console.log(`[BRIDGE] Incoming call from: ${name}`);
            await notifyIZACH('/whatsapp/call', { caller: name, number: call.from, type: 'call' });
        } catch (e) {
            console.log(`[BRIDGE] Call event error: ${e.message}`);
        }
    });

    client.on('message', async (msg) => {
        if (msg.isStatus) return;
        if (msg.from === 'status@broadcast') return;
        if (msg.fromMe) return;
        if (!acceptMessages) return;
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

    // Send message endpoint
    app.post('/send-message', async (req, res) => {
        const { number, text } = req.body;
        try {
            await client.sendMessage(number, text);
            res.json({ status: 'sent' });
        } catch (e) {
            res.json({ status: 'error', message: e.message });
        }
    });

    // Send voice note endpoint
    app.post('/send-voice', async (req, res) => {
        const { number, audio_path } = req.body;
        try {
            const resolved = path.resolve(audio_path);
            const allowed = path.resolve(__dirname);
            if (!resolved.startsWith(allowed + path.sep) && resolved !== allowed) {
                return res.status(403).json({ status: 'error', message: 'Path outside allowed directory' });
            }
            const media = MessageMedia.fromFilePath(resolved);
            await client.sendMessage(number, media, { sendAudioAsVoice: true });
            res.json({ status: 'sent' });
        } catch (e) {
            res.json({ status: 'error', message: e.message });
        }
    });

    // Health check
    app.get('/health', (req, res) => {
        res.json({ status: isReady ? 'connected' : 'connecting' });
    });

    app.post('/logout', async (req, res) => {
        try {
            await client.logout();
            res.json({ status: 'logged_out' });
        } catch (e) {
            res.json({ status: 'error', message: e.message });
        }
    });

    return client;
}

async function notifyIZACH(endpoint, data) {
    try {
        await fetch(`http://localhost:5050${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    } catch (e) {
        // iZACH not running yet, silently ignore
    }
}

app.listen(3000, () => console.log('[BRIDGE] Running on port 3000'));
const activeClient = createClient();

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