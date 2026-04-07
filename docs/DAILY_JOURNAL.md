# 📅 Journal de Bord Quotidien (Daily Tracker)

Ce document trace l'historique complet de l'évolution du projet **AI Phone Hunter**, classé par date. Il permet de suivre les décisions architecturales, les nouvelles fonctionnalités et les corrections apportées au fil des jours.

---

## 07 Avril 2026 — Phase 9 : Stabilité Environnementale & Support IDE

### 🛠️ Système d'Auto-Correction & Résilience
- **Correction du `venv` Corrompu** : Identification et résolution d'un problème critique où le `pip` binaire était manquant dans l'environnement virtuel. Réinitialisation complète du `venv` (Python 3.14).
- **Support IDE (`pyrightconfig.json`)** : Création d'un fichier de configuration pour aider les serveurs de langage (LSPs comme Pyrefly/Pyright) à localiser les dépendances dans `./venv`. Résout définitivement les avertissements "Cannot find module" dans l'éditeur.
- **Fallbacks "Zero-Dependency"** :
  - **Fallback `dotenv`** : Implémentation d'un lecteur de `.env` en Python pur dans `config.py` pour garantir le chargement des variables d'environnement même sans la librairie `python-dotenv`.
  - **Fallback `watchdog` (Polling mode)** : Ajout d'une tâche de monitoring asynchrone par balayage (polling) dans `main.py`. Si `watchdog` est absent, l'agent bascule automatiquement sur ce mode pour continuer la surveillance 24/7 des fichiers.
- **Optimisation du Monitoring** : Refonte de `scan_existing_files` pour utiliser un set `global_seen` persistant, empêchant tout re-traitement accidentel des fichiers lors des cycles de scan récurrents.
- **Support OS (Fedora 43 / RPM Dependency)** : Documentation de la résolution des erreurs de compilation de `lxml` sur Python 3.14 via l'installation des headers natifs (`sudo dnf install libxml2-devel libxslt-devel python3-devel`).

---

## 06 Avril 2026 — Phase 8 : Industrialisation V4 & Support JSON (Finals)

### 🚀 AI Tricom Hunter Agent (V4 INDUSTRIAL)
- **Correction Critique `AttributeError`** : Suppression définitive de la dépendance à `BROWSER_ENGINE` au profit de l'architecture **Hybrid Waterfall**. Ajout d'une constante de secours (`Fail-safe`) dans `config.py` pour assurer la rétrocompatibilité des anciens scripts.
- **Résolution Dépendances (`ModuleNotFoundError`)** : Installation et configuration de `nodriver` et `crawl4ai` dans l'environnement de production.
- **Fix Permissions Cache** : Correction des droits d'accès aux répertoires de cache Chrome (`/tmp/nodriver_...`) empêchant le démarrage des workers en mode non-privilégié.
- **Support Natif JSON** : Le pipeline (Watcher -> Chunker -> Reader) accepte désormais les fichiers `.json` en entrée massive. Les fichiers JSON sont automatiquement décomposés en batchs gérables par l'agent.
- **Hardening du HybridEngine** : 
  - Amélioration de la traçabilité avec des icônes de statut (👷/🤖).
  - Gestion optimisée du cycle de vie des sessions Chrome pour éviter les fuites de ressources en 24/7.
  - Reset forcé du tier par défaut à chaque nouvelle requête pour éviter de rester bloqué sur un tier d'escalade.

### ⚠️ Bugs & Problèmes "Not Yet" (En cours de résolution)
- **Saturation Mémoire (RAM)** : La multiplication des instances `nodriver` consomme énormément de ressources. Nécessite l'implémentation d'un "Reaper" (gestionnaire de pool) pour redémarrer les navigateurs toutes les X heures.
- **Stabilité des Proxys Gratuits** : Le taux d'échec des proxys publics reste le goulot d'étranglement n°1 (escalade systématique vers Tier 2/3). Migration vers un provider payant recommandée.
- **Précision du Tier 0 (Expert Researcher)** : Risque d'hallucination légère du prompt IA si le contexte brut extrait par Playwright est trop fragmenté ou pollué par des blocs publicitaires non filtrés.
- **Dérive des Données Excel** : Cas marginaux de décalage de colonnes sur des fichiers sources avec cellules fusionnées ou headers exotiques.

