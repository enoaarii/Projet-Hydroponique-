# Sources à valider (hors PDF)

| Donnée | Valeur utilisée | Source consultée | Remarque |
|---|---|---|---|
| Courbes I(U)/P(U) du SLP055 | 55,0 W à 17,2 V (25 °C) ... 43,8 W à 13,6 V (75 °C) | image fournie par l'étudiant (caracteristique_puissance_SLP055.png) | sert à valider le modèle à une diode |
| Étiquette TE1250 | 120 Wc, Vmp 17,6 V, Imp 6,8 A, Isc 7,3 A, Voc 22,0 V, Pmin 117,5 W, fusible 10 A | étude électrique version 1 de l'étudiant (données transmises par le coordinateur) | aucune fiche technique en ligne trouvée pour « TE1250 » ; à vérifier sur l'étiquette réelle, avec les coefficients de température |
| Irradiation Tahiti | pire mois 4,2 kWh/m²/j (version 1) | étude version 1 ; ordre de grandeur cohérent avec https://www.e3s-conferences.org/10.1051/e3sconf/201910701003 (14 MJ/m²/j en juin, soit 3,9 kWh/m²/j, jusqu'à 21 MJ/m²/j en novembre) | la valeur de juin publiée (3,9) est un peu plus basse que 4,2 : sensibilité calculée dans le PDF ; PVGIS et NASA POWER non accessibles depuis l'outil |
| Pompe péristaltique Adafruit 1150 | 12 V, 200 à 300 mA, jusqu'à 100 mL/min | https://www.adafruit.com/products/1150 | débit en charge à mesurer (M5) |
| Carte Adafruit 6318 | MOSFET AO3406, 30 V, 70 mohm, 3,6 A crête, diodes de roue libre, 3 à 24 V | https://www.adafruit.com/product/6318 | |
| UBEC Adafruit | entrée 6 à 16 V, sortie 5 V 3 A (5 A crête), rendement 82 à 89 % d'après le tableau de la page | https://www.adafruit.com/product/1385 | rendement 0,83 retenu (version 1) |
| Raspberry Pi 3 | environ 1,9 W au repos (mesure publiée pour le 3 B+), 5,2 W en pleine charge | https://raspberry.tips/en/raspberrypi-tutorials/raspberry-pi-power-consumption-update-2026-all-models-compared | 450 mA retenu pour le 3 B avec activité réseau ; à mesurer (M2) |
| Régulateur Solarland MPPT | autoconsommation 15 mA ou moins, rendement crête 97 %, PV jusqu'à 70 V (famille SLC-MPPT1012/2012/2024) | https://www.mrsolar.com/content/pdf/SolarLand/Controllers/MPPT.pdf | fiche du modèle exact SLC-MPPT2420D non trouvée : vérifier tension PV max, profil LiFePO4, négatif commun |
| Caractéristiques LiFePO4 / AGM | DoD, rendements, courants et tensions de charge (tableau partie 5) | valeurs usuelles de fabricants | à remplacer par celles des étiquettes des deux batteries |
| Résistivité et coefficient du cuivre | 0,0172 ohm.mm²/m à 20 °C ; 0,00393 /°C | valeurs de référence | |
| Composants de capteurs | courants typiques (DS18B20, DHT11, ADS1115, LIS3DHTR, INA260, MCP23017) | fiches techniques des fabricants (non relues une à une) | ensemble inférieur à 15 mA, influence négligeable |
