# ╔════════════════════════════════════════════════════════════════╗
# ║  Dockerfile - AI Phone Hunter (Industrial 4-Pillar Build)      ║
# ║  Base: Python 3.10 slim, Node.js 20, Xvfb (Virtual Display)    ║
# ╚════════════════════════════════════════════════════════════════╝

FROM python:3.10-slim-bookworm

# ── 1. Install System Dependencies & Headless Display (Xvfb) ──────────
# Xvfb provides a "fake" monitor. This consumes almost zero CPU/RAM,
# but it tricks anti-bot systems into thinking a real monitor exists,
# allowing patchright/nodriver to run in "headed" mode invisibly.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    xvfb \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    fonts-liberation \
    wget \
    ca-certificates \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libxshmfence1 \
    libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

# ── 2. (Removed Node.js - Native Python Validation is used) ────────────

# ── 3. Install 'uv' (Fast Python Package Manager - Pillar 1) ──────────
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Set up working directory
WORKDIR /app

# ── 4. Install Python Dependencies ────────────────────────────────────
# Copy requirements first to leverage Docker Layer Caching
COPY requirements-prod.txt .
RUN uv pip install --system -r requirements-prod.txt

# ── 5. Install Stealth Browsers ───────────────────────────────────────
# Patchright requires custom Chromium binaries
RUN patchright install chromium

# SeleniumBase Tier 1 requires chromedriver (UC Mode)
# We use the built-in installer to ensure version compatibility
RUN seleniumbase install chromedriver

# ── 6. Copy Application Source Code ───────────────────────────────────
# We copy everything, preserving the folder structure (src/, run/, scripts/, etc.)
COPY . .

# Professional Final Pass: Ensure all shell scripts have Linux LF endings
# and fix permissions for Windows-to-Linux transfers.
RUN find /app/scripts -name "*.sh" -exec sed -i 's/\r$//' {} + && \
    chmod +x /app/scripts/entrypoint.sh

# ── 7. Configure Environment ──────────────────────────────────────────
# Set PYTHONPATH so 'import agents' works from /app/src
ENV PYTHONPATH="/app/src"
# Force Python to unbuffer logs for real-time visibility in Docker logs
ENV PYTHONUNBUFFERED=1

# ── 8. Configure Container Startup ────────────────────────────────────
# The entrypoint launches Xvfb and validates the agent
ENTRYPOINT ["/bin/bash", "/app/scripts/entrypoint.sh"]

# Default command: Start the autonomous worker
CMD ["python", "run/worker.py"]
