// iZACH Secretary - V4.1 (Bridge Fixed)
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const googleTTS = require('google-tts-api');
const fs = require('fs'); // For The Bridge

const USER_NAME = "Vansh"; 
const BOT_PHONETIC_NAME = "Eye-Zack"; 
const COOLDOWN_SECONDS = 10; 
let lastCallTime = 0; 

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: { headless: true, args: ['--no-sandbox'] }
});

client.on('qr', (qr) => qrcode.generate(qr, { small: true }));
client.on('ready', () => console.log('>> iZACH Secretary is ONLINE <<'));

client.on('call', async (call) => {
    try {
        // --- FIX: Use CLIENT to look up the contact ---
        const contact = await client.getContactById(call.from);
        const callerName = contact.name || contact.pushname || contact.number;

        // Check Cooldown
        const now = Date.now();
        if ((now - lastCallTime) / 1000 < COOLDOWN_SECONDS) return;
        lastCallTime = now;

        console.log(`[CALL DETECTED] From: ${callerName}`);

        // --- THE BRIDGE: Write the file for Python ---
        fs.writeFileSync('../call_signal.txt', callerName); 
        console.log(`[BRIDGE] Signal sent to Python.`);

        // --- REJECT & REPLY ---
        await call.reject();

        const textToSpeak = `Hello. This is ${BOT_PHONETIC_NAME}. ${USER_NAME} is unavailable. Please leave a text message.`;
        const url = googleTTS.getAudioUrl(textToSpeak, { lang: 'en-GB', slow: false, host: 'https://translate.google.com' });
        const media = await MessageMedia.fromUrl(url, { unsafeMime: true });
        
        await client.sendMessage(call.from, media, { sendAudioAsVoice: true });

    } catch (error) {
        console.error("Error:", error);
    }
});

client.initialize();