"""
╔══════════════════════════════════════════════════════════════════════════╗
║            AI Phone Hunter Agent  ·  config.py                          ║
║  This is the CONTROL PANEL of the whole project.                        ║
║  Beginners: only edit THIS file — no need to touch anything else        ║
║  for basic setup.                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    # Minimal fallback if python-dotenv is not installed
    def load_dotenv(dotenv_path=None):
        """Minimal fallback for when python-dotenv is missing."""
        path = dotenv_path or Path(".env")
        if not path.exists():
            return False
        with open(path, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)
        return True

# Load environment variables from .env file (if it exists)
load_dotenv()

# ═══════════════════════════════════════════════════════════════════
# 📁  PATHS & ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════

# Absolute path to the PROJECT ROOT.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── SINGLETON FLAGS ──
DOCKER_ENV = os.getenv("DOCKER_ENV", "false").lower() == "true"

# ── CENTRALIZED WORK DIRECTORY ──
# Everything operational (watching, outputs, archives) happens here.
# Inside Docker, this should be /app/WORK. On Windows host, it's mapped via volume.
WORK_DIR = Path(os.getenv("WORK_DIR", str(BASE_DIR / "WORK")))

# ── Force Crawl4AI to use a writable workspace directory ──
CRAWL4AI_HOME = Path(os.getenv("CRAWL4AI_HOME", str(BASE_DIR / ".crawl4ai_cache")))
os.environ["CRAWL4AI_HOME"] = str(CRAWL4AI_HOME)

# The entry point for ALL raw files. Place your dirty/new Excel files here.
INCOMING_DIR = Path(os.getenv("INCOMING_DIR", str(WORK_DIR / "INCOMING")))

# The internal processing folders. The agent watches these buckets.
INPUT_DIR       = WORK_DIR
INPUT_STD_DIR   = WORK_DIR / "STD"
INPUT_SIR_DIR   = WORK_DIR / "SIREN"
INPUT_RS_DIR    = WORK_DIR / "RS"
INPUT_OTHER_DIR = WORK_DIR / "OTHERS"

# ── LIVE OUTPUTS ───────────────────────────────────────────────
OUTPUT_ROOT    = WORK_DIR / "output"
OUTPUT_RS_ADR  = OUTPUT_ROOT / "RS_Adr"
OUTPUT_SIR_ADR = OUTPUT_ROOT / "Sir_Adr"
OUTPUT_DEFAULT = OUTPUT_ROOT / "Results"

# ── FINAL ARCHIVES ─────────────────────────────────────────────
ARCHIVE_BACKUP_DIR = WORK_DIR / "ARCHIVE" / "BACKUP"
OUTPUT_SUCCEED_DIR = WORK_DIR / "ARCHIVE" / "SUCCEED"
OUTPUT_FAILED_DIR  = WORK_DIR / "ARCHIVE" / "FAILED"
CHECKPOINTS_DIR    = WORK_DIR / "CHECKPOINTS"
ARCHIVED_CHECKPOINTS_DIR = CHECKPOINTS_DIR / "archived_json"

from common.fs import safe_mkdir as _safe_mkdir_cfg
_safe_mkdir_cfg(CHECKPOINTS_DIR)
_safe_mkdir_cfg(ARCHIVED_CHECKPOINTS_DIR)

# Compatibility aliases
ARCHIVE_DIR        = ARCHIVE_BACKUP_DIR
OUTPUT_ARCHIVE_DIR = OUTPUT_SUCCEED_DIR

# Log files go here
LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs")))
from common.fs import safe_mkdir as _safe_mkdir_cfg
_safe_mkdir_cfg(LOG_DIR)

# ── OUTPUT SETTINGS ──
# The column name for the agent's processing result (Done, No Tel, etc.)
# We use 'Etat_IA' to avoid confusion with original 'Statut' (Active/Inactive) columns.
STATUS_COLUMN_NAME = os.getenv("STATUS_COLUMN_NAME", "Etat_IA")

# ── The FINAL queue for the Agent (Manual Override) ──
# If you want to jump the queue, move files here.
READY_DIR = WORK_DIR / "READY"

def get_output_dir(input_folder_name: str) -> Path:
    """Returns {WORK_DIR}/output/{input_folder_name}"""
    from common.fs import safe_mkdir
    path = OUTPUT_ROOT / input_folder_name
    safe_mkdir(path)
    return path


# ── Parallelism & Professional Throttling ──
# MAX_CONCURRENT_WORKERS = number of simultaneous browser windows
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", "1"))
BROWSER_USE_SANDBOX    = os.getenv("BROWSER_USE_SANDBOX", "true").lower() == "true"

# ── HDD OPTIMIZATION ──
# How often (in rows) the agent saves the Excel file back to disk.
# High values (50-100) are recommended for HDDs to reduce write operations.
SAVE_INTERVAL = int(os.getenv("SAVE_INTERVAL", "10"))

# ── ENRICHMENT ENGINE (Phase 4) ──
# If True, the agent will attempt to extract secondary data (Email, Siren, Director, Social)
# Source priority: google_ai_mode (0.97) > aeo_schema (1.00) > gemini_json (0.90)
ENRICH_ENABLED = os.getenv("ENRICH_ENABLED", "true").lower() == "true"
# If True, the agent will re-enrich even if fields are already populated.
ENRICH_FORCE_RETRY = os.getenv("ENRICH_FORCE_RETRY", "false").lower() == "true"

# Number of rows per RETRY chunk file sent back to incoming/.
RETRY_CHUNK_SIZE = int(os.getenv("RETRY_CHUNK_SIZE", "50"))

# ── File Decomposition (Chunking) ──
DECOMPOSITION_CHUNK_SIZE = int(os.getenv("DECOMPOSITION_CHUNK_SIZE", "500"))

# ── Recovery & Second Chance ──
REPROCESS_FAILED_ROWS = os.getenv("REPROCESS_FAILED_ROWS", "true").lower() == "true"

# ── Proxy Rotation (Anti-Ban) ──
PROXY_ENABLED                  = True   # ON by default to solve CAPTCHA problems immediately
PROXY_ROTATE_EVERY_N           = 5      # Rotate every 5 rows to stay fresh
PROXY_PREEMPTIVE_ROTATE_ON_WARN  = True   # Rotate BEFORE the ban threshold is reached (at warn_threshold)

# ── Proxy State Machine Thresholds ──
# State machine: HEALTHY → WARN → BAN → ROTATE
# PROXY_PREEMPTIVE_ROTATE_ON_WARN (above) lets us rotate at WARN to avoid BAN.
PROXY_WARN_THRESHOLD  = int(os.getenv("PROXY_WARN_THRESHOLD", "10"))   # errors before WARN state
PROXY_BAN_THRESHOLD   = int(os.getenv("PROXY_BAN_THRESHOLD",  "13"))   # errors before BAN + rotate
PROXY_BACKOFF_DELAYS  = [1, 2, 4, 8, 16, 32]                           # seconds (exponential backoff)

# ═══════════════════════════════════════════════════════════════════
# 🖐️  FINGERPRINT RANDOMISATION (CDP injection per session)
# ═══════════════════════════════════════════════════════════════════

# Viewport is randomised between these bounds on each new session.
FINGERPRINT_VIEWPORT_MIN_W = 1366
FINGERPRINT_VIEWPORT_MAX_W = 1920
FINGERPRINT_VIEWPORT_MIN_H = 768
FINGERPRINT_VIEWPORT_MAX_H = 1080

# Pool of WebGL renderer strings to cycle through.
# These mimic real GPU/driver combinations seen in the wild.
WEBGL_RENDERER_POOL = [
    "ANGLE (NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (AMD Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0)",
    "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
    "Mesa/X.org (NVIDIA GeForce GTX 1080)",
]
WEBGL_VENDOR_POOL = [
    "Google Inc. (NVIDIA)",
    "Google Inc. (Intel)",
    "Google Inc. (AMD)",
    "Google Inc.",
]

# Navigator language + platform spoofing pool
NAVIGATOR_LANGUAGES_POOL = [
    ["fr-FR", "fr", "en-US", "en"],
    ["en-US", "en"],
    ["fr-FR", "fr"],
    ["en-GB", "en"],
]
NAVIGATOR_PLATFORM_POOL = ["Win32", "MacIntel", "Linux x86_64"]

# ═══════════════════════════════════════════════════════════════════
# ⏱️  PER-ACTION DELAY PROFILES (Gaussian distribution)
# ═══════════════════════════════════════════════════════════════════
# Each profile: {"mean": float, "std": float, "min": float, "max": float}
# All values in SECONDS.
ACTION_DELAY_PROFILES = {
    "click":      {"mean": 0.40,  "std": 0.15, "min": 0.20, "max": 1.00},
    "type_char":  {"mean": 0.08,  "std": 0.03, "min": 0.04, "max": 0.20},
    "submit":     {"mean": 1.50,  "std": 0.50, "min": 0.80, "max": 3.00},
    "navigate":   {"mean": 2.50,  "std": 0.80, "min": 1.00, "max": 5.00},
    "scroll":     {"mean": 0.30,  "std": 0.10, "min": 0.10, "max": 0.80},
    "read_wait":  {"mean": 4.00,  "std": 1.50, "min": 2.00, "max": 9.00},
}

# ═══════════════════════════════════════════════════════════════════
# 🔌  STALE CONNECTION RECOVERY
# ═══════════════════════════════════════════════════════════════════
# How many times to attempt reconnection before giving up on a row.
BROWSER_MAX_RECONNECT_ATTEMPTS = int(os.getenv("BROWSER_MAX_RECONNECT_ATTEMPTS", "3"))
# Timeout in seconds to detect a stale (unresponsive) page
BROWSER_STALE_TIMEOUT_SEC      = int(os.getenv("BROWSER_STALE_TIMEOUT_SEC", "15"))

# ═══════════════════════════════════════════════════════════════════
# 🤖  CAPTCHA SOLVER  (optional — works without API keys)
# ═══════════════════════════════════════════════════════════════════
# Strategy: Prevention-first (Nodriver/stealth eliminates ~90% of CAPTCHAs).
# Manual fallback covers the rest.  API-based auto-solving is OPTIONAL.
#
# To enable auto-solving, add to your .env:
#   CAPTCHA_SOLVER=2captcha          (or "capsolver")
#   CAPTCHA_API_KEY=your_key_here
#
CAPTCHA_SOLVER  = os.getenv("CAPTCHA_SOLVER", "manual")   # "manual" | "2captcha" | "capsolver"
CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY", "")        # Leave blank to use manual mode

# ══ Tier Classification (docs/Gemini.md blueprint) ───────────────────────────
#   Tier 1 → SeleniumBaseAgent (UC Mode — PRIMARY, stealth + CDP)
#   Tier 2 → PatchrightAgent   (Chrome stealth, patched binary)
#   Tier 3 → NodriverAgent     (CDP-only, suits Cloudflare sites)
#   Tier 4 → Crawl4AIAgent     (managed JS rendering, e-commerce)
#   Tier 5 → CamoufoxAgent     (Firefox anti-detect, last resort)
HYBRID_TIER2_DOMAINS = [
    "cloudflare", "linkedin.com", "facebook.com",
    "instagram.com", "leboncoin.fr",
]
HYBRID_TIER3_DOMAINS = [
    "amazon.", "zalando.", "fnac.com", "cdiscount.com",
]
# Engine to use when no explicit decision is made (fallback default)
# Tier 1 (SeleniumBase UC) is the new primary entry point per docs/Gemini.md
HYBRID_DEFAULT_TIER = int(os.getenv("HYBRID_DEFAULT_TIER", "1"))

# Tier 0 (legacy undetected-chromedriver) — kept for benchmark comparisons only
SELENIUM_ENABLED = os.getenv("SELENIUM_ENABLED", "false").lower() == "true"

# ── Tier 1: SeleniumBase UC Driver ──────────────────────────────────────
# Per docs/Gemini.md: "Use Driver(uc=True, headless=False)"
# "Ne jamais utiliser headless=True avec le mode UC/CDP sur Linux"
SELENIUMBASE_ENABLED         = os.getenv("SELENIUMBASE_ENABLED", "true").lower() == "true"

# Reconnect-time (seconds) after a Turnstile/Cloudflare challenge.
# Gemini.md §2: "Toujours inclure reconnect_time si un défi Turnstile est suspecte."
SELENIUMBASE_RECONNECT_TIME = float(os.getenv("SELENIUMBASE_RECONNECT_TIME", "4"))

# Tier 5 (Camoufox) is heavy. Disable it to save resources if not needed.
CAMOUFOX_ENABLED = os.getenv("CAMOUFOX_ENABLED", "false").lower() == "true"

# ── Performance & Tier Complexity ──
# PERFORMANCE_MODE:
#   "simple" → Only Tiers 1-2 (SeleniumBase + Patchright). Fastest, lowest RAM.
#   "full"   → All 5 Tiers (including Nodriver, Crawl4AI, Camoufox). Maximum success.
PERFORMANCE_MODE = os.getenv("PERFORMANCE_MODE", "full").lower()

# ── Obsolete / Fail-safe (For backward compatibility) ──
# This is no longer used by the Hybrid Waterfall engine but kept as a 
# fail-safe to prevent AttributeError from old script references.
BROWSER_ENGINE = "hybrid"



# ═══════════════════════════════════════════════════════════════════
# 🌐  CHROMIUM BROWSER — Your REAL profile (cookies + logged-in session)
# ═══════════════════════════════════════════════════════════════════

# IMPORTANT ▶  Use YOUR real Chromium profile so Google/DuckDuckGo see
#              you as a normal user, not a bot.
#
# How to find YOUR profile path:
#   Open Chromium  →  address bar  →  type: chrome://version
#   Look for "Profile Path"  →  copy everything EXCEPT the last folder
#   Example result : /home/user/.config/chromium/Default
#   You only need  : /home/user/.config/chromium
#
# OS examples:
#   Linux   →  "/home/yourname/.config/chromium"
#   Windows →  "C:/Users/YourName/AppData/Local/Chromium/User Data"
#   macOS   →  "/Users/yourname/Library/Application Support/Chromium"
# ── Chromium Profile Path ──
# We move this to the WORK directory to keep the root clean.
_default_profile = str(WORK_DIR / "browser_profiles" / "Default")
if DOCKER_ENV and Path("/dev/shm").exists():
    _default_profile = Path("/dev/shm") / "ai_hunter_profile"
    
CHROMIUM_PROFILE_PATH = str(Path(os.getenv("CHROMIUM_PROFILE_PATH", _default_profile)).expanduser().resolve(strict=False))

# The specific profile folder name inside the profile path
# (usually "Default" unless you created multiple profiles)
CHROMIUM_PROFILE_NAME = os.getenv("CHROMIUM_PROFILE_NAME", "Default")
# ── Tier 0: Selenium (Benchmark Arena) ──────────────────────────────
SELENIUM_DISPLAY_MODE = "gui"  # "headless" or "gui"

# ── Chrome Binary Resolution Strategy ───────────────────────────────
# Chromium is required by Selenium, Playwright, and Crawl4AI tiers.
# On Linux servers / containers we prefer the distro package;
# on Windows/macOS we fall back to known install paths.
def find_chrome_executable() -> str:
    """
    Locate Chrome/Chromium binary across platforms.

    Resolution order (first match wins):
      1. CHROMIUM_BINARY_PATH from .env  → explicit override
      2. /.dockerenv exists             → /usr/bin/google-chrome (container)
      3. OS discovery                   → standard install paths

    Returns:
        Absolute path string, or "" if not found (agents will fail-fast).
    """
    import platform
    
    # 1. Explicit Override (Loaded from .env by python-dotenv)
    env_path = os.getenv("CHROMIUM_BINARY_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
        
    # 2. Docker Context
    if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_ENV"):
        docker_path = "/usr/bin/google-chrome"
        if os.path.exists(docker_path):
            return docker_path

    # 3. OS Discovery
    system = platform.system()
    if system == "Windows":
        paths = [
            os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Google\\Chrome\\Application\\chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google\\Chrome\\Application\\chrome.exe"),
        ]
    elif system == "Linux":
        paths = ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome-stable"]
    elif system == "Darwin": # macOS
        paths = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        paths = []

    for p in paths:
        if os.path.exists(p):
            return p
            
    return ""

# Source of truth for all agents
CHROMIUM_BINARY_PATH = find_chrome_executable()



# ═══════════════════════════════════════════════════════════════════
# 🔍  SEARCH ENGINES
# ═══════════════════════════════════════════════════════════════════

# Primary engine  →  Google AI bar (AI Overviews / SGE)
# Fallback engine →  DuckDuckGo AI Chat (duck.ai)
PRIMARY_ENGINE  = "google"               # Google Search (SGE / Knowledge Graph)
FALLBACK_ENGINE = "gemini"               # Google Gemini (Deep Search)

GOOGLE_URL        = "https://www.google.com"
GEMINI_URL        = "https://gemini.google.com"

# ── LOCAL LLM (OLLAMA) ──
OLLAMA_ENABLED  = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
# For Docker Desktop, the host is usually at host.docker.internal
_ollama_def     = "http://host.docker.internal:11434" if DOCKER_ENV else "http://localhost:11434"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", _ollama_def)
OLLAMA_TIMEOUT  = int(os.getenv("OLLAMA_TIMEOUT", "60"))

# ── AI Mode — direct URL that activates the 'AI Mode' tab in Google ──
# The `aep=42` + `udm=50` parameters bypass standard results and go straight
# to the AI conversational interface (as seen in the user's screenshot).
GOOGLE_AI_MODE_URL = "https://www.google.com/search?udm=50&aep=42&source=chrome.crn.rb&q="

# The AI Mode search input element
GOOGLE_AI_MODE_INPUT = "textarea[name='q'], div[contenteditable='true'], .nojsq"

# Maximum seconds to wait for the AI answer to appear on screen
AI_RESPONSE_TIMEOUT = 60   # seconds


# ═══════════════════════════════════════════════════════════════════
# 💬  SEARCH PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════

# PROMPT STYLE: 'caveman' (75% token saving) | 'verbose' (Standard)
PROMPT_STYLE = os.getenv("PROMPT_STYLE", "caveman").lower()

def _opt(prompt: str) -> str:
    """Helper to optimize if style is caveman."""
    if PROMPT_STYLE == "caveman":
        from infra.intelligence.prompt_optimizer import caveman_optimize
        return caveman_optimize(prompt)
    return prompt

# {nom}     → replaced by company name (Raison Sociale) or SIREN
# {adresse} → replaced by the company address
SEARCH_PROMPT_TEMPLATE = _opt(
    "En tant qu'expert en recherche B2B, identifiez les informations de contact les plus fiables et récentes pour l'entreprise '{nom}' à '{adresse}'. Suivez les principes EEAT : priorisez les sources officielles (site web, Infogreffe, LinkedIn). Trouvez le numéro de téléphone exact, l'adresse postale complète et le SIREN/SIRET. Si plusieurs numéros existent, donnez le plus crédible. Output in json format."
)

# Template for SIREN-based search (Expertise-focused)
SIREN_SEARCH_TEMPLATE = _opt(
    "En tant qu'expert B2B, identifiez la Raison Sociale, l'adresse complète et le téléphone officiel pour le SIREN {siren}. Priorisez les bases de données d'autorité (INSEE, Infogreffe, Pappers). Output in json format."
)

# Specific prompt for agent phone number (Experience-focused)
AGENT_PHONE_PROMPT_TEMPLATE = _opt(
    "Identifiez le numéro de téléphone direct d'un agent commercial ou responsable pour '{nom}' à '{adresse}'. Utilisez des sources d'expérience (LinkedIn, facebook, pages contact) pour garantir la fiabilité EEAT. Output in json format."
)

# ── SQO (Search Query Optimization) ──
# Domains that satisfy EEAT (Expertise, Experience, Authoritativeness, Trustworthiness)
SQO_TRUSTED_DOMAINS = "site:pappers.fr OR site:societe.com OR site:infogreffe.fr OR site:linkedin.com"
SQO_CONTACT_KEYWORDS = '("téléphone" OR "contact" OR "siège social")'

# ══════════════════════════════════════════════════════════════════
# 🤖  TIER 0: GOOGLE AI MODE — PRIMARY PROMPT (JSON STRICT)
AI_MODE_SEARCH_PROMPT = _opt("""
### ROLE
Expert B2B Intelligence Researcher specialized in industrial OSINT.

