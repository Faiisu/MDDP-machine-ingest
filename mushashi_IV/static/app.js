// app.js — Musashi IV Control Panel Client

const socket = io();

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    
    loadStatusAndConfig();
    setupFormHandlers();
    setupActionButtons();
    setupSocketEvents();
    resolveBackLink();
});

function updateClock() {
    const clockEl = document.getElementById('realtime-clock');
    if (!clockEl) return;
    const now = new Date();
    const hrs = String(now.getHours()).padStart(2, '0');
    const mins = String(now.getMinutes()).padStart(2, '0');
    const secs = String(now.getSeconds()).padStart(2, '0');
    clockEl.textContent = `${hrs}:${mins}:${secs}`;
}

async function loadStatusAndConfig() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        
        updateRunningStatus(data.is_running);
        populateConfigForm(data.config);
        
        if (data.last_stats) {
            updateStatsUI(data.last_stats);
        }
    } catch (err) {
        appendLog(`[ERROR] Failed to fetch status from server: ${err.message}`);
    }
}

function populateConfigForm(config) {
    if (!config) return;
    if (config.API_URL !== undefined) document.getElementById('API_URL').value = config.API_URL;
    if (config.TIME_INTERVAL !== undefined) document.getElementById('TIME_INTERVAL').value = config.TIME_INTERVAL;
    if (config.CHANNEL_NO !== undefined) document.getElementById('CHANNEL_NO').value = config.CHANNEL_NO;
    if (config.MOCKUP_MODE !== undefined) document.getElementById('MOCKUP_MODE').value = String(config.MOCKUP_MODE);
    if (config.DB_DSN !== undefined) document.getElementById('DB_DSN').value = config.DB_DSN;
}

function updateRunningStatus(isRunning) {
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');

    if (isRunning) {
        statusDot.className = 'pulse-dot online';
        statusText.textContent = 'RUNNING';
        btnStart.disabled = true;
        btnStop.disabled = false;
    } else {
        statusDot.className = 'pulse-dot offline';
        statusText.textContent = 'STOPPED';
        btnStart.disabled = false;
        btnStop.disabled = true;
    }
}

function updateStatsUI(stats) {
    if (stats.polled !== undefined) document.getElementById('telemetry-polled').textContent = stats.polled;
    if (stats.written !== undefined) document.getElementById('telemetry-written').textContent = stats.written;
    if (stats.dis_press !== undefined) {
        document.getElementById('telemetry-press').textContent = `${parseFloat(stats.dis_press).toFixed(2)} kPa`;
        document.getElementById('aud-disPress').textContent = parseFloat(stats.dis_press).toFixed(2);
    }
    if (stats.dis_vac !== undefined) {
        document.getElementById('telemetry-vac').textContent = `${parseFloat(stats.dis_vac).toFixed(2)} kPa`;
        document.getElementById('aud-disVacuum').textContent = parseFloat(stats.dis_vac).toFixed(2);
    }
    if (stats.dis_time !== undefined) {
        document.getElementById('telemetry-time').textContent = `${parseFloat(stats.dis_time).toFixed(3)} s`;
        document.getElementById('aud-disTime').textContent = parseFloat(stats.dis_time).toFixed(3);
    }
}

function appendLog(line) {
    const term = document.getElementById('log-terminal');
    if (!term) return;
    const el = document.createElement('div');
    el.className = 'log-line';
    el.textContent = line;
    term.appendChild(el);
    term.scrollTop = term.scrollHeight;
}

function setupFormHandlers() {
    const form = document.getElementById('config-form');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            API_URL: document.getElementById('API_URL').value,
            TIME_INTERVAL: parseFloat(document.getElementById('TIME_INTERVAL').value),
            CHANNEL_NO: parseInt(document.getElementById('CHANNEL_NO').value, 10),
            MOCKUP_MODE: document.getElementById('MOCKUP_MODE').value === 'true',
            DB_DSN: document.getElementById('DB_DSN').value
        };

        try {
            const resp = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const res = await resp.json();
            if (res.success) {
                alert('Configuration saved successfully!');
                appendLog('[SYSTEM] Configuration saved successfully.');
            } else {
                alert(`Error saving config: ${res.message}`);
                appendLog(`[ERROR] Save config failed: ${res.message}`);
            }
        } catch (err) {
            alert(`Network error: ${err.message}`);
        }
    });
}

function setupActionButtons() {
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const btnTestApi = document.getElementById('btn-test-api');
    const btnTestDb = document.getElementById('btn-test-db');

    btnStart.addEventListener('click', async () => {
        btnStart.disabled = true;
        try {
            const resp = await fetch('/api/start', { method: 'POST' });
            const res = await resp.json();
            if (res.success) {
                updateRunningStatus(true);
                appendLog(`[SYSTEM] ${res.message}`);
            } else {
                alert(`Failed to start: ${res.message}`);
                updateRunningStatus(false);
            }
        } catch (err) {
            alert(`Start error: ${err.message}`);
            updateRunningStatus(false);
        }
    });

    btnStop.addEventListener('click', async () => {
        btnStop.disabled = true;
        try {
            const resp = await fetch('/api/stop', { method: 'POST' });
            const res = await resp.json();
            if (res.success) {
                updateRunningStatus(false);
                appendLog(`[SYSTEM] ${res.message}`);
            } else {
                alert(`Failed to stop: ${res.message}`);
            }
        } catch (err) {
            alert(`Stop error: ${err.message}`);
        }
    });

    btnTestApi.addEventListener('click', async () => {
        const apiUrl = document.getElementById('API_URL').value;
        appendLog(`[SYSTEM] Testing API connection to ${apiUrl}...`);
        try {
            const resp = await fetch('/api/test_api', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_url: apiUrl })
            });
            const res = await resp.json();
            if (res.success) {
                alert('API Connection Successful!');
                appendLog(`[SUCCESS] API connection verified. Received data from channel.`);
            } else {
                alert(`API Connection Failed: ${res.message}`);
                appendLog(`[ERROR] API connection test failed: ${res.message}`);
            }
        } catch (err) {
            alert(`API test error: ${err.message}`);
        }
    });

    btnTestDb.addEventListener('click', async () => {
        const dsn = document.getElementById('DB_DSN').value;
        appendLog(`[SYSTEM] Testing database connection...`);
        try {
            const resp = await fetch('/api/test_db', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ dsn: dsn })
            });
            const res = await resp.json();
            if (res.success) {
                alert('Database Connection Successful!');
                appendLog(`[SUCCESS] Database connection verified.`);
            } else {
                alert(`DB Connection Failed: ${res.message}`);
                appendLog(`[ERROR] Database connection test failed: ${res.message}`);
            }
        } catch (err) {
            alert(`DB test error: ${err.message}`);
        }
    });
}

function setupSocketEvents() {
    socket.on('connect', () => {
        appendLog('[SYSTEM] WebSocket connected to Musashi IV server.');
    });

    socket.on('status_change', (data) => {
        updateRunningStatus(data.is_running);
    });

    socket.on('stats_update', (data) => {
        updateStatsUI(data);
    });

    socket.on('log_line', (data) => {
        if (data && data.data) {
            appendLog(data.data);
        }
    });
}

// Dynamically replace 'localhost' in back link with the accessing IP/hostname
function resolveBackLink() {
    const backLink = document.querySelector('.back-link');
    if (backLink) {
        const hostname = window.location.hostname || 'localhost';
        const targetUrl = `http://${hostname}:8080`;
        backLink.setAttribute('href', targetUrl);
        backLink.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = targetUrl;
        });
    }
}
