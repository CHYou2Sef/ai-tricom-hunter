Oui, absolument ! Le projet est désormais conçu de manière **100% "OS-agnostique"** (multi-plateforme). Depuis que nous avons remplacé les chemins de fichiers manuels en utilisant la librairie `pathlib` (qui gère automatiquement les barres obliques `\` sur Windows et `/` sur Linux), **le code fonctionnera parfaitement sous Windows.**

Voici le guide rapide et précis pour déployer et configurer ce robot sur votre PC Windows :

### 1. Prérequis Windows

- Assurez-vous que **Python 3.10 ou +** est installé. Pendant l'installation de Python, cochez bien la case **"Add Python to PATH"**.
- **Google Chrome** doit être installé "normalement" sur votre PC.

### 2. Installation (Terminal)

Ouvrez `cmd` ou `PowerShell` dans le dossier du projet (`ai_tricom_hunter`) et tapez :

```cmd
pip install -r requirements.txt
playwright install chromium
```

### 3. La Configuration Capitale : le fichier `.env`

Pour que le robot soit performant et ne se fasse pas bloquer pour "Anti-Bot", il doit **réutiliser votre profil Google Chrome Windows** (pour bénéficier de vos cookies, votre IP habituelle et votre historique humain).

1. Renommez le fichier `.env.example` en `.env` à la racine de votre projet.
2. Modifiez la variable `CHROMIUM_PROFILE_PATH` avec le chemin local Windows de Chrome.

Sur Windows, ce chemin est généralement :

```ini
CHROMIUM_PROFILE_PATH="C:\Users\VOTRE_NOM_UTILISATEUR\AppData\Local\Google\Chrome\User Data"
```

_(Remplacez `VOTRE_NOM_UTILISATEUR` par le nom de votre session Windows. Si vous avez un doute, tapez `%LOCALAPPDATA%\Google\Chrome\User Data` dans l'explorateur Windows pour le trouver)._

**⚠️ Attention :** Lorsque vous lancerez le script [main.py](cci:7://file:///home/youssef/ai_tricom_hunter/main.py:0:0-0:0), vous devrez **fermer toutes vos fenêtres Google Chrome habituelles**. Playwright ne peut pas prendre le contrôle du "User Data" si Chrome est déjà ouvert par vous-même en arrière-plan.

### 4. Mode d'Emploi Windows

Le fonctionnement reste exactement le même, mais avec des commandes Windows standard :

**Terminal 1 (Le Trieur) :**

```cmd
python pre_process.py
```

_Glacez vos fichiers sources (Excel/CSV) dans le dossier `input\incoming\`._

**Terminal 2 (L'Intelligence Artificielle) :**

```cmd
python main.py
```

### 5. Pour les Utilitaires (Rappel syntaxe Windows)

Pour les scripts de nettoyage et consolidation, selon la manière dont PowerShell est configuré, utilisez des anti-slashs `\` ou la conversion automatique Python :

```cmd
python scripts\consolidate_results.py
python scripts\clean_chrome_profiles.py
```

En résumé : **Il n'y a pas une seule ligne de code à changer dans les scripts Python**. Configurez juste votre chemin Chrome dans le `.env` de votre Windows et tout roulera !
