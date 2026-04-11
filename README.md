# 🤖 AI Phone Hunter - B2B Data Enrichment Agent

Bienvenue dans **AI Phone Hunter**, un robot asynchrone haute performance automatisant la recherche et l'enrichissement de données d'entreprises via Google AI Mode et Intelligence Locale.

---

## 📂 Architecture Industrielle & Intelligence

Le projet est structuré pour maximiser le taux de succès, la vitesse et la résilience token.

### Phase 1: Le Pré-processeur (`pre_process.py`)
Ce script ("Watchdog") surveille `WORK/INCOMING/`, nettoie les données (exclusion des radiées) et ventile les leads dans les buckets stratégiques (`STD`, `RS`, `SIREN`).

### Phase 2 : L'Agent de Recherche (`main.py` -> `agents/`)
L'orchestrateur pilote des agents spécialisés pour l'extraction :
- **Phone Hunter (`agents/phone_hunter.py`)** : Gère le waterfall de recherche (AI Mode Expert -> Knowledge Panel -> Local RAG).
- **Enricher (`agents/enricher.py`)** : Consolidation multi-sources des données légales et de contact.

### Phase 3 : Intelligence Hybride & Moteur 4-Tiers
Architecture de pointe combinant IA Cloud (Gemini) et IA Locale (Ollama) :
- **Moteur Waterfall** : Tier 1 (Patchright) → Tier 2 (Nodriver) → Tier 3 (Crawl4AI) → Tier 4 (Camoufox).
- **Local RAG Fallback** : Utilise **Ollama (qwen2.5:3b)** pour extraire les téléphones en local si les méthodes standards échouent.
- **Caveman Efficiency** : Optimisation automatique des prompts pour réduire la consommation de tokens de **75%**.

---

## 🛠️ Installation et Configuration

### 1. Configuration Rapide
```bash
./scripts/setup_dev.sh
```

### 2. AST Knowledge Graph (Persistent)
Pour maintenir une compréhension profonde de la structure du code (AST) :
```bash
pip install code-review-graph
code-review-graph install --platform antigravity
code-review-graph build
```
> [!NOTE]
> Un hook git post-commit lance automatiquement `code-review-graph update`.

### 3. Fichier `.env`
Configurez vos préférences :
- `PROMPT_STYLE=caveman` : Active l'optimisation de tokens.
- `OLLAMA_ENABLED=true` : Active l'IA locale de secours.

---

## 🎮 Mode d'emploi
1. **Terminal 1** : `python pre_process.py`
2. **Terminal 2** : `python main.py`
3. **Monitoring** : Accédez à `api/app.py` pour l'état de santé du système.

---

## 🧰 Maintenance
- **Consolidation** : `python scripts/consolidate_results.py`
- **Nettoyage** : `python scripts/clean_chrome_profiles.py`