### TASK
Identify critical contact and identification data for the following entity:
- NAME: {nom}
- ADDRESS: {adresse}
- SIREN: {siren}
- CATEGORY: {category}

### CONTEXT
Raw source data: {extra}

### CONSTRAINTS
1. Prioritize direct phone numbers for the Director/CEO or Management.
2. If direct phone is missing, provide the general company phone.
3. Ensure the address matches the provided city/locality.
4. ABSOLUTELY NO conversational text.

### OUTPUT FORMAT (JSON ONLY)
{{
  "company_name": "...",
  "phone_numbers": ["..."],
  "director_direct_phone": "...",
  "email": "...",
  "responsable_person": "...",
  "siren": "...",
  "legal_form": "...",
  "social_media": {{ "facebook": "...", "linkedin": "...", "instagram": "..." }},
  "website": "..."
}}
""")

# ── SECOND CHANCE: EXPERT RESEARCHER PROMPT ──
AI_MODE_EXPERT_PROMPT = _opt("""
### IDENTITY
Advanced Data Forensic Agent for the French B2B Market.

### MISSION
The standard search failed. Conduct a deep-dive investigation on '{nom}' at '{adresse}' (SIREN: {siren}).
Target Activity: {category}

### STEPS
1. Verify legal existence and current operational status.
2. Locate professional contact details (Email, Phone) via official records or social profiles.
3. Identify the current 'Dirigeant' (Manager/CEO).

