// app.js
// See: docs/architecture/context.md
// English comments only

const socket = io();
let isSystemRunning = false;
let scaleConfigs = {};
let currentScaleChannel = '0';

document.addEventListener('DOMContentLoaded', () => {
    // Initialize Theme Selector
    initThemeSelector();

    // Start clock thread
    updateClock();
    setInterval(updateClock, 1000);

    // Initial API loads
    loadConfig();
    checkProcessStatus();
    resolveBackLink();

    // Setup form submit handlers
    const form = document.getElementById('config-form');
    form.addEventListener('submit', handleConfigSave);

    // Setup Sidebar Tab Navigation — persist active panel in localStorage
    const sidebarBtns = document.querySelectorAll('#sidebar-tab-list .nav-tab-btn');
    const savedPanel = localStorage.getItem('daq_active_panel');
    if (savedPanel) {
        sidebarBtns.forEach(b => b.classList.toggle('active', b.dataset.panel === savedPanel));
        document.querySelectorAll('.workspace-panel').forEach(panel => {
            panel.classList.toggle('hidden', panel.id !== savedPanel);
        });
    }
    sidebarBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            sidebarBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const panelId = btn.dataset.panel;
            document.querySelectorAll('.workspace-panel').forEach(panel => {
                panel.classList.toggle('hidden', panel.id !== panelId);
            });
            localStorage.setItem('daq_active_panel', panelId);
        });
    });

    // Setup destination toggle, TLS toggle, and sampling field listeners
    const destEl = document.getElementById('DESTINATION');
    if (destEl) {
        destEl.addEventListener('change', toggleDestinationFields);
    }
    const tlsEl = document.getElementById('MQTT_TLS_ENABLED');
    if (tlsEl) {
        tlsEl.addEventListener('change', toggleTlsFields);
    }
    document.getElementById('ENABLE_AI')?.addEventListener('change', () => { toggleSamplingFields(); updateDataSizeEstimator(); checkDirtyState(); });
    document.getElementById('DI_CHANNEL_OFFSET')?.addEventListener('input', () => {
        const currentConfig = { ...(activeServerConfig || {}), DI_CHANNELS: collectDiChannelSelection() };
        renderIngestionMatrixTable(currentConfig);
        checkDirtyState();
    });
    const refreshRateMatrix = () => {
        const currentConfig = {
            ...(activeServerConfig || {}),
            DI_CHANNELS: collectDiChannelSelection(),
            CHANNEL_SAMPLE_RATES: collectChannelSampleRates()
        };
        renderIngestionMatrixTable(currentConfig);
        updateDataSizeEstimator();
        checkDirtyState();
    };
    document.getElementById('CLOCK_RATE')?.addEventListener('input', refreshRateMatrix);
    document.getElementById('SECTION_LENGTH')?.addEventListener('input', refreshRateMatrix);

    // Track input & change events for real-time unsaved changes detection
    const configForm = document.getElementById('config-form');
    if (configForm) {
        configForm.addEventListener('input', checkDirtyState);
        configForm.addEventListener('change', checkDirtyState);
    }

    // Setup action buttons
    document.getElementById('start-btn').addEventListener('click', handleStartProcess);
    document.getElementById('stop-btn').addEventListener('click', handleStopProcess);
    document.getElementById('clear-console-btn').addEventListener('click', clearConsole);
    
    // Setup Confirm Audit Modal Listeners
    document.getElementById('modal-close-btn')?.addEventListener('click', closeConfirmAuditModal);
    document.getElementById('btn-cancel-save')?.addEventListener('click', closeConfirmAuditModal);
    document.getElementById('btn-confirm-save')?.addEventListener('click', commitConfigToBackend);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeConfirmAuditModal();
            closeScannedDevicesMenu();
        }
    });

    const scanBtn = document.getElementById('btn-scan-usb');
    if (scanBtn) {
        scanBtn.addEventListener('click', handleScanUsbDevices);
    }

    // Close scanned devices dropdown when clicking outside
    document.addEventListener('click', (e) => {
        const menu = document.getElementById('scanned-devices-menu');
        const scanBtn = document.getElementById('btn-scan-usb');
        if (menu && !menu.classList.contains('hidden')) {
            if (!menu.contains(e.target) && !scanBtn?.contains(e.target)) {
                closeScannedDevicesMenu();
            }
        }
    });

    // Bind Socket.IO event listeners
    bindSocketEvents();

    // Start Phosphor Signal Trace Oscilloscope Animation
    initSignalTraceCanvas();
});

// Scan Host PC USB / DAQ Hardware
async function handleScanUsbDevices() {
    const scanBtn = document.getElementById('btn-scan-usb');
    const menu = document.getElementById('scanned-devices-menu');
    if (!scanBtn || !menu) return;

    scanBtn.classList.add('scanning');
    scanBtn.disabled = true;
    scanBtn.setAttribute('aria-expanded', 'true');
    menu.setAttribute('aria-busy', 'true');
    menu.innerHTML = '<div class="scan-loading" role="status"><span class="spinner" aria-hidden="true"></span><span>Scanning host USB bus and DAQ ports...</span></div>';
    menu.classList.remove('hidden');

    try {
        const response = await fetch('/api/scan_usb');
        const data = await response.json();

        if (data.status === 'success' && data.devices && data.devices.length > 0) {
            menu.innerHTML = '';
            
            const header = document.createElement('div');
            header.className = 'scan-menu-header';
            const headerTitle = document.createElement('span');
            headerTitle.className = 'scan-menu-title';
            headerTitle.textContent = 'Detected devices';
            const headerCount = document.createElement('span');
            headerCount.className = 'scan-menu-count';
            headerCount.textContent = `${data.devices.length} FOUND`;
            const closeButton = document.createElement('button');
            closeButton.type = 'button';
            closeButton.className = 'close-scan-btn';
            closeButton.setAttribute('aria-label', 'Close detected device list');
            closeButton.innerHTML = '&times;';
            header.append(headerTitle, headerCount, closeButton);
            menu.appendChild(header);

            data.devices.forEach(dev => {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'scan-item';
                item.setAttribute('role', 'option');
                item.setAttribute('aria-label', `${dev.name || 'Unknown device'}, ${dev.id || 'Unknown ID'}, ${dev.port || 'Unknown port'}`);

                const statusDot = document.createElement('span');
                statusDot.className = `scan-device-dot${dev.is_daq ? ' is-daq' : ''}`;
                statusDot.setAttribute('aria-hidden', 'true');

                const main = document.createElement('span');
                main.className = 'scan-item-main';
                const name = document.createElement('span');
                name.className = 'scan-item-name';
                name.textContent = dev.name || 'Unknown device';
                const id = document.createElement('span');
                id.className = 'scan-item-id monospace';
                id.textContent = dev.id || 'Unknown device ID';
                main.append(name, id);

                const meta = document.createElement('span');
                meta.className = 'scan-item-meta';
                const type = document.createElement('span');
                type.className = `scan-device-type ${dev.is_daq ? 'is-daq' : 'is-serial'}`;
                type.textContent = dev.type || 'Device';
                const port = document.createElement('span');
                port.className = 'scan-item-port text-muted';
                port.textContent = dev.port || '—';
                meta.append(type, port);

                item.append(statusDot, main, meta);

                item.addEventListener('click', () => {
                    const devInput = document.getElementById('DEVICE_DESCRIPTION');
                    if (devInput) {
                        devInput.value = dev.id;
                        devInput.dispatchEvent(new Event('input', { bubbles: true }));
                        devInput.classList.add('highlight-flash');
                        setTimeout(() => devInput.classList.remove('highlight-flash'), 1200);
                    }
                    closeScannedDevicesMenu();
                    showToast(`Selected device: ${dev.id}`);
                });

                menu.appendChild(item);
            });

            closeButton.addEventListener('click', closeScannedDevicesMenu);
        } else {
            menu.innerHTML = '<div class="scan-empty"><span class="scan-state-mark" aria-hidden="true">—</span><span>No USB or DAQ devices detected on this host.</span></div>';
        }
    } catch (err) {
        console.error('Error scanning USB devices:', err);
        const errorMessage = document.createElement('div');
        errorMessage.className = 'scan-error';
        errorMessage.innerHTML = '<span class="scan-state-mark" aria-hidden="true">!</span><span>Failed to scan USB ports. Check the service log for details.</span>';
        menu.replaceChildren(errorMessage);
    } finally {
        scanBtn.classList.remove('scanning');
        scanBtn.disabled = false;
        menu.setAttribute('aria-busy', 'false');
    }
}

