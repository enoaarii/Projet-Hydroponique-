# Résumé de l'étude électrique (version 2, 1er novembre 2026)

Source : `etudes/electrique/Etude_electrique_v2.tex`, `calculs.py`, `modele_panneau.py`, `traitement_mesures.py`, `HYPOTHESES.md`, `SOURCES_A_VALIDER.md`. Cette version remplace la version 1 (octobre 2026, 32 pages).

## 1. Changements depuis la version 1

| Sujet | Version 1 | Version 2 |
|---|---|---|
| Pompes | P1 à P5 dont pompe d'appoint P5 et bac de secours | Bac principal unique de 152 L, appoint manuel. Pompes nommées par fonction : circulation, doseuses engrais A, engrais B, pH- |
| Carte de puissance | Une sortie par pompe | Carte 6318 (8 MOSFET). Circulation sur 2 canaux en parallèle (0 et 1), pertes divisées par 2 |
| Capteurs | SHT31, BH1750, ADXL345, deux eTape | DHT11, capteur de lumière analogique, LIS3DHTR (Sensor Kit), un seul eTape. ADS1115 : A0 = EC, A1 = eTape. pH sur A1 de l'Arduino |
| Batteries | Plomb AGM supposé | LiFePO4 d'après le cahier des charges, les deux cas calculés côte à côte |
| Consommation | 281 Wh/j | 226,1 Wh/j |
| Production pire mois | 336 Wh/j | 354,5 Wh/j (LiFePO4) ou 317,2 Wh/j (AGM) |
| Fusibles | 10 / 5 / 15 / 7,5 A | 10 / 5 / 15 / 4 A, plus F3 = 2 A (entrée du convertisseur 5 V) |
| Mesures | Absentes | Protocole complet M1 à M5, CSV modèles, script de traitement |

L'écart de consommation vient surtout de l'électronique : 91,8 Wh/j estimés composant par composant, contre 149,8 Wh/j en version 1 (point d'essai du convertisseur à 1 A). La mesure M2 tranchera.

## 2. Architecture de l'alimentation

Chaîne : panneau TE1250 (120 Wc), fusible F_PV, régulateur MPPT 20 A SLC-MPPT2420D, INA260 sur la ligne batterie, bus batteries (B1 6 Ah et B2 17 Ah en parallèle, un fusible chacun), sortie LOAD vers un bornier 12 V, fusible F2, convertisseur UBEC 12 V vers 5 V (fusible F3), Raspberry Pi 3 B, Arduino Uno R3 alimenté par l'USB du Pi, carte 6318 (8 MOSFET, MCP23017 0x20) qui commute les pompes.

- Tension de calcul : 12,8 V en LiFePO4 (4 éléments de 3,2 V), 12,0 V en AGM.
- L'INA260 est entre BAT+ du régulateur et le bus batteries : il mesure le courant net (charge moins décharge) et la tension batterie. Il est lu par le Pi en I2C.
- Hypothèse de schéma : régulateur à négatif commun (PV-, BAT-, LOAD- reliés). À vérifier sur la notice.
- Ordre de branchement : batteries d'abord (fusibles retirés jusqu'à la fin du câblage), panneau ensuite. Débranchement dans l'ordre inverse.

## 3. Bilan de consommation

### 3.1 Électronique en 5 V (courants moyens)

| Composant | I moyen (mA) | P à 5 V (W) | E sur 24 h (Wh) |
|---|---|---|---|
| Raspberry Pi 3 B (sans écran, charge faible) | 450 | 2,250 | 54,00 |
| Dongle Wi-Fi USB à antenne externe | 120 | 0,600 | 14,40 |
| Arduino Uno R3 | 50 | 0,250 | 6,00 |
| Base Grove (LED témoin) | 3 | 0,015 | 0,36 |
| Carte pH Gravity V2.0 | 5 | 0,025 | 0,60 |
| Carte EC DFR0300 (alimentée seulement à la lecture) | 0,2 | 0,001 | 0,02 |
| eTape 30 cm et résistance de référence | 2 | 0,010 | 0,24 |
| ADS1115 | 0,2 | 0,001 | 0,02 |
| DS18B20 | 0,5 | 0,003 | 0,06 |
| DHT11 | 0,3 | 0,002 | 0,04 |
| Capteur de lumière | 0,5 | 0,003 | 0,06 |
| Accéléromètre LIS3DHTR | 0,02 | 0,000 | 0,00 |
| Module RTC | 0,2 | 0,001 | 0,02 |
| INA260 (logique) | 1,1 | 0,006 | 0,13 |
| Carte 6318 (MCP23017 et LED) | 2 | 0,010 | 0,24 |
| **Total côté 5 V** | **635** | **3,175** | **76,20** |

