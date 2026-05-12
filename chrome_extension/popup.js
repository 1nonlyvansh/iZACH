const el = document.getElementById('status');
const ws = new WebSocket('ws://127.0.0.1:5051');

ws.onopen = () => {
    el.textContent = 'iZACH Online';
    el.className = 'on';
    ws.close();
};

ws.onerror = () => {
    el.textContent = 'iZACH Offline';
    el.className = 'off';
};

ws.onclose = () => {
    if (el.textContent === 'Checking...') {
        el.textContent = 'iZACH Offline';
        el.className = 'off';
    }
};
