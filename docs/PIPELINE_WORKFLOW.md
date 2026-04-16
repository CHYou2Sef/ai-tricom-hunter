# Architecture et Pipeline de Traitement : AI Tricom Hunter

Ce document décrit en détail le cycle de vie complet d'une ligne de données au sein de notre architecture de recherche et d'enrichissement B2B. Il est conçu pour expliquer la robustesse de l'Agent et les mécanismes anti-échecs mis en place.

---

## 🏗️ 1. Phase d'Orchestration & Verification (Input Layer)

Lorsqu'un fichier Excel est placé dans le dossier `WORK/INCOMING`, il est découpé (**Chunking**) pour éviter la saturation mémoire. L'Orchestrateur (`agent.py`) distribue ces lignes de manière asynchrone aux agents disponibles.

**Processus de Ciblage (Verification Layer) :**
Avant toute recherche, l'agent construit un **Périmètre de Vérité**.
L'identifiant de recherche est composé en combinant les champs les plus sûrs :
1. `Nom` (Raison Sociale)
2. `Adresse` (Pour la désambiguïsation géographique)
3. `SIREN / SIRET` (Identifiant unique légal)

> *Log Généré : `🔍 [Verification] Row #42 | Target: 'BOULANGERIE DUPONT' | SIREN: 123456789 | Localité: '75001 Paris'`*

---

## 🕵️ 2. La Cascade de Recherche (Waterfall Search Engine)

L'agent n'effectue pas une simple requête Google. Il utilise un système de repli en entonnoir (Waterfall) pour maximiser le taux de succès tout en minimisant les risques de bannissement.

### 🥇 Niveau 1 : Le "Google AI Mode" (Recherche Sémantique Intensive)
L'agent cible directement la vue de recherche propulsée par l'IA de Google (`&udm=14` / `Search Labs`).
Il y injecte deux prompts successifs si le premier échoue :
1. **Prompt Standard** : Demande un résumé JSON des numéros de téléphone et emails de l'entité.
2. **Prompt Expert B2B** : S'il y a un échec, l'agent relance la requête en simulant le comportement d'un prospecteur B2B très spécifique pour forcer l'affichage de données enfouies.
*Avantage : Récupère au format JSON (facile à mapper) un maximum de données (Tel, Email, SIREN, Dirigeant, Site Web).*

### 🥈 Niveau 2 : Le Knowledge Panel & JSON-LD (Web Sémantique)
Si le Mode IA ne répond pas ou ne retourne pas de téléphone, l'agent bascule sur une **Recherche Google Classique**.
Plutôt que de lire le texte, il analyse le **"Web Invisible"** (le code source structuré de la page) :
- Les données Schema.org / `application/ld+json`.
- Les attributs `[data-attrid='kc:/local:phone']` (Google Knowledge Panel).
*Avantage : Le téléphone extrait ici est sûr à 100% car déclaré par les créateurs des sites ou par Google lui-même.*

### 🥉 Niveau 3 : Le Scraping Profond et l'Heuristique
Si la structure web est cassée, l'agent génère une requête ultra-ciblée grâce à des mots-clefs de confiance (Dorks) : `"{Nom}" "{Adresse}" contact societe.com pappers.fr`.
Puis, il extrait l'intégralité du code HTML résultant.

### 🆘 Niveau 4 : Intelligence Artificielle Locale (Ollama - Modèle Qwen)
En cas de désespoir (beaucoup de texte, numéro caché dans un paragraphe non structuré), le HTML épuré de la page est envoyé au LLM **Ollama (Local)**. Le LLM "lit" le texte et utilise sa logique sémantique pour déduire quel numéro appartient véritablement au standard de l'entreprise cible.

---

## 🎯 3. Le Moteur d'Extraction (Validation & Nettoyage)

Peu importe la couche de recherche ayant trouvé un potentiel numéro, la donnée passe dans le **`PhoneExtractor`**. 
Ce nettoyeur industriel garantit l'intégrité de la base de données finale.

1. **Filtrage Anti-Fax** : Les mots autour du numéro sont scannés (`télécopie`, `fax`). Si le numéro est situé à moins de 30 caractères du mot "Fax", il est rejeté.
2. **Standardisation** : Le numéro est nettoyé (retrait des indicatifs inutiles, formatage en `XX XX XX XX XX`).
3. **Ordre de Priorité** : Les numéros commençant par `06/07` (mobiles) sont toujours remontés en priorité #1 sur la ligne finale, augmentant la joignabilité (Reachability).

---

## 💎 4. L'Enrichissement des Données (Data Enrichment Layer)

Une fois le téléphone validé, l'Orchestrateur lance le script `enricher.py`.
Le rôle de l'Enricher est de piocher dans le réservoir de métadonnées invisibles (*les payloads JSON générés au Niveau 1 et 2 lors de la recherche du téléphone*) et d'affecter ces données aux colonnes de l'Excel de sortie.

Il obéit à la règle stricte du **"Never Overwrite"** (ne jamais écraser une donnée existante).
Données ciblées :
- L'URL du site web.
- Les adresses Email (souvent trouvées via Schema.org ou AEO).
- La page LinkedIn officielle.
- Les noms des Dirigeants, le Code NAF, le Capital Social.

---

## 💾 5. Sauvegarde & Archivage (Output Layer)

Le statut du traitement passe de `En Cours` à `DONE` (si un numéro principal a été récupéré) ou `NO TEL` (si aucune des 4 couches de recherche n'a trouvé de numéro valable).
La donnée est écrite (de manière bufferisée pour préserver le disque dur HDD) dans la colonne "Etat_IA" puis le fichier est stocké dans :
`WORK/ARCHIVE/SUCCEED/Extraction_{Date}_{Batch}.xlsx`.

L'agent passe automatiquement à la ligne suivante, jusqu'à épuisement complet du dossier `INCOMING`.