Le Pi et le dongle Wi-Fi représentent 90 % de la consommation de l'électronique. Pistes d'économie : désactiver HDMI, LED, Bluetooth, et le Wi-Fi interne si le dongle est utilisé.

Rappel de résultat (énergie à puissance constante) :

$$E = P \, \Delta t$$

$$E_5 = 3{,}175\ \mathrm{W} \times 24\ \mathrm{h} = 76{,}2\ \mathrm{Wh/j}$$

### 3.2 Convertisseur 12 V vers 5 V (rendement 0,83)

$$P_{12,e} = \frac{P_5}{\eta} = \frac{3{,}175\ \mathrm{W}}{0{,}83} = 3{,}825\ \mathrm{W}$$

$$P_{\mathrm{conv}} = P_5 \left(\frac{1}{\eta} - 1\right) = 0{,}650\ \mathrm{W}$$

$$I_{12,e} = \frac{3{,}825\ \mathrm{W}}{12{,}8\ \mathrm{V}} = 0{,}299\ \mathrm{A}$$

$$E_{12,e} = 3{,}825\ \mathrm{W} \times 24\ \mathrm{h} = 91{,}8\ \mathrm{Wh/j}$$

Dont 15,6 Wh/j de pertes du convertisseur.

### 3.3 Pompe de circulation

- Planning : de 6 h à 18 h, 15 min de marche et 15 min d'arrêt ; la nuit, 15 min à 21 h, 0 h et 3 h.
- Durée de marche : 6,00 h de jour plus 0,75 h de nuit, soit 6,75 h/j.
- Puissance 19 W, courant 1,48 A sous 12,8 V.

$$E_c = 19\ \mathrm{W} \times 6{,}75\ \mathrm{h} = 128{,}25\ \mathrm{Wh/j}$$

### 3.4 Pertes MOSFET de la carte 6318

Résistance à l'état passant 70 mΩ par canal. Deux canaux en parallèle partagent le courant : pertes divisées par 2, chaque transistor chauffe 4 fois moins.

$$P_1 = 0{,}070\ \Omega \times (1{,}48\ \mathrm{A})^2 = 0{,}154\ \mathrm{W}$$

$$P_2 = \frac{0{,}070\ \Omega \times (1{,}48\ \mathrm{A})^2}{2} = 0{,}077\ \mathrm{W}$$

$$E_{\mathrm{MOS}} = 0{,}077\ \mathrm{W} \times 6{,}75\ \mathrm{h} = 0{,}52\ \mathrm{Wh/j}$$

### 3.5 Pompes doseuses

Hypothèses : 0,30 A sous 12 V (3,84 W), débit en charge 80 mL/min (mesure M5 à faire). Baisse d'EC de 0,05 mS/cm par jour dans 152 L, sensibilité 0,56 mS/cm pour 1 mL/L de A et 1 mL/L de B.

$$V_A = \frac{\Delta EC \; V_{\mathrm{bac}}}{s} = \frac{0{,}05 \times 152}{0{,}56} = 13{,}6\ \mathrm{mL/j}$$

- Engrais A : 13,6 mL/j, soit 10,2 s. Engrais B : 13,6 mL/j, soit 10,2 s. pH- : 6 mL/j, soit 4,5 s.
- Énergie estimée : 0,027 Wh/j.
- Majorant retenu (10 commandes de 30 s par pompe et par jour) : 0,96 Wh/j.

### 3.6 Autoconsommation du régulateur

15 mA sous 12,8 V : 0,192 W, soit 4,61 Wh/j.

### 3.7 Total journalier

| Poste | P (W) | Durée (h/j) | E (Wh/j) |
|---|---|---|---|
| Électronique 5 V vue du 12 V (pertes UBEC comprises) | 3,825 | 24 | 91,81 |
| dont pertes du convertisseur | 0,650 | 24 | 15,61 |
| Pompe de circulation | 19,0 | 6,75 | 128,25 |
| Pertes MOSFET circulation | 0,077 | 6,75 | 0,52 |
| Pompes doseuses (majorant) | 3,84 | 0,25 | 0,96 |
| Autoconsommation MPPT | 0,192 | 24 | 4,61 |
| **Total** | | | **226,1** |