function closeScannedDevicesMenu() {
    const menu = document.getElementById('scanned-devices-menu');
    const scanBtn = document.getElementById('btn-scan-usb');
    if (menu) menu.classList.add('hidden');
    if (scanBtn) scanBtn.setAttribute('aria-expanded', 'false');
}

// Phosphor Signal Trace Oscilloscope Animation
let canvasPhase = 0;
function initSignalTraceCanvas() {
    const canvas = document.getElementById('signal-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function renderTrace() {
        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        // Draw grid baseline
        ctx.strokeStyle = 'rgba(0, 242, 254, 0.12)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h / 2);
        ctx.lineTo(w, h / 2);
        ctx.stroke();

        if (isSystemRunning) {
            canvasPhase += 0.15;
            ctx.beginPath();
            ctx.strokeStyle = '#00f2fe';
            ctx.lineWidth = 1.8;
            ctx.shadowBlur = 8;
            ctx.shadowColor = '#00f2fe';

            for (let x = 0; x < w; x++) {
                const y = h / 2 + Math.sin(x * 0.08 + canvasPhase) * (h * 0.35) + (Math.random() - 0.5) * 2;
                if (x === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.shadowBlur = 0;
        } else {
            // Idle flatline
            ctx.beginPath();
            ctx.strokeStyle = 'rgba(100, 116, 139, 0.4)';
            ctx.lineWidth = 1;
            ctx.moveTo(0, h / 2);
            ctx.lineTo(w, h / 2);
            ctx.stroke();
        }
        requestAnimationFrame(renderTrace);
    }
    requestAnimationFrame(renderTrace);
}

// Toggle visibility of Destination settings (shows ONLY selected destination)
function toggleDestinationFields() {
    const dest = document.getElementById('DESTINATION')?.value || 'postgresql';
    const postgresGroup = document.getElementById('postgres-config-group');
    const influxGroup = document.getElementById('influx-config-group');
    const mqttGroup = document.getElementById('mqtt-config-group');

    if (postgresGroup && influxGroup && mqttGroup) {
        if (dest === 'mqtt') {
            postgresGroup.style.display = 'none';
            influxGroup.style.display = 'none';
            mqttGroup.style.display = 'flex';
        } else if (dest === 'influxdb') {
            postgresGroup.style.display = 'none';
            influxGroup.style.display = 'flex';
            mqttGroup.style.display = 'none';
        } else {
            postgresGroup.style.display = 'flex';
            influxGroup.style.display = 'none';
            mqttGroup.style.display = 'none';
        }
    }
}

// Auto-generate DSN from split PostgreSQL fields
function syncPostgresDsn() {
    const host = document.getElementById('DB_HOST')?.value.trim() || 'localhost';
    const port = document.getElementById('DB_PORT')?.value.trim() || '5432';
    const user = document.getElementById('DB_USER')?.value.trim() || 'admin';
    const pass = document.getElementById('DB_PASSWORD')?.value.trim() || 'admin';
    const name = document.getElementById('DB_NAME')?.value.trim() || 'daq_db';
    const dsnEl = document.getElementById('DB_DSN');
    if (dsnEl) dsnEl.value = `postgresql://${user}:${pass}@${host}:${port}/${name}`;
}

document.addEventListener('DOMContentLoaded', () => {
    ['DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', syncPostgresDsn);
    });
});

function getBooleanControlValue(id, fallback = false) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    if (el.type === 'checkbox') return el.checked;
    return !['false', '0', 'off', 'no', ''].includes(String(el.value).trim().toLowerCase());
}

function parseBooleanValue(value, fallback = false) {
    if (value === undefined || value === null) return fallback;
    if (typeof value === 'string') {
        return !['false', '0', 'off', 'no', ''].includes(value.trim().toLowerCase());
    }
    return Boolean(value);
}

function normalizeDiChannels(value, fallbackEnabled = false) {
    if (Array.isArray(value) && value.length === 8) {
        return value.map(channel => parseBooleanValue(channel));
    }
    if (value && typeof value === 'object') {
        return Array.from({ length: 8 }, (_, bit) => parseBooleanValue(value[String(bit)]));
    }
    return Array(8).fill(parseBooleanValue(fallbackEnabled));
}

function normalizeChannelSampleRates(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const rates = {};
    Object.entries(value).forEach(([key, rawRate]) => {
        const rate = parseFloat(rawRate);
        if (Number.isFinite(rate) && rate > 0) rates[String(key).toUpperCase()] = rate;
    });
    return rates;
}

function getHardwareClockRate(config = {}) {
    const rawRate = document.getElementById('CLOCK_RATE')?.value ?? config.CLOCK_RATE;
    const rate = parseFloat(rawRate);
    return Number.isFinite(rate) && rate > 0 ? rate : 1000;
}

