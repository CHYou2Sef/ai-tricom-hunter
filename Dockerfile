# ╔══════════════════════════════════════════════════════════════════╗
# ║  Dockerfile - AI Phone Hunter (ULTRA-SLIM INDUSTRIAL OPTIMIZATION)║
# ║  Base: Python 3.10 slim, Multi-Stage, Binary & Python Pruning     ║
# ║  Target: < 2.0GB Final Image Size                                 ║
# ╚══════════════════════════════════════════════════════════════════╝

# ── STAGE 1: BUILDER (The Kitchen) ────────────────────────────────────
FROM python:3.10-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app

# Install build-time essentials + binutils (for strip)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential libssl-dev ca-certificates binutils \
    && rm -rf /var/lib/apt/lists/*

# Install UV & Python Dependencies
COPY requirements-prod.txt .
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv pip install --system --no-cache -r requirements-prod.txt

# Install & Prune Browsers
# We install exactly what's needed for our 10-tier waterfall.
RUN patchright install chromium && \
    python3 -m cloakbrowser install && \
    crawl4ai-setup && \
    # seleniumbase drivers (minimal footprint)
    seleniumbase install chromedriver && \
    # ── AGGRESSIVE BINARY PRUNING ──
    # 1. Remove non-Chromium browser engines (Saves ~600MB)
    rm -rf /opt/ms-playwright/firefox-* && \
    rm -rf /opt/ms-playwright/webkit-* && \
    rm -rf /opt/ms-playwright/zips && \
    # 2. Prune redundant locales (Keeping only English and French)
    find /opt/ms-playwright -name "locales" -type d -exec sh -c 'cd "{}" && ls | grep -v -E "en-US|en-GB|fr" | xargs rm -f' \; || true && \
    find /root/.cache/cloakbrowser -name "locales" -type d -exec sh -c 'cd "{}" && ls | grep -v -E "en-US|en-GB|fr" | xargs rm -f' \; || true && \
    # 3. Strip debug symbols and remove unnecessary large components
    find /opt/ms-playwright -name "*.debug" -delete && \
    find /opt/ms-playwright -name "WidevineCdm" -type d -exec rm -rf {} + && \
    find /root/.cache/cloakbrowser -name "*.debug" -delete && \
    # ── AGGRESSIVE PYTHON PRUNING ──
    # Remove tests, docs, and caches from site-packages (Saves ~200MB)
    find /usr/local/lib/python3.10/site-packages -name "tests" -type d -exec rm -rf {} + && \
    find /usr/local/lib/python3.10/site-packages -name "test" -type d -exec rm -rf {} + && \
    find /usr/local/lib/python3.10/site-packages -name "examples" -type d -exec rm -rf {} + && \
    find /usr/local/lib/python3.10/site-packages -name "__pycache__" -type d -exec rm -rf {} + && \
    find /usr/local/lib/python3.10/site-packages -name "*.pyi" -delete && \
    # Strip .so files to remove debug symbols from compiled extensions
    find /usr/local/lib/python3.10/site-packages -name "*.so" -exec strip --strip-unneeded {} + || true

# ── STAGE 2: RUNTIME (The Clean Room) ─────────────────────────────────
FROM python:3.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/src" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    DOCKER_ENV=true

WORKDIR /app

# Install ONLY runtime system dependencies
# CRITICAL: We DO NOT install google-chrome-stable here to save ~350MB.
# We will symlink the Patchright/CloakBrowser binary to /usr/bin/google-chrome.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb ca-certificates dos2unix \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 fonts-liberation libxshmfence1 libglu1-mesa \
    && apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy pruned binaries and site-packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /opt/ms-playwright /opt/ms-playwright
COPY --from=builder /root/.cache/cloakbrowser /root/.cache/cloakbrowser
COPY --from=builder /root/.cache/seleniumbase /root/.cache/seleniumbase

# Symlink our optimized browser to standard locations
# This ensures Tiers 1-3 (SeleniumBase, Botasaurus) find a browser.
RUN CHROMIUM_BIN=$(find /opt/ms-playwright -name "chrome" -path "*/chrome-linux/chrome" | head -n 1) && \
    if [ -n "$CHROMIUM_BIN" ]; then ln -s "$CHROMIUM_BIN" /usr/bin/google-chrome; fi && \
    ln -s /usr/bin/google-chrome /usr/bin/google-chrome-stable || true

# Copy application source (filtered by .dockerignore)
COPY . .

# Final touch: remove source bloat and fix permissions
RUN rm -rf /app/tests /app/docs /app/k8s /app/.github /app/.agents && \
    find /app/scripts -name "*.sh" -exec dos2unix {} + && \
    chmod +x /app/scripts/entrypoint.sh

ENTRYPOINT ["/bin/bash", "/app/scripts/entrypoint.sh"]
CMD ["python", "run/supervisor.py"]