La circulation pèse 57 % du besoin, l'électronique 41 %. Courant de repos sur le 12 V : environ 0,31 A.

## 4. Dimensionnement du panneau

### 4.1 Données d'étiquette du TE1250 (STC)

| Grandeur | Valeur |
|---|---|
| Puissance crête | 120 Wc |
| Puissance minimale garantie | 117,5 W |
| Vmp / Imp | 17,6 V / 6,8 A |
| Isc / Voc | 7,3 A / 22,0 V |
| Fusible série maximal | 10 A |

Coefficients de température pris égaux à ceux du SLP055 (même technologie 36 cellules) : tension de circuit ouvert -80 mV/°C, courant de court-circuit +0,065 %/°C, puissance -0,5 %/°C, NOCT 47 °C.

### 4.2 Modèle à une diode

Équation implicite du panneau (résolue numériquement) :

$$I = I_{ph} - I_0\left[\exp\left(\frac{V + R_s I}{a}\right) - 1\right] - \frac{V + R_s I}{R_{sh}}$$

avec $a = n N_s V_T$ et $V_T = kT/q = 25{,}7\ \mathrm{mV}$ à 25 °C.

Paramètres identifiés pour le TE1250 : $n = 1{,}063$, $R_s = 0{,}234\ \Omega$, $R_{sh} = 200\ \Omega$ (fixée), $a = 0{,}983\ \mathrm{V}$, $I_{ph} = 7{,}309\ \mathrm{A}$, $I_0 = 1{,}37 \times 10^{-9}\ \mathrm{A}$.

Validation sur le SLP055 ($n = 1{,}74$, $R_s = 0{,}143\ \Omega$) : écart au plus 3,9 % à 75 °C (0,0 % à 25 °C, -1,5 % à 47 °C, -1,9 % à 50 °C). Le modèle est légèrement pessimiste à chaud.

| Température de cellule | Vmp (V) | Imp (A) | Pmax (W) | Voc (V) |
|---|---|---|---|---|
| 25 °C | 17,60 | 6,80 | 119,7 | 22,00 |
| 47 °C | 15,82 | 6,83 | 107,9 | 20,24 |
| 50 °C | 15,58 | 6,83 | 106,3 | 20,00 |
| 54 °C | 15,26 | 6,83 | 104,2 | 19,68 |
| 75 °C | 13,60 | 6,82 | 92,8 | 18,00 |

Même à 75 °C, Vmp reste au-dessus de la tension d'une batterie 12 V vide : le MPPT peut toujours charger.

### 4.3 Température de cellule et facteur de température

$$T_c = T_a + \frac{\mathrm{NOCT} - 20}{800}\, G = 27 + \frac{47 - 20}{800} \times 800 = 54\ °\mathrm{C}$$

$$k_T = 1 - 0{,}005 \times (54 - 25) = 0{,}855$$

Sur les courbes du SLP055 le facteur serait 0,883, le modèle du TE1250 donne 0,870 : on garde 0,855 (prudent).

### 4.4 Énergie produite au pire mois

$$E_{\mathrm{th}} = P_c \, \frac{H}{G_{\mathrm{STC}}} = 120\ \mathrm{W} \times 4{,}2\ \mathrm{h/j} = 504\ \mathrm{Wh/j}$$

Facteurs de pertes : température 0,855 ; tolérance 117,5/120 = 0,979 ; salissures, sel et orientation 0,95 ; MPPT 0,95 ; câbles 0,98 ; batterie 0,95 (LiFePO4) ou 0,85 (AGM).

$$PR_{\mathrm{LFP}} = 0{,}855 \times 0{,}979 \times 0{,}95 \times 0{,}95 \times 0{,}98 \times 0{,}95 = 0{,}703$$

$$E_{\mathrm{prod,LFP}} = 504 \times 0{,}703 = 354{,}5\ \mathrm{Wh/j}$$

AGM : PR = 0,629 et 317,2 Wh/j.

