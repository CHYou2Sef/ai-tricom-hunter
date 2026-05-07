import os
import shutil
import csv
from pathlib import Path
from openpyxl import Workbook
from utils.fs import safe_mkdir, safe_touch

# 1. Clean folders
work_dir = Path("WORK")
dirs_to_clean = ["INCOMING", "CHUNKS", "STD", "RS", "SIREN", "OTHERS", "READY", "output"]

print("🧹 Nettoyage des dossiers de travail...")
for d in dirs_to_clean:
    dir_path = work_dir / d
    if dir_path.exists():
        for item in dir_path.iterdir():
            if item.is_file():
                try: item.unlink()
                except: pass
            elif item.is_dir():
                try: shutil.rmtree(item)
                except: pass

# 2. Generate CSV
print("📝 Création du fichier CSV de test...")
csv_header = "siren,nic,siret,statutDiffusionEtablissement,dateCreationEtablissement,trancheEffectifsEtablissement,anneeEffectifsEtablissement,activitePrincipaleRegistreMetiersEtablissement,dateDernierTraitementEtablissement,etablissementSiege,etatAdministratifUniteLegale,statutDiffusionUniteLegale,unitePurgeeUniteLegale,dateCreationUniteLegale,categorieJuridiqueUniteLegale,denominationUniteLegale,sigleUniteLegale,sexeUniteLegale,nomUniteLegale,nomUsageUniteLegale,prenom1UniteLegale,prenom2UniteLegale,prenom3UniteLegale,prenom4UniteLegale,prenomUsuelUniteLegale,pseudonymeUniteLegale,activitePrincipaleUniteLegale,nomenclatureActivitePrincipaleUniteLegale,identifiantAssociationUniteLegale,economieSocialeSolidaireUniteLegale,societeMissionUniteLegale,trancheEffectifsUniteLegale,anneeEffectifsUniteLegale,nicSiegeUniteLegale,dateDernierTraitementUniteLegale,categorieEntreprise,anneeCategorieEntreprise,complementAdresseEtablissement,numeroVoieEtablissement,indiceRepetitionEtablissement,dernierNumeroVoieEtablissement,typeVoieEtablissement,libelleVoieEtablissement,codePostalEtablissement,libelleCommuneEtablissement,libelleCommuneEtrangerEtablissement,codeCommuneEtablissement,codePaysEtrangerEtablissement,libellePaysEtrangerEtablissement,identifiantAdresseEtablissement,coordonneeLambertAbscisseEtablissement,coordonneeLambertOrdonneeEtablissement,etatAdministratifEtablissement,enseigne1Etablissement,enseigne2Etablissement,enseigne3Etablissement,denominationUsuelleEtablissement,activitePrincipaleEtablissement,nomenclatureActivitePrincipaleEtablissement,caractereEmployeurEtablissement,activitePrincipaleNAF25Etablissement".split(",")

# Row 1: Valid RS + ADR + SIREN
csv_r1 = [""] * len(csv_header)
csv_r1[csv_header.index("siren")] = "100056753" # SIREN
csv_r1[csv_header.index("denominationUniteLegale")] = "ECOMESH ADIABATIC SYSTEMS LTD" # NOM
csv_r1[csv_header.index("numeroVoieEtablissement")] = "32" # ADRESSE
csv_r1[csv_header.index("typeVoieEtablissement")] = "MERE VIEW INDUSTRIAL EST"
csv_r1[csv_header.index("codePostalEtablissement")] = "PE7 3HS"
csv_r1[csv_header.index("libelleCommuneEtablissement")] = "YAXLEY"
csv_r1[csv_header.index("etatAdministratifUniteLegale")] = "A" # Active

out_csv = Path("WORK/INCOMING/test_dataset_1.csv")
safe_mkdir(out_csv.parent)

with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f, delimiter=";")
    writer.writerow(csv_header)
    writer.writerow(csv_r1)
safe_touch(out_csv)
    
# 3. Generate XLSX
print("📗 Création du fichier XLSX de test...")
xlsx_header = ["Nom, Prénom(s)", "Nom d’usage", "SIREN (siège)", "Date d’immatriculation au RNE", "Début d’activité", "Nature de l’entreprise", "Forme juridique", "Activité principale", "Code APE", "Adresse du siège", "Complément localisation", "Date naissance 1", "Date naissance 2", "Nom commercial"]

# Row 1: Valid RS + ADR + SIREN
xlsx_r1 = [""] * len(xlsx_header)
xlsx_r1[xlsx_header.index("SIREN (siège)")] = "919028886"
xlsx_r1[xlsx_header.index("Nom, Prénom(s)")] = "DELL TECHNOLOGIES"
xlsx_r1[xlsx_header.index("Adresse du siège")] = "1 ROND POINT BENJAMIN FRANKLIN 34000 MONTPELLIER"
xlsx_r1[xlsx_header.index("Activité principale")] = "Fabrication d'ordinateurs"

wb = Workbook()
ws = wb.active
ws.append(xlsx_header)
ws.append(xlsx_r1)
xlsx_path = "WORK/INCOMING/test_dataset_2.xlsx"
wb.save(xlsx_path)
safe_touch(xlsx_path)

print("✅ Base de données réinitialisée. Fichiers prêts dans WORK/INCOMING/")