---

## 06 Avril 2026 — Phase 7 : Nettoyage & Refonte Pré-Processing 

### 🧹 Nettoyage de l'Architecture Legacy (Obsolete Code Removal)
- **`browser/benchmark.py`** [SUPPRIMÉ] : Script obsolète conçu pour l'architecture mono-moteur (Playwright vs Selenium). La logique est désormais couverte par l'escalade intelligente du `HybridAutomationEngine` (Waterfall Strategy).
- **`browser/selenium_agent.py`** [SUPPRIMÉ] : Retrait définitif de Selenium. Jugé trop lent et trop facile à détecter par les WAF (Web Application Firewalls) de Google. Le scraping furtif moderne repose purement sur les CDP (Nodriver) et les navigateurs patchés (Playwright).
- **`config.py` & `requirements.txt`** : Suppression de la constante obsolète `BROWSER_ENGINE`, ainsi que de `selenium` et `webdriver-manager` des dépendances. Séparation claire achevée.

### 🧩 Refonte de la Logique de Décomposition (Pre-Processing)
- **Déplacement du `FileChunker`** : La logique de décomposition des très gros fichiers (>1000 lignes) a été physiquement retirée du thread principal (`main.py`) pour être greffée dans la Phase 1 (`pre_process.py`).
- **Avantage Architectural** : Les fichiers déposés dans `incoming/` sont dorénavant tronçonnés *avant* classification. L'agent de recherche (`main.py`) ne gère plus que les "bouchées" calibrées et qualifiées de son bucket, le rendant plus rapide et focus à 100% sur l'extraction IA. Le risque de boucle infinie (`infinite loop`) lors de la création de chunks a été totalement annihilé.
- **Sécurité `main.py`** : Maintien du filtre de sécurité dans les handlers Watchdog, assorti d'un renommage dynamique de `_part_` vers `_batch_` lors du tronçonnage afin d'éviter le blocage automatique des chunks sains.

---

## 06 Avril 2026 — Phase 6 : Architecture Anti-Détection (GEMINI.md – 6 Tasks)

### 🔐 Hybrid Automation Engine (Task 1)
- **`browser/hybrid_engine.py`** [NOUVEAU] : Orchestre trois niveaux de scraping selon le domaine cible.
  - **Tier 1 → PlaywrightAgent** : sites sans protection (Google, sites standards)
  - **Tier 2 → NodriverAgent** : sites Cloudflare/LinkedIn (CDP-only, zero WebDriver flag)
  - **Tier 3 → Crawl4AIAgent** : sites hardés Amazon/Fnac (moteur JS managé open-source)
  - Escalade automatique T1→T2→T3 en cas d'échec. Alerte CRITICAL si tous les tiers tombent.
  - `classify_url(url)` : routing automatique selon `config.HYBRID_TIER2_DOMAINS` / `HYBRID_TIER3_DOMAINS`
  - `get_engine_stats()` : métriques de succès + temps moyen par tier

### 🖐️ Fingerprint Randomisation CDP (Task 2)
- **`utils/anti_bot.py`** amélioré : Injection des 10 propriétés fingerprint via `add_init_script()` (Playwright) et `page.evaluate()` (Nodriver) **avant** tout JS de la page.
  - `get_fingerprint_bundle()` : génère un bundle unique par session (UA, viewport, WebGL renderer+vendor, canvas noise, navigator.languages/platform/plugins, hardwareConcurrency, deviceMemory)
  - `build_cdp_injection_script(bundle)` : convertit le bundle en JS d'injection CDP complet
  - `randomise_viewport()` : helper viewport seul (1366–1920 × 768–1080)
- **`browser/playwright_agent.py`** mis à jour : viewport aléatoire + fingerprint injecté à chaque `start()`

### 🔄 Proxy State Machine + Backoff (Task 3)
- **`utils/proxy_manager.py`** réécrit : machine à états complète.
  - HEALTHY → (≥10 erreurs) → WARN → (≥13 erreurs) → BAN → rotation → HEALTHY
  - Backoff exponentiel : 1s → 2s → 4s → 8s → 16s → 32s
  - `report_proxy_error(addr, status_code)`, `force_ban_proxy(addr)`, `get_proxy_stats()`
  - Thresholds configurables via `.env` (`PROXY_WARN_THRESHOLD`, `PROXY_BAN_THRESHOLD`)

