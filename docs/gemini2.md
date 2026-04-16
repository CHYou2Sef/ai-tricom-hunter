🚀 Stratégies d'Optimisation (SQO, AEO, GEO) pour AI Phone Hunter

Ce document sert de spécification technique pour transformer l'agent de collecte en un outil de précision chirurgicale. Utilisez les blocs de code ci-dessous pour mettre à jour votre projet.

🔍 1. SEO → SQO (Search Query Optimization)

Fichier cible : agent.py

Objectif : Utiliser les Google Dorks pour forcer l'affichage de sites à haute autorité (EEAT) et éliminer le "bruit" des annuaires non fiables.

Modification suggérée pour build_search_query :

def build_sqo_query(nom_entreprise, adresse):
"""
Construit une requête optimisée SQO avec Google Dorks.
Cible les sources de confiance : Pappers, Societe.com, Infogreffe, LinkedIn.
""" # Liste blanche de domaines autoritaires (EEAT)
trusted_sources = "site:pappers.fr OR site:societe.com OR site:infogreffe.fr OR site:linkedin.com"

    # Force la présence de mots-clés de contact
    keywords = '("téléphone" OR "contact" OR "siège social")'

    # Requête finale combinée
    query = f'"{nom_entreprise}" "{adresse}" {keywords} {trusted_sources}'
    return query

⚡ 2. AEO (Answer Engine Optimization)

Fichier cible : extractor.py (ou le module gérant Playwright)

Objectif : Extraire les données structurées (JSON-LD) que Google utilise pour ses "Featured Snippets". Cela permet d'obtenir la donnée sans même lire le texte visible.

Implémentation du collecteur de métadonnées :

import json

async def extract_aeo_data(page):
"""
Capture les balises <script type="application/ld+json">.
Méthode 'Zero-Click' pour extraire les données Schema.org.
""" # Récupérer tous les scripts JSON-LD de la page de résultats
json_ld_scripts = await page.locator('script[type="application/ld+json"]').all_inner_texts()

    extracted_data = []
    for script in json_ld_scripts:
        try:
            data = json.loads(script)
            # On cherche récursivement les clés 'telephone' ou 'contactPoint'
            if isinstance(data, dict):
                extracted_data.append(data)
        except Exception:
            continue

    return extracted_data

🧠 3. GEO (Generative Engine Optimization)

Fichier cible : config.py et agent.py

Objectif : Utiliser Gemini comme un extracteur logique (RAG) sur le texte brut des premiers sites officiels trouvés, plutôt que de le laisser "chercher" seul.

Mise à jour du Prompt dans config.py :

GEO_FALLBACK_PROMPT = """
Rôle : Expert en extraction de données B2B (EEAT).
Analyse le CONTEXTE suivant issu des pages officielles pour l'entreprise : {nom} à {adresse}.

CONTEXTE :
{raw_web_context}

INSTRUCTIONS :

1. Extrais uniquement le numéro de téléphone direct ou du siège.
2. Formate le numéro au standard international (+33...).
3. Si l'information n'est pas présente dans le texte fourni, réponds strictement "NOT_FOUND".
4. Ta réponse doit être un JSON pur.

FORMAT DE SORTIE :
{{
  "telephone": "01XXXXXXXX",
  "source": "URL ou Nom du Site",
  "confiance": 0.95,
  "raisonnement": "Trouvé dans le footer de la page contact"
}}
"""

🛠 Plan d'Exécution avec Cursor

SQO : Demandez à Cursor : "Modifie la fonction de génération de requête dans agent.py pour utiliser le dorking de gemini.md".

AEO : Demandez à Cursor : "Ajoute la fonction extract_aeo_data à extractor.py pour capturer le JSON-LD via Playwright".

GEO : Demandez à Cursor : "Mets à jour l'appel API Gemini pour utiliser le GEO_FALLBACK_PROMPT défini dans gemini.md et passer le texte scrappé comme contexte".

✅ Critères de Succès

[ ] Zéro "faux positifs" provenant d'annuaires vides.

[ ] Récupération du numéro de téléphone directement via le Schema.org (AEO).

[ ] Analyse sémantique par Gemini avec un score de confiance > 0.8 (GEO).
