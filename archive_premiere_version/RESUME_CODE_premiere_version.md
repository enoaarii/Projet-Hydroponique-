# Résumé du code HydroTour (état au 31 octobre 2026)

Source : `code/SPEC.md`, `code/ETAT_DU_CODE.md`, `code/arduino/README_ARDUINO.md`, `code/dashboard/README_DASHBOARD.md`, et les fichiers `HydroTour_Actionneur.ino`, `server.py`, `hydrotour.html`, `cerveau.py`.

## 1. Architecture

- Le Raspberry Pi 3 Model B est le cerveau : logique, planning, décisions, conversions, base de données, dashboard (Raspberry Pi OS Lite, accès Raspberry Pi Connect et Tailscale, dongle Wi-Fi USB à antenne externe car boîtier métallique).
- L'Arduino Uno R3 (avec base Grove du Sensor Kit) est seulement l'actionneur : il lit les capteurs en brut, exécute les commandes de pompes, et applique les sécurités matérielles non contournables.
- Liaison : un câble USB (alimentation et données), 115200 bauds, lignes ASCII terminées par `\n`.
- Aucun agent IA dans le programme de la tour.
- Le cerveau remplace l'ancien pont `pont_usb.py` (service `hydrotour-pont`).

## 2. Protocole série Pi et Arduino (contrat)

| Commande | Effet | Réponse |
|---|---|---|
| `P` | ping | `OK P` |
| `L` | lecture de tous les capteurs bruts (environ 2 s) | `M ph=<mV>,ec=<mV>,niv=<mV>,te=<°C>,ta=<°C>,hu=<%>,lux=<0-1023>,inc=<deg>` (`nan` si absent) |
| `D <c> <ms>` | pompe c (0 circulation, 1 engrais A, 2 engrais B, 3 pH-) pendant ms ; ms = 0 arrête c | `OK D <c> <ms>` ou `ERR <raison>` |
| `S` | arrêt de toutes les pompes | `OK S` |
| `E` | état | `E pompes=<4 bits>,secours=<0/1>,chute=<0/1>,niv_bas=<0/1>,inc=<deg>` |
| `N <seuil_mV> <sens>` | seuil de niveau bas, gardé en EEPROM (sens 1 : bas si mV supérieur au seuil ; -1 : bas si inférieur) | `OK N` |
| `Z` | mémorise l'orientation tour droite de l'accéléromètre (EEPROM) | `OK Z` |
| `R` | réarme l'alarme chute (refusé si toujours inclinée) | `OK R` ou `ERR incline` |

Messages spontanés : `# texte`, `! CHUTE`, `! NIVEAU_BAS`, `! NIVEAU_OK`, `! SECOURS 1`, `! SECOURS 0`.

- Durées maximales : circulation 1 000 000 ms, doseuses 30 000 ms (au-delà : `ERR duree`).
- La circulation est commandée par bail : `D 0 90000` renouvelé toutes les 60 s environ tant qu'elle doit tourner. Si le Pi plante, la pompe s'arrête seule.
- Toute commande reçue remet à zéro le compteur de silence et fait sortir du mode secours.
- Autres erreurs possibles : `syntaxe`, `canal`, `commande`, `trop_long`, `pompes` (carte absente), `niveau_bas` (circulation demandée pendant un niveau bas), `accel`.
- Note : l'étude de la sonde EC change le champ `ec=` en ohms (mise à jour de `SPEC.md` et `cerveau.py` à faire).

## 3. Arduino : `HydroTour_Actionneur.ino`

Compile pour l'Uno (flash 23 216 octets sur 32 256, 71 % ; RAM 681 octets sur 2 048, 33 %). Pas encore testé sur la vraie carte.

### Sécurités