| Cas | Production (Wh/j) | Marge sur 226,1 Wh/j |
|---|---|---|
| LiFePO4 | 354,5 | +57 % |
| AGM | 317,2 | +40 % |
| LiFePO4 avec H = 3,9 kWh/m²/j | 329,2 | +46 % |

L'ancien panneau SLP055 produirait 166 Wh/j : insuffisant, il ne peut servir que d'appoint.

## 5. Dimensionnement des batteries (23 Ah)

| Grandeur | LiFePO4 | Plomb AGM |
|---|---|---|
| Tension de calcul | 12,8 V | 12,0 V |
| Profondeur de décharge admise | 80 % | 50 % |
| Rendement charge et décharge | 0,95 | 0,85 |
| Courant de charge admis | 0,5 C | 0,25 C |
| Tension d'absorption | 14,2 à 14,6 V | 14,4 à 14,7 V |
| Énergie nominale | 294,4 Wh | 276,0 Wh |
| Énergie utilisable | 235,5 Wh | 138,0 Wh |

Alerte : deux technologies différentes en parallèle sont interdites. Il faut lire l'étiquette de chaque batterie, et régler le MPPT sur le profil réel.

- Nuit (14 h, de 17 h à 7 h, avec 7 marches de 15 min) : 89,6 Wh, soit 38 % de l'énergie utilisable en LiFePO4 et 65 % en AGM. Décharge réelle au matin : 30 % (LiFePO4) ou 32 % (AGM).
- Autonomie sans aucune production : 1,04 j (LiFePO4) ou 0,61 j (AGM).
- Jours très couverts (H = 1,2 kWh/m²/j) : production 101,3 Wh/j, déficit 124,9 Wh/j, soit 1,9 j supportés en LiFePO4 ; 90,6 Wh/j, déficit 135,5 Wh/j, 1,0 j en AGM.
- Deux jours sans soleil demanderaient 44 Ah (LiFePO4) ou 75 Ah (AGM).
- Mode sobriété à programmer sur la tension batterie (par exemple sous 12,9 V au repos en LiFePO4) : circulation réduite à 10 min par heure le jour, consommation vers 154 Wh/j.

Partage du courant entre deux batteries de capacités différentes (même état de charge, résistance interne inversement proportionnelle à la capacité) :

$$I_1 = I \, \frac{C_1}{C_1 + C_2}$$

- Courant de charge maximal : 8,9 A, soit 2,32 A dans B1 (0,39 C) et 6,58 A dans B2 (0,39 C). Acceptable en LiFePO4, un peu fort en AGM.
- Courant de circulation entre batteries avec 0,3 V d'écart (60 mΩ et 21 mΩ) : 3,7 A, d'où les précautions de mise en parallèle.

Précautions : même technologie et même tension ; charger chaque batterie séparément puis vérifier un écart inférieur à 0,05 V ; un fusible par batterie au plus près du +; câbles de même section et de même longueur ; raccordement en diagonale ; BMS à surveiller ; remplacer les deux batteries ensemble.

## 6. Câbles et fusibles

Section minimale :

$$S \ge \frac{2 \rho L I}{\varepsilon U}$$

avec $\rho = 0{,}0199\ \Omega\,\mathrm{mm^2/m}$ (cuivre à 60 °C).

| Liaison | L (m) | I (A) | U (V) | Chute admise | S min (mm²) | S retenue (mm²) | Chute réelle |
|---|---|---|---|---|---|---|---|
| Panneau vers MPPT | 5,0 | 6,83 | 15,3 | 3 % | 2,97 | 4 | 2,2 % |
| MPPT vers INA260 vers bus | 0,5 | 8,91 | 12,8 | 1 % | 1,38 | 4 | 0,35 % |
| Bus vers B1 | 0,3 | 2,32 | 12,8 | 0,5 % | 0,43 | 2,5 | 0,09 % |
| Bus vers B2 | 0,3 | 6,58 | 12,8 | 0,5 % | 1,23 | 2,5 | 0,25 % |
| LOAD vers bornier | 0,5 | 2,70 | 12,8 | 1 % | 0,42 | 1,5 | 0,28 % |
| Bornier vers circulation | 3,0 | 1,48 | 12,8 | 3 % | 0,46 | 1,5 | 0,92 % |
| Bornier vers doseuse | 1,0 | 0,30 | 12,8 | 3 % | 0,03 | 0,5 | 0,19 % |
| UBEC vers Pi (5 V) | 0,3 | 1,00 | 5,0 | 2 % | 0,12 | 0,5 | 0,48 % |

