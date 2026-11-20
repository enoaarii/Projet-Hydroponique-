# Résumé du code HydroTour (version installée sur le Raspberry Pi)

Source : les fichiers du dossier `HYDROCODE/` (copiés depuis le Pi) et le rapport de projet v6.6, parties 8 et 10.
La première version du programme (`cerveau.py`, protocole à lignes de texte) est rangée dans `archive_premiere_version/` ; elle n'est pas installée.

## 1. Architecture

- Le Raspberry Pi 3 B est le cerveau : mesures, décisions, base SQLite, dashboard (service systemd `hydrotour`, dossier `~/hydrotour`, Python dans un venv).
- L'Arduino Uno R3 est une simple carte d'entrées/sorties : il fait tourner `HydroTour_Firmata` (ConfigurableFirmata). Une seule sécurité côté Arduino : si le Pi se tait 30 s, il coupe les pompes de la carte 8 MOSFET (le Pi renvoie l'état des pompes toutes les 10 s).
- Liaison : câble USB, 115200 bauds, protocole Firmata (bibliothèque `pyfirmata2`).
- Accès à distance : Tailscale (machine `hydro-info`), connexion protégée par identifiant, mot de passe et captcha (`acces.py`).

## 2. Fichiers

| Fichier | Rôle |
|---|---|
| `HYDROCODE/ARDUINO/HydroTour_Firmata/HydroTour_Firmata.ino` | Firmware : Firmata, coupure de sécurité 30 s, commande de mesure de l'EC (SysEx 0x0E) |
| `HYDROCODE/ARDUINO/HydroTour_Firmata_uno.hex` | Firmware précédent compilé (sans la commande EC), pour revenir en arrière |
| `HYDROCODE/SERVEUR/arduino.py` | Liaison avec l'Arduino : valeurs brutes (mV, ohms, sommes S1 et S2 de l'EC), pompes, I2C, DS18B20, OLED |
| `HYDROCODE/SERVEUR/pilote.py` | Décisions (cycle de la pompe, batterie, dosage) et conversions des valeurs brutes (pH, EC, niveau) |
| `HYDROCODE/SERVEUR/server.py` | Serveur Flask, base SQLite, boucle de mesure toutes les 10 s, étalonnage |
| `HYDROCODE/SERVEUR/hydrotour.html` | Dashboard |
| `HYDROCODE/SERVEUR/acces.py` | Connexion avec captcha |
| `HYDROCODE/SERVEUR/diagnostic.py`, `essai_materiel.py`, `fausses_mesures.py` | Outils de diagnostic et d'essai |
| `HYDROCODE/DEMO/` | Version de démonstration (faux Arduino) |

## 3. Matériel sur le bus I2C (arduino.py)

| Adresse | Module |
|---|---|
| 0x20 | Carte 8 MOSFET Adafruit 6318 (MCP23017) : sorties 0 pompe principale, 1 engrais A, 2 engrais B, 3 pH-, 4 alimentation de la carte pH |
| 0x48 | ADS1115 : A0 sonde pH, A2 ruban eTape |
| 0x40 | INA260 (batterie) |
| 0x68 | Horloge DS3231 ou DS1307 |
| 0x38 | DHT20 (air) |
| 0x77 | BMP280 (pression) |
| 0x3C | Écran OLED 128 x 64 |

Autres : DS18B20 (eau) sur D2, capteur de lumière sur A3.

## 4. Sonde EC en graphite (ajoutée)

- Montage : D5, R1 = 340 ohms, point J lu sur A0, sonde en graphite, D6.
- Mesure faite dans l'Arduino (une commande SysEx) : 64 allers-retours du courant, 20 µs d'attente par phase, environ 17 ms. L'Arduino renvoie deux sommes S1 et S2.
- Calcul sur le Pi (`pilote.py`) : x = S1 / S2, puis Rw = R1 + P (x - 1), puis sigma = K / Rw, ramenée à 25 °C. Valeurs par défaut : R1 = 340 ohms, P = 365 ohms, K = 0,489 cm-1, alpha = 0,02 par degré.
- Cadence : l'EC une fois par minute, le pH toutes les 10 s ; la carte pH est coupée pendant la mesure de l'EC.
- Étalonnage deux points : boutons du dashboard (ou `POST /api/etalonner?ec=1` puis `?ec=2`) dans les solutions à 1,413 et 12,88 mS/cm ; le Pi en déduit P et K.
- État : calcul testé en Python contre l'exemple du rapport ; firmware non compilé et non essayé sur la carte.

## 5. Réglages du pilote (pilote.py)

- Cycle de la pompe principale : 15 min de marche, 15 min d'arrêt. Coupure sous 30 % de batterie, reprise à 35 %.
- Niveau minimal 15 % : en dessous, pompe et dosage arrêtés.
- Dosage : 120 s de circulation avant d'avoir le droit de doser, 10 min entre deux dosages, 2 s de pH- ou 3 s de chaque engrais (A puis B) par dose, 12 doses par jour au maximum.
- Les cibles de pH et d'EC suivent le légume et son stade (tableau `PLANTS` du dashboard).

## 6. Routes du serveur

`/api/pompe`, `/api/pilotage`, `/api/culture`, `/api/etalonner`, `/api/stock`, `/api/batterie`, `/api/latest`.

## 7. Points ouverts

- Compiler et essayer la commande EC sur la vraie carte.
- Étalonner la sonde EC, puis régler les seuils d'EC de chaque légume.
- Le dossier `DEMO/` garde encore l'ancienne conversion de l'EC (sonde DFRobot).
