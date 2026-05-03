# Agent Behavior Specification

## PhoneHunterAgent

- PRIMARY path: AI Mode search → JSON parse → phone extract
- FALLBACK 1: Knowledge Panel (UUE heuristic)
- FALLBACK 2: Deep Discovery (Social Media & Website crawl)
- VALIDATION: Every phone number is checked via **Neutrino API** (Phase 5).
- SKIP condition: Row already marked as `DONE` in progress tracker.
- RETRY condition: `config.REPROCESS_FAILED_ROWS = True`.

## HybridEngine Waterfall (10 Tiers)

L'infrastructure utilise une cascade de 10 tiers pour garantir l'extraction :

1.  **Tier 2 (SeleniumBase UC)** : ⭐ Primaire. Stealth maximal, gère Cloudflare Turnstile.
2.  **Tier 3 (Botasaurus)** : 🦖 Anti-détection robuste avec rotation de profils.
3.  **Tier 4 (CloakBrowser)** : 🕵️ **Supreme Stealth**. Patches C++ source-level, bypass Turnstile/reCAPTCHA.
4.  **Tier 5 (Nodriver)** : 🟢 Pilotage CDP direct (sans WebDriver), idéal pour les WAF durs.
5.  **Tier 6 (Crawl4AI)** : 🟡 Rendu JS managé pour les sites e-commerce.
6.  **Tier 7 (Camoufox)** : 🦊 Firefox anti-detect (très puissant, dernier recours Chrome).
7.  **Tier 8 (Firecrawl)** : 🔥 API managée premium (Scale).
8.  **Tier 9 (Jina Reader)** : ⚡ Conversion Markdown haute vitesse.
9.  **Tier 10 (Crawlee)** : 🛠️ Crawling industriel Playwright.
10. **Tier 0 (Legacy)** : 🟧 Selenium standard pour benchmark de comparaison.

**Scrapy Sniper** : Activé en bonus post-découverte si l'URL est trouvée mais que le numéro échappe aux navigateurs.

## Enricher (Phase 4)

- **Priorité des sources** : google_ai_mode (0.97) > aeo_schema (1.00) > gemini_json (0.90)
- **Règle d'or** : Ne jamais écraser un champ déjà renseigné par une valeur vide.

## MCP Tools: code-review-graph & Jina

**IMPORTANT** : Ce projet utilise des graphes de connaissance et des serveurs MCP.
- **code-review-graph** : Utilisez-le pour explorer la structure du code (callers, tests).
- **jina** : Utilisez-le pour effectuer des recherches web en Markdown ou lire des URLs en direct via l'assistant.