### ⏱️ Per-Action Delay Matrix (Task 4)
- **`utils/anti_bot.py`** : `action_delay(action)` + `action_delay_async(action)` — délais Gaussian par type d'action :
  - `click` (mean=0.4s) | `type_char` (mean=0.08s) | `submit` (mean=1.5s)
  - `navigate` (mean=2.5s) | `scroll` (mean=0.3s) | `read_wait` (mean=4.0s)
- Profils stockés dans `config.ACTION_DELAY_PROFILES`, tous configurables

### 🤖 CAPTCHA Decision Tree — Prevention-First (Task 5)
- **`utils/captcha_solver.py`** [NOUVEAU] : Arbre de décision complet.
  - Détection par type : Turnstile → hCaptcha → reCAPTCHA v2 → manual
  - **Stratégie principale** : prévention (Nodriver supprime ~90% des CAPTCHAs)
  - **Fallback** : pause manuelle async (existante, toujours disponible)
  - **Stubs API** prêts : 2Captcha + Capsolver activables via `.env` (`CAPTCHA_SOLVER`, `CAPTCHA_API_KEY`)
  - Injection de token dans la page pour reCAPTCHA v2, hCaptcha, Turnstile

### 📊 Three-Tier Monitoring Alerts (Task 6)
- **`utils/logger.py`** amélioré : système d'alertes structurées `alert(level, message, context)`
  - `INFO` → log fichier seulement (rotation + proxy + session start)
  - `WARN` → log + bannière console jaune (403/429, CAPTCHA détecté, connexion stale)
  - `CRITICAL` → log + bloc console rouge (BAN streak, timeout CAPTCHA, tous tiers épuisés)
  - `stale_connection_alert(attempt, max_attempts)` : WARN sur 1ère tentative, CRITICAL sur la dernière

### 🕷️ Nodriver Agent — Stealth CDP (Tier 2)
- **`browser/nodriver_agent.py`** [NOUVEAU] : agent CDP-only zero WebDriver.
  - Fingerprint injecté à chaque session
  - Reconnexion stale connection avec backoff (config `BROWSER_MAX_RECONNECT_ATTEMPTS`)
  - Intégration complète pipeline CAPTCHA

