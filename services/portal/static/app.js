const servicePorts = [8081, 8082, 8083, 8084, 8085, 18085, 8086];

function getHostForUrl() {
    const hostname = window.location.hostname || 'localhost';
    if (hostname.includes(':') && !hostname.startsWith('[')) return `[${hostname}]`;
    return hostname;
}

function getServiceUrl(port) {
    const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
    return `${protocol}//${getHostForUrl()}:${port}`;
}

function updateServiceLinks() {
    document.querySelectorAll('.service-card[data-port]').forEach((card) => {
        const port = Number(card.dataset.port);
        if (!servicePorts.includes(port)) return;
        const url = getServiceUrl(port);
        card.href = url;
        card.setAttribute('aria-label', `Open ${card.querySelector('h3').textContent} at ${url}`);
    });

    const host = `${getHostForUrl()}:${window.location.port || '8080'}`;
    document.getElementById('host-address').textContent = host;
    document.getElementById('route-preview').textContent = getServiceUrl(8081);
}

function updateClock() {
    document.getElementById('portal-clock').textContent = new Date().toTimeString().split(' ')[0];
}

async function refreshServiceStatus() {
    const summary = document.getElementById('service-summary');
    try {
        const response = await fetch('/api/services', { cache: 'no-store' });
        if (!response.ok) throw new Error('Service status request failed');
        const payload = await response.json();
        payload.services.forEach((service) => {
            const card = document.querySelector(`.service-card[data-port="${service.port}"]`);
            if (!card) return;
            const statusElement = card.querySelector('[data-status]');
            statusElement.textContent = service.status.toUpperCase();
            card.classList.toggle('service-online', service.status === 'online');
            card.classList.toggle('service-offline', service.status !== 'online');
        });
        summary.textContent = `${payload.online}/${payload.total} service ports responding`;
    } catch (error) {
        summary.textContent = 'Portal status probe unavailable';
    }
}

updateServiceLinks();
updateClock();
refreshServiceStatus();
document.getElementById('refresh-services').addEventListener('click', refreshServiceStatus);
window.setInterval(updateClock, 1000);
window.setInterval(refreshServiceStatus, 5000);
