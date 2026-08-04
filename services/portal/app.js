// app.js
// See: docs/architecture/context.md
// English comments only

// System Start Timestamp
const startTimestamp = Date.now();

// Start Clock and Counters
document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    
    updateUptime();
    setInterval(updateUptime, 1000);

    // Resolve localhost hostnames dynamically
    resolveHostnames();

    // Simulate occasional background system activity logs
    setInterval(simulateSystemLog, 15000);

    // Add interceptors to portal links to display log messages
    setupPortalLinks();
});

// Dynamically replace 'localhost' in link URLs with the accessing IP/hostname
function resolveHostnames() {
    const hostname = window.location.hostname;
    const links = document.querySelectorAll('.module-portal-link');
    links.forEach(link => {
        const originalHref = link.getAttribute('href');
        if (originalHref && originalHref.includes('localhost')) {
            link.setAttribute('href', originalHref.replace('localhost', hostname));
        }
    });
}

// Update the real-time clock in the header (local format)
function updateClock() {
    const clockEl = document.getElementById('realtime-clock');
    if (!clockEl) return;
    
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    
    clockEl.textContent = `${hours}:${minutes}:${seconds}`;
}

// Update uptime tracker since landing page was loaded
function updateUptime() {
    const uptimeEl = document.getElementById('uptime-counter');
    if (!uptimeEl) return;
    
    const diff = Math.floor((Date.now() - startTimestamp) / 1000);
    const hours = String(Math.floor(diff / 3600)).padStart(2, '0');
    const minutes = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
    const seconds = String(diff % 60).padStart(2, '0');
    
    uptimeEl.textContent = `${hours}:${minutes}:${seconds}`;
}

// Intercept portal link clicks to log the action in the console
function setupPortalLinks() {
    const links = document.querySelectorAll('.module-portal-link');
    links.forEach(link => {
        link.addEventListener('click', (e) => {
            const card = link.querySelector('.module-row');
            const title = card.querySelector('h3').textContent;
            const badge = card.querySelector('.status-badge').textContent.trim();
            
            appendLog('INFO', `Redirecting to ${title} Control Panel on ${badge}...`);
        });
    });
}

// Append new log lines to the scrolling terminal console footer
function appendLog(level, message) {
    const consoleBody = document.getElementById('log-console');
    if (!consoleBody) return;

    const now = new Date();
    const timeStr = `[${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}]`;
    
    const logLine = document.createElement('div');
    logLine.className = 'log-line';
    
    let tagClass = 'tag-info';
    if (level === 'SUCCESS') tagClass = 'tag-success';
    if (level === 'WARN') tagClass = 'tag-warning';
    
    logLine.innerHTML = `<span class="log-time">${timeStr}</span> <span class="log-tag ${tagClass}">${level}</span> ${message}`;
    
    consoleBody.appendChild(logLine);
    
    // Auto-scroll to the bottom of the console log
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

// Simulate periodic ingestion events for background logging realism
const dummyEvents = [
    { level: 'INFO', msg: 'Syncing portal metadata across distributed nodes.' },
    { level: 'SUCCESS', msg: 'Telemetry database sync completed. 0 packets dropped.' },
    { level: 'INFO', msg: 'Heartbeat signal acknowledged from Musashi II portal on Port 8082.' },
    { level: 'WARN', msg: 'High jitter detected on DAQ hardware clock. Aligning back-computation buffer.' },
    { level: 'INFO', msg: 'Checking client connection handshakes...' }
];

function simulateSystemLog() {
    const event = dummyEvents[Math.floor(Math.random() * dummyEvents.length)];
    appendLog(event.level, event.msg);
}
