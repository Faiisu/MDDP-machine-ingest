// app.js
// See: docs/architecture/context.md
// English comments only

let activePlots = [];
let defaultDsn = '';
let connectionValidated = false;

document.addEventListener('DOMContentLoaded', () => {
    // Start UTC clock display
    updateClock();
    setInterval(updateClock, 1000);

    // Initial loads
    fetchDefaultDsn();
    resolveBackLink();
    loadStoredLayout();
    loadStoredPlots();

    // Modal UI hooks
    document.getElementById('open-modal-btn').addEventListener('click', openModal);
    document.getElementById('reset-workspace-btn').addEventListener('click', handleResetWorkspace);
    document.getElementById('empty-state-add-btn').addEventListener('click', openModal);
    document.getElementById('close-modal-btn').addEventListener('click', closeModal);
    document.getElementById('modal-service-select').addEventListener('change', handleModalServiceChange);
    document.getElementById('modal-mode-select').addEventListener('change', handleModalModeChange);
    document.getElementById('test-conn-btn').addEventListener('click', testDatabaseConnection);
    document.getElementById('create-plot-form').addEventListener('submit', handleCreatePlotSubmit);

    // Layout Column toggles
    const toggleBtns = document.querySelectorAll('.toggle-btn');
    toggleBtns.forEach(btn => {
        btn.addEventListener('click', handleLayoutColumnToggle);
    });

    // Close modal on escape or clicking overlay background
    window.addEventListener('click', (e) => {
        const modal = document.getElementById('plot-modal');
        if (e.target === modal) closeModal();
    });
});

// Update header clock (local)
function updateClock() {
    const clockEl = document.getElementById('realtime-clock');
    if (!clockEl) return;
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    clockEl.textContent = `${hours}:${minutes}:${seconds}`;
}

// Fetch the default database connection string from backend configuration
async function fetchDefaultDsn() {
    try {
        const res = await fetch('/api/db/default');
        const data = await res.json();
        defaultDsn = data.dsn;
        document.getElementById('modal-db-dsn').value = defaultDsn;
    } catch (e) {
        console.error("Failed to load default DSN:", e);
    }
}

// Modal open/close actions
function openModal() {
    document.getElementById('plot-modal').classList.remove('hidden');
    // Pre-populate input
    if (defaultDsn) {
        document.getElementById('modal-db-dsn').value = defaultDsn;
    }
    resetConnectionStatus();
    // Default mode setup
    document.getElementById('modal-mode-select').value = 'live';
    handleModalModeChange();
}

function closeModal() {
    document.getElementById('plot-modal').classList.add('hidden');
}

// Reset DSN validation feedback
function resetConnectionStatus() {
    connectionValidated = false;
    const feedback = document.getElementById('test-feedback');
    feedback.textContent = 'Awaiting connection verification...';
    feedback.className = 'test-feedback';
    document.getElementById('create-plot-btn').disabled = true;
}

// Handle Service changes on the Modal Config Form
function handleModalServiceChange() {
    const service = document.getElementById('modal-service-select').value;
    const daqGroup = document.getElementById('modal-daq-group');
    if (service === 'daq') {
        daqGroup.classList.remove('hidden');
    } else {
        daqGroup.classList.add('hidden');
    }
}

// Handle Live vs Static toggle changes on the Modal Form
function handleModalModeChange() {
    const mode = document.getElementById('modal-mode-select').value;
    const liveGroup = document.getElementById('modal-live-range-group');
    const staticGroup = document.getElementById('modal-static-range-group');
    
    if (mode === 'live') {
        liveGroup.classList.remove('hidden');
        staticGroup.classList.add('hidden');
    } else {
        liveGroup.classList.add('hidden');
        staticGroup.classList.remove('hidden');
        
        // Populate default custom times (start: 5 mins ago, end: now)
        const now = new Date();
        const start = new Date(now.getTime() - 5 * 60 * 1000);
        document.getElementById('modal-start-datetime').value = toLocalISOString(start);
        document.getElementById('modal-end-datetime').value = toLocalISOString(now);
    }
}