- Chien de garde de 8 s : si le programme se bloque, l'Uno redémarre, toutes les pompes à l'arrêt.
- Niveau bas : circulation coupée, `ERR niveau_bas` sur les demandes de circulation, doseuses restent autorisées, hystérésis de 50 mV. Inactive tant que `N` n'a pas été réglé.
- Chute : inclinaison supérieure à 35° pendant 1 s (filtre qui ignore les vibrations de la pompe) : toutes les pompes s'arrêtent, `D` répond `ERR chute` (même `D c 0`). Inactive tant que `Z` n'a pas été fait.
- Mode secours : si le Pi se tait plus de 5 min, circulation 15 min en marche et 15 min à l'arrêt, aucune doseuse. Toute commande renvoie d'abord `! SECOURS 0`.
- Carte pompes absente au démarrage : message d'erreur toutes les 10 s, `ERR pompes`, reprise automatique si elle réapparaît.

### Brochage

| Élément | Broche ou adresse |
|---|---|
| Sonde pH DFRobot Gravity V2.0 | A1 |
| Capteur de lumière Grove | A3 |
| DHT11 | D3 |
| Alimentation de la carte EC DFR0300 | D7 (HIGH seulement pendant la lecture EC, jamais en même temps que le pH) |
| DS18B20 | D8 (4,7 kΩ vers 5 V) |
| I2C | A4 (SDA), A5 (SCL) |
| ADS1115 | 0x48 (A0 = EC, A1 = eTape) |
| Carte pompes 6318 (MCP23017) | 0x20 |
| Accéléromètre LIS3DHTR | 0x19 |

| Canal | Pompe | Sorties 6318 |
|---|---|---|
| 0 | circulation 12 V | 0 et 1 ensemble |
| 1 | engrais A | 2 |
| 2 | engrais B | 3 |
| 3 | pH- | 4 |

Les sorties 5, 6 et 7 restent à l'arrêt. À vérifier avant le premier essai, pompes débranchées, que les sorties 0 à 7 de la carte correspondent à GPA0 à GPA7 du MCP23017.

### Bibliothèques

Adafruit MCP23017 Arduino Library (2.3.2), Adafruit BusIO (1.17.4), Adafruit ADS1X15 (2.6.2), OneWire (2.3.8), DallasTemperature (4.0.6), DHT sensor library (1.4.7), Adafruit Unified Sensor (1.1.15), Grove 3-Axis Digital Accelerometer LIS3DHTR de Seeed Studio (1.2.4). Wire, EEPROM et SPI font partie du cœur AVR.

### Téléversement et test

Carte « Arduino Uno », IDE 2.x ou `arduino-cli compile` puis `upload` sur `/dev/ttyACM0`. Arrêter d'abord le programme qui occupe le port série. Ouvrir le port série redémarre l'Uno (environ 2 s) : attendre la ligne `# pret`. Tests à la main au moniteur série (115200 bauds) : `P`, `L`, `E`, `Z`, `D 1 2000`, `D 0 90000`, `D 1 40000` (doit répondre `ERR duree`), `S`, `N 900 -1`, puis tests des sécurités niveau bas, chute, mode secours et carte absente.

## 4. Dashboard : `server.py` et `hydrotour.html` (version 2)

