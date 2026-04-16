# Nettoyage et classification des fichiers d'entrée

## Objectif

À la suite du lancement d'un agent, ajouter une étape de post-traitement pour nettoyer et classifier les fichiers d'entrée.  
Le but est de :

- Supprimer les lignes ne contenant aucune information pertinente (SIREN/SIRET, adresse, raison sociale, téléphone).
- Classer les lignes selon la présence de certaines combinaisons d'informations dans des dossiers distincts afin de faciliter les traitements ultérieurs.
- Maximiser la conservation des informations, en particulier le numéro de téléphone.

## Prérequis

- Les fichiers d'entrée sont au format CSV avec une ligne d'en-tête (ou du texte structuré avec des colonnes).
- Les colonnes peuvent avoir des noms variables (ex. `nom`, `dénomination`, `raison_sociale` pour la raison sociale ; `adresse`, `rue`, `ville` pour l'adresse ; `tel`, `téléphone`, `mobile` pour le téléphone ; `siren`, `siret`, `numéro_siren` pour l'identifiant).
- Le script doit analyser chaque ligne sur l'ensemble des colonnes pour détecter la présence des informations.

## Étapes du traitement

### 1. Définition des champs à identifier

| Champ              | Critères de tection                                                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| **SIREN/SIRET**    | Chaîne de 9 chiffres (SIREN) ou 14 chiffres (SIRET). Peut être stocké sous forme de nombre ou texte.                                 |
| **Raison sociale** | Toute valeur non vide dans une colonne dont le nom contient `nom`, `denomination`, `raison_sociale`, `enseigne`, `appellation`, etc. |
| **Adresse**        | Toute valeur non vide dans une colonne dont le nom contient `adresse`, `rue`, `voie`, `lieu`, `ville`, `code_postal`, `cp`, etc.     |
| **Téléphone**      | Toute valeur non vide dans une colonne dont le nom contient `tel`, `telephone`, `mobile`, `fax`, etc.                                |

**Remarque** : Pour la détection, on utilise une correspondance insensible à la casse et des mots-clés partiels.  
On vérifie également les valeurs des cellules (par exemple une chaîne de 9 chiffres est un SIREN potentiel, même si la colonne n'est pas explicitement nommée `siren`).

### 2. Algorithme de nettoyage et classification

Pour chaque ligne d'un fichier d'entrée :

1. **Collecter les informations** :
   - `has_siren` : vrai si une colonne contient une valeur ressemblant à un SIREN ou SIRET (regex `^\d{9}$` ou `^\d{14}$`).
   - `has_rs` : vrai si une colonne de type "raison sociale" contient une valeur non vide.
   - `has_adresse` : vrai si une colonne de type "adresse" contient une valeur non vide.
   - `has_tel` : vrai si une colonne de type "téléphone" contient une valeur non vide.

2. **Décider du sort de la ligne** :
   - Si **aucun** des quatre champs n'est présent (`has_siren = False`, `has_rs = False`, `has_adresse = False`, `has_tel = False`) → **supprimer** la ligne.
   - Sinon, classer selon la priorité suivante (premier match) :
     - **Catégorie A** : `has_siren` ET `has_rs` ET `has_adresse` → copier dans `std_input/`
     - **Catégorie B** : `has_rs` ET `has_adresse` (sans `has_siren`) → copier dans `RS_input/`
     - **Catégorie C** : `has_rs` ET `has_adresse` (sans `has_rs`) → copier dans `sir_input/`
     - **Catégorie D** : tous les autres cas (ex. seulement `has_siren`, seulement `has_adresse`, seulement `has_tel`, ou combinaisons non couvertes) → copier dans `other_input/`

   Les noms des dossiers (`std_input`, `RS_input`, `sir_input`, `other_input`) sont paramétrables.

3. **Format de sortie** : Chaque fichier de sortie porte le même nom que le fichier d'entrée, placé dans le dossier correspondant.  
   Exemple :
   - Entrée : `data/entree.csv`
   - Sorties : `std_input/entree.csv`, `RS_input/entree.csv`, `sir_input/entree.csv`, `other_input/entree.csv` (selon les lignes présentes).

### 3. Gestion des colonnes similaires

Pour tenir compte des variations de noms de colonnes, on utilise des listes de mots-clés pour identifier chaque type de champ.  
On applique une correspondance partielle (ex. `contains`) insensible à la casse.

**Exemples de listes :**

```python
RS_KEYWORDS = ["nom", "denomination", "raison_sociale", "enseigne", "appellation", "societe", "entreprise"]
ADRESSE_KEYWORDS = ["adresse", "rue", "voie", "lieu", "ville", "code_postal", "cp", "commune"]
TEL_KEYWORDS = ["tel", "telephone", "mobile", "fax", "portable"]
SIREN_KEYWORDS = ["siren", "siret", "numero_siren", "numero_siret"]
```