// Helper to format datetime-local input strings
function toLocalISOString(date) {
    const tzOffset = date.getTimezoneOffset() * 60000;
    return (new Date(date.getTime() - tzOffset)).toISOString().slice(0, 16);
}

// Submit DSN to backend connection tester
async function testDatabaseConnection() {
    const dsn = document.getElementById('modal-db-dsn').value.trim();
    const feedback = document.getElementById('test-feedback');
    const createBtn = document.getElementById('create-plot-btn');
    
    if (!dsn) {
        feedback.textContent = 'Error: Please enter a valid database DSN.';
        feedback.className = 'test-feedback error';
        return;
    }

    feedback.textContent = 'Testing connection...';
    feedback.className = 'test-feedback';

    try {
        const res = await fetch('/api/db/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dsn: dsn })
        });
        const result = await res.json();

        if (result.status === 'success') {
            connectionValidated = true;
            feedback.textContent = 'Connection Successful.';
            feedback.className = 'test-feedback success';
            createBtn.disabled = false;
        } else {
            connectionValidated = false;
            feedback.textContent = `Connection Failed: ${result.message}`;
            feedback.className = 'test-feedback error';
            createBtn.disabled = true;
        }
    } catch (e) {
        connectionValidated = false;
        feedback.textContent = `Request Error: ${e.message}`;
        feedback.className = 'test-feedback error';
        createBtn.disabled = true;
    }
}

// Toggle grid columns layout (1, 2, or 3 columns)
function handleLayoutColumnToggle(e) {
    const target = e.currentTarget;
    const cols = target.getAttribute('data-cols');
    const grid = document.getElementById('workspace-grid');
    
    // Update active class on buttons
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    target.classList.add('active');

    // Update grid container class
    grid.className = `workspace-grid col-${cols}`;

    // Save layout to storage
    saveStoredLayout(cols);

    // Force Plotly to resize all active charts to fit new container widths
    setTimeout(() => {
        activePlots.forEach(plot => {
            const chartDiv = document.getElementById(`plotly-chart-${plot.id}`);
            if (chartDiv) Plotly.Plots.resize(chartDiv);
        });
    }, 150);
}

// Add fresh plot metadata to workspace array and render card
function handleCreatePlotSubmit(e) {
    e.preventDefault();
    if (!connectionValidated) return;

    const service = document.getElementById('modal-service-select').value;
    const dsn = document.getElementById('modal-db-dsn').value.trim();
    const channel = parseInt(document.getElementById('modal-channel-select').value, 10);
    const mode = document.getElementById('modal-mode-select').value;

    let timeRange = 60;
    let startVal = '';
    let endVal = '';

    if (mode === 'live') {
        timeRange = parseInt(document.getElementById('modal-range-select').value, 10);
    } else {
        startVal = document.getElementById('modal-start-datetime').value;
        endVal = document.getElementById('modal-end-datetime').value;
        if (!startVal || !endVal) {
            alert("Please input both start and end datetimes.");
            return;
        }
    }

    const plotId = Date.now();
    const newPlot = {
        id: plotId,
        service: service,
        dsn: dsn,
        channel: channel,
        mode: mode,
        timeRange: timeRange,
        startDatetime: startVal,
        endDatetime: endVal,
        intervalId: null
    };

    activePlots.push(newPlot);
    renderPlotCard(newPlot);
    initPlotlyChart(newPlot);
    
    // Save to localStorage
    saveActivePlots();
    
    // Start interval querying only if in LIVE mode
    if (mode === 'live') {
        newPlot.intervalId = setInterval(() => queryPlotData(newPlot), 1000);
    }
    
    // Trigger initial query
    queryPlotData(newPlot); 

    closeModal();
    showToast(`Plot created successfully (${service.toUpperCase()} | ${mode.toUpperCase()})`);
}

// Helper to format timestamps inside static footer labels
function formatFooterDate(isoStr) {
    if (!isoStr) return '--';
    const d = new Date(isoStr);
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const hrs = String(d.getHours()).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    const secs = String(d.getSeconds()).padStart(2, '0');
    return `${day}/${month} ${hrs}:${mins}:${secs}`;
}

