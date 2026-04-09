# 🤖 AI Phone Hunter - B2B Data Enrichment Agent

Bienvenue dans **AI Phone Hunter**, un robot asynchrone haute performance automatisant la recherche et l'enrichissement de données d'entreprises (Téléphones, SIREN, Emails, Dirigeants) via Google AI Mode.

## 🚀 Documentation de Référence

- 👉 **[Rapport Architectural & Historique Complet (PROJECT_REPORT.md)](docs/PROJECT_REPORT.md)** *(Lecture recommandée pour l'examen)*
- 👉 **[Journal de Bord Quotidien (DAILY_JOURNAL.md)](docs/DAILY_JOURNAL.md)**
- 👉 **[Architecture d'Enrichissement des Données](docs/ENRICHMENT_ARCHITECTURE.md)**

---

## 📂 Architecture Industrielle en 2 Étapes

Le projet est divisé en deux phases distinctes pour maximiser le taux de succès et la vitesse de traitement.

### Phase 1 : Le Pré-processeur (`pre_process.py`)
Ce script ("Watchdog") surveille en continu le dossier `input/incoming/`.
- **Support CSV & Excel** : Détection automatique des formats et délimiteurs (virgule, point-virgule, etc.).
- **Nettoyage Dynamique** : Exclusion automatique des entreprises marquées comme "Radiées".
- **Classification** : Ventile les leads selon leur richesse initiale de données (`std_input`, `RS_input`, `sir_input`).

### Phase 2 : L'Agent IA Asynchrone (`main.py`)
Ce script traite les listes triées en utilisant un pool de navigateurs parallèles (Multi-Worker).

- **Google AI Expert Mode (Tier 0)** : Technologie "Double Check". Si le premier scan échoue, un expert virtuel prend le relais avec une stratégie de recherche agressive pour capturer les détails cachés (LinkedIn, CEOS, etc.).
- **Immunité au Décalage (Atomic Mapping)** : Les colonnes Excel sont bindées par clé unique, empêchant tout glissement de données, même sur des fichiers fusionnés.

### Phase 3 : Moteur Hybride 4-Tiers & Anti-Détection (`hybrid_engine.py`)
Architecture de pointe pour l'industrialisation B2B :
- **Moteur Multi-Tier (Waterfall)** : Bascule automatique en cascade pour maximiser le succès :
  - **Tier 1 : Patchright** (Chromium patché, furtivité native, 100% stable).
  - **Tier 2 : Nodriver** (CDP-only, zéro signal WebDriver, idéal Google/LinkedIn).
  - **Tier 3 : Crawl4AI** (Scraper managé pour sites E-commerce complexes).
  - **Tier 4 : Camoufox** (Firefox Anti-Detect, empreinte Gecko radicalement différente, ultime recours).
- **Adaptive Circuit Breaker** : Système intelligent détectant les bans IP globaux pour stopper les requêtes et déclencher une pause de 300s + rotation de proxy.
- **Fingerprinting CDP & Gecko** : Injection de signatures hardware et logiciel uniques à chaque session.
- **Gestionnaire de CAPTCHA Actif** : Intégration API (2Captcha/Capsolver) pour une résolution 100% autonome.

---

## 🛠️ Installation et Configuration

### 1. Prérequis
- Python 3.10+
- Google Chrome & Firefox installés localement.

### 2. Installation
```bash
# 1. Installer les dépendances Python
pip install -r requirements.txt

# 2. Installer les moteurs anti-détection & binaires
patchright install chromium
python -m camoufox fetch
crawl4ai-setup
```

### 3. Fichier de Configuration (`.env`)
Configurez vos clés et chemins dans `.env` :
- `HYBRID_DEFAULT_TIER=1` (Recommandé pour Patchright)
- `CAPTCHA_API_KEY=...` (Pour le mode autonome)
- `CHROMIUM_PROFILE_PATH=...` (Votre profil Chrome habituel)

---

## 🎮 Mode d'emploi (Terminal)

### Terminal 1 : Gestionnaire de Fichiers (Watcher)
```bash
python pre_process.py
```
> *Déposez vos fichiers sources (Excel ou CSV) dans le dossier `input/incoming/`.*

### Terminal 2 : Intelligence Artificielle (Runner)
```bash
python main.py
```
> *Le robot prend le relais, enrichit les données en parallèle (3 fenêtres par défaut) et archive les fichiers une fois "DONE".*

---

## 🧰 Maintenance & Utilitaires

### Consolidation Master Excel
Pour regrouper tous vos succès ("DONE") dans un seul méga-fichier dédoublonné (par SIREN) :
```bash
python scripts/consolidate_results.py
```

### Nettoyage des Profils Chrome
Les profils de navigation stockent beaucoup de cache avec le temps. Pour libérer de l'espace disque sans perdre vos cookies de session vitaux :
```bash
python scripts/clean_chrome_profiles.py
```
