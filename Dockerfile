FROM python:3.10-slim

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

# Upgrade pip, setuptools, and wheel to guarantee binary wheel installation
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

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