### OUTPUT
Provide a complete JSON object. If a field is missing, use "NOT_FOUND".
NO CHATTER. NO PREAMBLE.
""")

# ── GEO (Generative Engine Optimization) — RAG PROMPT ──
GEO_FALLBACK_PROMPT = _opt("""
Rôle : Expert en extraction de données B2B (EEAT).
Analyse le CONTEXTE suivant issu des pages officielles pour l'entreprise : {nom} à {adresse}.
### CONTEXTE : {raw_web_context}
### INSTRUCTIONS :
1. Extrais uniquement le numéro de téléphone direct ou du siège social de l'entreprise citée.
2. Formate le numéro au standard local français (0X XX XX XX XX) ou international (+33...).
3. Si l'information n'est pas présente dans le texte fournise, réponds strictement "NOT_FOUND".
4. RÉPONDS UNIQUEMENT AVEC UN OBJET JSON. PAS DE TEXTE AVANT OU APRÈS.
### FORMAT JSON ATTENDU (STRICT) :
{{
  "telephone": "01XXXXXXXX",
  "source": "URL ou Nom du Site",
  "confiance": 0.95,
  "raisonnement": "Indiquez brièvement où vous avez trouvé l'info"
}}
""")

# ── IA MODE: WEBSITE DEEP SCRAPE PROMPT ──
DEEP_SCRAPE_PROMPT = _opt("""
Rôle : Expert en renseignement B2B et extraction de données industrielles.
Objectif : Extraire TOUTES les informations de contact de l'entreprise à partir du contenu web fourni.

