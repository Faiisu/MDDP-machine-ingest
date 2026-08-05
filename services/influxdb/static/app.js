document.addEventListener('DOMContentLoaded', () => {
    initThemeSelector();
    initPanelNavigation();
    updateClock();
    window.setInterval(updateClock, 1000);
    loadConfig();
    checkStatus();
    fetchLogs();
    window.setInterval(checkStatus, 5000);
    setupRetentionListeners();

    document.getElementById('config-form').addEventListener('submit', handleConfigSave);
    document.getElementById('btn-start').addEventListener('click', handleStart);
    document.getElementById('btn-stop').addEventListener('click', handleStop);
    document.getElementById('btn-refresh-status').addEventListener('click', checkStatus);
    document.getElementById('btn-copy-token').addEventListener('click', handleCopyToken);
    document.getElementById('btn-sync-daq').addEventListener('click', handleSyncDaq);
    document.getElementById('btn-apply-retention').addEventListener('click', handleApplyRetention);
    document.getElementById('btn-refresh-logs').addEventListener('click', fetchLogs);
    document.querySelectorAll('#config-form input').forEach((input) => {
        input.addEventListener('input', () => document.querySelector('[data-panel="panel-connection"]').classList.add('has-changes'));
    });
});

function updateClock() {
    const clock = document.getElementById('realtime-clock');
    if (clock) clock.textContent = new Date().toTimeString().split(' ')[0];
}

function initThemeSelector() {
    const selector = document.getElementById('ui-theme-select');
    if (!selector) return;
    const savedTheme = localStorage.getItem('influx_ui_theme') || 'arctic-light';
    selector.value = savedTheme;
    document.documentElement.setAttribute('data-theme', savedTheme);
    selector.addEventListener('change', (event) => {
        document.documentElement.setAttribute('data-theme', event.target.value);
        localStorage.setItem('influx_ui_theme', event.target.value);
        showToast(`Theme switched to ${event.target.options[event.target.selectedIndex].text}`);
    });
}

function initPanelNavigation() {
    const buttons = [...document.querySelectorAll('#sidebar-tab-list .nav-tab-btn')];
    const panels = [...document.querySelectorAll('.workspace-panel')];
    const savedPanel = localStorage.getItem('influx_active_panel');
    const initialPanel = savedPanel && document.getElementById(savedPanel) ? savedPanel : 'panel-overview';

    const selectPanel = (panelId) => {
        buttons.forEach((button) => button.classList.toggle('active', button.dataset.panel === panelId));
        panels.forEach((panel) => panel.classList.toggle('hidden', panel.id !== panelId));
        localStorage.setItem('influx_active_panel', panelId);
    };

    selectPanel(initialPanel);
    buttons.forEach((button) => button.addEventListener('click', () => selectPanel(button.dataset.panel)));
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    const messageElement = document.getElementById('toast-message');
    if (!toast || !messageElement) return;
    messageElement.textContent = message;
    toast.classList.toggle('toast-error', isError);
    toast.classList.add('show');
    window.clearTimeout(showToast.timeout);
    showToast.timeout = window.setTimeout(() => toast.classList.remove('show'), 3500);
}

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) throw new Error('Config request failed');
        const config = await response.json();
        setValue('INFLUX_URL', config.INFLUX_URL || 'http://localhost:8086');
        setValue('INFLUX_ORG', config.INFLUX_ORG || 'mddp');
        setValue('INFLUX_BUCKET', config.INFLUX_BUCKET || 'daq_telemetry');
        setValue('INFLUX_MEASUREMENT', config.INFLUX_MEASUREMENT || 'daq_telemetry');
        setValue('INFLUX_USERNAME', config.INFLUX_USERNAME || 'admin');
        setValue('INFLUX_PASSWORD', config.INFLUX_PASSWORD || '');
        setValue('INFLUX_TOKEN', config.INFLUX_TOKEN || '');
        document.getElementById('RETENTION_ENABLED').checked = config.RETENTION_ENABLED === true;
        setValue('RETENTION_DAYS', config.RETENTION_DAYS ?? 30);
        setValue('RETENTION_HOURS', config.RETENTION_HOURS ?? 0);
        setValue('RETENTION_MINUTES', config.RETENTION_MINUTES ?? 0);
        setValue('RETENTION_SECONDS', config.RETENTION_SECONDS ?? 0);
        updateRetentionSummary();
        updateEndpoint(config.INFLUX_URL || 'http://localhost:8086');
    } catch (error) {
        showToast('Unable to load service configuration.', true);
    }
}

