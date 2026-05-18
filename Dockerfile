# ╔═══════════════════════════════════════════════════════════════════════╗
# ║  Dockerfile — AI Phone Hunter (v1.1.0-golden)                         ║
# ║  Base  : Python 3.10-slim-bookworm · Multi-Stage · UV package manager ║
# ║  Path  : Tier2-SeleniumBase ► Tier5-Nodriver ► Tier4-Cloak ► Tier6-  ║
# ║          Crawl4AI  +  Scrapy Sniper  +  LangGraph 3-Layer             ║
# ║  Target: < 2 GB final image · Windows HDD-host compatible             ║
# ║  Observability: Prometheus/Grafana via --profile monitoring (dev only) ║
# ╚═══════════════════════════════════════════════════════════════════════╝

# ── STAGE 1: BUILDER ─────────────────────────────────────────────────────
FROM python:3.10-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    # Tell pip/uv not to write .pyc in the build layer
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── System build deps (curl for UV, git for some pip sdists) ──────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential libssl-dev ca-certificates binutils \
    && rm -rf /var/lib/apt/lists/*

# ── Pre-create writable browser cache dirs to avoid CI/CD COPY failures ──
RUN mkdir -p \
    /root/.cache/cloakbrowser \
    /root/.cloakbrowser \
    /root/.seleniumbase \
    /root/.cache/seleniumbase && \
    touch \
    /root/.cache/cloakbrowser/.keep \
    /root/.cloakbrowser/.keep \
    /root/.seleniumbase/.keep \
    /root/.cache/seleniumbase/.keep

# ── Install UV & Python dependencies (Golden Path only) ───────────────────
# Uses requirements-prod-golden.txt which excludes:
#   Botasaurus (Tier 3 - not in full-mode waterfall)
#   Firecrawl  (Tier 8 - FIRECRAWL_ENABLED=false)
#   Crawlee    (Tier 10 - CRAWLEE_ENABLED=false)
#   undetected-chromedriver (Tier 0 - SELENIUM_ENABLED=false)
COPY requirements-prod-golden.txt .
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv pip install --system --no-cache -r requirements-prod-golden.txt

# ── Install browsers for the 4 ACTIVE Golden Path tiers ───────────────────
# Tier 2 (SeleniumBase): needs chromedriver managed by seleniumbase
# Tier 4 (CloakBrowser): needs its own C++-patched Chromium binary
# Tier 5 (Nodriver):     uses existing Chromium via CDP — no extra install
# Tier 6 (Crawl4AI):     uses patchright Chromium (installed below)
#
# NOTE: patchright installs to /opt/ms-playwright — shared by Crawl4AI.
#       crawl4ai-setup configures the crawl4ai environment beyond the browser.
#       We do NOT install Camoufox (Firefox) — CAMOUFOX_ENABLED=false.
RUN patchright install chromium \
    && python3 -m cloakbrowser install \
    && crawl4ai-setup \
    && seleniumbase install chromedriver \
    && seleniumbase install uc_driver

# ── BROWSER BINARY PRUNING ────────────────────────────────────────────────
RUN \
    # 1. Remove unused browser engines (Firefox / WebKit / zip archives)
    rm -rf /opt/ms-playwright/firefox-* \
           /opt/ms-playwright/webkit-* \
           /opt/ms-playwright/zips && \
    # 2. Keep only EN + FR locales to slim locale packs
    find /opt/ms-playwright -name "locales" -type d \
        -exec sh -c 'cd "{}" && ls | grep -v -E "en-US|en-GB|fr" | xargs rm -f' \; \
        || true && \
    find /root/.cloakbrowser -name "locales" -type d \
        -exec sh -c 'cd "{}" && ls | grep -v -E "en-US|en-GB|fr" | xargs rm -f' \; \
        || true && \
    find /root/.cache/cloakbrowser -name "locales" -type d \
        -exec sh -c 'cd "{}" && ls | grep -v -E "en-US|en-GB|fr" | xargs rm -f' \; \
        || true && \
    # 3. Remove debug symbols and DRM stub (unneeded in our scraping context)
    find /opt/ms-playwright -name "*.debug" -delete && \
    find /opt/ms-playwright -name "WidevineCdm" -type d -exec rm -rf {} + \
        2>/dev/null || true && \
    find /root/.cache/cloakbrowser -name "*.debug" -delete && \
    find /root/.cloakbrowser -name "*.debug" -delete

# ── PYTHON PACKAGE PRUNING ────────────────────────────────────────────────
RUN \
    SITE=/usr/local/lib/python3.10/site-packages && \
    # 1. Remove internal test suites (saves ~150 MB)
    find "$SITE" -name "tests"    -type d -exec rm -rf {} + 2>/dev/null || true && \
    find "$SITE" -name "test"     -type d -exec rm -rf {} + 2>/dev/null || true && \
    find "$SITE" -name "examples" -type d -exec rm -rf {} + 2>/dev/null || true && \
    # 2. Remove bytecode caches and stub files
    find "$SITE" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true && \
    find "$SITE" -name "*.pyi" -delete 2>/dev/null || true && \
    # 3. Strip debug symbols from C-extensions.
    #    IMPORTANT: Exclude packages with PyInit_ or internal symbol requirements.
    #    numpy / pandas / lxml / cryptography / aiohttp all have critical .so symbols.
    #    Wheel-bundled BLAS/LAPACK live under *.libs/ (e.g. numpy.libs/libscipy_openblas*.so).
    #    strip breaks their ELF LOAD segments → "page-aligned" ImportError and a misleading
    #    numpy "source directory" message from numpy.__config__ re-raise logic.
    find "$SITE" -name "*.so" \
        ! -path "*/numpy/*" \
        ! -path "*/numpy.libs/*" \
        ! -path "*/pandas/*" \
        ! -path "*/pandas.libs/*" \
        ! -path "*/scipy.libs/*" \
        ! -path "*/lxml/*" \
        ! -path "*/cryptography/*" \
        ! -path "*/aiohttp/*" \
        ! -path "*/pydantic/*" \
        ! -path "*/grpc/*" \
        -exec strip --strip-unneeded {} + 2>/dev/null || true

# Guarantee existence of browser dirs before COPY in runtime stage
RUN mkdir -p \
    /root/.cache/cloakbrowser \
    /root/.cloakbrowser \
    /root/.seleniumbase \
    /root/.cache/seleniumbase

# ── STAGE 2: RUNTIME (Clean Room) ────────────────────────────────────────
FROM python:3.10-slim-bookworm

# NOTE: PYTHONPATH is intentionally NOT set here.
# Setting PYTHONPATH=/app/src caused numpy C-extension import failures:
# Python resolved /app/src BEFORE site-packages, triggering the
# "do not import from source directory" error.
# Path management is handled by bootstrap.py using sys.path.append() semantics.
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    DOCKER_ENV=true \
    NETWORK_SPEED_MULTIPLIER=1.0

WORKDIR /app

# ── Runtime system libraries only ─────────────────────────────────────────
# Chromium requires all of these on Linux; xvfb provides virtual display for
# SeleniumBase UC mode which cannot run fully headless on some WAF-protected sites.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    ca-certificates \
    dos2unix \
    # Chromium / Patchright / CloakBrowser shared libs
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    fonts-liberation \
    libxshmfence1 libglu1-mesa \
    # Patchright/Playwright Chromium (chrome-linux64) needs Cairo/Pango stack
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libdbus-1-3 \
    && apt-get autoremove -y && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    # Remove documentation and locale bloat from base image
    && rm -rf /usr/share/doc /usr/share/man /usr/share/locale

# ── Copy pruned artefacts from builder ───────────────────────────────────
COPY --from=builder /usr/local/lib/python3.10/site-packages \
                    /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin                /usr/local/bin
COPY --from=builder /opt/ms-playwright            /opt/ms-playwright
COPY --from=builder /root/.cache/cloakbrowser     /root/.cache/cloakbrowser
COPY --from=builder /root/.cloakbrowser           /root/.cloakbrowser
COPY --from=builder /root/.seleniumbase           /root/.seleniumbase
COPY --from=builder /root/.cache/seleniumbase     /root/.cache/seleniumbase

# ── Symlink patchright Chromium to /usr/bin (used by SeleniumBase / Scrapy) ─
# Playwright ships chrome under chrome-linux64/ (new) or chrome-linux/ (legacy).
RUN CHROMIUM_BIN=$(find /opt/ms-playwright -name "chrome" \( \
        -path "*/chrome-linux64/chrome" -o -path "*/chrome-linux/chrome" \) \
        -type f 2>/dev/null | head -n 1) && \
    if [ -n "$CHROMIUM_BIN" ]; then \
        ln -sf "$CHROMIUM_BIN" /usr/bin/google-chrome && \
        ln -sf /usr/bin/google-chrome /usr/bin/google-chrome-stable || true; \
    fi

# ── Copy application source (filtered by .dockerignore) ──────────────────
COPY . .

# ── Final clean-up: remove dev-only directories & fix permissions ─────────
RUN rm -rf \
        /app/tests \
        /app/docs \
        /app/k8s \
        /app/.github \
        /app/.agents \
        /app/.claude \
        /app/scratch && \
    find /app/scripts -name "*.sh" -exec dos2unix {} + && \
    chmod +x /app/scripts/entrypoint.sh

ENTRYPOINT ["/bin/bash", "/app/scripts/entrypoint.sh"]
CMD ["python", "run/supervisor.py"]