function getChannelSourceRate(channelKey, hardwareRate, sectionLength) {
    return String(channelKey).toUpperCase().startsWith('DI')
        ? hardwareRate / Math.max(1, sectionLength)
        : hardwareRate;
}

function getConfiguredChannelRate(rates, channelKey, sourceRate) {
    const configuredRate = parseFloat(rates?.[String(channelKey).toUpperCase()]);
    if (!Number.isFinite(configuredRate) || configuredRate <= 0) return sourceRate;
    return Math.min(configuredRate, sourceRate);
}

function formatRate(rate) {
    return Number.isInteger(rate) ? String(rate) : rate.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
}

// Toggle sampling fields according to ENABLE_AI. DI selection is controlled
// independently by the eight row toggles in the ingestion matrix.
function toggleSamplingFields() {
    const aiChecked = getBooleanControlValue('ENABLE_AI', true);

    const aiFields = document.getElementById('ai-sampling-fields');

    if (aiFields) {
        aiFields.style.opacity = aiChecked ? '1' : '0.4';
        aiFields.querySelectorAll('input').forEach(i => {
            if (i.id !== 'ENABLE_AI') i.disabled = !aiChecked;
        });
    }
}

// Toggle visibility of TLS certificate fields
function toggleTlsFields() {
    const tlsChecked = document.getElementById('MQTT_TLS_ENABLED')?.checked || false;
    const tlsGroup = document.getElementById('mqtt-tls-group');
    if (tlsGroup) {
        tlsGroup.style.display = tlsChecked ? 'flex' : 'none';
    }
}

// Update Header UTC Clock Display
function updateClock() {
    const clockEl = document.getElementById('realtime-clock');
    if (!clockEl) return;
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    clockEl.textContent = `${hours}:${minutes}:${seconds}`;
}

// Fetch and load configuration into form fields
async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error("Failed to load config.");
        const config = await res.json();
        
        // Populate standard inputs
        Object.keys(config).forEach(key => {
            const input = document.getElementById(key);
            if (input && key !== 'SCALE_CONFIGS') {
                if (input.type === 'checkbox') {
                    input.checked = config[key];
                } else {
                    input.value = config[key];
                }
            }
        });
        
        // DI_CHANNELS is the user-facing source of truth. Keep the DAQNavi
        // port fields fixed internally for the USB-4716's one byte port.
        config.DI_CHANNELS = normalizeDiChannels(config.DI_CHANNELS, config.ENABLE_DI === true);
        config.ENABLE_DI = config.DI_CHANNELS.some(Boolean);
        config.CHANNEL_SAMPLE_RATES = normalizeChannelSampleRates(config.CHANNEL_SAMPLE_RATES);
        config.DI_START_PORT = 0;
        config.DI_PORT_COUNT = 1;
        config.DI_END_PORT = 0;
        const enableDiInput = document.getElementById('ENABLE_DI');
        if (enableDiInput) enableDiInput.value = String(config.ENABLE_DI);
        const startPortInput = document.getElementById('DI_START_PORT');
        if (startPortInput) startPortInput.value = '0';
        const endPortInput = document.getElementById('DI_END_PORT');
        if (endPortInput) endPortInput.value = '0';
        const portCountInput = document.getElementById('DI_PORT_COUNT');
        if (portCountInput) portCountInput.value = '1';

        // Store active server baseline configuration
        activeServerConfig = JSON.parse(JSON.stringify(config));

        // Store per-channel scale configurations & render matrix table
        scaleConfigs = config.SCALE_CONFIGS || {};
        renderIngestionMatrixTable(config);
        toggleDestinationFields();
        toggleTlsFields();
        toggleSamplingFields();
        updateDataSizeEstimator();
        checkDirtyState();
        
        appendLog('INFO', 'System configuration loaded from config.json.');
    } catch (e) {
        appendLog('ERROR', `Failed to load config: ${e.message}`);
    }
}

// Check if current form/matrix values differ from active server baseline config
function checkDirtyState() {
    const form = document.getElementById('config-form');
    if (!form || !activeServerConfig || Object.keys(activeServerConfig).length === 0) return false;

    const matrixScales = collectScaleConfigsFromMatrixTable();
    const inputs = form.querySelectorAll('input[name], select[name]');
    let isDirty = false;

    for (let el of inputs) {
        if (!el.name) continue;
        const oldVal = activeServerConfig[el.name];
        let newVal;
        if (el.type === 'checkbox') {
            newVal = el.checked;
        } else if (['ENABLE_AI', 'ENABLE_DI'].includes(el.name)) {
            newVal = (el.value === 'true' || el.checked === true);
        } else if (el.name === 'ANCHOR_RECALIBRATE_INTERVAL_HR') {
            newVal = parseFloat(el.value);
        } else if (['START_CHANNEL', 'CHANNEL_COUNT', 'CLOCK_RATE', 'SECTION_LENGTH', 'SECTION_COUNT', 'QUEUE_MAXSIZE', 'DB_PAGE_SIZE', 'STATS_INTERVAL_SEC', 'MQTT_PORT', 'MQTT_QOS', 'DI_START_PORT', 'DI_END_PORT', 'DI_PORT_COUNT', 'DI_CHANNEL_OFFSET'].includes(el.name)) {
            newVal = parseInt(el.value, 10);
        } else {
            newVal = el.value;
        }

        const normOld = oldVal === undefined ? '' : String(oldVal);
        const normNew = (newVal === undefined || Number.isNaN(newVal)) ? '' : String(newVal);

        if (normOld !== normNew) {
            isDirty = true;
            break;
        }
    }

    // Check scale configs (including stream toggle state)
    if (!isDirty) {
        const oldScales = activeServerConfig.SCALE_CONFIGS || {};
        for (let ch of Object.keys(matrixScales)) {
            const oldCh = oldScales[ch] || {};
            const newCh = matrixScales[ch] || {};
            for (let f of ['stream', 'enabled', 'low_voltage', 'high_voltage', 'low_value', 'high_value']) {
                const normOld = oldCh[f] === undefined ? '' : String(oldCh[f]);
                const normNew = newCh[f] === undefined ? '' : String(newCh[f]);
                if (normOld !== normNew) {
                    isDirty = true;
                    break;
                }
            }
            if (isDirty) break;
        }
    }

    if (!isDirty) {
        const oldDiChannels = normalizeDiChannels(activeServerConfig.DI_CHANNELS, activeServerConfig.ENABLE_DI === true);
        const newDiChannels = collectDiChannelSelection();
        isDirty = oldDiChannels.some((selected, bit) => selected !== newDiChannels[bit]);
    }

    if (!isDirty) {
        const oldRates = normalizeChannelSampleRates(activeServerConfig.CHANNEL_SAMPLE_RATES);
        const newRates = collectChannelSampleRates();
        const rateKeys = new Set([...Object.keys(oldRates), ...Object.keys(newRates)]);
        isDirty = Array.from(rateKeys).some(key => oldRates[key] !== newRates[key]);
    }

    // Update save status badges according to dirty state
    document.querySelectorAll('.save-status-badge').forEach(badge => {
        const textEl = badge.querySelector('.save-status-text');
        if (isDirty) {
            badge.classList.add('badge-warning');
            badge.classList.remove('hidden');
            if (textEl) textEl.textContent = '⚠️ UNSAVED CHANGES';
        } else {
            badge.classList.remove('badge-warning');
            if (badge.dataset.savedTime) {
                if (textEl) textEl.textContent = badge.dataset.savedTime;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
    });

    return isDirty;
}

// Check if a process is already running on page load
async function checkProcessStatus() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error("Failed to get status.");
        const status = await res.json();
        updateUIState(status.is_running, status.run_mode, status.destination);
    } catch (e) {
        appendLog('ERROR', `Failed to query process status: ${e.message}`);
    }
}

