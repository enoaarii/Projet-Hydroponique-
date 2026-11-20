# Hypothèses de l'étude électrique (version 2)

Chaque hypothèse est à confirmer par l'étudiant (mesures M1 à M5 du protocole, ou lecture des étiquettes et notices).

## Reprises de la version 1 (données fournies)
- TE1250 : Pmax 120 Wc, Pmin 117,5 W, Vmp 17,6 V, Imp 6,8 A, Isc 7,3 A, Voc 22,0 V, fusible série max 10 A.
- Irradiation du pire mois H = 4,2 kWh/m²/j (sensibilité testée à 3,9 kWh/m²/j).
- Rendement du convertisseur 12 V vers 5 V (UBEC) : 0,83.

## Panneau
- Coefficients de température du TE1250 pris égaux à ceux du SLP055 (même technologie 36 cellules) : Voc -80 mV/°C, Isc +0,065 %/°C, Pmax -0,5 %/°C, NOCT 47 °C.
- Nombre de cellules en série du TE1250 : 36 (cohérent avec Voc = 22 V). Rsh = 200 ohm (SLP055 : 300 ohm), peu influente.
- Température de l'air en milieu de journée du pire mois : 27 °C ; éclairement de calcul de la température de cellule : 800 W/m², d'où Tc = 54 °C.
- Facteurs de pertes : salissures, sel et orientation 0,95 ; régulateur MPPT 0,95 ; câbles 0,98 ; batterie 0,95 (LiFePO4) ou 0,85 (AGM), appliqué à toute l'énergie (prudent).
- Jour très couvert : 1,2 kWh/m²/j.

## Consommation
- Raspberry Pi 3 B sans écran, charge faible : 450 mA moyen à 5 V (plage typique 260 à 500 mA au repos, plus en charge).
- Dongle Wi-Fi USB à antenne externe : 120 mA moyen (émission intermittente).
- Arduino Uno R3 : 50 mA ; capteurs : courants de fiche typiques (tableau du PDF) ; carte EC alimentée 2 s par minute environ.
- Pompe de circulation : 19 W (donnée SPEC) à 12,8 V, soit 1,48 A ; planning 6,75 h/j (SPEC).
- MOSFET de la carte 6318 : RDS(on) = 70 mohm par canal.
- Pompes doseuses : 0,30 A sous 12 V, débit 80 mL/min en charge (fiche : jusqu'à 100 mL/min à vide).
- Dosage : baisse d'EC de 0,05 mS/cm par jour dans 152 L ; sensibilité de la solution mère 0,56 mS/cm pour 1 mL/L de A + 1 mL/L de B ; 6 mL/j de pH-. Valeur d'énergie retenue : majorant de 10 commandes de 30 s par pompe et par jour (0,96 Wh/j).
- Autoconsommation du régulateur : 15 mA à 12,8 V.
- Nuit de calcul : 14 h (17 h à 7 h), avec 7 marches de 15 min de la circulation.

## Batteries
- Technologie réelle inconnue (SPEC : LiFePO4 ; version 1 : AGM). Les deux cas sont calculés.
- LiFePO4 : 12,8 V, DoD 80 %, rendement 0,95, charge admise 0,5 C, absorption 14,2 à 14,6 V.
- AGM : 12,0 V, DoD 50 %, rendement 0,85, charge conseillée 0,25 C, absorption 14,4 à 14,7 V.
- Résistance interne de la batterie 6 Ah : 60 mohm ; celle de la 17 Ah déduite par proportion inverse à la capacité (21 mohm).
- Seuil de mode sobriété proposé : 12,9 V au repos (LiFePO4), à ajuster.

## Câbles et fusibles
- Résistivité du cuivre à 60 °C : 0,0199 ohm.mm²/m.
- Longueurs : panneau vers régulateur 5 m ; régulateur vers bus 0,5 m ; bus vers chaque batterie 0,3 m ; LOAD vers bornier 0,5 m ; bornier vers pompe de circulation 3 m ; vers doseuses 1 m ; UBEC vers Pi 0,3 m.
- Chutes admises : 3 % côté PV et pompes, 1 % côté batterie, 0,5 % entre batteries, 2 % sur le 5 V.
- Régulateur à négatif commun (PV-, BAT-, LOAD- reliés) : à vérifier sur la notice du SLC-MPPT2420D (fiche exacte non trouvée).
- Tension PV maximale admise par le régulateur supérieure à 22,4 V : à vérifier sur la notice.

## Données d'exemple
- Les fichiers protocole/exemple_*.csv sont FICTIFS (journée nuageuse simulée) et servent uniquement à prouver que le script fonctionne.