### 🌐 Crawl4AI Agent — Open-Source Tier 3 (remplace Firecrawl)
- **`browser/crawl4ai_agent.py`** [NOUVEAU] : scraper async JS gratuit.
  - 3 tentatives avec backoff 5s→15s→30s sur rate-limit
  - `crawl_website()` : homepage + sous-pages contact (jusqu'à 3 pages)
  - Sortie Markdown propre pour extraction LLM

### ✅ Tests — 36/36 Passants
- **`tests/test_anti_detection.py`** [NOUVEAU] : suite de 36 tests unitaires.
  - `TestFingerprintBundle` (6) · `TestProxyStateMachine` (5) · `TestActionDelays` (7)
  - `TestCaptchaDetection` (7) · `TestAlertSystem` (5) · `TestHybridEngineClassification` (6)
  - Durée : 0.12s · Résultat : **36 passed ✅**

---

## 06 Avril 2026 - Phase 5 : Résilience Industrielle & Pipeline Anti-Saturation

- **Système de Logging Dual (Anti-Saturation)** : Implémentation de `utils/logger.py`. Séparation des flux : un log permanent léger (`agent.log`) pour les erreurs critiques et une archive tournante (`debug_archive.log`) de 50 Mo pour le debug complet. Évite le remplissage du disque sur les longs runs.
- **Décomposition Anti-Crash (`FileChunker`)** : Création de `utils/chunker.py`. Découpage automatique des fichiers massifs (>500 lignes) en mini-chunks CSV. Utilisation de fichiers sidecar `.meta.json` pour garantir une reprise atomique en cas de crash système (Progress tracking).
- **Simulations de Comportement Humain (Gaussian Delays)** : Intégration de délais aléatoires basés sur une distribution normale (Gaussienne) pour toutes les interactions de recherche et navigation, réduisant drastiquement le taux de détection par les WAF (Web Application Firewalls).
- **Nettoyage de Contexte (`TextCleaner`)** : Optimisation de `utils/text_cleaner.py` pour purifier le HTML extrait avant injection dans l'IA, supprimant les scripts, styles et métadonnées inutiles pour économiser les tokens et améliorer la précision.
- **Respect de la Hiérarchie BI** : Mise en conformité du pipeline avec les standards de Business Intelligence (Work/Backup/Archive).

---

## 03 Avril 2026 - Phase 4 : Architecture de Sortie & Stabilité Data

- **Correction des Décalages (Column Sliding)** : Réécriture complète de la logique d'écriture Excel dans `excel/writer.py`. Les colonnes s'alignent désormais via mapping par dictionnaire, éliminant définitivement les erreurs de double-nommage (conflits `Etat` / `Etat_IA`).
- **Mode Tier 0 "Expert Researcher"** : Implémentation d'une seconde tentative automatique en cas d'échec du premier scan IA. Un prompt spécifique, simulant un expert senior en B2B, est utilisé pour forcer l'extraction des coordonnées critiques (phones mobiles dirigeants, FB, etc.).
- **Suppression du Recyclage Infini (Loop RETRY)** : Refonte de `agent.py -> finalize_file_processing`. Le processus ne renvoie plus les fichiers "NO TEL" dans l'entrée. Le flux de travail devient purement linéaire de `input` -> `AI` -> vers les archives définitives.
- **Nouvelle Structure Ouptut** :
  - `output/Archived_Results/` (Lignes enrichies avec succès)
  - `output/Archived_Failed/` (Lignes sans numéro ou sautées)
- **Nettoyage JSON & Maintenance** : Migration vers un stockage 100% Excel Fusionné avec expansion automatique des en-têtes. Nettoyage des bugs de concurrence dans le `main_async` et `pre_process`.
- **Logiciel de Reconstruction** : Opitalisation de `scripts/rebuild_output.py` pour synchroniser avec le standard `Etat`.

---

RQ :

- log saturatiion file -> alert (log ken les erreurs)
- decomposition des gors fichiers
- Respect architecture des fichier /BI/WORK/BACKUP/...
- ajouter close browser apres un delaiy aleatoir
- tous les delaiys du human intercation and search == ajouter une methode aleatoire
- !!! utiliser 2 methods : Webdrive package !!!
- reset modem (changer @ip) apres Captcha
- ***

---

---

### 🟢 2026-04-03 : Finalisation Industrielle & Documentation de Sortie

#### 🛡️ Anti-Ban : Système de Rotation de Proxy

- **`ProxyManager` (`utils/proxy_manager.py`)** : Nouveau moteur qui scrape et valide des proxys HTTP/HTTPS gratuits depuis des sources publiques (`proxyscrape.com`, `geonode.com`, GitHub).
- **Activation Dynamique** : Les proxys sont désactivés par défaut. Ils s'activent **uniquement** sur détection d'un bannissement IP (5 CAPTCHAs consécutifs).
- **Restart Invisible** : Redémarrage automatique du worker Playwright avec l'argument `--proxy-server` sans perte de progression.

#### 🛠️ Corrections Industrielles & Consolidation

- **Élimination des Doublons de Colonnes** : Le moteur d'écriture Excel filtre désormais les en-têtes pré-existants (évite les répétitions de "Etat" ou colonnes "AI\_").
- **Injection Immédiate (Tier 0)** : Les données structurées issues de l'IA Mode sont injectées directement dans les attributs de la ligne avant le passage des regex, garantissant un taux d'acceptation de 100% des infos qualifiées.
- **Moteur de Consommation JSON → Excel** : Création de `scripts/consolidate_results.py` pour compiler tous les fichiers d'audit partiels en un seul Master Excel de succès.

#### 📈 Métriques de Performance par Worker

- **Log d'identification par worker** : Chaque ligne de log préfixée par `[🔵 Worker-X]` indique quel navigateur Chrome traite quelle ligne.
- **Temps de traitement par ligne** : Chaque ligne terminée affiche `⏱ X.Xs` — le temps exact passé sur cette entreprise.
- **Source du succès** : Le tag `source=google_ai_mode` (ou `google_name`, etc.) dans les logs indique quelle méthode a trouvé le numéro.
- **Tableau de bord en temps réel** : Toutes les 10 lignes, un log `[📊 Progress]` affiche : `X/Y rows done │ ✅ Found: N (%)  │ ❌ No Tel: M`.

#### 📝 Documentation Premium

- **`PROJECT_REPORT.md`** : Création d'un rapport architectural complet retraçant l'évolution du projet du "Jour 0" à l'industrialisation. Idéal pour présentation finale.
- **Optimisation README.md** : Refonte totale pour un focus pur sur l'installation et l'utilisation industrielle (la partie rapport a été externalisée).

#### ⚠️ Points de vigilance, bugs potentiels et améliorations

- **Fiabilité des Proxys Gratuits** : Les serveurs gratuits sont instables ; envisager un fournisseur payant (Webshare/Bright Data) pour une production massive.
- **Fragilité UI Google** : Risque de changement de sélecteurs pour le bouton "Mode IA" ; prévoir une détection visuelle par capture d'écran.
- **Dédoublonnage Master SIREN** : Le script de consolidation ne dédoublonne pas par SIREN si le lead est présent dans plusieurs fichiers sources.
- **Différenciation Tel/Fax** : Heuristiques à renforcer pour éviter la capture accidentelle de numéros de Fax sans labels clairs.
- **Nettoyage Automatique des Profils** : Les dossiers de cache Chrome gonflent avec le temps ; prévoir une purge hebdomadaire.
- **Résolution Automatisée de CAPTCHA** : Intégrer un service tiers (2Captcha) pour les blocages persistants inaccessibles par proxy.
- **Support des Formats CSV "Exotiques"** : Problème : Certains fichiers CSV utilisent des encodages bizarres (UTF-16, MacRoman). Risque : Erreur de lecture lors du scan initial.

---

### 🟢 2026-04-02 : Industrialisation Complète — Async, IA Mode & Post-Processing

#### 🔧 Architecture & Concurrence

- **Moteur Asynchrone (Asyncio + Playwright)** : Migration totale de `ThreadPoolExecutor` vers `asyncio`. Résolution définitive de l'erreur `Cannot switch to a different thread`. Utilisation d'un `asyncio.Semaphore` pour la concurrence.
- **Parallélisme Réel (Multi-Browser Pool)** : Implémentation d'un pool de navigateurs dans `agent.py` (`init_agent_pool`, `close_agent_pool`). Chaque worker possède son propre profil Chrome isolé (`profile_worker_X`), permettant à plusieurs fenêtres de travailler en simultané.
- **Correction `NameError` (`Path`)** : Ajout du `from pathlib import Path` manquant dans `playwright_agent.py` qui empêchait le démarrage.

#### 🤖 Stratégie de Recherche (Refonte Majeure)

- **⭐ Tier 0 — Google AI Mode (Méthode Principale)** : `search_google_ai_mode()` navigue directement vers `google.com/search?aep=42&udm=50&q=...`. L'agent envoie un prompt structuré (Nom + Adresse + "JSON format, phones priority"), attend la réponse streaming, l'extrait et la parse en une seule action — exactement ce que l'utilisateur fait manuellement.
- **Parser JSON Multi-Stratégie** : `parse_ai_mode_json()` (3 stratégies : code-block, accolades brutes, regex ligne par ligne) + `_fill_row_from_ai_mode()` remplit téléphone, email, SIREN, SIRET, LinkedIn, site web, adresse en un seul passage.
- **Prompt JSON Strict (`AI_MODE_SEARCH_PROMPT`)** : Ajouté dans `config.py`. Ordres explicites : pas de texte, pas de phrases, uniquement un objet JSON valide.
- **Anciens Tiers conservés en Fallback** : Knowledge Panel (Tier 1), Google Search (Tier 2), GEO Gemini RAG (Tier 3), Website DeepScrape (Tier 6) gardés en commentaire pour référence et utilisés uniquement si l'AI Mode échoue.

#### 🌐 Website Deep Scrape (Nouveau)

- **`crawl_website(url)`** : Visite la page d'accueil + jusqu'à 2 sous-pages contact/mentions-légales. Collecte le texte de chaque page.
- **`ignore_https_errors=True`** : Le navigateur accepte désormais les sites HTTP non-sécurisés des entreprises.
- **`DEEP_SCRAPE_PROMPT` + `CONTACT_KEYWORDS`** : Ajoutés dans `config.py` pour le crawl guidé des sites officiels.

#### 🛠️ Qualité & Robustesse

- **Nettoyeur de bruit (`utils/text_cleaner.py`)** : `clean_html_to_text()` supprime les `<script>`, `<style>` et balises HTML avant d'envoyer le contexte à Gemini. Élimine le problème des "blocs JavaScript" envoyés à l'IA.
- **Prompts Gemini ultra-stricts** : `DEEP_SCRAPE_PROMPT` et `GEO_FALLBACK_PROMPT` mis à jour avec interdiction explicite de phrases, réponse JSON uniquement.
- **Checkpoint saving** : Sauvegarde des résultats toutes les 10 lignes (au lieu de chaque ligne) pour optimiser les performances sans risquer de perdre les données.

#### 📁 Post-Processing & Fichiers

- **`finalize_file_processing()`** : Après 100% des lignes traitées, split automatique : lignes "DONE" → `output/Archived_Results/`, lignes "NO TEL" → fichier `RETRY_` dans le dossier source, fichier original supprimé.
- **Correction doublon colonne "Etat"** : Si le fichier source contient déjà une colonne "Etat", la colonne générée par l'agent est renommée `Etat_IA` pour éviter la duplication.
- **Smart Resume** : Au redémarrage, l'agent lit le `_AUDIT.json` existant et saute automatiquement les lignes déjà traitées (DONE, NO TEL, SKIP).

#### 🐛 Corrections Critiques (Fin de Journée)

- **Clic "Mode IA" après chaque recherche** : Ajout de `_click_ai_mode_tab()` appelée systématiquement après chaque `_navigate_and_search()`. L'agent détecte et clique le bouton "Mode IA" visible dans la barre Google (7 sélecteurs robustes : français + anglais).
- **Désactivation Gemini Deep Scrape** : Les tiers 3 et 6 (envoi de HTML brut dans le chatbox Gemini) sont désactivés. Ils causaient l'injection de code JavaScript de schema.org dans le prompt Gemini. Ils sont conservés en commentaire pour réactivation ultérieure.
- **`search_google_ai` retourne du texte pur** : Remplacement de `page.content()` (HTML brut) par `page.inner_text("body")` pour ne retourner que le texte visible, éliminant le bruit HTML dans les regex de numéro.

### 🟢 2026-04-01 : Optimisation de la Résilience (Système "Incassable") & Crawling Direct

- **Résumabilité Native (Auto-Sync)** : Implémentation du moteur `sync_with_previous_results` dans `agent.py`. L'agent détecte désormais automatiquement les fichiers `_AUDIT.json` partiels et reprend exactement là où il s'est arrêté, sans perte de données ni requêtes doublées.
- **Tier 5 : Website Phone Crawler** : Ajout d'une nouvelle couche d'extraction. Si Google ne fournit pas le numéro dans ses résultats (Knowledge Panel ou extraits), l'agent se rend désormais **directement sur le site officiel** de l'entreprise pour scanner le HTML (headers/footers/balises `tel:`). Boost massif du taux de succès.
- **Correction Critique "NO TEL" (Manual Stop)** : Résolution du bug dans `writer.py` qui remplissait l'Excel de "NO TEL" lors d'une interruption manuelle. Les lignes non traitées sont maintenant correctement marquées comme **"Pending"**, permettant une reprise propre.
- **Gestion Transparente des Cookies Google** : Ajout d'un handler de consentement aux cookies dans les agents Playwright et Selenium. Plus de blocage visuel lors de la première recherche, garantissant une fluidité maximale dès le lancement.
- **Filtrage Intelligent du Bruit Web** : Correction du moteur de détection de site web pour ignorer les URLs parasites (schema.org, Google Tag Manager, etc.), redirigeant l'agent vers les véritables portails d'entreprise.
- **Refonte des Prompts RAG (JSON Strict)** : Durcissement des instructions Gemini pour forcer des retours JSON atomiques et éviter les réponses marketing ("Bonjour, ravi de vous aider..."), accélérant le parsing logique.
- **Optimisation de la Navigation** : Réduction des délais d'attente codés en dur (`time.sleep`) au profit de détections d'états de page, rendant le robot jusqu'à 30% plus rapide sur les gros volumes.

### 🟢 2026-03-31 : Implémentation du Tier 0 (Knowledge Panel) & Industrialisation du Pipeline

- **Extraction "Zero-Click" (Tier 0)** : Intégration de la stratégie **GEMINI.md** comme première tentative de recherche. L'agent extrait désormais le numéro de téléphone directement depuis le **Google Knowledge Panel** via trois méthodes de repli (Sélecteurs CSS `data-dtype`, scans d'aria-labels, et Regex sur le panneau latéral `#rhs`).
- **Initialisation Optimisée du Browser** : Le navigateur est désormais lancé **une seule fois** au démarrage de `main.py` et réutilisé pour tous les fichiers. Gain de performance majeur et réduction drastique de la charge CPU.
- **Géolocalisation & Tracking** : Ajout du support de la géolocalisation native (Paris, France par défaut) dans les agents Selenium et Playwright pour accroître la précision des résultats de recherche locaux.
- **Traitement par Priorité Stricte** : Refonte de la file d'attente de `main.py` pour traiter les dossiers dans l'ordre suivant : **`std_input`** (complet) → **`RS_input`** (nom seul) → reste des dossiers.
- **Data Augmentation (Enrichissement Réseaux Sociaux)** : Ajout de nouveaux extracteurs pour capturer automatiquement les URL **LinkedIn, Facebook, Instagram, et Twitter/X**.
- **Deep Enrichment Systématique** : La fonction `enrich_row` est désormais exécutée pour **chaque ligne**, y compris celles déjà marquées "DONE" (téléphone existant), afin de combler les données manquantes (emails, social links).
- **Expansion des Alias de Colonnes** : Ajout de nouveaux alias flexibles dans `cleaner.py` (ex: "Nom commercial", "Adresse du siège", "RS", "ADR") pour une détection automatique des headers encore plus robuste.
- **Fusion des Résultats par Date** : Refonte de `excel/writer.py` pour fusionner automatiquement les résultats traités le même jour dans des fichiers consolidés par bucket (`Extraction_{folder}_{date}.xlsx`), facilitant l'intégration en base de données.
- **Nettoyage Automatique de l'Espace de Travail** : Implémentation d'une fonction de nettoyage dans `main.py` qui supprime les dossiers temporaires de traitement à la fermeture de l'agent, ne laissant que les dossiers `incoming` et `archived`.