function setValue(id, value) {
    const element = document.getElementById(id);
    if (element) element.value = value;
}

function updateEndpoint(url) {
    const endpoint = document.getElementById('overview-endpoint');
    if (endpoint) endpoint.textContent = url;
}

async function checkStatus() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) throw new Error('Status request failed');
        const data = await response.json();
        const containerState = (data.container_status || 'unknown').toUpperCase();
        const healthState = data.is_healthy ? 'ONLINE' : containerState === 'RUNNING' ? 'BOOTING' : 'OFFLINE';
        const tokenState = data.has_token ? 'PRESENT' : 'MISSING';
        const statusText = data.is_healthy ? 'INFLUXDB_ONLINE' : containerState === 'RUNNING' ? 'BOOTING...' : 'STOPPED';
        const statusClass = data.is_healthy ? 'green' : containerState === 'RUNNING' ? 'yellow' : 'red';

        document.getElementById('status-dot').className = `pulse-dot ${statusClass}`;
        document.getElementById('status-text').textContent = statusText;
        document.getElementById('container-status-pill').textContent = `CONTAINER: ${containerState}`;
        setStatusMetric('overview-container-state', containerState, data.container_status === 'running');
        setStatusMetric('overview-health-state', healthState, data.is_healthy);
        setStatusMetric('overview-token-state', tokenState, data.has_token);
        document.getElementById('orbit-state').textContent = data.is_healthy ? 'LIVE' : 'IDLE';
        document.getElementById('rail-storage-status').textContent = data.is_healthy ? 'STREAMING' : 'STANDBY';
        document.getElementById('rail-storage-detail').textContent = data.is_healthy ? 'HTTP health confirmed' : 'Awaiting health probe';
        updateEndpoint(data.influx_url || document.getElementById('INFLUX_URL').value);
        if (data.token && !document.getElementById('INFLUX_TOKEN').value) setValue('INFLUX_TOKEN', data.token);
    } catch (error) {
        document.getElementById('status-dot').className = 'pulse-dot red';
        document.getElementById('status-text').textContent = 'OFFLINE';
        setStatusMetric('overview-health-state', 'UNREACHABLE', false);
        document.getElementById('rail-storage-status').textContent = 'OFFLINE';
        document.getElementById('rail-storage-detail').textContent = 'Status request failed';
    }
}

function setStatusMetric(id, value, isOnline) {
    const element = document.getElementById(id);
    if (!element) return;
    element.textContent = value;
    element.classList.toggle('online', isOnline);
    element.classList.toggle('offline', !isOnline);
}

function setupRetentionListeners() {
    const toggle = document.getElementById('RETENTION_ENABLED');
    if (toggle) toggle.addEventListener('change', updateRetentionSummary);
    ['RETENTION_DAYS', 'RETENTION_HOURS', 'RETENTION_MINUTES', 'RETENTION_SECONDS', 'INFLUX_BUCKET'].forEach((id) => {
        const element = document.getElementById(id);
        if (element) element.addEventListener('input', updateRetentionSummary);
    });
}

