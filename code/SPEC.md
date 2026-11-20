# Cahier commun du projet HydroTour (à respecter par TOUS les agents)

Racine des livrables : /tmp/claude-0/-home-claude/e058d60e-e43f-5a93-8733-0fcc1d160534/scratchpad/projet/
Chaque agent écrit UNIQUEMENT dans son propre sous-dossier (indiqué dans sa mission).

## 1. Le projet
- Projet tutoré de L3 SPI (Sciences pour l'ingénieur), Université de la Polynésie française (UPF), 2026-2027.
  Étudiant : Enoaarii RAPARII, équipe de 3. Durée oct. 2026 -> mars/avril 2027. Site de culture : UPF (Tahiti) ; l'étudiant habite Moorea.
- Produit : tour hydroponique verticale autonome, 100 % solaire, en boucle fermée, vendable (produit fini).
- Tour : tuyau PVC vertical de 1 m, 12 plants de laitue (culture pilote : laitues / aromatiques). Le haut de la tour fait un jet d'eau (effet douche) qui retombe dans les godets et redescend par gravité dans le bac.
- Bac principal : 152 L. Pas de bac de secours, pas de pompe d'appoint : l'appoint en eau claire est fait à la main.
- Climat : Polynésie française, tropical, eau du bac qui chauffe vite au soleil (cible 18-24 °C, alarme > 28 °C).

## 2. Matériel retenu
- Énergie : panneau Total Energie TE1250 120 Wc (nouveau) ; ancien panneau Solarland SLP055-12U 55 W
  (STC : Pmax 55 W, Vmp 17,2 V, Imp 3,20 A, Voc 21,6 V, Isc 3,56 A ; coeff. Voc -80 mV/°C, Isc +0,065 %/°C, Pmax -0,5 %/°C ; NOCT 47 °C).
  Courbes I(U)/P(U) du SLP055 : Pmax ~55,0 W à 17,2 V (25 °C), ~50,1 W à 15,6 V (47 °C), ~49,5 W à 15,4 V (50 °C), ~43,8 W à 13,6 V (75 °C).
  Régulateur MPPT 20 A SLC-MPPT2420D. Batteries 12 V lithium (LiFePO4) 6 Ah et 12 V 17 Ah, en parallèle (23 Ah).
  Capteur de puissance INA260 sur la ligne batterie (charge/décharge nette). Convertisseur 12 V -> 5 V Adafruit UBEC (rendement retenu ~0,83).
- Cerveau : Raspberry Pi 3 Model B (Raspberry Pi OS Lite, accès Raspberry Pi Connect, Tailscale), dongle Wi-Fi USB à antenne externe (boîtier métallique).
- Actionneur : Arduino Uno R3 + base Grove de l'Arduino Sensor Kit (Vittascience), relié au Pi par UN câble USB (alim + données).
- Capteurs : sonde pH DFRobot Gravity Analog pH V2.0 ; sonde EC DFRobot Gravity DFR0300 (K=1) ; niveau Adafruit eTape 30 cm ;
  température eau DS18B20 ; Sensor Kit : DHT11 (T/humidité air), capteur de lumière (analogique), accéléromètre 3 axes LIS3DHTR (détection de chute) ;
  CAN ADS1115 (I2C 0x48) car les entrées analogiques de l'Uno sont occupées ; module RTC disponible.
- Pompes (commandées par la carte Adafruit 6318, 8 MOSFET, MCP23017 I2C 0x20, tout ou rien, pas de PWM) :
  - pompe de circulation : submersible 12 V sans balais 800 L/h, Hmax 5 m (LPFIDI), ~19 W, câblée sur 2 canaux en parallèle (0 et 1) pour limiter l'échauffement des MOSFET ;
  - pompes doseuses péristaltiques Adafruit 1150 (12 V) : engrais A (canal 2), engrais B (canal 3), pH- (canal 4). Pas de pH+.
- Boîtier électronique : imprimé en 3D, visé IP67, presse-étoupes.
- Énergie (étude précédente, à revérifier) : consommation ~279,5 Wh/jour ; panneau 120 Wc -> 504 Wh théoriques / 336 Wh disponibles ; fusibles F_PV=10 A, F_B1=5 A, F_B2=15 A, F2=5 A.

## 3. Fonctionnement
- Planning de la pompe de circulation (heure locale Pacific/Tahiti) :
  de 6 h à 18 h : 15 min de marche / 15 min d'arrêt (marche de hh:00 à hh:15 et de hh:30 à hh:45) ;
  la nuit : 15 min toutes les 3 h (21:00, 00:00, 03:00), puis reprise à 6 h. Total 6,75 h/jour.
- pH, EC et température de l'eau sont relevés pompe à l'arrêt (après stabilisation).
- Plages laitue : pH cible 6,0 (5,5-6,5) ; EC cible 1,4 mS/cm (1,2-1,8) à 25 °C ; T eau 18-24 °C.
- Dosage automatique en boucle fermée : engrais A + B à volumes égaux si EC trop basse ; pH- si pH trop haut. Doses petites et progressives.
- Architecture : le Raspberry Pi est le CERVEAU (logique, planning, décisions, conversions, base de données, dashboard).
  L'Arduino est uniquement l'ACTIONNEUR (lit les capteurs en brut, exécute les commandes de pompes) + sécurités matérielles non contournables :
  durée max par commande, chien de garde (watchdog), arrêt circulation si niveau bas, arrêt de tout si chute de la tour,
  mode secours autonome si le Pi se tait plus de 5 min (circulation 15/15 min seule, aucun dosage).
- Aucun agent IA dans le programme de la tour.

## 4. Protocole série Pi <-> Arduino (CONTRAT, ne pas modifier sans le signaler)
115200 bauds, lignes ASCII terminées par "\n". Pi -> Arduino = commandes ; Arduino -> Pi = réponses.
| Commande | Effet | Réponse |
|---|---|---|
| `P` | ping | `OK P` |
| `L` | lecture de tous les capteurs (bruts) | `M ph=<mV>,ec=<mV>,niv=<mV>,te=<°C>,ta=<°C>,hu=<%>,lux=<0-1023>,inc=<deg>` (valeur absente : `nan`) |
| `D <c> <ms>` | pompe c (0=circulation, 1=engrais A, 2=engrais B, 3=pH-) pendant ms ; ms=0 = arrêt de c | `OK D <c> <ms>` ou `ERR <raison>` |
| `S` | arrêt de toutes les pompes | `OK S` |
| `E` | état | `E pompes=<4 bits c0..c3>,secours=<0/1>,chute=<0/1>,niv_bas=<0/1>,inc=<deg>` |
| `N <seuil_mV> <sens>` | règle le seuil niveau bas (sens=1 : bas si mV > seuil ; -1 : bas si mV < seuil), gardé en EEPROM | `OK N` |
| `Z` | mémorise l'orientation "tour droite" de l'accéléromètre (EEPROM) | `OK Z` |
| `R` | réarme l'alarme chute (refusé si toujours inclinée) | `OK R` ou `ERR incline` |
Messages spontanés de l'Arduino : `# texte` (info pour l'humain), `! CHUTE`, `! NIVEAU_BAS`, `! NIVEAU_OK`, `! SECOURS 1`, `! SECOURS 0`.
Durées max : circulation 1 000 000 ms ; doseuses 30 000 ms. Commande au-delà : `ERR duree`.
Le Pi commande la circulation par "bail" : `D 0 90000` renouvelé toutes les ~60 s tant qu'elle doit tourner (si le Pi plante, la pompe s'arrête seule).
Toute commande reçue remet à zéro le compteur de silence (mode secours) et fait sortir du mode secours.
Seuil chute : inclinaison > 35° pendant 1 s. Brochage Uno : pH A1, lumière A3, DHT11 D3, alim EC D7 (EC alimentée seulement pendant sa lecture, jamais en même temps que le pH), DS18B20 D8, I2C A4/A5 (ADS1115 0x48 : A0=EC, A1=eTape ; MCP23017 0x20 ; LIS3DHTR 0x19).