### 🟢 2026-03-28 : Refonte Sécurité (GEMINI.md) et Lancement du Data Enrichment Layer

- **Optimisation de la Stratégie de Recherche (Tiered Search)** : L'agent priorise désormais la recherche par **Nom + Adresse** pour maximiser les chances de trouver un numéro "humain". En cas d'échec, il bascule automatiquement sur une recherche par **SIREN** avant de solliciter l'analyse RAG Gemini.
- **Audit Logging Avancé** : Chaque étape de recherche est tracée indépendamment dans le `_AUDIT.json`.
- **Correction Critique ("Doublons de numéros")** : Fixation du moteur d'extraction de téléphone pour supprimer les faux positifs (comme les dates ou codes postaux 10 chiffres). Les regex sont désormais bornées et sécurisées.
- **Mise à jour du Writer Excel** : Le module `excel/writer.py` génère désormais dynamiquement les colonnes additionnelles (`AI_EMAIL`, `AI_NAF`, etc.) uniquement si des données ont été trouvées.
- **Sécurité renforcée (.env)** : Migration totale vers `.env` pour supprimer les chemins statiques (Chromium profile etc.).
- **Standards Qualité (Max 50 Lignes)** : Refactoring selon SOLID et GEMINI.md des moteurs `agent.py` et browser agents pour une modularité maximale.