// Update Start/Stop buttons and indicator dots
function updateUIState(running, mode = 'mockup', destination = 'database') {
    isSystemRunning = running;
    
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const modeSelect = document.getElementById('mode-select');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const statusIndicator = document.getElementById('system-status-indicator');

    const destLabel = (destination || 'database').toUpperCase();

    if (running) {
        startBtn.disabled = true;
        stopBtn.disabled = false;
        modeSelect.disabled = true;
        
        statusIndicator.classList.add('active');
        statusDot.className = 'pulse-dot green';
        statusText.textContent = `RUNNING (${mode.toUpperCase()} - ${destLabel})`;
    } else {
        startBtn.disabled = false;
        stopBtn.disabled = true;
        modeSelect.disabled = false;
        
        statusIndicator.classList.remove('active');
        statusDot.className = 'pulse-dot offline';
        statusText.textContent = 'OFFLINE';
        
        // Reset telemetry values to 0
        document.getElementById('telemetry-queue').textContent = '0 / 200';
    }
}

// Intercept form submissions and open Tactical Config Audit Modal
async function handleConfigSave(e) {
    if (e) e.preventDefault();
    
    // Collect matrix table scale configurations & sampling parameters
    const matrixScales = collectScaleConfigsFromMatrixTable();
    updateGlobalSamplingFromTable();
    
    // Deep clone activeServerConfig as base payload to prevent losing unrendered keys
    const configData = JSON.parse(JSON.stringify(activeServerConfig || {}));
    
    const form = document.getElementById('config-form');
    const inputs = form ? form.querySelectorAll('input[name], select[name]') : document.querySelectorAll('input[name], select[name]');
    
    // Parse form fields manually to support checkboxes, integers, floats, and text
    for (let el of inputs) {
        if (!el.name) continue;
        
        if (el.type === 'checkbox') {
            configData[el.name] = el.checked;
        } else if (['ENABLE_AI', 'ENABLE_DI'].includes(el.name)) {
            configData[el.name] = (el.value === 'true' || el.checked === true);
        } else if (el.name === 'ANCHOR_RECALIBRATE_INTERVAL_HR') {
            const val = parseFloat(el.value);
            configData[el.name] = isNaN(val) ? 24.0 : val;
        } else if (['START_CHANNEL', 'CHANNEL_COUNT', 'CLOCK_RATE', 'SECTION_LENGTH', 'SECTION_COUNT', 'QUEUE_MAXSIZE', 'DB_PAGE_SIZE', 'STATS_INTERVAL_SEC', 'MQTT_PORT', 'MQTT_QOS', 'DI_START_PORT', 'DI_END_PORT', 'DI_PORT_COUNT', 'DI_CHANNEL_OFFSET'].includes(el.name)) {
            const val = parseInt(el.value, 10);
            configData[el.name] = isNaN(val) ? (activeServerConfig[el.name] ?? 0) : val;
        } else {
            configData[el.name] = el.value;
        }
    }

    // Inject scaling configs dictionary
    configData['SCALE_CONFIGS'] = matrixScales;
    configData['DI_CHANNELS'] = collectDiChannelSelection();
    configData['ENABLE_DI'] = configData.DI_CHANNELS.some(Boolean);
    configData['CHANNEL_SAMPLE_RATES'] = collectChannelSampleRates();

    // Present Audit & Confirmation Modal
    openConfirmAuditModal(configData);
}