function updateRetentionSummary() {
    const enabled = document.getElementById('RETENTION_ENABLED').checked;
    const days = parseInt(document.getElementById('RETENTION_DAYS').value || '0', 10);
    const hours = parseInt(document.getElementById('RETENTION_HOURS').value || '0', 10);
    const minutes = parseInt(document.getElementById('RETENTION_MINUTES').value || '0', 10);
    const seconds = parseInt(document.getElementById('RETENTION_SECONDS').value || '0', 10);
    const totalSeconds = (days * 86400) + (hours * 3600) + (minutes * 60) + seconds;
    const bucket = document.getElementById('INFLUX_BUCKET').value || 'daq_telemetry';
    const settings = document.getElementById('retention-settings-block');
    settings.style.opacity = enabled ? '1' : '0.4';
    settings.style.pointerEvents = enabled ? 'auto' : 'none';

    if (!enabled) {
        document.getElementById('retention-summary-text').textContent = `Automatic expiry is off — bucket "${bucket}" keeps data indefinitely.`;
        document.getElementById('retention-total-sec-text').textContent = 'Total retention duration: Infinite (0s)';
        return;
    }

    const parts = [];
    if (days > 0) parts.push(`${days} day${days > 1 ? 's' : ''}`);
    if (hours > 0) parts.push(`${hours} hour${hours > 1 ? 's' : ''}`);
    if (minutes > 0) parts.push(`${minutes} minute${minutes > 1 ? 's' : ''}`);
    if (seconds > 0) parts.push(`${seconds} second${seconds > 1 ? 's' : ''}`);
    document.getElementById('retention-summary-text').textContent = `Data older than ${parts.join(', ') || '0 seconds'} will be purged from bucket "${bucket}".`;
    document.getElementById('retention-total-sec-text').textContent = `Total retention duration: ${totalSeconds.toLocaleString()} seconds`;
}

async function handleConfigSave(event) {
    event.preventDefault();
    const payload = {};
    ['INFLUX_URL', 'INFLUX_ORG', 'INFLUX_BUCKET', 'INFLUX_MEASUREMENT', 'INFLUX_USERNAME', 'INFLUX_PASSWORD', 'INFLUX_TOKEN'].forEach((id) => { payload[id] = document.getElementById(id).value; });
    try {
        const response = await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (!response.ok) throw new Error('Save failed');
        document.querySelector('[data-panel="panel-connection"]').classList.remove('has-changes');
        updateEndpoint(payload.INFLUX_URL);
        showToast('Connection credentials saved.');
    } catch (error) {
        showToast('Failed to save connection credentials.', true);
    }
}

async function handleStart() {
    showToast('Starting InfluxDB container...');
    try {
        const response = await fetch('/api/start', { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || 'Start failed');
        showToast('InfluxDB container started.');
        await checkStatus();
        fetchLogs();
    } catch (error) {
        showToast(`Start failed: ${error.message}`, true);
    }
}

async function handleStop() {
    showToast('Stopping InfluxDB container...');
    try {
        const response = await fetch('/api/stop', { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || 'Stop failed');
        showToast('InfluxDB container stopped.');
        await checkStatus();
        fetchLogs();
    } catch (error) {
        showToast(`Stop failed: ${error.message}`, true);
    }
}

function handleCopyToken() {
    const token = document.getElementById('INFLUX_TOKEN').value;
    if (!token) return showToast('No API token available to copy.', true);
    navigator.clipboard.writeText(token).then(() => showToast('Token copied to clipboard.')).catch(() => showToast('Failed to copy token.', true));
}

async function handleSyncDaq() {
    showToast('Syncing InfluxDB settings to DAQ service...');
    try {
        const response = await fetch('/api/sync_daq', { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || 'Sync failed');
        showToast(data.message || 'DAQ service synchronized.');
    } catch (error) {
        showToast(`Sync failed: ${error.message}`, true);
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
        const response = await fetch('/api/retention', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || 'Retention update failed');
        showToast(data.message || 'Retention policy applied.');
    } catch (error) {
        showToast(`Retention update failed: ${error.message}`, true);
    }
}

async function fetchLogs() {
    const logBody = document.getElementById('log-body');
    if (!logBody) return;
    try {
        const response = await fetch('/api/logs');
        if (!response.ok) throw new Error('Log request failed');
        const data = await response.json();
        logBody.textContent = data.logs || 'No log output returned.';
        logBody.scrollTop = logBody.scrollHeight;
    } catch (error) {
        logBody.textContent = 'Unable to connect or fetch container logs.';
    }
}
