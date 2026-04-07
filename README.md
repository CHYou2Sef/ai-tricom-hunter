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

### Phase 3 : Moteur Hybride & Anti-Détection (`hybrid_engine.py`)
Nouveauté majeure pour l'industrialisation B2B :
- **Moteur Multi-Tier** : Bascule automatique entre **Playwright** (T1 - Vitesse), **Nodriver** (T2 - furtivité CDP pure), et **Crawl4AI** (T3 - Scraper managé open-source) selon la protection du site cible (Cloudflare, etc.).
- **Fingerprinting CDP (10 points)** : Injection dynamique de WebGL, Canvas, et signatures Navigator avant le chargement des scripts de détection.
- **Machine à États de Proxy** : Système auto-réparateur `HEALTHY -> WARN -> BAN` avec backoff exponentiel.
- **Gestionnaire de CAPTCHA** : Arbre de décision intelligent (Turnstile / hCaptcha / reCAPTCHA) avec pause manuelle non-bloquante.

---

## 🛠️ Installation et Configuration

### 1. Prérequis
- Python 3.10+
- Navigateur Google Chrome (installé localement sur Linux, Windows ou Mac).

### 2. Installation
```bash
# 1. Installer les dépendances Python
pip install -r requirements.txt

# 2. Installer les nouveaux moteurs anti-détection
pip install nodriver crawl4ai
crawl4ai-setup  # Télécharge les binaires Chromium pour le moteur T3

# 3. Installer les binaires Playwright Chromium
playwright install chromium
```

### 3. Fichier de Configuration (`.env`)
Toutes les données sensibles et chemins systèmes sont à configurer ici :
- Copiez `.env.example` en un fichier `.env`.
- Configurez `CHROMIUM_PROFILE_PATH` avec le chemin de votre dossier local Chrome (pour bénéficier de votre session de confiance Google).

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