## 5. Serveur / dashboard existants sur le Pi (dossier ~/hydro ou équivalent)
- server.py (Flask, port 5000, authentification HTTP Basic, identifiants dans les variables HYDRO_USER / HYDRO_PASS chargées depuis hydro.env, service systemd `hydrotour`),
  hydrotour.html, base SQLite hydrotour.db (table `mesures(t TEXT PRIMARY KEY, ph, ec, temp_eau, temp_air, humidite, lux, niveau REAL, pompes TEXT JSON)`, ~3800 mesures de pH à conserver).
- Routes : `/api/data` (GET/POST : champs ph, ec, temp_eau, temp_air, humidite, lux, niveau ; pompes en JSON `pompes` ou `p_<nom>=1` avec noms principale, engrais_a, engrais_b, ph, eau), `/api/latest`, `/api/history?hours=`.
- Ancien pont `pont_usb.py` (service `hydrotour-pont`) : sera REMPLACÉ par le cerveau.
- Accès distant : Tailscale (machine "hydro-info"), tunnel Cloudflare temporaire.

## 6. Règles de rédaction (documents et réponses)
- Tout en français. Ne JAMAIS utiliser le tiret cadratin (le caractère long). Utiliser des virgules, deux-points ou parenthèses.
- Documents livrés en PDF (LaTeX, pdflatex, babel french), toutes les pages numérotées ; pages de schéma en paysage, le reste en portrait.
  En-tête sur chaque page : nom du document + "Enoaarii RAPARII". Page de garde UPF (texte, pas de logo), table des matières, titres de section en bleu.
- Formules en LaTeX, présentation aérée : UNE formule par ligne, bien espacée, jamais de pavé de formules.
- Chaque formule utilisée est démontrée dans les moindres détails (sans citer d'auteur ni d'origine). Démonstrations dans des encadrés "Calcul de ..." (style libre).
- Chaque application numérique porte les unités à chaque étape.
- Ne garder que les calculs réellement utiles. Un encadré "Résumé" à la fin de chaque partie.
- Ne citer AUCUNE source dans les documents (pas de bibliographie). Les données et hypothèses venant de sources externes sont listées à part dans un fichier SOURCES_A_VALIDER.md du sous-dossier, pour validation par l'étudiant.
- Quand une donnée manque, faire une hypothèse explicite et justifiée, et la signaler dans HYPOTHESES.md.
- Chaque étude contient un chapitre "Protocole de mesure" que l'étudiant réalisera : matériel, étapes numérotées, tableaux de relevés vides à remplir,
  ET un fichier CSV modèle vide + un script Python de traitement (matplotlib, Agg) qui lit ce CSV, calcule, trace et compare aux valeurs théoriques.
  Le script doit tourner sur des données d'exemple générées (fichier exemple_*.csv clairement marqué EXEMPLE) pour preuve de fonctionnement.
- Compiler les PDF et vérifier qu'ils compilent sans erreur ; regarder au moins une page rendue (pdftoppm) pour vérifier la mise en page.
