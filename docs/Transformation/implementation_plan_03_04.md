# Plan d'Implémentation : Architecture Distribuée V2 (Scalabilité & Haute Disponibilité)

Ce document décrit le plan stratégique, sécurisé et robuste pour transformer l'agent **AI Phone Hunter** d'un script asynchrone local vers un **système distribué cloud-native de grade entreprise**.

## Objectif Principal
Supporter la scalabilité horizontale (traiter des millions de lignes avec N workers) tout en garantissant la disponibilité (zéro perte de données) et la maintenabilité à long terme.

---

## 1. Vue d'Ensemble de la Nouvelle Architecture (Event-Driven)

### Composants V2
1. **API Gateway / Ingestion (FastAPI)** : Remplace le `Watcher`. Reçoit les requêtes ou fichiers CSV via API sécurisée.
2. **Message Broker (Redis + Celery ou RabbitMQ)** : Remplace les files d'attente natives en mémoire (`asyncio.Queue`).
3. **Workers Node (Docker + Python)** : Conteneurs sans état (stateless) encapsulant exclusivement la logique métier (agent AI). Évolutifs dynamiquement (Auto-scaling).
4. **Browser Cluster (Browserless.io ou Selenium Grid)** : Externalisation du moteur Playwright.
5. **Base de Données (PostgreSQL)** : Remplace les fichiers finaux `.xlsx` et les dépendances I/O locales.
6. **Stockage Objets (AWS S3 ou MinIO)** : Pour l'archivage sécurisé des fichiers [_AUDIT.json](file:///home/youssef/ai_tricom_hunter/output/Extraction_std_input/Export_Portail_Data_Du_02-04-2026_2026-04-02_AUDIT.json) originaux.

---

## 2. Déroulement du Plan d'Implémentation

### Phase 1 : Conteneurisation Absolue (Dockerisation)
*Rendre le système "Agnostique de l'infrastructure"*
- [ ] Rédiger un `Dockerfile` optimisé (Multi-stage build) utilisant une image de base `python:3.10-slim`.
- [ ] Créer un `docker-compose.yml` pour le déploiement local facile (incluant les services pour Redis et DB).
- [ ] Isoler `playwright install chromium` dans l'étape de *build* Docker.

### Phase 2 : Migration de la Couche de Persistance
*Éliminer les risques de corruption de fichiers locaux*
- [ ] **Data Layer** : Implémenter SQLAlchemy (ou SQLModel) pour mapper les entités (Entreprises, Enregistrements enrichis, Tentatives, Statistiques).
- [ ] **Découplage** : Modifier [enrichment/row_enricher.py](file:///home/youssef/ai_tricom_hunter/enrichment/row_enricher.py) et l'agent pour écrire les résultats dans PostgreSQL au lieu d'un [list](file:///home/youssef/ai_tricom_hunter/scripts/clean_chrome_profiles.py#24-34) python gardé en mémoire pour [excel/writer.py](file:///home/youssef/ai_tricom_hunter/excel/writer.py).

### Phase 3 : Transition vers un Message Broker (Redis/Celery)
*Tolérance aux pannes et distribution de charge*
- [ ] Transformer [process_row](file:///home/youssef/ai_tricom_hunter/agent.py#180-267) en une tâche asynchrone `Celery` ("Worker task").
- [ ] Refonte de [pre_process.py](file:///home/youssef/ai_tricom_hunter/pre_process.py) (L'orchestrateur) : Lorsqu'un fichier est validé, il génère les "Tâches" en les poussant dans Redis plutôt que de lancer [main.py](file:///home/youssef/ai_tricom_hunter/main.py) directement.
- [ ] Implémenter le "Retry Algorithm" de Celery avec backoff exponentiel pour les pannes Google.

### Phase 4 : Externalisation du Navigateur & Proxys (Cloud)
*Économie massive de CPU et RAM sur les workers*
- [ ] Modifier l'initialisation de [PlaywrightAgent](file:///home/youssef/ai_tricom_hunter/browser/playwright_agent.py#73-671) pour gérer une connexion `.connect_over_cdp("wss://browserless.io/...")` au lieu d'un `.launch(...)` local.
- [ ] Migration vers un fournisseur de proxies rotatifs API Premium (Webshare, Bright Data) managé directement par le cluster Browserless.

### Phase 5 : CI/CD et Sécurité avec GitHub Actions
*Maintenabilité et déploiement continu sécurisé*
- [ ] Créer `.github/workflows/main.yml`.
- [ ] Implémenter les pipelines de Code Quality : Automations `Flake8` (lint), `Black` (format), et `Bandit` (Security static analysis).
- [ ] Construire les images Docker automatiques à chaque `PUSH` sur [main](file:///home/youssef/ai_tricom_hunter/scripts/clean_chrome_profiles.py#76-92) et les uploader sur Github Container Registry (GHCR).

---

## 3. Sécurité de cette V2

1. **Isolation des variables (Vault / Secrets)** : Les credentials (PostgreSQL, Redis, Provider Proxy, API Keys) ne transitent jamais via `.env` en production, mais par GitHub Secrets injectés au "run" du Docker.
2. **Workers "Stateless"** : Aucun Worker ne détient l'état du système. Si un worker Docker crash (ex: OOM, RAM dépassée), Celery / RabbitMQ réassignera immédiatement la ligne (le lead) à un autre worker. Zéro perte de données.
3. **Protection IP** : En basculant sur Browserless.io (ou Proxy Résidentiels certifiés), les IPs utilisées changent par requêtes, rendant le blocage CAPTCHA quasi inexistant.

---

## 4. User Review Required (Validation Attendue)
> [!IMPORTANT]
> Pourriez-vous valider cette architecture cible (Docker, Celery, PostgreSQL, GitHub Actions) ? Une fois validée par vous ou votre direction technique, ce plan pourra être découpé en tickets de développement (Jira / GitHub Issues) et exécuté sprint par sprint.