// Render dynamic card markup into grid
function renderPlotCard(plot) {
    const grid = document.getElementById('workspace-grid');
    const emptyState = document.getElementById('empty-workspace-state');

    // Hide empty state on first addition
    if (emptyState) emptyState.classList.add('hidden');

    const card = document.createElement('div');
    card.className = 'plot-card';
    card.id = `plot-card-${plot.id}`;

    let titleText = '';
    if (plot.service === 'daq') titleText = `DAQ USB-4716 | CH ${plot.channel}`;
    else if (plot.service === 'musashi_ii') titleText = 'Musashi II Dispenser';
    else if (plot.service === 'musashi_iv') titleText = 'Musashi IV Robot';

    // Footer config layout: range selector for live, text labels for static
    let footerControlsHtml = '';
    if (plot.mode === 'live') {
        const isPaused = !!plot.isPaused;
        const pauseBtnText = isPaused ? 'RESUME' : 'PAUSE';
        const pauseBtnStyle = isPaused 
            ? 'background-color: transparent; border: 1px solid var(--accent-sky); color: var(--accent-sky); font-weight: 700; padding: 0.25rem 0.65rem;'
            : 'background-color: var(--accent-sky); color: var(--bg-main); font-weight: 700; border: none; padding: 0.25rem 0.65rem;';

        footerControlsHtml = `
            ${plot.service === 'daq' ? `
            <select class="footer-select" onchange="updatePlotChannel(${plot.id}, this.value)">
                <option value="0" ${plot.channel === 0 ? 'selected' : ''}>CH 0</option>
                <option value="1" ${plot.channel === 1 ? 'selected' : ''}>CH 1</option>
                <option value="2" ${plot.channel === 2 ? 'selected' : ''}>CH 2</option>
                <option value="3" ${plot.channel === 3 ? 'selected' : ''}>CH 3</option>
            </select>
            ` : ''}
            <select class="footer-select" onchange="updatePlotTimeRange(${plot.id}, this.value)">
                <option value="5" ${plot.timeRange === 5 ? 'selected' : ''}>5s</option>
                <option value="30" ${plot.timeRange === 30 ? 'selected' : ''}>30s</option>
                <option value="60" ${plot.timeRange === 60 ? 'selected' : ''}>1m</option>
                <option value="300" ${plot.timeRange === 300 ? 'selected' : ''}>5m</option>
                <option value="900" ${plot.timeRange === 900 ? 'selected' : ''}>15m</option>
                <option value="1800" ${plot.timeRange === 1800 ? 'selected' : ''}>30m</option>
            </select>
            <button class="footer-select" onclick="togglePlotPause(${plot.id}, this)" id="pause-btn-${plot.id}" style="${pauseBtnStyle}">${pauseBtnText}</button>
        `;
    } else {
        footerControlsHtml = `
            <span class="footer-meta" style="color: var(--accent-sky); font-weight: 500;">
                RANGE: ${formatFooterDate(plot.startDatetime)} - ${formatFooterDate(plot.endDatetime)}
            </span>
        `;
    }

    const isLiveActive = plot.mode === 'live' && !plot.isPaused;
    const badgeText = plot.isPaused ? 'PAUSED' : plot.mode;
    const badgeClass = plot.isPaused ? 'static' : plot.mode;

    // Build card markup with status indicator badges
    card.innerHTML = `
        <div class="plot-card-header">
            <div class="plot-title-block">
                <span class="pulse-dot ${isLiveActive ? 'green' : 'grey'}" style="background-color: ${isLiveActive ? 'var(--accent-emerald)' : 'var(--text-muted)'}; box-shadow: ${isLiveActive ? '0 0 6px var(--accent-emerald)' : 'none'};"></span>
                <h3>${titleText}</h3>
                <span class="card-badge ${badgeClass}">${badgeText}</span>
            </div>
            <button class="delete-plot-btn" onclick="deletePlot(${plot.id})">&times;</button>
        </div>
        <div class="plot-card-body">
            <div id="plotly-chart-${plot.id}" class="chart-wrapper"></div>
        </div>
        <div class="plot-card-footer">
            <div class="footer-meta" title="${plot.dsn}">DB: ${plot.dsn}</div>
            <div class="footer-controls">
                ${footerControlsHtml}
            </div>
        </div>
    `;

    grid.appendChild(card);
}

