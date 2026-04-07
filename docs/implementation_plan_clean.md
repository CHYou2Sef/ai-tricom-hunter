# Input File Cleaning & Classification

Ajout d'une étape de **post-traitement** déclenchée automatiquement après la fin du traitement d'un fichier Excel. Chaque ligne est analysée et copiée dans un sous-dossier de classification selon les informations disponibles (SIREN, Raison Sociale, Adresse, Téléphone).

---

## Proposed Changes

### Module de nettoyage/classification

#### [NEW] [cleaner.py](file:///home/youssef/ai_tricom_hunter/excel/cleaner.py)

Nouveau fichier `excel/cleaner.py` contenant :

- `classify_row(row: ExcelRow) → str` — retourne la catégorie d'une ligne :
  - **`std_input`** : SIREN + RS + Adresse
  - **`RS_input`** : RS + Adresse (sans SIREN)
  - **`sir_input`** : RS seul
  - **`other_input`** : tous les autres cas
  - **`DISCARD`** : aucun champ présent → ligne supprimée

- `clean_and_classify(rows, filepath, mapping)` — fonction principale :
  1. Regroupe les lignes par catégorie
  2. Pour chaque catégorie non vide, crée un fichier Excel dans le bon sous-dossier
  3. Log les statistiques de classification

---

### Configuration

#### [MODIFY] [config.py](file:///home/youssef/ai_tricom_hunter/config.py)

Ajout des chemins des 4 dossiers de classification :

```python
# ── Classification folders (post-processing) ──
INPUT_STD_DIR   = os.path.join(BASE_DIR, "input", "std_input")
INPUT_RS_DIR    = os.path.join(BASE_DIR, "input", "RS_input")
INPUT_SIR_DIR   = os.path.join(BASE_DIR, "input", "sir_input")
INPUT_OTHER_DIR = os.path.join(BASE_DIR, "input", "other_input")
```

---

### Intégration dans l'agent

#### [MODIFY] [agent.py](file:///home/youssef/ai_tricom_hunter/agent.py)

Dans [process_file()](file:///home/youssef/ai_tricom_hunter/agent.py#152-213), après `save_results(...)`, appeler :

```python
from excel.cleaner import clean_and_classify
clean_and_classify(rows, filepath, mapping)
```

---

### Création des dossiers au démarrage

#### [MODIFY] [main.py](file:///home/youssef/ai_tricom_hunter/main.py)

Dans [ensure_directories()](file:///home/youssef/ai_tricom_hunter/main.py#40-51), ajouter les 4 nouveaux dossiers :

```python
config.INPUT_STD_DIR,
config.INPUT_RS_DIR,
config.INPUT_SIR_DIR,
config.INPUT_OTHER_DIR,
```

---

### Documentation

#### [MODIFY] [README.md](file:///home/youssef/ai_tricom_hunter/README.md)

Ajout d'une section **Post-traitement** décrivant les 4 catégories et la logique de classification.

---

## Logique de classification (résumé)

| Priorité | Condition | Dossier |
|---|---|---|
| 1 | SIREN + RS + Adresse | `input/std_input/` |
| 2 | RS + Adresse (sans SIREN) | `input/RS_input/` |
| 3 | RS seul | `input/sir_input/` |
| 4 | Autre (données partielles) | `input/other_input/` |
| — | Aucun champ présent | Supprimée |

La détection réutilise les champs déjà calculés sur chaque [ExcelRow](file:///home/youssef/ai_tricom_hunter/excel/reader.py#27-103) (`nom`, `adresse`, `siren`) — pas de re-parsing des colonnes nécessaire.

---

## Verification Plan

### Automated Tests

Création d'un nouveau fichier `tests/test_cleaner.py` avec `pytest` :

```bash
# Depuis la racine du projet
pytest tests/test_cleaner.py -v
```

Tests unitaires couverts :
- Ligne avec SIREN + RS + Adresse → `std_input`
- Ligne avec RS + Adresse → `RS_input`
- Ligne avec RS seul → `sir_input`
- Ligne avec seulement adresse → `other_input`
- Ligne vide → `DISCARD`
- Fichier Excel réel généré dans les bons dossiers

### Manual Verification

1. Copier un fichier `.xlsx` de test dans `input/`
2. Lancer `python main.py`
3. Attendre la fin du traitement
4. Vérifier que les fichiers classifiés apparaissent dans `input/std_input/`, `input/RS_input/`, etc.
5. Ouvrir chaque fichier et vérifier que les lignes correspondent à la bonne catégorie
