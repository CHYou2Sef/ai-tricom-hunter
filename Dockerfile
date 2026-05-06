# ╔════════════════════════════════════════════════════════════════╗
# ║  Dockerfile - AI Phone Hunter (Optimized Industrial Build)     ║
# ║  Base: Python 3.10 slim, Consolidated Stealth Browsers         ║
# ╚════════════════════════════════════════════════════════════════╝

FROM python:3.10-slim-bookworm

# ── 1. Setup Environment ──────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/src" \
    # Ensure browsers are installed in a predictable, persistent path
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app

# ── 2. Install System Dependencies & Google Chrome ───────────────────
# Grouping all apt operations to minimize layers and cleaning up immediately.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg xvfb wget ca-certificates dos2unix \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 fonts-liberation libxshmfence1 libglu1-mesa \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    google-chrome-stable \
    && apt-get purge -y wget gnupg \
    && apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── 3. Install Python Dependencies with 'uv' ──────────────────────────
# Copy requirements first to leverage Docker Layer Caching.
COPY requirements-prod.txt .
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv pip install --system --no-cache -r requirements-prod.txt \
    && rm -rf /root/.local/bin/uv /root/.cache/uv

# ── 4. Install & Configure Stealth Browsers ───────────────────────────
# We install exactly what we need and immediately purge installation caches.
RUN patchright install chromium && \
    python3 -m cloakbrowser install && \
    crawl4ai-setup && \
    seleniumbase install chromedriver && \
    # Aggressive Cleanup of Browser Caches (Saving ~500MB+)
    rm -rf /root/.cache/ms-playwright/firefox-* && \
    rm -rf /root/.cache/ms-playwright/webkit-* && \
    rm -rf /root/.cache/seleniumbase/methods && \
    rm -rf /root/.cache/pip && \
    # Remove any stray node_modules if crawl4ai-setup created them
    rm -rf /app/node_modules

# ── 5. Copy Application Source Code ───────────────────────────────────
# .dockerignore handles excluding WORK/, logs/, venv/, etc.
COPY . .

# Professional Final Pass: Fix endings and permissions
RUN find /app/scripts -name "*.sh" -exec dos2unix {} + && \
    chmod +x /app/scripts/entrypoint.sh

# ── 6. Configure Runtime ──────────────────────────────────────────────
ENTRYPOINT ["/bin/bash", "/app/scripts/entrypoint.sh"]
CMD ["python", "run/supervisor.py"]
