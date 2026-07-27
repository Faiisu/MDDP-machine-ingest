FROM python:3.12-slim

WORKDIR /app

# Install system build tools, development headers, and USB system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    python3-dev \
    libpq-dev \
    curl \
    libusb-1.0-0 \
    udev \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reliable dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies using uv into global container environment
COPY pyproject.toml requirements.txt uv.lock ./
RUN uv pip install --system -r requirements.txt

# Copy codebase and set permissions
COPY . .
RUN chmod +x /app/docker-entrypoint.sh

# Expose web application ports
# 8080: Portal Gateway
# 8081: DAQ USB-4716 Control Panel
# 8083: Musashi IV Dispenser Panel
# 8084: Database Plotter Service
EXPOSE 8080 8081 8083 8084

ENTRYPOINT ["/app/docker-entrypoint.sh"]