// Compute diff and present Tactical Configuration Audit Modal
function openConfirmAuditModal(newConfig) {
    pendingConfigPayload = newConfig;
    const diffContainer = document.getElementById('diff-list-container');
    const countBadge = document.getElementById('diff-count-badge');
    if (!diffContainer) return;
    
    diffContainer.innerHTML = '';
    let diffCount = 0;

    Object.keys(newConfig).forEach(key => {
        // ENABLE_DI is retained only as a derived compatibility flag.
        if (key === 'ENABLE_DI') return;

        if (key === 'SCALE_CONFIGS') {
            const oldScales = activeServerConfig.SCALE_CONFIGS || {};
            const newScales = newConfig.SCALE_CONFIGS || {};
            Object.keys(newScales).forEach(ch => {
                const oldCh = oldScales[ch] || {};
                const newCh = newScales[ch] || {};
                ['stream', 'enabled', 'low_voltage', 'high_voltage', 'low_value', 'high_value'].forEach(f => {
                    const normOld = oldCh[f] === undefined ? '(none)' : String(oldCh[f]);
                    const normNew = newCh[f] === undefined ? '(none)' : String(newCh[f]);
                    if (normOld !== normNew) {
                        diffCount++;
                        const item = document.createElement('div');
                        item.className = 'diff-item';
                        const label = f === 'stream' ? `AI ${ch} Stream` : `AI ${ch} Scale (${f})`;
                        item.innerHTML = `
                            <span class="diff-key">${label}</span>
                            <div class="diff-vals">
                                <span class="diff-old">${normOld}</span>
                                <span class="diff-arrow">&rarr;</span>
                                <span class="diff-new">${normNew}</span>
                            </div>
                        `;
                        diffContainer.appendChild(item);
                    }
                });
            });
            return;
        }

        if (key === 'DI_CHANNELS') {
            const oldDiChannels = normalizeDiChannels(activeServerConfig.DI_CHANNELS, activeServerConfig.ENABLE_DI === true);
            const newDiChannels = normalizeDiChannels(newConfig.DI_CHANNELS, newConfig.ENABLE_DI === true);
            newDiChannels.forEach((selected, bit) => {
                if (oldDiChannels[bit] === selected) return;
                diffCount++;
                const item = document.createElement('div');
                item.className = 'diff-item';
                item.innerHTML = `
                    <span class="diff-key">DI${bit} Stream</span>
                    <div class="diff-vals">
                        <span class="diff-old">${oldDiChannels[bit] ? 'ON' : 'OFF'}</span>
                        <span class="diff-arrow">&rarr;</span>
                        <span class="diff-new">${selected ? 'ON' : 'OFF'}</span>
                    </div>
                `;
                diffContainer.appendChild(item);
            });
            return;
        }

        if (key === 'CHANNEL_SAMPLE_RATES') {
            const oldRates = normalizeChannelSampleRates(activeServerConfig.CHANNEL_SAMPLE_RATES);
            const newRates = normalizeChannelSampleRates(newConfig.CHANNEL_SAMPLE_RATES);
            const rateKeys = new Set([...Object.keys(oldRates), ...Object.keys(newRates)]);
            rateKeys.forEach(rateKey => {
                const oldRate = oldRates[rateKey];
                const newRate = newRates[rateKey];
                if (oldRate === newRate) return;
                diffCount++;
                const item = document.createElement('div');
                item.className = 'diff-item';
                item.innerHTML = `
                    <span class="diff-key">${rateKey} Save Rate</span>
                    <div class="diff-vals">
                        <span class="diff-old">${oldRate === undefined ? 'INHERIT' : `${formatRate(oldRate)} Hz`}</span>
                        <span class="diff-arrow">&rarr;</span>
                        <span class="diff-new">${newRate === undefined ? 'INHERIT' : `${formatRate(newRate)} Hz`}</span>
                    </div>
                `;
                diffContainer.appendChild(item);
            });
            return;
        }

        const oldVal = activeServerConfig[key];
        const newVal = newConfig[key];
        const normOld = oldVal === undefined ? '(none)' : String(oldVal);
        const normNew = newVal === undefined ? '(none)' : String(newVal);

        if (normOld !== normNew) {
            diffCount++;
            const item = document.createElement('div');
            item.className = 'diff-item';
            item.innerHTML = `
                <span class="diff-key">${key}</span>
                <div class="diff-vals">
                    <span class="diff-old">${normOld}</span>
                    <span class="diff-arrow">&rarr;</span>
                    <span class="diff-new">${normNew}</span>
                </div>
            `;
            diffContainer.appendChild(item);
        }
    });

    if (diffCount === 0) {
        diffContainer.innerHTML = '<div class="no-diff-msg" style="padding:0.75rem 0.85rem;color:var(--text-muted);">No parameters modified. Click "Confirm & Write to Disk" to re-save current configuration.</div>';
    }

    if (countBadge) countBadge.textContent = `${diffCount} CHANGES`;

    const clockRate = newConfig.CLOCK_RATE || 1000;
    const metaClock = document.getElementById('modal-meta-clock');
    if (metaClock) metaClock.textContent = `${clockRate} Hz`;

    const minRateText = document.getElementById('calc-size-min')?.textContent || '--';
    const metaRate = document.getElementById('modal-meta-rate');
    if (metaRate) metaRate.textContent = minRateText;
    updateModalChannelMeta(newConfig);

    document.getElementById('confirm-modal-overlay')?.classList.remove('hidden');
}

// Close audit modal
function closeConfirmAuditModal() {
    document.getElementById('confirm-modal-overlay')?.classList.add('hidden');
    pendingConfigPayload = null;
}

// Execute write operation to backend config.json
async function commitConfigToBackend() {
    if (!pendingConfigPayload) return;
    const payload = pendingConfigPayload;

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!res.ok) throw new Error("Failed to save.");

        activeServerConfig = JSON.parse(JSON.stringify(payload));
        closeConfirmAuditModal();
        showToast("Configuration written to disk successfully.");
        appendLog('SUCCESS', 'Configuration audit approved and committed to config.json.');

        // Re-render matrix table so stream toggles reflect newly saved values
        scaleConfigs = payload.SCALE_CONFIGS || {};
        renderIngestionMatrixTable(payload);
        toggleSamplingFields();
        updateDataSizeEstimator();
        checkDirtyState();

        // Show Save Status Confirmation Badges across all panels
        const now = new Date();
        const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
        const savedText = `✓ CONFIG SAVED AT ${timeStr}`;
        document.querySelectorAll('.save-status-badge').forEach(badge => {
            badge.classList.remove('badge-warning');
            badge.dataset.savedTime = savedText;
            const textEl = badge.querySelector('.save-status-text');
            if (textEl) textEl.textContent = savedText;
            badge.classList.remove('hidden');
        });
    } catch (e) {
        showToast("Error saving configuration.", true);
        appendLog('ERROR', `Failed to write config: ${e.message}`);
    }
}

// Handle Run command
function handleStartProcess() {
    const mode = document.getElementById('mode-select').value;
    socket.emit('start_daq', { mode: mode });
}

// Handle Stop command
function handleStopProcess() {
    socket.emit('stop_daq');
}

// Clear terminal logs
function clearConsole() {
    const consoleBody = document.getElementById('console-output');
    if (consoleBody) {
        consoleBody.innerHTML = '<div class="log-line text-muted">[CONSOLE] Logs cleared.</div>';
    }
}

