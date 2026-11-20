# Projet Hydroponique : HydroTour

Projet tutoré de L3 SPI à l'Université de la Polynésie française : tour hydroponique verticale autonome, 12 plants de laitue, réservoir de 152 L, alimentation 100 % solaire, dosage automatique des engrais et du pH.

## Contenu

- `resume/` : résumés complets du travail effectué.
  - `RESUME_TRAVAIL_PROJET.md` : index, à lire en premier.
  - `RESUME_ETUDE_ELECTRIQUE.md`, `RESUME_ETUDE_HYDRAULIQUE.md`, `RESUME_ETUDE_SONDE_EC.md` : les trois études.
  - `RESUME_CODE.md` : le code installé sur le Raspberry Pi (Firmata, serveur, pilote, sonde EC).
  - `RESUME_DECISIONS_ET_MATERIEL.md` : décisions, matériel, organisation, points ouverts.
- `HYDROCODE/` : le code réellement installé sur la tour (Arduino Firmata, `server.py`, `pilote.py`, `arduino.py`, dashboard).
- `archive_premiere_version/` : la première architecture (`cerveau.py`, Arduino à lignes de texte), gardée pour mémoire, non installée.
- `etudes/` : études LaTeX, scripts de calcul et mesures. Voir `etudes/COMPILER.md` : les figures sont produites par les scripts avant la compilation.
- `documents/` : PDF compilés des études, schémas, étude informatique et nomenclature.

## Architecture en bref

Raspberry Pi 3 B : cerveau (mesures, décisions, base SQLite, dashboard). Arduino Uno R3 : carte d'entrées/sorties (Firmata) qui coupe les pompes si le Pi se tait 30 s. Liaison USB à 115200 bauds.
