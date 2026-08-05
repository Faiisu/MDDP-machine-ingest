// app.js - InfluxDB Manager Frontend Logic

document.addEventListener('DOMContentLoaded', () => {
    // 1. Clock Thread
    updateClock();
    setInterval(updateClock, 1000);

    // 2. Load Config & Initial Status
    loadConfig();
    checkStatus();
    setInterval(checkStatus, 5000);

    // 3. Setup Retention Input Listeners
    setupRetentionListeners();

    // 4. Setup Button Handlers
    document.getElementById('config-form').addEventListener('submit', handleConfigSave);
    document.getElementById('btn-start').addEventListener('click', handleStart);
    document.getElementById('btn-stop').addEventListener('click', handleStop);
    document.getElementById('btn-refresh-status').addEventListener('click', checkStatus);
    document.getElementById('btn-copy-token').addEventListener('click', handleCopyToken);
    document.getElementById('btn-sync-daq').addEventListener('click', handleSyncDaq);
    document.getElementById('btn-apply-retention').addEventListener('click', handleApplyRetention);
    document.getElementById('btn-refresh-logs').addEventListener('click', fetchLogs);
});

function updateClock() {
    const el = document.getElementById('realtime-clock');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toTimeString().split(' ')[0];
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    const msgEl = document.getElementById('toast-message');
    if (!toast || !msgEl) return;

    msgEl.textContent = message;
    toast.style.borderColor = isError ? '#f43f5e' : '#0ea5e9';
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3500);
}

async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) return;
        const cfg = await res.json();

        document.getElementById('INFLUX_URL').value = cfg.INFLUX_URL || 'http://localhost:8086';
        document.getElementById('INFLUX_ORG').value = cfg.INFLUX_ORG || 'mddp';
        document.getElementById('INFLUX_BUCKET').value = cfg.INFLUX_BUCKET || 'daq_telemetry';
        document.getElementById('INFLUX_MEASUREMENT').value = cfg.INFLUX_MEASUREMENT || 'daq_telemetry';
        document.getElementById('INFLUX_USERNAME').value = cfg.INFLUX_USERNAME || 'admin';
        document.getElementById('INFLUX_PASSWORD').value = cfg.INFLUX_PASSWORD || '';
        document.getElementById('INFLUX_TOKEN').value = cfg.INFLUX_TOKEN || '';

        const retEnabled = cfg.RETENTION_ENABLED !== false;
        document.getElementById('RETENTION_ENABLED').checked = retEnabled;
        document.getElementById('RETENTION_DAYS').value = cfg.RETENTION_DAYS ?? 30;
        document.getElementById('RETENTION_HOURS').value = cfg.RETENTION_HOURS ?? 0;
        document.getElementById('RETENTION_MINUTES').value = cfg.RETENTION_MINUTES ?? 0;
        document.getElementById('RETENTION_SECONDS').value = cfg.RETENTION_SECONDS ?? 0;

        updateRetentionSummary();
    } catch (e) {
        console.error('Failed to load config:', e);
    }
}

async function checkStatus() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    const pill = document.getElementById('container-status-pill');

    try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error('Status request failed');
        const data = await res.json();

        if (pill) pill.textContent = `Container: ${data.container_status.toUpperCase()}`;

        if (data.is_healthy) {
            dot.className = 'pulse-dot green';
            text.textContent = 'INFLUXDB_ONLINE';
        } else if (data.container_status === 'running') {
            dot.className = 'pulse-dot yellow';
            text.textContent = 'BOOTING...';
        } else {
            dot.className = 'pulse-dot red';
            text.textContent = 'STOPPED';
        }

        if (data.token && !document.getElementById('INFLUX_TOKEN').value) {
            document.getElementById('INFLUX_TOKEN').value = data.token;
        }
    } catch (e) {
        if (dot) dot.className = 'pulse-dot red';
        if (text) text.textContent = 'OFFLINE';
    }
}

function setupRetentionListeners() {
    const toggle = document.getElementById('RETENTION_ENABLED');
    const inputs = ['RETENTION_DAYS', 'RETENTION_HOURS', 'RETENTION_MINUTES', 'RETENTION_SECONDS'];

    toggle.addEventListener('change', updateRetentionSummary);
    inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', updateRetentionSummary);
        }
    });
}