// Append log message directly inside console body
function appendLog(level, message) {
    const consoleBody = document.getElementById('console-output');
    if (!consoleBody) return;

    const now = new Date();
    const timeStr = `[${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}]`;
    
    const logLine = document.createElement('div');
    logLine.className = 'log-line';
    
    let tagClass = 'text-muted';
    if (level === 'SUCCESS') tagClass = 'text-success';
    if (level === 'ERROR' || level === 'WARN') tagClass = 'text-error';
    
    logLine.innerHTML = `<span class="log-time">${timeStr}</span> <span class="${tagClass}">${message}</span>`;
    consoleBody.appendChild(logLine);
    
    // Auto-scroll
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

// Display simple alert toaster
function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    
    if (isError) {
        toast.style.borderColor = '#ef4444';
    } else {
        toast.style.borderColor = '#0ea5e9';
    }
    
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Setup WebSocket triggers
function bindSocketEvents() {
    socket.on('connect', () => {
        appendLog('SUCCESS', 'WebSocket bridge connected.');
    });

    socket.on('disconnect', () => {
        appendLog('ERROR', 'WebSocket bridge disconnected.');
        updateUIState(false);
    });

    // Update status elements
    socket.on('status_change', (data) => {
        updateUIState(data.is_running, data.mode, data.destination);
    });

    // Handle new log streams
    socket.on('log_update', (data) => {
        const line = data.log;
        let level = 'INFO';
        if (line.includes('error') || line.includes('Error') || line.includes('failed') || line.includes('Full!')) {
            level = 'ERROR';
        } else if (line.includes('started') || line.includes('connected') || line.includes('ready') || line.includes('ready')) {
            level = 'SUCCESS';
        }
        appendLog(level, line);
    });

    // Process statistics and telemetry
    socket.on('stats_update', (data) => {
        document.getElementById('telemetry-polled').textContent = data.polled;
        document.getElementById('telemetry-written').textContent = data.written;
        document.getElementById('telemetry-queue').textContent = data.queue_util;
        
        const lossVal = document.getElementById('telemetry-loss');
        lossVal.textContent = `${data.loss_pct}% (${data.dropped})`;
        
        // Highlight loss if rate is above 0
        if (parseInt(data.dropped, 10) > 0) {
            lossVal.className = 'telemetry-value monospace text-error';
        } else {
            lossVal.className = 'telemetry-value monospace text-amber';
        }
    });
}

// Render Channel Ingestion Matrix Table
function renderIngestionMatrixTable(config) {
    const tbody = document.getElementById('ingestion-matrix-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    scaleConfigs = config.SCALE_CONFIGS || {};
    const channelCountValue = Number(config.CHANNEL_COUNT);
    const channelCount = Number.isFinite(channelCountValue) ? Math.max(0, channelCountValue) : 0;
    const enableAi = getBooleanControlValue('ENABLE_AI', config.ENABLE_AI !== false);
    const hardwareRate = getHardwareClockRate(config);
    const sectionLength = Math.max(1, parseInt(document.getElementById('SECTION_LENGTH')?.value ?? config.SECTION_LENGTH, 10) || 500);
    const channelRates = normalizeChannelSampleRates(config.CHANNEL_SAMPLE_RATES);
    let activeAiCount = 0;

    // 1. Render Analog Input (AI) Rows (0 to 7)
    for (let i = 0; i < 8; i++) {
        const scaleCfg = scaleConfigs[String(i)] || { stream: false, enabled: false, low_voltage: 0.0, high_voltage: 10.0, low_value: 0.0, high_value: 100.0 };
        const rateKey = `AI${i}`;
        const sourceRate = getChannelSourceRate(rateKey, hardwareRate, sectionLength);
        const configuredRate = channelRates[rateKey] === undefined
            ? null
            : Math.min(channelRates[rateKey], sourceRate);
        // Per-channel stream state: use scaleCfg.stream if present, else fall back to range check
        const isIngestActive = enableAi && (scaleCfg.stream !== undefined ? scaleCfg.stream : (i < channelCount));
        if (isIngestActive) activeAiCount++;
        
        const tr = document.createElement('tr');
        tr.className = `row-ai ${isIngestActive ? '' : 'row-disabled'}`;
        tr.dataset.ch = i;

        tr.innerHTML = `
            <td>
                <div class="ch-badge-cell">
                    <span class="badge badge-ai">AI ${i}</span>
                    <span class="ch-id monospace">ch${i}</span>
                </div>
            </td>
            <td><span class="type-label">Analog Volt</span></td>
            <td style="text-align: center;">
                <label class="toggle-switch">
                    <input type="checkbox" class="ingest-toggle-ai" data-ch="${i}" ${isIngestActive ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                </label>
            </td>
            <td>
                <input type="number" class="table-input channel-rate-input" data-rate-key="${rateKey}" min="0.001" max="${sourceRate}" step="any" value="${configuredRate ?? ''}" placeholder="HW ${formatRate(sourceRate)}" title="Blank inherits ${formatRate(sourceRate)} Hz">
            </td>
            <td style="text-align: center;">
                <label class="toggle-switch switch-cyan">
                    <input type="checkbox" class="scale-toggle-ai" data-ch="${i}" ${scaleCfg.enabled ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                </label>
            </td>
            <td><input type="number" class="table-input scale-low-volt" data-ch="${i}" step="any" value="${scaleCfg.low_voltage}" ${scaleCfg.enabled ? '' : 'disabled'}></td>
            <td><input type="number" class="table-input scale-high-volt" data-ch="${i}" step="any" value="${scaleCfg.high_voltage}" ${scaleCfg.enabled ? '' : 'disabled'}></td>
            <td><input type="number" class="table-input scale-low-val" data-ch="${i}" step="any" value="${scaleCfg.low_value}" ${scaleCfg.enabled ? '' : 'disabled'}></td>
            <td><input type="number" class="table-input scale-high-val" data-ch="${i}" step="any" value="${scaleCfg.high_value}" ${scaleCfg.enabled ? '' : 'disabled'}></td>
        `;

        tbody.appendChild(tr);
    }

    // 2. Render all eight Digital Input (DI) channel rows.
    const diOffsetValue = parseInt(document.getElementById('DI_CHANNEL_OFFSET')?.value ?? config.DI_CHANNEL_OFFSET, 10);
    const diOffset = Number.isFinite(diOffsetValue) ? Math.max(0, diOffsetValue) : 100;
    const diChannels = normalizeDiChannels(config.DI_CHANNELS, config.ENABLE_DI === true);

    let selectedDiCount = 0;
    for (let bit = 0; bit < 8; bit++) {
        const isSelected = diChannels[bit];
        if (isSelected) selectedDiCount++;
        const chId = diOffset + bit;
        const rateKey = `DI${bit}`;
        const sourceRate = getChannelSourceRate(rateKey, hardwareRate, sectionLength);
        const configuredRate = channelRates[rateKey] === undefined
            ? null
            : Math.min(channelRates[rateKey], sourceRate);
        const tr = document.createElement('tr');
        tr.className = `row-di ${isSelected ? '' : 'row-disabled'}`;
        tr.dataset.di = bit;
        tr.innerHTML = `
            <td>
                <div class="ch-badge-cell">
                    <span class="badge badge-di">DI ${bit}</span>
                    <span class="ch-id monospace">ch${chId}</span>
                </div>
            </td>
            <td><span class="type-label text-cyan">Digital Bit</span></td>
            <td style="text-align: center;">
                <label class="toggle-switch switch-cyan">
                    <input type="checkbox" class="ingest-toggle-di" data-di="${bit}" ${isSelected ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                </label>
            </td>
            <td>
                <input type="number" class="table-input channel-rate-input" data-rate-key="${rateKey}" min="0.001" max="${sourceRate}" step="any" value="${configuredRate ?? ''}" placeholder="DI ${formatRate(sourceRate)}" title="Blank inherits ${formatRate(sourceRate)} Hz">
            </td>
            <td style="text-align: center;"><span class="text-muted monospace" style="font-size: 0.65rem;">N/A</span></td>
            <td><span class="text-muted monospace">—</span></td>
            <td><span class="text-muted monospace">—</span></td>
            <td><span class="text-muted monospace">—</span></td>
            <td><span class="text-muted monospace">—</span></td>
        `;
        tbody.appendChild(tr);
    }

    // Update Matrix Meta Info Text
    const metaInfo = document.getElementById('matrix-meta-info');
    if (metaInfo) {
        metaInfo.textContent = `${activeAiCount} AI Channels · ${selectedDiCount}/8 DI Channels selected`;
    }
    const selectionSummary = document.getElementById('di-selection-summary');
    if (selectionSummary) {
        selectionSummary.textContent = `${selectedDiCount}/8 DI Channels selected in the matrix`;
    }

    // 3. Bind Event Listeners for Row Scale Toggles & Ingestion Switches
    bindMatrixTableEvents();
}

// Bind Matrix Table Row Controls & Filters
function bindMatrixTableEvents() {
    const tbody = document.getElementById('ingestion-matrix-tbody');
    if (!tbody) return;

    // AI Ingestion Row Toggle
    tbody.querySelectorAll('.ingest-toggle-ai').forEach(sw => {
        sw.addEventListener('change', (e) => {
            const tr = e.target.closest('tr');
            if (tr) tr.classList.toggle('row-disabled', !e.target.checked);
            updateGlobalSamplingFromTable();
            checkDirtyState();
        });
    });

    // DI Ingestion Row Toggle
    tbody.querySelectorAll('.ingest-toggle-di').forEach(sw => {
        sw.addEventListener('change', (e) => {
            const tr = e.target.closest('tr');
            if (tr) tr.classList.toggle('row-disabled', !e.target.checked);
            updateGlobalSamplingFromTable();
            checkDirtyState();
        });
    });

    // AI Linear Scale Toggle
    tbody.querySelectorAll('.scale-toggle-ai').forEach(sw => {
        sw.addEventListener('change', (e) => {
            const ch = e.target.dataset.ch;
            const isChecked = e.target.checked;
            const tr = e.target.closest('tr');
            if (tr) {
                tr.querySelectorAll('.table-input').forEach(input => {
                    input.disabled = !isChecked;
                });
            }
            if (!scaleConfigs[ch]) scaleConfigs[ch] = {};
            scaleConfigs[ch].enabled = isChecked;
            checkDirtyState();
        });
    });

    // Input changes update scaleConfigs in memory
    tbody.querySelectorAll('.table-input:not(.channel-rate-input)').forEach(input => {
        const handleTableInput = (e) => {
            const ch = e.target.dataset.ch;
            const tr = e.target.closest('tr');
            if (!tr) return;
            const enabled = tr.querySelector('.scale-toggle-ai')?.checked || false;
            const lowVoltVal = tr.querySelector('.scale-low-volt')?.value;
            const highVoltVal = tr.querySelector('.scale-high-volt')?.value;
            const lowValVal = tr.querySelector('.scale-low-val')?.value;
            const highValVal = tr.querySelector('.scale-high-val')?.value;

            scaleConfigs[ch] = {
                enabled: enabled,
                low_voltage: (lowVoltVal !== '' && !isNaN(parseFloat(lowVoltVal))) ? parseFloat(lowVoltVal) : 0.0,
                high_voltage: (highVoltVal !== '' && !isNaN(parseFloat(highVoltVal))) ? parseFloat(highVoltVal) : 10.0,
                low_value: (lowValVal !== '' && !isNaN(parseFloat(lowValVal))) ? parseFloat(lowValVal) : 0.0,
                high_value: (highValVal !== '' && !isNaN(parseFloat(highValVal))) ? parseFloat(highValVal) : 100.0
            };
            checkDirtyState();
        };

        input.addEventListener('input', handleTableInput);
        input.addEventListener('change', handleTableInput);
    });

    // Per-channel output-rate changes do not affect hardware acquisition.
    tbody.querySelectorAll('.channel-rate-input').forEach(input => {
        const handleRateInput = () => {
            updateDataSizeEstimator();
            checkDirtyState();
        };
        input.addEventListener('input', handleRateInput);
        input.addEventListener('change', handleRateInput);
    });

    // Tab filter buttons
    const filterTabs = document.querySelectorAll('#matrix-tab-filters .tab-btn');
    filterTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            filterTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const filter = tab.dataset.filter;

            tbody.querySelectorAll('tr').forEach(tr => {
                if (filter === 'all') {
                    tr.style.display = '';
                } else if (filter === 'ai') {
                    tr.style.display = tr.classList.contains('row-ai') ? '' : 'none';
                } else if (filter === 'di') {
                    tr.style.display = tr.classList.contains('row-di') ? '' : 'none';
                }
            });
        });
    });
}

