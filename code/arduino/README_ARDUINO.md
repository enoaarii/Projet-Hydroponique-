# HydroTour : programme de l'Arduino actionneur

Sketch : `HydroTour_Actionneur/HydroTour_Actionneur.ino` (Arduino Uno R3 + base Grove du Sensor Kit).
L'Arduino lit les capteurs en brut, pilote les pompes sur ordre du Raspberry Pi et applique seul les sécurités
(chien de garde, durées max, niveau bas, chute, mode secours). Toute la logique est sur le Pi.

Taille mesurée (compilation arduino-cli, cœur AVR 1.8.6, FQBN `arduino:avr:uno`) :
flash 23 216 octets sur 32 256 (71 %), RAM globale 681 octets sur 2 048 (33 %).

## 1. Bibliothèques à installer (IDE Arduino, Outils > Gérer les bibliothèques)

| Nom exact dans le gestionnaire | Auteur | Version testée |
|---|---|---|
| Adafruit MCP23017 Arduino Library | Adafruit | 2.3.2 |
| Adafruit BusIO (installée automatiquement avec la précédente) | Adafruit | 1.17.4 |
| Adafruit ADS1X15 | Adafruit | 2.6.2 |
| OneWire | Paul Stoffregen | 2.3.8 |
| DallasTemperature | Miles Burton | 4.0.6 |
| DHT sensor library | Adafruit | 1.4.7 |
| Adafruit Unified Sensor (dépendance de DHT) | Adafruit | 1.1.15 |
| Grove-3-Axis-Digital-Accelerometer-2g-to-16g-LIS3DHTR | Seeed Studio | 1.2.4 |

Wire, EEPROM et SPI font partie du cœur "Arduino AVR Boards" (rien à installer).
Si le gestionnaire propose d'installer les dépendances, répondre "Tout installer".

## 2. Brochage

| Élément | Broche Uno | Remarque |
|---|---|---|
| Sonde pH DFRobot Gravity V2.0 | A1 | analogique, lue EC éteinte |
| Capteur de lumière Grove | A3 | valeur brute 0 à 1023 |
| DHT11 (air) | D3 | |
| Alimentation de la carte EC DFR0300 | D7 | HIGH seulement pendant la lecture EC |
| DS18B20 (eau) | D8 | résistance de tirage 4,7 kOhm vers 5 V |
| Bus I2C | A4 (SDA), A5 (SCL) | |
| ADS1115 | I2C 0x48 | voie A0 = EC, voie A1 = eTape |
| Carte pompes Adafruit 6318 (MCP23017) | I2C 0x20 | |
| Accéléromètre LIS3DHTR | I2C 0x19 | |

Pompes (canal logique du protocole -> sortie de la carte 6318) :

| Canal | Pompe | Sortie(s) 6318 |
|---|---|---|
| 0 | circulation 12 V | 0 et 1 en même temps |
| 1 | engrais A | 2 |
| 2 | engrais B | 3 |
| 3 | pH- | 4 |

Les sorties 5, 6 et 7 restent toujours à l'arrêt. Le programme suppose que les sorties 0 à 7 de la carte
correspondent aux broches GPA0 à GPA7 du MCP23017 (à vérifier sur la sérigraphie de la carte avant le premier essai,
pompes débranchées, avec une LED ou un multimètre).

## 3. Téléversement

1. Installer l'IDE Arduino 2.x, puis les bibliothèques du paragraphe 1.
2. Ouvrir `HydroTour_Actionneur/HydroTour_Actionneur.ino` (le dossier doit garder le même nom que le fichier).
3. Outils > Type de carte : "Arduino Uno". Outils > Port : le port de l'Uno (COMx sous Windows, /dev/ttyACM0 sous Linux).
4. Cliquer sur "Vérifier", puis "Téléverser".
5. Sur le Raspberry Pi, arrêter d'abord le programme qui occupe le port série (sinon le téléversement échoue),
   ou téléverser depuis le Pi avec arduino-cli :
   `arduino-cli compile -b arduino:avr:uno HydroTour_Actionneur` puis
   `arduino-cli upload -b arduino:avr:uno -p /dev/ttyACM0 HydroTour_Actionneur`.

Remarque : chaque ouverture du port série redémarre l'Uno (environ 2 s). Le Pi doit attendre la ligne `# pret`
avant d'envoyer ses commandes.

