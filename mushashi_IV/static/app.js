// app.js — Musashi IV Control Panel Client

document.addEventListener('DOMContentLoaded', () => {
    const socket = io();

    // DOM Elements - Status & Header
    const realtimeClock = document.getElementById('realtime-clock');
    const statusIndicator = document.getElementById('system-status-indicator');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    // DOM Elements - Telemetry Cards
    const elPolled = document.getElementById('telemetry-polled');
    const elWritten = document.getElementById('telemetry-written');
    const elPress = document.getElementById('telemetry-press');
    const elVac = document.getElementById('telemetry-vac');
    const elTime = document.getElementById('telemetry-time');
    const elErrors = document.getElementById('telemetry-errors');

    // DOM Elements - Audit Grid
    const audNo = document.getElementById('aud-no');
    const audShotMode = document.getElementById('aud-shotMode');
    const audDisPress = document.getElementById('aud-disPress');
    const audDisVacuum = document.getElementById('aud-disVacuum');
    const audDisTime = document.getElementById('aud-disTime');
    const audWatchPermit = document.getElementById('aud-watchPermit');
    const audRsmLevel = document.getElementById('aud-rsmLevel');
    const audCorrVac = document.getElementById('aud-corrVac');

    // DOM Elements - Form Fields
    const configForm = document.getElementById('config-form');
    const apiUrlInput = document.getElementById('API_URL');
    const timeIntervalInput = document.getElementById('TIME_INTERVAL');
    const channelNoInput = document.getElementById('CHANNEL_NO');
    const mockupModeSelect = document.getElementById('MOCKUP_MODE');

    // Database Fields & Groups
    const dbTypeSelect = document.getElementById('DB_TYPE');
    const postgresGroup = document.getElementById('postgres-config-group');
    const influxGroup = document.getElementById('influx-config-group');
    const sqliteGroup = document.getElementById('sqlite-config-group');

    const dbHostInput = document.getElementById('DB_HOST');
    const dbPortInput = document.getElementById('DB_PORT');
    const dbNameInput = document.getElementById('DB_NAME');
    const dbTableInput = document.getElementById('DB_TABLE');
    const dbUserInput = document.getElementById('DB_USER');
    const dbPasswordInput = document.getElementById('DB_PASSWORD');
    const dbDsnInput = document.getElementById('DB_DSN');

    const influxUrlInput = document.getElementById('INFLUX_URL');
    const influxOrgInput = document.getElementById('INFLUX_ORG');
    const influxBucketInput = document.getElementById('INFLUX_BUCKET');
    const influxMeasurementInput = document.getElementById('INFLUX_MEASUREMENT');
    const influxTokenInput = document.getElementById('INFLUX_TOKEN');

    const sqlitePathInput = document.getElementById('SQLITE_PATH');

    // Action & Test Buttons
    const btnStartReal = document.getElementById('btn-start-real');
    const btnStartMock = document.getElementById('btn-start-mock');
    const btnStop = document.getElementById('btn-stop');
    const btnTestApi = document.getElementById('btn-test-api');
    const btnTestDb = document.getElementById('btn-test-db');

    const terminalBody = document.getElementById('terminal-body');
    const logSearchInput = document.getElementById('log-search');
    const logAutoScrollCheck = document.getElementById('log-autoscroll');
    const logCounter = document.getElementById('log-counter');
    const btnClearLog = document.getElementById('btn-clear-log');
    const btnDownloadLog = document.getElementById('btn-download-log');

    let totalLogLines = 0;
    const logHistory = [];

    // Realtime Digital Clock
    function updateClock() {
        if (!realtimeClock) return;
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const secs = String(now.getSeconds()).padStart(2, '0');
        realtimeClock.textContent = `${hrs}:${mins}:${secs}`;
    }
    setInterval(updateClock, 1000);
    updateClock();

    // DB Type Switcher
    function updateDbTypeVisibility() {
        const selected = dbTypeSelect.value;
        if (selected === 'postgresql') {
            postgresGroup.style.display = 'block';
            influxGroup.style.display = 'none';
            sqliteGroup.style.display = 'none';
        } else if (selected === 'influxdb') {
            postgresGroup.style.display = 'none';
            influxGroup.style.display = 'block';
            sqliteGroup.style.display = 'none';
        } else if (selected === 'sqlite') {
            postgresGroup.style.display = 'none';
            influxGroup.style.display = 'none';
            sqliteGroup.style.display = 'block';
        }
    }
    dbTypeSelect.addEventListener('change', updateDbTypeVisibility);

    // Auto-generate DSN from split PostgreSQL fields
    function syncPostgresDsn() {
        const host = dbHostInput.value.trim() || 'localhost';
        const port = dbPortInput.value.trim() || '5432';
        const user = dbUserInput.value.trim() || 'admin';
        const pass = dbPasswordInput.value.trim() || 'admin';
        const name = dbNameInput.value.trim() || 'daq_db';
        dbDsnInput.value = `postgresql://${user}:${pass}@${host}:${port}/${name}`;
    }

    [dbHostInput, dbPortInput, dbUserInput, dbPasswordInput, dbNameInput].forEach(el => {
        if (el) el.addEventListener('input', syncPostgresDsn);
    });

    // Update Status Indicator UI
    function updateRunningStatus(isRunning, mode) {
        if (isRunning) {
            if (mode === 'real') {
                statusDot.className = 'pulse-dot online';
                statusText.textContent = 'ONLINE';
            } else {
                statusDot.className = 'pulse-dot mockup';
                statusText.textContent = 'MOCKUP ACTIVE';
            }
            btnStartReal.disabled = true;
            btnStartMock.disabled = true;
            btnStop.disabled = false;
        } else {
            statusDot.className = 'pulse-dot offline';
            statusText.textContent = 'STOPPED';
            btnStartReal.disabled = false;
            btnStartMock.disabled = false;
            btnStop.disabled = true;
        }
    }

    // Update Telemetry & Audit UI
    function updateStatsUI(stats) {
        if (!stats) return;
        if (stats.polled !== undefined) elPolled.textContent = stats.polled;
        if (stats.written !== undefined) elWritten.textContent = stats.written;
        if (stats.errors !== undefined) elErrors.textContent = stats.errors;

        if (stats.dis_press !== undefined) {
            elPress.textContent = parseFloat(stats.dis_press).toFixed(2);
            audDisPress.textContent = parseFloat(stats.dis_press).toFixed(2);
        }
        if (stats.dis_vac !== undefined) {
            elVac.textContent = parseFloat(stats.dis_vac).toFixed(2);
            audDisVacuum.textContent = parseFloat(stats.dis_vac).toFixed(2);
        }
        if (stats.dis_time !== undefined) {
            elTime.textContent = parseFloat(stats.dis_time).toFixed(3);
            audDisTime.textContent = parseFloat(stats.dis_time).toFixed(3);
        }
    }

    // Log Console Helper
    function appendLog(line, type = '') {
        if (!terminalBody) return;
        logHistory.push(line);
        totalLogLines++;

        const div = document.createElement('div');
        div.className = 'log-line';

        if (line.includes('[SYSTEM]')) div.classList.add('sys-line');
        else if (line.includes('[ERROR]') || type === 'err') div.classList.add('err-line');
        else if (line.includes('[STATS]')) div.classList.add('stat-line');
        else if (line.includes('[MOCK]')) div.classList.add('mock-line');
        else if (line.includes('[SUCCESS]') || type === 'success') div.classList.add('info-line');

        div.textContent = line;
        terminalBody.appendChild(div);

        if (logCounter) logCounter.textContent = `${totalLogLines} lines`;

        if (logAutoScrollCheck && logAutoScrollCheck.checked) {
            terminalBody.scrollTop = terminalBody.scrollHeight;
        }

        const query = logSearchInput ? logSearchInput.value.toLowerCase().trim() : '';
        if (query && !line.toLowerCase().includes(query)) {
            div.style.display = 'none';
        }
    }

    // Search Log Filtering
    if (logSearchInput) {
        logSearchInput.addEventListener('input', () => {
            const query = logSearchInput.value.toLowerCase().trim();
            const lines = terminalBody.querySelectorAll('.log-line');
            lines.forEach(line => {
                if (!query || line.textContent.toLowerCase().includes(query)) {
                    line.style.display = 'block';
                } else {
                    line.style.display = 'none';
                }
            });
        });
    }

    // Clear Log Button
    if (btnClearLog) {
        btnClearLog.addEventListener('click', () => {
            terminalBody.innerHTML = '';
            totalLogLines = 0;
            if (logCounter) logCounter.textContent = '0 lines';
        });
    }

    // Download Log Button
    if (btnDownloadLog) {
        btnDownloadLog.addEventListener('click', () => {
            const blob = new Blob([logHistory.join('\n')], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `musashi_iv_logs_${new Date().toISOString().slice(0, 10)}.log`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }

    // Load Initial Config & Status
    async function loadStatusAndConfig() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();

            updateRunningStatus(data.is_running, data.run_mode);

            const config = data.config || {};
            if (config.API_URL !== undefined) apiUrlInput.value = config.API_URL;
            if (config.TIME_INTERVAL !== undefined) timeIntervalInput.value = config.TIME_INTERVAL;
            if (config.CHANNEL_NO !== undefined) {
                channelNoInput.value = config.CHANNEL_NO;
                audNo.textContent = config.CHANNEL_NO;
            }
            if (config.MOCKUP_MODE !== undefined) mockupModeSelect.value = String(config.MOCKUP_MODE);

            if (config.DB_TYPE !== undefined) dbTypeSelect.value = config.DB_TYPE;
            if (config.DB_HOST !== undefined) dbHostInput.value = config.DB_HOST;
            if (config.DB_PORT !== undefined) dbPortInput.value = config.DB_PORT;
            if (config.DB_NAME !== undefined) dbNameInput.value = config.DB_NAME;
            if (config.DB_TABLE !== undefined) dbTableInput.value = config.DB_TABLE;
            if (config.DB_USER !== undefined) dbUserInput.value = config.DB_USER;
            if (config.DB_PASSWORD !== undefined) dbPasswordInput.value = config.DB_PASSWORD;
            if (config.DB_DSN !== undefined) dbDsnInput.value = config.DB_DSN;

            if (config.INFLUX_URL !== undefined) influxUrlInput.value = config.INFLUX_URL;
            if (config.INFLUX_ORG !== undefined) influxOrgInput.value = config.INFLUX_ORG;
            if (config.INFLUX_BUCKET !== undefined) influxBucketInput.value = config.INFLUX_BUCKET;
            if (config.INFLUX_MEASUREMENT !== undefined) influxMeasurementInput.value = config.INFLUX_MEASUREMENT;
            if (config.INFLUX_TOKEN !== undefined) influxTokenInput.value = config.INFLUX_TOKEN;

            const autoStartCheck = document.getElementById('AUTO_START_ON_STARTUP');
            const autoStartModeSelect = document.getElementById('AUTO_START_MODE');
            if (autoStartCheck && config.AUTO_START_ON_STARTUP !== undefined) autoStartCheck.checked = config.AUTO_START_ON_STARTUP;
            else if (autoStartCheck) autoStartCheck.checked = true;
            if (autoStartModeSelect && config.AUTO_START_MODE !== undefined) autoStartModeSelect.value = config.AUTO_START_MODE;

            if (config.SQLITE_PATH !== undefined) sqlitePathInput.value = config.SQLITE_PATH;

            updateDbTypeVisibility();

            if (data.last_stats) updateStatsUI(data.last_stats);
            appendLog('[SYSTEM] Loaded configuration from server.');
        } catch (err) {
            appendLog(`[ERROR] Failed to fetch status: ${err.message}`, 'err');
        }
    }

    // Form Submit (Save Config)
    configForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const autoStartCheck = document.getElementById('AUTO_START_ON_STARTUP');
        const autoStartModeSelect = document.getElementById('AUTO_START_MODE');
        const payload = {
            AUTO_START_ON_STARTUP: autoStartCheck ? autoStartCheck.checked : true,
            AUTO_START_MODE: autoStartModeSelect ? autoStartModeSelect.value : 'mockup',
            API_URL: apiUrlInput.value.trim(),
            TIME_INTERVAL: parseFloat(timeIntervalInput.value),
            CHANNEL_NO: parseInt(channelNoInput.value, 10),
            MOCKUP_MODE: mockupModeSelect.value === 'true',
            DB_TYPE: dbTypeSelect.value,
            DB_HOST: dbHostInput.value.trim(),
            DB_PORT: parseInt(dbPortInput.value, 10) || 5432,
            DB_NAME: dbNameInput.value.trim(),
            DB_TABLE: dbTableInput.value.trim(),
            DB_USER: dbUserInput.value.trim(),
            DB_PASSWORD: dbPasswordInput.value.trim(),
            DB_DSN: dbDsnInput.value.trim(),
            INFLUX_URL: influxUrlInput.value.trim(),
            INFLUX_ORG: influxOrgInput.value.trim(),
            INFLUX_BUCKET: influxBucketInput.value.trim(),
            INFLUX_MEASUREMENT: influxMeasurementInput.value.trim(),
            INFLUX_TOKEN: influxTokenInput.value.trim(),
            SQLITE_PATH: sqlitePathInput.value.trim()
        };

        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.success || data.status === 'success') {
                appendLog('[SYSTEM] Configuration saved successfully to config.json.');
                alert('Configuration saved successfully!');
            } else {
                alert(`Error saving config: ${data.message}`);
                appendLog(`[ERROR] Save config failed: ${data.message}`, 'err');
            }
        } catch (err) {
            alert(`Network error: ${err.message}`);
        }
    });

    // Start Real Ingestion Handler
    btnStartReal.addEventListener('click', async () => {
        btnStartReal.disabled = true;
        btnStartMock.disabled = true;
        try {
            const res = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'real' })
            });
            const data = await res.json();
            if (data.success) {
                updateRunningStatus(true, 'real');
                appendLog(`[SYSTEM] ${data.message}`);
            } else {
                alert(`Start error: ${data.message}`);
                updateRunningStatus(false);
            }
        } catch (err) {
            alert(`Network error: ${err.message}`);
            updateRunningStatus(false);
        }
    });

    // Start Mock Mode Handler
    btnStartMock.addEventListener('click', async () => {
        btnStartReal.disabled = true;
        btnStartMock.disabled = true;
        try {
            const res = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'mockup' })
            });
            const data = await res.json();
            if (data.success) {
                updateRunningStatus(true, 'mockup');
                appendLog(`[SYSTEM] ${data.message}`);
            } else {
                alert(`Start error: ${data.message}`);
                updateRunningStatus(false);
            }
        } catch (err) {
            alert(`Network error: ${err.message}`);
            updateRunningStatus(false);
        }
    });

    // Stop Handler
    btnStop.addEventListener('click', async () => {
        btnStop.disabled = true;
        try {
            const res = await fetch('/api/stop', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                updateRunningStatus(false);
                appendLog(`[SYSTEM] ${data.message}`);
            } else {
                alert(`Stop error: ${data.message}`);
            }
        } catch (err) {
            alert(`Stop error: ${err.message}`);
        }
    });

    // Test API Button Handler
    btnTestApi.addEventListener('click', async () => {
        const url = apiUrlInput.value.trim();
        appendLog(`[SYSTEM] Testing API endpoint connection to ${url}...`);
        try {
            const res = await fetch('/api/test_api', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_url: url })
            });
            const data = await res.json();
            if (data.success) {
                alert('API Connection Successful!');
                appendLog(`[SUCCESS] API connected successfully! Received sample payload.`, 'success');
            } else {
                alert(`API Connection Failed: ${data.message}`);
                appendLog(`[ERROR] API test failed: ${data.message}`, 'err');
            }
        } catch (err) {
            alert(`API test error: ${err.message}`);
        }
    });

    // Test DB Button Handler
    btnTestDb.addEventListener('click', async () => {
        const dbType = dbTypeSelect.value;
        const payload = {
            DB_TYPE: dbType,
            DB_HOST: dbHostInput.value.trim(),
            DB_PORT: parseInt(dbPortInput.value, 10) || 5432,
            DB_NAME: dbNameInput.value.trim(),
            DB_USER: dbUserInput.value.trim(),
            DB_PASSWORD: dbPasswordInput.value.trim(),
            DB_DSN: dbDsnInput.value.trim(),
            INFLUX_URL: influxUrlInput.value.trim(),
            INFLUX_TOKEN: influxTokenInput.value.trim(),
            INFLUX_ORG: influxOrgInput.value.trim(),
            INFLUX_BUCKET: influxBucketInput.value.trim(),
            SQLITE_PATH: sqlitePathInput.value.trim()
        };

        appendLog(`[SYSTEM] Testing ${dbType.toUpperCase()} connection...`);
        try {
            const res = await fetch('/api/test_db', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.success) {
                alert(`${dbType.toUpperCase()} Connection Successful!`);
                appendLog(`[SUCCESS] ${data.message}`, 'success');
            } else {
                alert(`DB Connection Failed: ${data.message}`);
                appendLog(`[ERROR] Database connection test failed: ${data.message}`, 'err');
            }
        } catch (err) {
            alert(`DB test error: ${err.message}`);
        }
    });

    // Socket.IO Handlers
    socket.on('connect', () => {
        appendLog('[SYSTEM] Socket.IO connection established with Musashi IV server.');
    });

    socket.on('status_change', (data) => {
        updateRunningStatus(data.is_running, data.mode);
    });

    socket.on('stats_update', (data) => {
        updateStatsUI(data);
    });

    socket.on('log_line', (data) => {
        if (data && data.data) {
            appendLog(data.data);
        }
    });

    socket.on('log_update', (data) => {
        if (data && data.log) {
            appendLog(data.log);
        }
    });

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
    resolveBackLink();
    loadStatusAndConfig();
});
