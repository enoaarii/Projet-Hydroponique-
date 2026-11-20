# Décisions, matériel, organisation et planning

## 1. Le projet

- Projet tutoré de L3 SPI à l'UPF : tour hydroponique autonome « HydroTour ».
- Tuteur : Anthony Utahia. Binôme : Gabriel Piritua (armoire électrique, chariot, structure et plateau du panneau).
- Tour verticale en PVC de 1 m, fournie par le tuteur, montée le 12 novembre 2026 à l'UPF.
- 12 plants de laitue sur 3 niveaux, semés le 27 octobre 2026.
- Réservoir principal de 152 L, circuit fermé, alimentation 100 % solaire.
- Dosage automatique : engrais A, engrais B, pH-. Pas de pH+. Appoint en eau claire fait à la main.
- Dépenses prises en charge par l'université.
- Travail valorisé à 1 000 XPF de l'heure, au moins 4 h par jour depuis le 20 septembre 2026.

## 2. Décisions d'architecture

| Décision | Choix retenu |
|---|---|
| Rôle du Raspberry Pi 3 B | Cerveau : planning, décisions, base SQLite, dashboard |
| Rôle de l'Arduino Uno R3 | Actionneur : lecture brute des capteurs, pompes, sécurités matérielles |
| Liaison | USB série, 115200 bauds, protocole ASCII |
| Commande de la circulation | Bail renouvelé (D 0 90000 toutes les 60 s environ) |
| Mode secours | Pi muet plus de 5 min : circulation 15 min sur 30, aucune doseuse |
| Dashboard | Flask, port 5000, authentification Basic, SQLite en UTC, affichage en heure de Tahiti |
| Accès distant | Tailscale (machine hydro-info), Raspberry Pi Connect |
| Alimentation du Pi | Chargeur USB d'allume-cigare (le UBEC 12 V vers 5 V n'est pas retenu) |
| Sonde EC | Sonde maison à deux fils de graphite à la place de la DFR0300 commerciale |
| Mesure EC | Onde carrée de moyenne nulle, environ 2,36 kHz, résistance de référence 330 ohms |
| Dosage | Boucle fermée, petites doses, engrais A et B à volumes égaux, pH- seul |
| Pas de pH+ | Le pH ne fait que monter dans ce système |
| Aucun agent IA dans le programme de la tour | Décision ferme |

## 3. Matériel

### En main

- Panneau solaire TE1250 120 Wc.
- Régulateur MPPT SLC-MPPT2420D, 20 A.
- Batteries 12 V : 6 Ah (Steco YTX7A-BS) et 17 Ah (Yuasa NP17-12I) en parallèle, soit 23 Ah. La technologie (LiFePO4 ou AGM) reste à confirmer.
- INA260 pour mesurer tension et courant.
- Pompe de circulation LPFIDI 800 L/h, 19 W.
- Raspberry Pi 3 B, Arduino Uno R3, base Grove du Sensor Kit.
- Capteurs : pH DFRobot Gravity V2.0, eTape 30 cm via ADS1115, DS18B20, DHT11, capteur de lumière, accéléromètre LIS3DHTR, RTC Grove DS1307.

### Commandé

- Commande Adafruit passée le 18 novembre 2026, pas encore reçue : carte pompes 6318 (8 MOSFET, MCP23017 à l'adresse 0x20) et doseuses 1150. Sans convertisseur 12 V vers 5 V.

### À faire ou à vérifier

- Technologie des batteries (LiFePO4 ou AGM) : change la marge de production (+57 % ou +40 %) et l'autonomie (1,04 ou 0,61 jour).
- Seconde référence du contrôleur de charge mentionnée (SLC-MT2024) à clarifier avec la référence réelle du boîtier.

## 4. Chronologie connue

| Date | Événement |
|---|---|
| 20 septembre 2026 | Début du travail quotidien sur le projet |
| 27 octobre 2026 | Semis des laitues |
| 31 octobre 2026 | État du code : .ino compile, nouveau dashboard écrit, cerveau.py compile |
| 12 novembre 2026 | Montage de la tour à l'UPF |
| 18 novembre 2026 | Commande Adafruit passée |

## 5. Livrables du projet

- Étude électrique (version 2) : dimensionnement solaire, batteries, câbles, fusibles, protocole de mesures M1 à M5.
- Étude hydraulique : point de fonctionnement, bilan d'eau, dosage, mélange, protocole de mesures.
- Étude de la sonde de conductivité et son schéma.
- Code : Arduino, Raspberry Pi, dashboard.
- Étude informatique : absente du dossier du projet, à ajouter.
- Nomenclature (Bill of Materials 4) et PDF des études électriques dans le dossier du projet.

## 6. Points ouverts

1. Mesures réelles à faire pour remplacer les hypothèses (électrique M1 à M5, hydraulique, sonde EC E1 à E6).
2. Incohérence de broche du DS18B20 (D2 dans l'étude de la sonde, D8 dans le reste) : aligner sur le câblage réel.
3. Champ `ec=` du protocole à passer en ohms.
4. Reste du code : simulateur, tests, étalonnage, configuration, service systemd, notice d'installation, fusion de l'ancien dashboard.
5. Vérifier la correspondance des sorties de la carte 6318 avec GPA0 à GPA7.
6. Réception de la commande Adafruit et essais sur le vrai matériel.
7. Confirmer la technologie des batteries.