// Update top-level AI/DI sampling parameters from table toggles
function updateGlobalSamplingFromTable() {
    const aiSwitches = document.querySelectorAll('.ingest-toggle-ai');
    let maxAiCh = -1;
    let anyAiActive = false;
    aiSwitches.forEach((sw) => {
        const chNum = parseInt(sw.dataset.ch ?? '0', 10);
        // Keep scaleConfigs stream state in sync with toggle
        if (!scaleConfigs[String(chNum)]) scaleConfigs[String(chNum)] = {};
        scaleConfigs[String(chNum)].stream = sw.checked;
        if (sw.checked) {
            anyAiActive = true;
            if (!isNaN(chNum) && chNum > maxAiCh) maxAiCh = chNum;
        }
    });

    const enableAiEl = document.getElementById('ENABLE_AI');
    if (enableAiEl) {
        enableAiEl.checked = anyAiActive;
        enableAiEl.value = String(anyAiActive);
    }

    const chCountEl = document.getElementById('CHANNEL_COUNT');
    if (chCountEl) {
        chCountEl.value = String(anyAiActive ? (maxAiCh + 1) : 0);
    }

    const diChannels = collectDiChannelSelection();
    const enableDiEl = document.getElementById('ENABLE_DI');
    if (enableDiEl) enableDiEl.value = String(diChannels.some(Boolean));

    updateDataSizeEstimator();
}