// Initialize Plotly trace structures inside card wrapper
function initPlotlyChart(plot) {
    const chartDivId = `plotly-chart-${plot.id}`;
    let traces = [];

    // Define trace lines and hover templates matching the service
    if (plot.service === 'daq') {
        traces.push({
            x: [],
            y: [],
            name: 'DAQ Voltage',
            type: 'scatter',
            mode: 'lines',
            line: { color: '#0ea5e9', width: 1.5 },
            hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Voltage:</b> %{y:.4f} V<extra></extra>'
        });
    } else if (plot.service === 'musashi_ii') {
        traces.push({
            x: [],
            y: [],
            name: 'Pressure (kPa)',
            type: 'scatter',
            mode: 'lines',
            line: { color: '#a855f7', width: 1.5 },
            hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Pressure:</b> %{y} kPa<extra></extra>'
        }, {
            x: [],
            y: [],
            name: 'Fluid Temp (°C)',
            type: 'scatter',
            mode: 'lines',
            line: { color: '#f59e0b', width: 1.5 },
            hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Temp:</b> %{y} °C<extra></extra>'
        });
    } else if (plot.service === 'musashi_iv') {
        traces.push({
            x: [],
            y: [],
            name: 'Axis X',
            type: 'scatter',
            mode: 'lines',
            line: { color: '#0ea5e9', width: 1.2 },
            hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>X:</b> %{y} mm<extra></extra>'
        }, {
            x: [],
            y: [],
            name: 'Axis Y',
            type: 'scatter',
            mode: 'lines',
            line: { color: '#10b981', width: 1.2 },
            hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Y:</b> %{y} mm<extra></extra>'
        }, {
            x: [],
            y: [],
            name: 'Axis Z',
            type: 'scatter',
            mode: 'lines',
            line: { color: '#ef4444', width: 1.2 },
            hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Z:</b> %{y} mm<extra></extra>'
        });
    }

    const layout = {
        paper_bgcolor: '#0f1013',
        plot_bgcolor: '#0f1013',
        margin: { t: 15, r: 15, b: 35, l: 40 },
        dragmode: 'pan',
        showlegend: plot.service !== 'daq',
        legend: {
            font: { color: '#64748b', size: 8 },
            orientation: 'h',
            y: 1.15
        },
        xaxis: {
            type: 'date',
            gridcolor: 'rgba(14, 165, 233, 0.08)',
            zerolinecolor: 'rgba(14, 165, 233, 0.25)',
            tickcolor: 'rgba(14, 165, 233, 0.1)',
            tickfont: { color: '#cbd5e1', size: 9 },
            hoverformat: '%H:%M:%S.%L'
        },
        yaxis: {
            gridcolor: 'rgba(14, 165, 233, 0.08)',
            zerolinecolor: 'rgba(14, 165, 233, 0.25)',
            tickcolor: 'rgba(14, 165, 233, 0.1)',
            tickfont: { color: '#cbd5e1', size: 9 },
            autorange: true
        }
    };

    const config = {
        responsive: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
    };

    Plotly.newPlot(chartDivId, traces, layout, config);
}

