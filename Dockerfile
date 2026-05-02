# ╔════════════════════════════════════════════════════════════════╗
# ║  Dockerfile - AI Phone Hunter (Industrial 4-Pillar Build)      ║
# ║  Base: Python 3.10 slim, Node.js 20, Xvfb (Virtual Display)    ║
# ╚════════════════════════════════════════════════════════════════╝

FROM python:3.10-slim-bookworm

# ── 1. Install System Dependencies, Chrome & Xvfb ──────────
# We combine these into a single RUN command so we can purge wget and gnupg
# in the exact same layer, preventing them from bloating the final image size.
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
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && apt-get purge -y wget gnupg \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── 2. (Removed Node.js - Native Python Validation is used) ────────────

WORKDIR /app

# ── 3. Install Python Dependencies with Ephemeral 'uv' ────────────────
# Copy requirements first to leverage Docker Layer Caching.
# We download uv, use it to install packages, and immediately delete it.
COPY requirements-prod.txt .
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv pip install --system -r requirements-prod.txt \
    && rm -rf /root/.local/bin/uv /root/.cache/uv

# ── 5. Install Stealth Browsers ───────────────────────────────────────
# Patchright requires custom Chromium binaries
RUN patchright install chromium

# SeleniumBase Tier 1 requires chromedriver (UC Mode)
# We use the built-in installer to ensure version compatibility
RUN seleniumbase install chromedriver \
    && rm -rf /root/.cache/seleniumbase

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

# Default command: Start the 3-Layer Autonomous Supervisor
CMD ["python", "run/supervisor.py"]
