# État du code HydroTour (31 octobre 2026)

Architecture : le Raspberry Pi 3 B est le cerveau, l'Arduino Uno R3 est seulement l'actionneur. Le contrat entre les deux (protocole série) et toutes les données du projet sont dans `SPEC.md`.

## Terminé
- `HydroTour_Actionneur.ino` : sketch Arduino. Compile pour l'Uno (flash 71 %, RAM 33 %). Pas encore testé sur la vraie carte.
  - À savoir : ouvrir le port série redémarre l'Uno, attendre la ligne `# pret` ; une lecture `L` dure environ 2 s ; en mode secours, toute commande renvoie d'abord `! SECOURS 0` ; pendant une chute, `D` répond `ERR chute`, même pour `D c 0`.
  - À vérifier pompes débranchées : les sorties 0 à 7 de la carte 6318 correspondent bien à GPA0..GPA7 du MCP23017 (voir `README_ARDUINO.md`).
- `server.py` + `hydrotour.html` : nouveau serveur et dashboard, compatibles avec l'ancien.
  - Base `hydrotour.db` en UTC au format `2026-10-22T08:15:03Z`, affichage et export en heure de Tahiti.
  - Migration sans perte avec sauvegarde automatique ; routes `/api/journal` et `/api/export.csv` ajoutées.
  - Installation : `README_DASHBOARD.md`.
  - Les fonctions de l'ancien `hydrotour.html` (seuils, schéma de la tour) ne sont pas reprises : fusion à faire avec l'ancien fichier.

## En cours : `cerveau.py`
1 433 lignes, il compile. Vérifié : planning de circulation (6,75 h par jour, nuit à 21 h, 0 h, 3 h), conversion du pH (étalonnage 2 points), lecture des lignes `M`.

Contient : horloges (réelle, accélérée, manuelle), planning, conversions pH, EC et eTape, filtre médian, validité des mesures pompe à l'arrêt, décision de dosage, liaison série, journal, envoi au serveur avec file d'attente, classe `Cerveau`.

Format attendu par le dashboard dans le POST JSON vers `/api/data` :
- pompes : `{"circulation", "engrais_a", "engrais_b", "ph_moins"}` (booléens) ;
- alarmes : `chute`, `niveau_bas`, `temp_eau_haute`, `ph_haut`, `ph_bas`, `ec_haute`, `ec_basse`, `secours`, `arduino`, `capteur` ;
- `inclinaison` en degrés ;
- `t` en UTC avec Z, ou absent ;
- journal : POST `/api/journal` avec `{type, message}`.

## Reste à faire
1. `faux_arduino.py` (simulateur du protocole) et tests (planning, conversions, dosage, intégration).
2. Relire `cerveau.py` en entier (code laissé par un agent interrompu) et vérifier qu'il respecte les points ci-dessus.
3. `calibrer.py` : pH 2 points, EC 1 point, eTape vide/plein et seuil `N`, zéro accéléromètre `Z`, test des pompes.
4. `config.json`, service `hydrotour-cerveau.service`, notice `INSTALL_PI.md` (chaque commande expliquée), en remplacement de `pont_usb.py` / `hydrotour-pont`.
5. Installation et essais sur le Pi avec le vrai matériel.