### 🟢 2026-03-27 : Optimisation de l'Extraction & Refonte EEAT

- **Amélioration de l'extraction des données** : L'agent ne dépend plus uniquement des réponses générées par les modèles LLM souvent instables pour détecter les téléphones. Il effectue désormais un scan complet du code source HTML de la page de recherche Google.
- **Ajout du parsing natif** : Le module `phone_extractor.py` utilise maintenant des expressions régulières pour cibler directement les ancres expertes `<a href="tel:...">` et les balises `schema.org/telephone`, offrant un taux de réussite quasi parfait.
- **Suppression des LLM superflus pour la recherche de numéros** : Si un numéro est affiché sur la page Google standard, l'agent l'extrait immédiatement sans lancer de requêtes coûteuses à DuckDuckGo ou Gemini.
- **Conformité EEAT** : Refonte totale des différents prompts (`config.py`) pour les recherches avancées. L'IA a désormais l'instruction de privilégier l'Expertise, l'Expérience, l'Autorité, et la Fiabilité (ex: Infogreffe, LinkedIn, INSEE, Pappers).
- **Implémentation SQO (Search Query Optimization)** : Automatisation des Google Dorks dans `agent.py`. Les requêtes sont désormais ciblées sur des domaines de confiance (`site:pappers.fr`, etc.) pour éliminer les annuaires vides.
- **Activation AEO (Answer Engine Optimization)** : Extraction systématique des données structurées JSON-LD (Schema.org) via Playwright/Selenium pour une récupération "Zero-Click" des numéros de téléphone.
- **Intégration GEO (Generative Engine Optimization)** : Utilisation de Gemini comme extracteur logique RAG. L'IA analyse le contexte texte brut des pages pour garantir l'exactitude des données collectées.
- **Détection Dynamique des Titres Excel** : Création d'un parser `find_header_row` basé sur un score de mots-clés (`siren`, `nom`, etc.) garantissant de sauter les entêtes parasites des exports de BDD, couplé à un nettoyage des sauts de ligne `\n` sur les noms de colonnes.
- **Filtrage des Radiées et SIREN Padding** : Gain de requêtes et de temps en éliminant les entités radiées directement lors du parsing et en formatant dynamiquement le SIREN à 9 chiffres.
- **Roadmap SEO/AEO/GEO** : Définition d'une stratégie d'optimisation de recherche pour améliorer la précision des résultats futurs.