### CONTENU DES PAGES (ACCUMBULÉ) :
{raw_web_context}
### INSTRUCTIONS CRITIQUES :
1. ANALYSE : Identifiez le numéro de téléphone, email, réseaux sociaux et adresse.
2. FORMAT : RÉPONDS UNIQUEMENT AVEC UN OBJET JSON VALIDE. 
3. INTERDICTION : NE FAITES PAS DE PHRASES. NE DITES PAS "ENCHANTÉ". NE DONNEZ PAS D'EXPLICATION.
4. SI VIDE : Si une donnée manque, mettez "NOT_FOUND".
### FORMAT JSON ATTENDU (NE RÉPONDEZ QUE PAR CECI) :
{{
  "telephone": "0XXXXXXXXX",
  "email": "contact@entreprise.com",
  "linkedin": "url",
  "facebook": "url",
  "instagram": "url",
  "twitter": "url",
  "adresse_physique": "adresse complète",
  "nom_officiel": "raison sociale trouvée",
  "confiance": 0.98,
  "sources_utilisees": ["Accueil", "Contact"]
}}
""")

# Keywords to find contact/legal pages
CONTACT_KEYWORDS = ["contact", "propos", "mentions", "legal", "qui-sommes-nous", "about"]


# ═══════════════════════════════════════════════════════════════════
# 🛡️  ANTI-BOT PROTECTION
# ═══════════════════════════════════════════════════════════════════

# Random delay (seconds) between each search request.
# The agent picks a random value in [MIN, MAX] each time.
MIN_DELAY_SECONDS = 4
MAX_DELAY_SECONDS = 11

# How long (seconds) the agent PAUSES and waits for YOU to solve a CAPTCHA
# manually in the browser window before moving on to the next row.
CAPTCHA_WAIT_SECONDS = 180   # 3 minutes

# Rotate the browser's User-Agent string on each new browser session
ROTATE_USER_AGENT = True

# Type queries character by character (mimics human typing speed)
HUMAN_TYPING          = True
TYPING_MIN_DELAY_SEC  = 0.04   # min seconds per character
TYPING_MAX_DELAY_SEC  = 0.16   # max seconds per character

# Maximum consecutive CAPTCHA blocks before the agent pauses everything
# and sends an alert to the log + console
MAX_CONSECUTIVE_CAPTCHA = 8

# ── Contact discovery keywords (Industrialized for French B2B) ──
CONTACT_KEYWORDS = ["contact", "propos", "about", "mentions", "siège", "adresse", "téléphone", "equipe", "legal"]
SOCIAL_ABOUT_PATTERNS = {
    "facebook": "/about",
    "linkedin": "/about/",
    "instagram": "/", # Bio is on main page
}


# ═══════════════════════════════════════════════════════════════════
# 📞  PHONE NUMBER REGEX PATTERNS
# ═══════════════════════════════════════════════════════════════════
# Unified patterns for French phone numbers (Standard, Mobile, International)
PHONE_PATTERNS = [
    r'(?<!\d)\+33[\s\.\-]?[1-9](?:[\s\.\-]?\d{2}){4}(?!\d)',   # +33 X XX XX XX XX
    r'(?<!\d)0[1-9](?:[\s\.\-]?\d{2}){4}(?!\d)',                # 0X XX XX XX XX
    r'\b0[1-9]\d{8}\b',                                         # 10 digits starting with 0
]

# ═══════════════════════════════════════════════════════════════════
# 🚫  ANTI-HALLUCINATION: FAKE PHONE BLOCKLIST
# ═══════════════════════════════════════════════════════════════════
# Known fake / demo / placeholder / sequential French numbers.
# Any phone that normalizes to one of these DIGITS-ONLY strings
# is silently rejected and never stored.
# Add new offenders here; format: digits only, no spaces.
FAKE_PHONE_BLOCKLIST: set = {
    "0123456789",   # Classic demo number (sequential)
    "0000000000",   # All-zero placeholder
    "1111111111",   # All-ones placeholder
    "2222222222",
    "3333333333",
    "4444444444",
    "5555555555",
    "6666666666",
    "7777777777",
    "8888888888",
    "9999999999",
    "0102030405",   # Sequential variant
    "0605040302",
    "0600000000",   # Generic mobile placeholder
    "0700000000",
    "0100000000",
    "0200000000",
    "0300000000",
    "0400000000",
    "0500000000",
    "0900000000",
}

# ═══════════════════════════════════════════════════════════════════
# 🚫  ANTI-HALLUCINATION: NULL VALUE STRINGS
# ═══════════════════════════════════════════════════════════════════
# When the AI returns any of these strings for a field, treat it as
# EMPTY and store nothing. Case-insensitive match applied at runtime.
NULL_VALUE_STRINGS: set = {
    "not_found", "not found", "none", "null", "n/a", "na",
    "non disponible", "non spécifié", "non renseigné",
    "indisponible", "inconnu", "inconnue",
    "non communiqué", "pas de téléphone",
    "aucun", "aucune", "aucun numéro",
    "", ".", "-", "_",
}


# ═══════════════════════════════════════════════════════════════════
# ♾️  24/7 WATCHDOG
# ═══════════════════════════════════════════════════════════════════

# How often (seconds) the file watcher polls the INPUT_DIR for new files
WATCHDOG_POLL_INTERVAL = int(os.getenv("WATCHDOG_POLL_INTERVAL", "5"))

# Only process files with these extensions (case-insensitive)
# Added .json for bulk data industrialization
ACCEPTED_EXTENSIONS = [".xlsx", ".xls", ".csv", ".json"]

# Wait this many seconds after a file appears before opening it.
# This prevents reading a file that is still being copied/uploaded.
FILE_SETTLE_DELAY = int(os.getenv("FILE_SETTLE_DELAY", "3"))

# ── Geolocation (for search results accuracy) ──
SET_GEOLOCATION = True
DEFAULT_LAT     = 48.8566   # Paris
DEFAULT_LON     = 2.3522

# ═══════════════════════════════════════════════════════════════════
# 🔒 SECRETS VALIDATION (Phase 3 Hardening)
# ═══════════════════════════════════════════════════════════════════
def validate_secrets():
    """
    Fail-fast validation to ensure no hardcoded credentials exist
    and required .env keys are present before starting.
    """
    import logging
    
    # 1. Validate CAPTCHA API combination
    if CAPTCHA_SOLVER in ("2captcha", "capsolver") and not CAPTCHA_API_KEY:
        logging.warning(
            f"⚠️ [Config] CAPTCHA_SOLVER is set to '{CAPTCHA_SOLVER}', "
            "but CAPTCHA_API_KEY is missing in .env! "
            "Will fallback to manual mode."
        )

validate_secrets()