- Serveur Flask, port 5000, authentification HTTP Basic (variables `HYDRO_USER` et `HYDRO_PASS` chargées depuis `hydro.env`, le serveur refuse de démarrer si elles manquent), service systemd `hydrotour`.
- Routes : `/`, `/api/data` (GET et POST), `/api/latest`, `/api/history?hours=` (au plus 1 500 points par tranches), nouvelles `/api/journal` (GET et POST) et `/api/export.csv` (période en heures ou dates, séparateur configurable).
- Base SQLite `hydrotour.db` : table `mesures(t, ph, ec, temp_eau, temp_air, humidite, lux, niveau, pompes)` plus les colonnes ajoutées `inclinaison` et `alarmes`, et une table `journal(t, type, message)`. Environ 3 800 mesures de pH historiques conservées. Migration automatique sans perte avec copie de sauvegarde `hydrotour.db.avant_migration_<date>`.
- Heures : `t` stocké en UTC au format `2026-10-22T08:15:03Z`, affichage et export en heure de Tahiti (UTC-10).
- Graphiques uPlot chargés depuis internet ; sans internet, cartes de valeurs, pompes, alarmes, journal et résumés restent affichés en texte. Rafraîchissement : mesure toutes les 30 s, historique toutes les 3 min, journal toutes les minutes.
- Alarmes reconnues : `chute`, `niveau_bas`, `temp_eau_haute`, `ph_haut`, `ph_bas`, `ec_haute`, `ec_basse`, `secours`, `arduino`, `capteur`.
- Format du POST du cerveau : pompes `{circulation, engrais_a, engrais_b, ph_moins}` en booléens, `inclinaison` en degrés, `t` en UTC avec Z ou absent, journal avec `{type, message}`.
- Accès distant : Tailscale (machine `hydro-info`), tunnel Cloudflare temporaire. Données aussi enregistrées en local sur la carte SD du Pi pour une coupure du Wi-Fi.
- Limite : les fonctions de l'ancien `hydrotour.html` (seuils, schéma de la tour, commande des pompes) ne sont pas reprises. Fusion à faire à partir de l'ancien fichier du Pi.
- Installation sur le Pi : sauvegarde de la base, de l'ancien serveur et de l'ancienne page, copie par `scp` via Tailscale, test à la main, relance du service, retour arrière possible. Détail dans `README_DASHBOARD.md`.

## 5. Cerveau : `code/pi/cerveau.py`

1 433 lignes, compile. Vérifié : planning de circulation (6,75 h par jour, nuit à 21 h, 0 h, 3 h), conversion du pH (étalonnage 2 points), lecture des lignes `M`.

Contenu : horloges (réelle, accélérée, manuelle), planning, conversions pH, EC et eTape, filtre médian, validité des mesures pompe à l'arrêt, décision de dosage, liaison série, journal, envoi au serveur avec file d'attente, classe `Cerveau`. Le fichier est un code laissé par un agent interrompu : relecture complète nécessaire.

## 6. Règles et réglages de fonctionnement

- Plages laitue : pH cible 6,0 (5,5 à 6,5), EC cible 1,4 mS/cm (1,2 à 1,8) à 25 °C, eau 18 à 24 °C (alarme au-dessus de 28 °C).
- Planning de circulation (heure locale Pacific/Tahiti) : de 6 h à 18 h, marche de hh:00 à hh:15 et de hh:30 à hh:45 ; la nuit 15 min à 21 h, 0 h et 3 h ; total 6,75 h par jour.
- pH, EC et température de l'eau relevés pompe à l'arrêt.
- Dosage en boucle fermée : engrais A et B à volumes égaux si l'EC est trop basse, pH- si le pH est trop haut, doses petites et progressives. Réglages conseillés issus de l'étude hydraulique (seuils, 10 mL, 4 mL, 4 doses par jour au maximum, rien la nuit).
- Mode sobriété prévu sur la tension batterie mesurée par l'INA260.

## 7. Reste à faire

1. `faux_arduino.py` (simulateur du protocole) et tests (planning, conversions, dosage, intégration).
2. Relecture complète de `cerveau.py`, mise à jour du champ EC en ohms.
3. `calibrer.py` : pH 2 points, EC 1 point, eTape vide et plein et seuil `N`, zéro accéléromètre `Z`, test des pompes.
4. `config.json`, service systemd `hydrotour-cerveau.service`, notice `INSTALL_PI.md` (chaque commande expliquée).
5. Fusion avec les fonctions de l'ancien `hydrotour.html`.
6. Vérification de la correspondance des sorties de la carte 6318 avec le MCP23017.
7. Installation et essais sur le Pi avec le vrai matériel.