Chute totale panneau vers batteries : environ 2,6 % au courant maximal. Sur le 5 V du Pi, une chute supérieure à 0,25 V provoque des alertes de sous-tension : éviter un câble USB fin et long.

Fusibles (règle : $I_n \ge 1{,}25\,I_b$, calibre normalisé supérieur) :

| Fusible | Emplacement | Courant de base (A) | v1 | v2 |
|---|---|---|---|---|
| F_PV | panneau, borne + | 7,3 | 10 A | 10 A |
| F_B1 | batterie 6 Ah | 2,32 | 5 A | 5 A |
| F_B2 | batterie 17 Ah | 6,58 (8,9) | 15 A | 15 A |
| F2 | sortie LOAD | 2,68 | 7,5 A | 4 A |
| F3 | entrée UBEC | 0,30 (1,41) | absent | 2 A |

Autres vérifications : INA260 supporte 15 A en continu ; tension PV maximale à 20 °C : 22,4 V, à vérifier sous la tension PV maximale de la notice du régulateur ; chaque canal de la carte 6318 supporte 3,6 A en pointe (circulation 0,74 A par canal, doseuses 0,30 A).

## 7. Protocole de mesure (à réaliser)

- **M1** : courant de chaque pompe (multimètre 10 A en série, après 5 s de marche). Théorie : circulation 1,48 A et 19 W, doseuses 0,30 A.
- **M2** : consommation au repos et rendement de l'UBEC (INA260 pendant 10 min, contrôle au multimètre). Théorie : 0,314 A, sortie 5,0 V, 0,635 A côté 5 V, rendement 0,83.
- **M3** : bilan d'une journée (INA260 toutes les 5 min, tension et courant du panneau toutes les 30 min de 6 h à 18 h, état de la pompe).
- **M4** : étiquette et tension de chaque batterie à vide, bus fin de nuit (au moins 13,0 V), à midi en charge (13,8 à 14,6 V), pompe en marche.
- **M5** : débit des doseuses à l'éprouvette (30 s, 3 essais). Théorie : 80 mL/min.

Traitement par la méthode des trapèzes :

$$E \approx \sum_{k=0}^{N-1} (t_{k+1} - t_k)\,\frac{p_k + p_{k+1}}{2}$$

$$E_{\mathrm{cons}} = k_{\mathrm{MPPT}} \, E_{PV} - E_{\mathrm{net}}$$

Le script (`traitement_mesures.py`, CSV modèles `modele_mesures_ponctuelles.csv` et `modele_mesures_energie.csv`) tourne sur des données d'EXEMPLE fictives : production 350,5 Wh/j (écart -1,1 %), consommation 225,2 Wh/j (-0,4 %), pompe 1,52 A (+2,4 %), repos 0,33 A (+5,1 %). Si un écart réel dépasse 10 %, remplacer l'hypothèse dans `calculs.py` et relancer.

## 8. Hypothèses principales (`HYPOTHESES.md`)

- Irradiation du pire mois 4,2 kWh/m²/j (sensibilité testée à 3,9). Jour très couvert : 1,2 kWh/m²/j.
- Température de l'air en milieu de journée du pire mois : 27 °C, éclairement de calcul 800 W/m², d'où 54 °C.
- Rendement de l'UBEC 0,83. Raspberry Pi 450 mA, dongle Wi-Fi 120 mA, Arduino 50 mA.
- Technologie réelle des batteries inconnue, les deux cas sont calculés. Résistance interne de la batterie 6 Ah : 60 mΩ, 17 Ah : 21 mΩ.
- Longueurs de câbles : 5 m panneau vers régulateur, 0,5 m régulateur vers bus, 0,3 m bus vers chaque batterie, 0,5 m LOAD vers bornier, 3 m bornier vers circulation, 1 m vers doseuses, 0,3 m UBEC vers Pi.
- Les fichiers `exemple_*.csv` sont fictifs.

## 9. Points à vérifier en priorité

1. Technologie réelle des deux batteries (étiquette) et réglage du régulateur.
2. Négatif commun du régulateur et tension PV maximale (notice du SLC-MPPT2420D, fiche exacte non trouvée).
3. Étiquette réelle du TE1250 et coefficients de température.
4. Mesures M1 à M5.