function updateRetentionSummary() {
    const enabled = document.getElementById('RETENTION_ENABLED').checked;
    const days = parseInt(document.getElementById('RETENTION_DAYS').value || '0', 10);
    const hours = parseInt(document.getElementById('RETENTION_HOURS').value || '0', 10);
    const minutes = parseInt(document.getElementById('RETENTION_MINUTES').value || '0', 10);
    const seconds = parseInt(document.getElementById('RETENTION_SECONDS').value || '0', 10);

    const totalSec = (days * 86400) + (hours * 3600) + (minutes * 60) + seconds;
    const bucketName = document.getElementById('INFLUX_BUCKET').value || 'daq_telemetry';

    const textEl = document.getElementById('retention-summary-text');
    const calcEl = document.getElementById('retention-total-sec-text');
    const blockEl = document.getElementById('retention-settings-block');

    if (blockEl) {
        blockEl.style.opacity = enabled ? '1' : '0.4';
        blockEl.style.pointerEvents = enabled ? 'auto' : 'none';
    }

    if (!enabled) {
        textEl.textContent = `Auto-remove disabled — telemetry data in bucket "${bucketName}" will be kept indefinitely (infinite retention).`;
        calcEl.textContent = 'Total Retention Duration: Infinite (0s)';
    } else {
        let durationParts = [];
        if (days > 0) durationParts.push(`${days} day${days > 1 ? 's' : ''}`);
        if (hours > 0) durationParts.push(`${hours} hour${hours > 1 ? 's' : ''}`);
        if (minutes > 0) durationParts.push(`${minutes} minute${minutes > 1 ? 's' : ''}`);
        if (seconds > 0) durationParts.push(`${seconds} second${seconds > 1 ? 's' : ''}`);

        const str = durationParts.length > 0 ? durationParts.join(', ') : '0 seconds';
        textEl.textContent = `Data older than ${str} will be automatically purged from bucket "${bucketName}".`;
        calcEl.textContent = `Total Retention Duration: ${totalSec.toLocaleString()} seconds`;
    }
}

async function handleConfigSave(e) {
    e.preventDefault();
    const payload = {
        INFLUX_URL: document.getElementById('INFLUX_URL').value,
        INFLUX_ORG: document.getElementById('INFLUX_ORG').value,
        INFLUX_BUCKET: document.getElementById('INFLUX_BUCKET').value,
        INFLUX_MEASUREMENT: document.getElementById('INFLUX_MEASUREMENT').value,
        INFLUX_USERNAME: document.getElementById('INFLUX_USERNAME').value,
        INFLUX_PASSWORD: document.getElementById('INFLUX_PASSWORD').value,
        INFLUX_TOKEN: document.getElementById('INFLUX_TOKEN').value
    };

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error('Save failed');
        showToast('Credentials saved successfully!');
    } catch (err) {
        showToast('Failed to save config.', true);
    }
}

async function handleStart() {
    showToast('Starting InfluxDB container...');
    try {
        const res = await fetch('/api/start', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast('InfluxDB container started!');
            checkStatus();
            fetchLogs();
        } else {
            showToast(`Start failed: ${data.message}`, true);
        }
    } catch (e) {
        showToast('Start request error.', true);
    }
}

async function handleStop() {
    showToast('Stopping InfluxDB container...');
    try {
        const res = await fetch('/api/stop', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast('InfluxDB container stopped.');
            checkStatus();
            fetchLogs();
        } else {
            showToast(`Stop failed: ${data.message}`, true);
        }
    } catch (e) {
        showToast('Stop request error.', true);
    }
}

function handleCopyToken() {
    const tokenInput = document.getElementById('INFLUX_TOKEN');
    if (!tokenInput || !tokenInput.value) {
        showToast('No API token available to copy.', true);
        return;
    }
    navigator.clipboard.writeText(tokenInput.value)
        .then(() => showToast('Token copied to clipboard!'))
        .catch(() => showToast('Failed to copy token.', true));
}

async function handleSyncDaq() {
    showToast('Syncing InfluxDB settings to DAQ Service (8081)...');
    try {
        const res = await fetch('/api/sync_daq', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Synced successfully!');
        } else {
            showToast(`Sync failed: ${data.message}`, true);
        }
    } catch (e) {
        showToast('Sync error. Ensure DAQ service is running on Port 8081.', true);
    }
}

async function handleApplyRetention() {
    const payload = {
        enabled: document.getElementById('RETENTION_ENABLED').checked,
        days: parseInt(document.getElementById('RETENTION_DAYS').value || '0', 10),
        hours: parseInt(document.getElementById('RETENTION_HOURS').value || '0', 10),
        minutes: parseInt(document.getElementById('RETENTION_MINUTES').value || '0', 10),
        seconds: parseInt(document.getElementById('RETENTION_SECONDS').value || '0', 10)
    };

    showToast('Applying retention policy to InfluxDB bucket...');
    try {
        const res = await fetch('/api/retention', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Retention policy applied!');
        } else {
            showToast(`Retention error: ${data.message}`, true);
        }
    } catch (e) {
        showToast('Failed to apply retention policy.', true);
    }
}

async function fetchLogs() {
    const logBody = document.getElementById('log-body');
    if (!logBody) return;

    try {
        const res = await fetch('/api/logs');
        if (!res.ok) throw new Error();
        const data = await res.json();
        logBody.textContent = data.logs || 'No log output returned.';
        logBody.scrollTop = logBody.scrollHeight;
    } catch (e) {
        logBody.textContent = 'Unable to connect or fetch container logs.';
    }
}