// Calculate Telemetry Data Size per Min, Hour, Month
function updateDataSizeEstimator() {
    const clockRateEl = document.getElementById('CLOCK_RATE');
    const clockRate = clockRateEl ? (parseInt(clockRateEl.value, 10) || 1000) : 1000;
    const sectionLength = Math.max(1, parseInt(document.getElementById('SECTION_LENGTH')?.value, 10) || 500);
    const channelRates = collectChannelSampleRates();

    // Count active AI channels
    let aiRowsPerSec = 0;
    const aiSwitches = document.querySelectorAll('.ingest-toggle-ai');
    if (aiSwitches.length > 0) {
        aiSwitches.forEach(sw => {
            if (!sw.checked) return;
            const key = `AI${sw.dataset.ch}`;
            aiRowsPerSec += getConfiguredChannelRate(channelRates, key, clockRate);
        });
    } else {
        const enableAi = getBooleanControlValue('ENABLE_AI', true);
        const chCount = Math.max(0, parseInt(document.getElementById('CHANNEL_COUNT')?.value, 10) || 0);
        aiRowsPerSec = enableAi ? chCount * clockRate : 0;
    }

    // Count selected DI channels. Instant DI produces one snapshot per AI
    // acquisition block, so each selected bit has the snapshot rate.
    const diSwitches = document.querySelectorAll('.ingest-toggle-di');
    const diSnapshotRate = clockRate / sectionLength;
    let diRowsPerSec = 0;
    if (diSwitches.length > 0) {
        diSwitches.forEach(toggle => {
            if (!toggle.checked) return;
            const key = `DI${toggle.dataset.di}`;
            diRowsPerSec += getConfiguredChannelRate(channelRates, key, diSnapshotRate);
        });
    } else {
        const selectedDiCount = normalizeDiChannels(activeServerConfig?.DI_CHANNELS, activeServerConfig?.ENABLE_DI === true)
            .filter(Boolean).length;
        diRowsPerSec = selectedDiCount * diSnapshotRate;
    }

    const sampleRowsPerSec = aiRowsPerSec + diRowsPerSec;
    const bytesPerSec = sampleRowsPerSec * 40; // ~40 bytes per sample row (ts + ch + val + DB overhead)

    const bytesMin = bytesPerSec * 60;
    const bytesHour = bytesPerSec * 3600;
    const bytesMonth = bytesPerSec * 3600 * 24 * 30; // 30-day month

    const minEl = document.getElementById('calc-size-min');
    const hourEl = document.getElementById('calc-size-hour');
    const monthEl = document.getElementById('calc-size-month');

    if (minEl) minEl.textContent = formatBytes(bytesMin) + ' / min';
    if (hourEl) hourEl.textContent = formatBytes(bytesHour) + ' / hr';
    if (monthEl) monthEl.textContent = formatBytes(bytesMonth) + ' / month';
}

function updateModalChannelMeta(config) {
    const meta = document.getElementById('modal-meta-ch');
    if (!meta) return;

    const aiRows = document.querySelectorAll('.ingest-toggle-ai');
    const activeAi = aiRows.length
        ? Array.from(aiRows).filter(toggle => toggle.checked).length
        : (getBooleanControlValue('ENABLE_AI', config.ENABLE_AI !== false)
            ? Math.max(0, parseInt(config.CHANNEL_COUNT, 10) || 0) : 0);
    const diSwitches = document.querySelectorAll('.ingest-toggle-di');
    const activeDi = diSwitches.length
        ? Array.from(diSwitches).filter(toggle => toggle.checked).length
        : normalizeDiChannels(config.DI_CHANNELS, config.ENABLE_DI === true).filter(Boolean).length;
    meta.textContent = `${activeAi} AI · ${activeDi} DI`;
}

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0.00 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function collectDiChannelSelection() {
    const toggles = document.querySelectorAll('.ingest-toggle-di');
    if (!toggles.length) {
        return normalizeDiChannels(activeServerConfig?.DI_CHANNELS, activeServerConfig?.ENABLE_DI === true);
    }

    const selected = Array(8).fill(false);
    toggles.forEach(toggle => {
        const bit = parseInt(toggle.dataset.di, 10);
        if (Number.isInteger(bit) && bit >= 0 && bit < 8) selected[bit] = toggle.checked;
    });
    return selected;
}

function collectChannelSampleRates() {
    const existingRates = normalizeChannelSampleRates(activeServerConfig?.CHANNEL_SAMPLE_RATES);
    const inputs = document.querySelectorAll('.channel-rate-input');
    if (!inputs.length) return existingRates;

    const rates = { ...existingRates };
    const hardwareRate = getHardwareClockRate(activeServerConfig || {});
    const sectionLength = Math.max(1, parseInt(document.getElementById('SECTION_LENGTH')?.value, 10) || 500);

    inputs.forEach(input => {
        const key = String(input.dataset.rateKey || '').toUpperCase();
        if (!key) return;
        const sourceRate = getChannelSourceRate(key, hardwareRate, sectionLength);
        const rawValue = String(input.value ?? '').trim();
        if (!rawValue) {
            delete rates[key];
            return;
        }

        const rate = parseFloat(rawValue);
        if (!Number.isFinite(rate) || rate <= 0) return;
        rates[key] = Math.min(rate, sourceRate);
    });

    return rates;
}

// Save inputs back to active channel configuration in memory from table
function collectScaleConfigsFromMatrixTable() {
    const tbody = document.getElementById('ingestion-matrix-tbody');
    if (!tbody) return scaleConfigs;

    tbody.querySelectorAll('tr.row-ai').forEach(tr => {
        const ch = tr.dataset.ch;
        const streamToggle = tr.querySelector('.ingest-toggle-ai');
        const isStreaming = streamToggle ? streamToggle.checked : false;
        const enabled = tr.querySelector('.scale-toggle-ai')?.checked || false;
        const lowVoltVal = tr.querySelector('.scale-low-volt')?.value;
        const highVoltVal = tr.querySelector('.scale-high-volt')?.value;
        const lowValVal = tr.querySelector('.scale-low-val')?.value;
        const highValVal = tr.querySelector('.scale-high-val')?.value;

        scaleConfigs[ch] = {
            stream: isStreaming,
            enabled: enabled,
            low_voltage: (lowVoltVal !== '' && !isNaN(parseFloat(lowVoltVal))) ? parseFloat(lowVoltVal) : 0.0,
            high_voltage: (highVoltVal !== '' && !isNaN(parseFloat(highVoltVal))) ? parseFloat(highVoltVal) : 10.0,
            low_value: (lowValVal !== '' && !isNaN(parseFloat(lowValVal))) ? parseFloat(lowValVal) : 0.0,
            high_value: (highValVal !== '' && !isNaN(parseFloat(highValVal))) ? parseFloat(highValVal) : 100.0
        };
    });

    return scaleConfigs;
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

// UI Theme Selector & Persistence
function initThemeSelector() {
    const themeSelect = document.getElementById('ui-theme-select');
    if (!themeSelect) return;

    const savedTheme = localStorage.getItem('daq_ui_theme') || 'dark-ocean';
    themeSelect.value = savedTheme;
    document.documentElement.setAttribute('data-theme', savedTheme);

    themeSelect.addEventListener('change', (e) => {
        const theme = e.target.value;
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('daq_ui_theme', theme);
        const themeLabel = themeSelect.options[themeSelect.selectedIndex].text;
        showToast(`Theme switched to ${themeLabel}`);
    });
}