---

### 🟢 2026-03-26 : Automatisation du Pipeline en 2 Étapes

- **Architecture Industrielle** : Abandon final des Jupyter Notebooks, jugés trop instables, et passage à une architecture divisée en 2 scripts autonomes (`pre_process.py` et `main.py`).
- **Pré-processeur Excel** : Mise en place du module de tri et de nettoyage pour détecter et ranger les fichiers entrants dans 4 sous-catégories spécifiques selon les données présentes (SIREN, RS, Adresse).
- **Local Chrome Profile** : Configuration de Playwright pour qu'il s'interface avec un véritable profil Google Chrome existant de l'utilisateur. Chute drastique des blocages "Anti-Bot".

---

### 🟢 2026-03-25 : Preuve de Concept (PoC) Initiale

- Création du premier robot en Python pour automatiser le traitement.
- Test d'un environnement associant le navigateur Brave à DuckDuckGo AI (Chat/Ask mode).
- Première sauvegarde des données de retour sous format JSON structuré.

---

### 🟢 2026-03-22 : Correction Documentaire (LaTeX)

- Révision de `scrum.tex` et modification de la configuration de `.latexmkrc` pour résoudre des boucles de compilation.

---

### 🟢 2026-03-16 : Sécurisation de la Configuration Agent

- **Sécurité et .env** : Supression définitive des token API "en dur" (comme `INSEE_TOKEN`) pour les remiser dans des fichiers d'environnement `.env`.
- **Passage en Script** : Transformation du notebook problématique `Agent_tricom.ipynb` vers un script robuste `agent_tricom_fixed.py`.
- Finalisation de l'installation des dépendances bloquantes : `ipywidgets` et le package `Scrapling`.

---

### 🟢 2026-03-15 : Initialisation Dev & Environnement

- Mise en place du fichier `.env.dev` contenant les paramètres centraux pour le développement.
- Stabilisation de la "Dev Environment".

---

### 🟢 2026-03-13 : Résolution de Conflits & Tests

- Réparations des erreurs d'import modules et stabilisation de la stack Python pour permettre à l'agent de collecter ses premières données locales en tout sécurité.

---

### 🟢 2026-03-09 : DevOps & Architecture Graphique

- Création des pipelines de **CI/CD** avec l'implémentation de la compilation continue via **GitHub Actions**.
- Génération d'infographies architecturales permettant d'illustrer chaque couche (Scraping, AI, Parsing) des futures présentations.
- Nettoyage du fichier `Report_PFE.tex` et corrections d'erreurs dues aux paquets manquants (`amsthm.sty`, `algorithm2e`, Babel `french`).
