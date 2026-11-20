# Résumé de l'étude hydraulique (novembre 2026)

Source : `etudes/hydraulique/Etude_hydraulique.tex`, `schema.tex`, `calculs.py`, `traitement_mesures.py`, cinq CSV de mesures, `HYPOTHESES.md`, `SOURCES_A_VALIDER.md`.

L'étude répond à cinq questions : comment l'eau et les solutions circulent, quel débit réel fournit la pompe, si ce débit suffit aux plants et à quelle fréquence faire l'appoint, quelle dose injecter et combien attendre avant de mesurer, comment vérifier par des mesures.

## 1. Données de départ

| Donnée | Valeur |
|---|---|
| Volume du bac | 152 L |
| Pompe de circulation | Qmax = 800 L/h, Hmax = 5 m, 12 V, 19 W |
| Planning | 6,75 h de marche par jour |
| Hauteur géométrique (surface du bac jusqu'au jet) | 1,2 m |
| Plants | 12 laitues |
| Doseuses | 12 V, 0,30 A, 80 mL/min en charge (hypothèse) |
| Cibles | pH 6,0 (5,5 à 6,5) ; EC 1,4 mS/cm (1,2 à 1,8) |

## 2. Schéma hydraulique

- La pompe est au fond du bac, loin du retour de la tour, pour aspirer une eau déjà mélangée.
- La conduite de montée longe la tour et débouche dans une pomme percée sous le chapeau : l'eau retombe en pluie dans le tuyau PVC, coule le long des parois, mouille les racines des 12 godets puis tombe dans le bac.
- Les trois doseuses débouchent au-dessus de la zone de retour : la solution concentrée est diluée et brassée par la chute d'eau, jamais injectée près des sondes.
- Les sondes pH, EC et DS18B20 plongent dans une zone calme, à l'opposé du retour. L'eTape est dans un tube tranquilliseur (tube PVC percé en bas) pour que les vagues ne faussent pas le niveau.
- pH et EC sont mesurés pompe arrêtée, après stabilisation.

## 3. Point de fonctionnement de la pompe

### Hypothèses

- Pompe : droite entre (0 ; 5 m) et (800 L/h ; 0). C'est prudent : une vraie courbe est bombée, une parabole donnerait 596 L/h au lieu de 494 L/h.
- Tuyau souple de diamètre intérieur 13 mm (1/2 pouce), lisse. Longueur de montée 1,8 m (0,4 m dans le bac, 1,0 m le long de la tour, 0,4 m de raccord).
- Pertes singulières K = 2,8 (entrée 0,5 ; deux coudes 2 x 0,9 ; pomme 0,5).
- Pomme de douche : 12 trous de 3 mm, coefficient de contraction 0,62.
- Eau à 25 °C : masse volumique 997 kg/m³, viscosité cinématique 0,893e-6 m²/s.

### Équations

$$H_p(Q) = H_{\max}\left(1 - \frac{Q}{Q_{\max}}\right)$$

$$H_r(Q) = H_g + \left(\lambda \frac{L}{D} + K\right)\frac{Q^2}{2 g A^2} + \frac{Q^2}{2 g\, a^2}$$

avec $\lambda = 0{,}316\, Re^{-1/4}$ (tuyau lisse turbulent, $4000 < Re < 10^5$), $A = 1{,}327 \times 10^{-4}\ \mathrm{m^2}$ et $a = 5{,}26 \times 10^{-5}\ \mathrm{m^2}$ (section utile de la pomme, 2,5 fois plus petite que celle du tuyau).

### Résultat (résolution numérique, vérifiée terme par terme)

| Grandeur | Valeur |
|---|---|
| Débit Q | 494 L/h (1,372e-4 m³/s) |
| Hauteur manométrique H | 1,914 m |
| Vitesse dans le tuyau | 1,03 m/s |
| Reynolds | 15 000 (turbulent) |
| Coefficient de frottement | 0,0285 |
| Pertes régulières | 0,215 m |
| Pertes singulières | 0,152 m |
| Vitesse du jet | 2,61 m/s |
| Énergie cinétique du jet | 0,347 m |
| Surpression avant la pomme | 2 860 Pa (0,029 bar) |
| Hauteur du jet vertical sans frottement | environ 35 cm |
| Puissance hydraulique | 2,57 W pour 19 W électriques (rendement global 0,135) |

$$H_r = 1{,}2 + 0{,}215 + 0{,}152 + 0{,}347 = 1{,}914\ \mathrm{m} = H_p$$

### Sensibilité au diamètre du tuyau

| D (mm) | Q avec pomme (L/h) | v (m/s) | H (m) | Q tuyau ouvert (L/h) |
|---|---|---|---|---|
| 10 | 424 | 1,50 | 2,35 | 437 |
| **13** | **494** | **1,03** | **1,91** | **531** |
| 16 | 520 | 0,72 | 1,75 | 572 |
| 19 | 531 | 0,52 | 1,68 | 590 |

Le débit reste entre 420 et 530 L/h : l'étude dépend peu du diamètre. Le tuyau de 10 mm est à éviter (1,5 m/s, bruit et pertes).

## 4. Débit par plant, renouvellement, bilan hydrique

- Débit par plant : 494 / 12 = 41 L/h (0,69 L/min). Besoin minimal retenu : 2 L/h par godet pendant la marche (critère réel visuel : toutes les racines mouillées). Le débit est 20 fois le besoin, même si un quart seulement de l'eau touche les racines. Aucune vanne de réglage n'est nécessaire.
- L'eau absorbée par un plant est négligeable devant le débit qui le traverse (0,1 %) : la composition ne varie pas entre le haut et le bas.
- Temps de renouvellement du bac :

$$\tau = \frac{V}{Q} = \frac{152}{494} = 0{,}308\ \mathrm{h} = 18{,}5\ \mathrm{min}$$

Le bac passe 21,9 fois par jour dans la tour. Une marche de 15 min en brasse environ 80 %.

### Bilan hydrique

Hypothèses : consommation de pointe 0,30 L/j par plant (10 derniers jours avant récolte), moyenne de cycle 0,15 L/j, évaporation sur 0,10 m² de surface libre à 5 mm/j, hauteur d'eau 0,40 m (surface du bac 0,38 m²).

$$E_{\mathrm{evap}} = 0{,}10\ \mathrm{m^2} \times 5\ \mathrm{mm/j} \times 1\ \mathrm{L/(mm\,m^2)} = 0{,}5\ \mathrm{L/j}$$

| Cas | Consommation | Intervalle d'appoint (baisse de 10 % = 15,2 L = 4 cm) |
|---|---|---|
| Pointe | 4,1 L/j (1,1 cm/j de niveau) | 3,7 jours |
| Moyenne de cycle | 2,3 L/j | 6,6 jours |

$$T = \frac{V_{\mathrm{tol}}}{C} = \frac{15{,}2}{4{,}1} = 3{,}7\ \mathrm{j}$$

Absence de 2 semaines : 57,4 L consommés en pointe (32,2 L en moyenne), le bac descend à 94,6 L (38 % de baisse, 15 cm). Dans le pire cas (sels non prélevés), l'EC monte à 2,25 mS/cm. Tolérance dépassée : acceptable seulement en début de cycle, ou bac plein au maximum avant le départ avec un seuil de niveau bas au-dessus de l'aspiration. En pointe, un passage d'appoint au moins tous les 3 à 4 jours.

## 5. Dosage des engrais et du pH-

### Débit et durée de commande

$$t = \frac{v_{\mathrm{dose}}}{q_d}$$

- 10 mL d'engrais = 7 500 ms. 4 mL de pH- = 3 000 ms. La limite de l'Arduino est 30 000 ms par commande (40 mL).

### Effet sur l'EC

Hypothèse : 1 mL/L de A et 1 mL/L de B augmentent l'EC de 0,56 mS/cm. La cible 1,4 mS/cm demande 2,5 mL/L de chaque solution, soit 380 mL de A et 380 mL de B pour remplir le bac.

$$\Delta EC = \beta \, \frac{v_A}{V} = 0{,}56 \times \frac{10}{152} = 0{,}037\ \mathrm{mS/cm}$$

Un appoint de 15,2 L d'eau claire fait baisser l'EC de 10 % (0,14 mS/cm), compensé par 4 doses.

### Effet sur le pH

Hypothèses : bac doseur pH- à 0,5 mol/L d'acidité (par exemple un pH- à base d'acide phosphorique à 81 % dilué : environ 36 mL par litre d'eau), tampon phosphates seuls (1,6 mmol/L de phosphore, pKa 7,2), carbonates ignorés (effet majoré, donc prudent).

$$\alpha = \frac{1}{1 + 10^{\,\mathrm{p}K_a - \mathrm{pH}}}$$

$$\beta_P = \ln 10 \; C_P \; \alpha (1 - \alpha)$$

$$\Delta \mathrm{pH} = -\frac{c_a}{\beta_P}$$

| pH du bac | α | β_P (mmol/L par unité de pH) | Baisse pour 4 mL |
|---|---|---|---|
| 6,5 | 0,166 | 0,511 | 0,026 |
| 6,3 | 0,112 | 0,366 | 0,036 |
| 6,0 | 0,059 | 0,206 | 0,064 |
| 5,5 | 0,020 | 0,071 | 0,186 |

Plus le pH descend, moins il est tamponné : ne jamais doser de pH- sous 6,0, faute de pH+ pour corriger.

### Mélange

Fraction du bac jamais passée par la pompe : $f(t) = e^{-t/\tau}$. Après 1, 2 et 3 renouvellements, 63 %, 86 % et 95 % du bac est mélangé. 95 % après 3 x 18,5 = 55 min de pompage, soit 4 périodes de marche, c'est-à-dire 2 h de jour. Les arrêts ne comptent pas.

### Réglages conseillés pour le cerveau

| Réglage | Valeur |
|---|---|
| Moment de mesure | 5 min après l'arrêt de la pompe (hh:20 et hh:50), de 6 h à 18 h |
| Moment d'injection | 1 min après le démarrage de la marche suivante (hh:31 ou hh:01) |
| Seuil de dose engrais | EC à 25 °C inférieure à 1,30 mS/cm |
| Dose engrais | `D 1 7500` (10 mL de A), puis 60 s plus tard `D 2 7500` (10 mL de B), effet +0,037 mS/cm |
| Seuil de dose pH- | pH supérieur à 6,3 |
| Dose pH- | `D 3 3000` (4 mL), au moins 5 min après les engrais |
| Ordre | corriger l'EC d'abord, le pH ensuite |
| Délai entre deux doses du même type | 2 h de jour |
| Maximum par jour | 4 doses d'engrais (40 mL de A et 40 mL de B, +0,15 mS/cm), 4 doses de pH- (16 mL) |
| Nuit | aucune dose |
| Blocages | pas de dose si niveau bas, eau à plus de 28 °C, ou mesure incohérente |
| Alarmes | EC supérieure à 1,8 (diluer à la main) ; pH inférieur à 5,5 ; maximum journalier atteint |
| Étalonnage | durée (ms) = volume (mL) x 60 000 / débit mesuré (mL/min) |

Cohérence : les plants prélèvent environ 10,3 mL/j de A (pointe) ou 5,8 mL/j (moyenne), soit une ou deux doses par jour. Le maximum de 4 doses laisse une marge d'un facteur 4.

## 6. Protocole de mesure (à réaliser)

Matériel : seau gradué de 10 L, chronomètre, mètre ruban, règle graduée, éprouvette de 50 mL, sonde EC étalonnée, accès au dashboard. Relevés dans les CSV (séparateur point-virgule) traités par `traitement_mesures.py` (option `--exemple` pour des données fictives).

| Mesure | Fichier | Valeur attendue |
|---|---|---|
| Débit réel de la pompe (seau de 10 L, 5 essais, pomme remise) | `mesure_debit.csv` | 494 L/h |
| Hauteur du jet (chapeau retiré, 5 photos devant le mètre) | `mesure_jet.csv` | 35 cm |
| Consommation journalière (règle et tension de l'eTape à 7 h, 7 jours au moins) | `mesure_niveau.csv` | 2,3 L/j en moyenne, 4,1 L/j en pointe |
| Débit des doseuses (7 500, 15 000 et 30 000 ms, pompes A, B, pH-) | `mesure_doseuse.csv` | 80 mL/min |
| Temps de mélange et effet d'une dose (EC à 0, 2, 5, 10, 15, 20, 30, 45, 60 min de pompage cumulé) | `mesure_melange.csv` | +0,037 mS/cm, constante 18,5 min |

Le script donne aussi l'étalonnage de l'eTape (mV en fonction des cm) et les durées de dose corrigées.

## 7. Conclusion

La pompe de 800 L/h débite environ 494 L/h sous 1,9 m dans ce circuit, soit 20 fois le besoin des plants, et le bac de 152 L est brassé en 18,5 min. Appoint manuel d'environ 15 L tous les 4 jours en pointe (7 jours en moyenne). Le dosage par petites doses (10 mL d'engrais, 4 mL de pH-) espacées de 2 h corrige l'EC et le pH sans dépassement. Les mesures permettront de remplacer les hypothèses (diamètre du tuyau, pomme, débit des doseuses, concentrations).

## 8. Données externes à valider (aucune n'est citée dans le PDF)

Pompe LPFIDI (diamètre d'embout, courbe), loi de frottement des tuyaux lisses, coefficients de pertes singulières, propriétés de l'eau à 25 °C, consommation d'eau d'une laitue (0,2 à 0,3 L/j adulte), évaporation en climat tropical humide (4 à 6 mm/j), besoin en débit des tours, débit de la doseuse Adafruit 1150, sensibilité EC des engrais (notice de l'engrais), teneur en phosphore et pKa2 de l'acide phosphorique, concentration du pH- du commerce, alcalinité de l'eau du robinet de l'UPF.