// Fetch database records for a specific plot card and refresh the Plotly layout
async function queryPlotData(plot) {
    let url = '';
    
    // Choose endpoint based on service type
    if (plot.service === 'daq') {
        url = `/api/data?channel=${plot.channel}&dsn=${encodeURIComponent(plot.dsn)}`;
    } else {
        url = `/api/data/mock?service=${plot.service}`;
    }

    // Append timeframe range queries depending on mode
    if (plot.mode === 'live') {
        url += `&last=${plot.timeRange}`;
    } else {
        // Convert datetime-local picker string to UTC ISO format for backend parsing
        const startISO = new Date(plot.startDatetime).toISOString();
        const endISO = new Date(plot.endDatetime).toISOString();
        url += `&start=${startISO}&end=${endISO}`;
    }

    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error("Database query failed.");
        const result = await res.json();
        
        const chartDivId = `plotly-chart-${plot.id}`;
        const chartDiv = document.getElementById(chartDivId);
        if (!chartDiv) return;

        let traces = [];
        const times = result.times;

        if (plot.service === 'daq') {
            traces.push({
                x: times,
                y: result.values,
                name: 'DAQ Voltage',
                type: 'scatter',
                mode: 'lines',
                line: { color: '#0ea5e9', width: 1.5 },
                hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Voltage:</b> %{y:.4f} V<extra></extra>'
            });
        } else if (plot.service === 'musashi_ii') {
            traces.push({
                x: times,
                y: result.data.pressure,
                name: 'Pressure (kPa)',
                type: 'scatter',
                mode: 'lines',
                line: { color: '#a855f7', width: 1.5 },
                hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Pressure:</b> %{y} kPa<extra></extra>'
            }, {
                x: times,
                y: result.data.temp,
                name: 'Fluid Temp (°C)',
                type: 'scatter',
                mode: 'lines',
                line: { color: '#f59e0b', width: 1.5 },
                hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Temp:</b> %{y} °C<extra></extra>'
            });
        } else if (plot.service === 'musashi_iv') {
            traces.push({
                x: times,
                y: result.data.x,
                name: 'Axis X',
                type: 'scatter',
                mode: 'lines',
                line: { color: '#0ea5e9', width: 1.2 },
                hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>X:</b> %{y} mm<extra></extra>'
            }, {
                x: times,
                y: result.data.y,
                name: 'Axis Y',
                type: 'scatter',
                mode: 'lines',
                line: { color: '#10b981', width: 1.2 },
                hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Y:</b> %{y} mm<extra></extra>'
            }, {
                x: times,
                y: result.data.z,
                name: 'Axis Z',
                type: 'scatter',
                mode: 'lines',
                line: { color: '#ef4444', width: 1.2 },
                hovertemplate: '<b>Time:</b> %{x|%H:%M:%S.%L}<br><b>Z:</b> %{y} mm<extra></extra>'
            });
        }

        // Apply traces to layout using react (highly performant repaint)
        Plotly.react(chartDivId, traces, chartDiv.layout);
        
    } catch (e) {
        console.error(`Query failed for plot ${plot.id}:`, e);
    }
}

// Inline Footer controls changes
function updatePlotChannel(plotId, val) {
    const plot = activePlots.find(p => p.id === plotId);
    if (plot) {
        plot.channel = parseInt(val, 10);
        queryPlotData(plot);
        saveActivePlots();
    }
}

// Inline Time window changes
function updatePlotTimeRange(plotId, val) {
    const plot = activePlots.find(p => p.id === plotId);
    if (plot) {
        plot.timeRange = parseInt(val, 10);
        queryPlotData(plot);
        saveActivePlots();
    }
}

// Delete and clean up plot card
function deletePlot(plotId) {
    const index = activePlots.findIndex(p => p.id === plotId);
    if (index === -1) return;

    const plot = activePlots[index];
    
    // 1. Clear setInterval timer
    if (plot.intervalId) {
        clearInterval(plot.intervalId);
    }

    // 2. Remove from global list
    activePlots.splice(index, 1);
    saveActivePlots();

    // 3. Remove DOM element card
    const card = document.getElementById(`plot-card-${plotId}`);
    if (card) card.remove();

    // 4. Restore empty state if no charts left
    if (activePlots.length === 0) {
        const emptyState = document.getElementById('empty-workspace-state');
        if (emptyState) emptyState.classList.remove('hidden');
    }

    showToast("Plot removed.");
}

