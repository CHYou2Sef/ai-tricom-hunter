---

## 🛠 Plan d'Action pour Cursor

1. **Ouvrir `cleaner.py`** : Demandez à Cursor : *"Remplace la fonction de chargement Excel par la logique de find_header_row présente dans gemini.md pour détecter dynamiquement la ligne des titres."*
2. **Gestion des doublons** : Ajoutez cette instruction : *"Assure-toi de nettoyer les noms de colonnes (strip et replace \n) car les fichiers Excel de Pappers contiennent souvent des retours à la ligne dans les titres."*
3. **Validation** : Testez avec un fichier ayant 3 lignes de texte inutile au début.

---

## ✅ Améliorations de Nettoyage (Bonus)

Pour rendre les données exploitables par l'agent :

- **Normalisation SIREN** : Forcer le formatage en string de 9 chiffres (pour éviter les `1.23E+08`).
- **Filtrage des Radiées** : Si une colonne "Statut" existe, supprimer les lignes "Radiée" dès l'étape du cleaner pour ne pas gaspiller de jetons API Gemini.

### Code de normalisation SIREN :

```python
df['SIREN'] = df['SIREN'].astype(str).str.replace('.0', '', regex=False).str.zfill(9)
```

import pandas as pd

def find_header_row(file_path, sheet_name=0):
"""
Scanne le fichier Excel pour trouver l'index de la ligne contenant les titres.
""" # Lire les 15 premières lignes pour analyse
df_preview = pd.read_excel(file_path, sheet_name=sheet_name, nrows=15, header=None)

    # Mots-clés critiques qui définissent nos colonnes
    target_keywords = {
        "siren", "nom", "dénomination", "adresse",
        "forme juridique", "activité", "immatriculation"
    }

    best_row = 0
    max_matches = 0

    for idx, row in df_preview.iterrows():
        # Nettoyer et normaliser les valeurs de la ligne
        row_values = [str(val).lower() for val in row.values if pd.notna(val)]

        # Compter combien de mots-clés sont présents dans cette ligne
        matches = sum(1 for word in target_keywords if any(word in val for val in row_values))

        if matches > max_matches:
            max_matches = matches
            best_row = idx

    return best_row

def load_and_clean_excel(file_path):
"""
Charge le fichier en sautant les lignes inutiles automatiquement.
"""
header_idx = find_header_row(file_path)

    # Charger le DataFrame à partir de la bonne ligne
    df = pd.read_excel(file_path, header=header_idx)

    # Supprimer les colonnes totalement vides (souvent présentes dans les exports)
    df = df.dropna(how='all', axis=1)

    # Nettoyage des noms de colonnes (suppression des sauts de ligne, espaces en trop)
    df.columns = [str(c).replace('\n', ' ').strip() for c in df.columns]

    return df

```

---

## 📋 Résumé des modifications

- [ ] Ajout de `find_header_row` avec système de scoring par mots-clés.
- [ ] Mise à jour de `read_excel(header=header_idx)`.
- [ ] Nettoyage automatique des noms de colonnes (`\n` et espaces).
- [ ] Suppression des colonnes fantômes (`axis=1, how='all'`).
```