## 4. Test à la main avec le moniteur série

Moniteur série : 115200 bauds, fin de ligne "Nouvelle ligne" (ou "Les deux, NL et CR", le CR est ignoré).

Au démarrage, l'Arduino affiche des lignes d'information, par exemple :

```
# HydroTour actionneur, demarrage
# carte pompes MCP23017 OK
# ADS1115 OK
# LIS3DHTR OK
# seuil niveau non regle (commande N) : securite niveau inactive
# orientation non memorisee (commande Z) : securite chute inactive
# pret
```

Exemples de commandes (à gauche) et de réponses attendues (à droite) :

| Envoyé | Réponse attendue |
|---|---|
| `P` | `OK P` |
| `L` | `M ph=1520.3,ec=845.6,niv=1203.4,te=23.50,ta=27.0,hu=78.0,lux=612,inc=nan` (environ 2 s) |
| `E` | `E pompes=0000,secours=0,chute=0,niv_bas=0,inc=nan` |
| `Z` (tour bien droite) | `OK Z` |
| `E` | `E pompes=0000,secours=0,chute=0,niv_bas=0,inc=0.8` |
| `D 1 2000` | `OK D 1 2000` (engrais A tourne 2 s puis s'arrête seul) |
| `D 0 90000` | `OK D 0 90000` (circulation, bail de 90 s) |
| `E` | `E pompes=1000,secours=0,chute=0,niv_bas=0,inc=0.8` |
| `D 0 0` | `OK D 0 0` (arrêt de la circulation) |
| `D 1 40000` | `ERR duree` (doseuse limitée à 30 000 ms) |
| `D 0 2000000` | `ERR duree` (circulation limitée à 1 000 000 ms) |
| `S` | `OK S` |
| `N 900 -1` | `OK N` (niveau bas si eTape < 900 mV) |

Une valeur indisponible s'affiche `nan` (capteur absent ou en défaut).

Tests des sécurités :

1. Niveau bas : régler `N` avec un seuil qui place la mesure actuelle du côté "bas" (par exemple `N 5000 -1`).
   En moins de 5 s : `! NIVEAU_BAS`, la circulation est coupée et `D 0 90000` répond `ERR niveau_bas`
   (les doseuses restent autorisées). Remettre un seuil normal : `! NIVEAU_OK` dès que la mesure dépasse le seuil
   de plus de 50 mV (hystérésis).
2. Chute : après `Z`, coucher la carte accéléromètre de plus de 35° pendant plus de 1 s : `! CHUTE`, toutes les pompes
   s'arrêtent, toute commande `D` répond `ERR chute`. `R` encore penché : `ERR incline`. Redresser puis `R` : `OK R`.
3. Mode secours : ne rien envoyer pendant 5 min : `! SECOURS 1`, la circulation tourne 15 min puis s'arrête 15 min, etc.
   Aucune doseuse. Envoyer n'importe quelle commande (par exemple `P`) : `! SECOURS 0` puis `OK P`, la circulation de
   secours s'arrête.
4. Carte pompes débranchée au démarrage : message `# ERREUR carte pompes MCP23017 (0x20) absente, pompes inutilisables`
   répété toutes les 10 s, `D <c> <ms>` (ms > 0) répond `ERR pompes`. Elle est reprise automatiquement si elle réapparaît.

## 5. Détails de fonctionnement

- Réglages `N` et `Z` gardés en EEPROM (ils survivent aux coupures). Tant que `N` n'a jamais été fait, la sécurité niveau
  est inactive ; tant que `Z` n'a jamais été fait, la sécurité chute est inactive et `inc=nan`.
- Chien de garde de 8 s : si le programme se bloque, l'Uno redémarre et toutes les pompes repartent à l'arrêt.
- L'inclinaison est l'angle entre le vecteur accélération mesuré (filtré pour ignorer les vibrations de la pompe)
  et le vecteur "tour droite" mémorisé par `Z`.
- Réponses `ERR` possibles : `duree`, `chute`, `incline` (contrat), et pour les cas non prévus par le contrat :
  `syntaxe`, `canal`, `commande`, `trop_long`, `pompes` (carte absente), `niveau_bas` (circulation demandée pendant un
  niveau bas), `accel` (Z impossible car accéléromètre absent).