// Display Toast alert
function showToast(message) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.style.borderColor = '#0ea5e9';
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Toggle Pause/Resume on live charts
function togglePlotPause(plotId, btn) {
    const plot = activePlots.find(p => p.id === plotId);
    if (!plot) return;

    const card = document.getElementById(`plot-card-${plotId}`);
    const dot = card.querySelector('.pulse-dot');
    const badge = card.querySelector('.card-badge');

    if (!plot.isPaused) {
        // Pause updates
        plot.isPaused = true;
        if (plot.intervalId) {
            clearInterval(plot.intervalId);
            plot.intervalId = null;
        }
        btn.textContent = 'RESUME';
        btn.style.backgroundColor = 'transparent';
        btn.style.border = '1px solid var(--accent-sky)';
        btn.style.color = 'var(--accent-sky)';

        // Update header UI to Paused state
        dot.className = 'pulse-dot grey';
        dot.style.backgroundColor = 'var(--text-muted)';
        dot.style.boxShadow = 'none';
        
        badge.textContent = 'PAUSED';
        badge.className = 'card-badge static';
        showToast("Updates paused.");
    } else {
        // Resume updates
        plot.isPaused = false;
        btn.textContent = 'PAUSE';
        btn.style.backgroundColor = 'var(--accent-sky)';
        btn.style.color = 'var(--bg-main)';
        btn.style.border = 'none';

        // Update header UI back to Live state
        dot.className = 'pulse-dot green';
        dot.style.backgroundColor = 'var(--accent-emerald)';
        dot.style.boxShadow = '0 0 6px var(--accent-emerald)';
        
        badge.textContent = 'LIVE';
        badge.className = 'card-badge live';

        // Restart interval loop
        plot.intervalId = setInterval(() => queryPlotData(plot), 1000);
        queryPlotData(plot); // Fetch immediately
        showToast("Updates resumed.");
    }
    saveActivePlots();
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

// LocalStorage Persistence Helpers
function saveActivePlots() {
    const serializedPlots = activePlots.map(p => ({
        id: p.id,
        service: p.service,
        dsn: p.dsn,
        channel: p.channel,
        mode: p.mode,
        timeRange: p.timeRange,
        startDatetime: p.startDatetime,
        endDatetime: p.endDatetime,
        isPaused: !!p.isPaused
    }));
    localStorage.setItem('plotter_active_plots', JSON.stringify(serializedPlots));
}

function loadStoredPlots() {
    const stored = localStorage.getItem('plotter_active_plots');
    if (!stored) return;

    try {
        const parsed = JSON.parse(stored);
        if (!Array.isArray(parsed)) return;

        parsed.forEach(plot => {
            const restoredPlot = {
                ...plot,
                intervalId: null
            };
            activePlots.push(restoredPlot);
            renderPlotCard(restoredPlot);
            initPlotlyChart(restoredPlot);

            if (restoredPlot.mode === 'live' && !restoredPlot.isPaused) {
                restoredPlot.intervalId = setInterval(() => queryPlotData(restoredPlot), 1000);
            }
            queryPlotData(restoredPlot);
        });
    } catch (e) {
        console.error("Failed to restore saved plots:", e);
    }
}

function saveStoredLayout(cols) {
    localStorage.setItem('plotter_layout_cols', cols);
}

function loadStoredLayout() {
    const cols = localStorage.getItem('plotter_layout_cols') || '1';
    const grid = document.getElementById('workspace-grid');
    if (grid) {
        grid.className = `workspace-grid col-${cols}`;
    }
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        if (btn.getAttribute('data-cols') === cols) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

function handleResetWorkspace() {
    if (!confirm("Are you sure you want to clear the workspace layout and all created plots?")) return;
    
    // Clear all interval timers for live plots
    activePlots.forEach(plot => {
        if (plot.intervalId) {
            clearInterval(plot.intervalId);
        }
    });

    // Reset list
    activePlots = [];
    
    // Clear localStorage
    localStorage.removeItem('plotter_active_plots');
    localStorage.removeItem('plotter_layout_cols');

    // Remove DOM element cards
    document.querySelectorAll('.plot-card').forEach(card => card.remove());

    // Restore empty state
    const emptyState = document.getElementById('empty-workspace-state');
    if (emptyState) emptyState.classList.remove('hidden');

    // Restore layout columns to 1
    const grid = document.getElementById('workspace-grid');
    if (grid) grid.className = 'workspace-grid col-1';
    
    // Reset layout column buttons active class
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        if (btn.getAttribute('data-cols') === '1') {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    showToast("Workspace cleared. Stored memories removed.");
}

// Bind functions to window object for dynamic onclick access
window.deletePlot = deletePlot;
window.updatePlotChannel = updatePlotChannel;
window.updatePlotTimeRange = updatePlotTimeRange;
window.togglePlotPause = togglePlotPause;
