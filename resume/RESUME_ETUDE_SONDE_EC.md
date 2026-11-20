# Résumé de l'étude de conception de la sonde de conductivité (version 1.0, novembre 2026)

Source : `etudes/sonde_ec/Etude_sonde_conductivite.tex` et `Schema_sonde_conductivite.tex` (schéma de référence HT-EC-01, révision 1.0, 02/11/2026).

Cette étude remplace la sonde du commerce (DFRobot DFR0300) de l'étude électrique v2 par une sonde fabriquée, lue directement par l'Arduino Uno R3, sans carte d'interface. Le rôle de la sonde : donner au Pi la quantité d'engrais dans le bac pour décider des doses de A et B.

## 1. Cahier des charges

| Exigence | Valeur ou contrainte |
|---|---|
| Grandeur | conductivité ramenée à 25 °C, en mS/cm |
| Plage (hypothèse) | 0,5 à 3,0 mS/cm |
| Point de fonctionnement | 1,5 mS/cm (plage laitue 1,2 à 1,8, à valider) |
| Électronique | Arduino Uno R3 seul, une résistance, deux électrodes |
| Courant par broche | inférieur à 20 mA |
| Mise en place | entièrement immergée dans le bac de 152 L |
| Électrodes | matériau inerte, sans libération d'ions métalliques |
| Mesure | pompe de circulation à l'arrêt, sonde pH non perturbée |
| Température de l'eau | environ 25 à 32 °C, compensée avec la sonde de température d'eau (DS18B20) |

## 2. Principe physique

La résistance mesurée entre deux électrodes se relie à la conductivité par la constante de cellule $K$ (ne dépend que de la géométrie). Démonstration avec deux plaques parallèles : $\vec{j} = \sigma \vec{E}$, $I = \sigma E S$, $U = E d$.

$$R = \frac{K}{\sigma}, \qquad K = \frac{d}{S}$$

$$\sigma = \frac{K}{R}$$

La conductivité ne dépend pas de la taille de la sonde : multiplier la surface par $n$ divise $K$ et $R$ par $n$, donc $\sigma$ est inchangée. Ce qui compte, c'est que la surface active reste constante (donc sonde entièrement immergée, longueur exposée fixée par le support).

## 3. Matériaux

| Matériau | Avantages | Inconvénients |
|---|---|---|
| Cuivre | bon conducteur, soudable | libère des ions Cu²⁺ toxiques, rejeté |
| Inox 316 | solide | corrosion lente à l'anode, s'encrasse |
| **Graphite (mines de crayon)** | inerte, aucun ion métallique, très bon marché | fragile, non soudable, liant d'argile |

- Électrodes retenues : mines de 2 mm de diamètre, dureté B à 4B (plus de graphite, conduisent mieux).
- Support imprimé en 3D en PETG ou ASA (pas de PLA, qui se dégrade en immersion dans une eau tiède). Surface immergée recouverte d'époxy car les couches imprimées ne sont pas étanches.
- Mines serrées par une vis M2 plaquant une cosse (le graphite ne se soude pas). Tête (vis, cosses, fils) noyée dans l'époxy après la réussite des essais E1 et E2. Câble par presse-étoupe lui aussi noyé. Connecteur démontable (bornier ou JST-XH 2 broches) côté boîtier, jamais sous l'eau.

## 4. Alimentation en alternatif

En continu, la polarisation (couche d'ions contre chaque électrode) et l'électrolyse (dioxygène à l'anode qui oxyde le carbone en CO₂) abîment la sonde.

Seuil de décomposition de l'eau :

$$E^\circ = \frac{\Delta_r G^\circ}{n F} = \frac{237{,}1 \times 10^3}{2 \times 96\,485} = 1{,}23\ \mathrm{V}$$

La sonde voit environ 2,5 V : l'électrolyse aurait lieu en continu, donc il faut inverser le courant.

Principe : la sonde (en série avec $R_{\mathrm{ref}}$) est entre deux broches numériques D5 et D6 qui basculent en opposition (pont en H logiciel).

| Phase | D5 | D6 | Tension appliquée | Action |
|---|---|---|---|---|
| 1 : mesure | 5 V | 0 V | +5 V | lecture de A0 |
| 2 : inversion | 0 V | 5 V | -5 V | aucune lecture |
| Repos | haute impédance | haute impédance | aucune | aucun courant |

$$\langle U \rangle = 5\ \mathrm{V} \cdot \frac{t_1 - t_2}{t_1 + t_2} = 0 \iff t_1 = t_2$$

- Chaque phase : 100 µs de stabilisation plus environ 112 µs de lecture (à mesurer avec `micros()`), soit 212 µs. Période 424 µs, fréquence 2,36 kHz.
- Une mesure : 200 périodes, 84,8 ms. Pour une mesure toutes les 15 min : sonde sous tension environ 0,01 % du temps (9,4e-5).

## 5. Dimensionnement de la sonde

Constante de cellule de deux tiges parallèles de rayon $a$, d'entraxe $D$ et de longueur exposée $L$ (hypothèse $D \gg a$) :

$$K = \frac{\ln(D/a)}{\pi L}$$

Cotes retenues : $a = 1\ \mathrm{mm}$, $D = 10\ \mathrm{mm}$, $L = 15\ \mathrm{mm}$.

$$K = \frac{\ln 10}{\pi \times 1{,}5\ \mathrm{cm}} = 0{,}489\ \mathrm{cm^{-1}}$$

Contrôle avec la formule exacte (argument cosinus hyperbolique) : 0,486 cm⁻¹, écart de 0,6 %. La valeur réelle sera obtenue par étalonnage.

| σ (mS/cm) | R_w (Ω) |
|---|---|
| 0,5 | 977 |
| 1,5 | 326 |
| 3,0 | 163 |

La sonde reste à au moins 2 à 3 cm des parois, de la sonde pH et de la pompe.

## 6. Circuit de mesure

Pont diviseur : $R_{\mathrm{ref}}$ en série avec la sonde $R_w$, tension lue au point J par l'entrée A0 (CAN 10 bits).

$$R_w = R_{\mathrm{ref}}\,\frac{V}{V_{cc} - V}$$

Avec la référence du CAN égale à Vcc, la mesure est ratiométrique (indépendante de la tension USB) :

$$R_w = R_{\mathrm{ref}}\,\frac{N}{1024 - N}$$

Choix de $R_{\mathrm{ref}}$ : la sensibilité $\partial V / \partial R_w$ est maximale pour $R_{\mathrm{ref}} = R_w$ (alors $V = V_{cc}/2$).

- Valeur normalisée E12 retenue : 330 Ω, tolérance 1 %, 0,25 W (écart de 1,2 % à l'optimum de 326 Ω).
- Courant maximal en haut de plage : 5 V / (330 + 163) Ω = 10,1 mA, inférieur à 20 mA. Condition générale : $R_{\mathrm{ref}} + R_w \ge 250\ \Omega$.

| σ (mS/cm) | R_w (Ω) | V (V) | N | I (mA) |
|---|---|---|---|---|
| 0,5 | 977 | 3,74 | 766 | 3,8 |
| 1,5 | 326 | 2,48 | 509 | 7,6 |
| 3,0 | 163 | 1,65 | 338 | 10,1 |

Résolution au point de fonctionnement :

$$\frac{\mathrm{d}R_w}{R_w} = \mathrm{d}N \, \frac{1024}{N(1024 - N)} = \frac{1024}{509 \times 515} = 3{,}9 \times 10^{-3}$$

Soit 0,39 % par pas, environ 0,006 mS/cm à 1,5 mS/cm. La moyenne sur 200 lectures réduit encore le bruit.

Brochage : D5 vers $R_{\mathrm{ref}}$ puis électrode E1, A0 au point J entre $R_{\mathrm{ref}}$ et E1, D6 vers électrode E2. Inchangées : D0 et D1 (USB), la broche du DS18B20 avec sa résistance de tirage de 4,7 kΩ (voir ci-dessous), A1 (pH), A3 (lumière), A4 et A5 (I2C). Incohérence à corriger : l'étude (texte du brochage et schéma intégré) place le DS18B20 sur D2, alors que `Schema_sonde_conductivite.tex`, `SPEC.md` et `README_ARDUINO.md` le placent sur D8. À aligner sur le câblage réel. Point J soudé côté boîtier, jamais dans l'eau. Aucun fil de la sonde vers la masse.

Schéma électrique : une feuille paysage, repères 1 à 11 (rail +5 V, masse, D5, R_ref, point J, A0, sonde graphite, D6, résistance de tirage 4,7 kΩ, broche 1-Wire, DS18B20), normes IEC 61082-1, 60617 et 81346, cartouche HT-EC-01.

## 7. Erreurs et compensation

### Résistance interne des broches

Avec $r_h = r_l = 25\ \Omega$ (à confirmer) :

$$R_{\mathrm{app}} = g\,R_w + r_0, \qquad g = \frac{R_{\mathrm{ref}}}{R_{\mathrm{ref}} + r_h}, \qquad r_0 = g\,r_l$$

$$g = 0{,}930, \qquad r_0 = 23{,}2\ \Omega$$

| σ (mS/cm) | R_w (Ω) | R_app (Ω) | Erreur sur R |
|---|---|---|---|
| 0,5 | 977 | 932 | -4,6 % |
| 1,5 | 326 | 326 | +0,1 % |
| 3,0 | 163 | 175 | +7,2 % |

Erreur presque nulle au point de fonctionnement, plusieurs pour cent aux bords : corrigée par l'étalonnage électronique.

### Température

$$\sigma_{25} = \frac{\sigma_T}{1 + \alpha\,(T - 25\ °\mathrm{C})}$$

Hypothèse $\alpha = 0{,}02\ °\mathrm{C^{-1}}$. Exemple : 1,65 mS/cm à 30 °C donne 1,50 mS/cm à 25 °C. Sans compensation, l'erreur serait de 10 % pour 5 °C d'écart.

### Autres causes

- Interférence avec la sonde pH : pH lu quand D5 et D6 sont en haute impédance, sonde EC à au moins 3 cm de la sonde pH.
- Encrassement : nettoyage et contrôle de K toutes les 2 à 4 semaines.
- Bulles d'air sur les mines : mesure pompe arrêtée, sonde inclinée ou tapotée à l'installation.
- Parois proches : étalonnage dans un récipient d'au moins 10 cm de diamètre, sonde centrée.

## 8. Étalonnage

1. **Électronique** : deux résistances précises $R_1 = 150\ \Omega$ et $R_2 = 1\ \mathrm{k\Omega}$ à la place de la sonde.

$$g = \frac{R_{\mathrm{app},2} - R_{\mathrm{app},1}}{R_2 - R_1}, \qquad r_0 = R_{\mathrm{app},1} - g\,R_1, \qquad R_w = \frac{R_{\mathrm{app}} - r_0}{g}$$

Exemple : 162,7 Ω et 952,8 Ω donnent g = 0,930 et r₀ = 23,2 Ω.

2. **Sonde au KCl** : solution à 0,01 mol/L (0,746 g de KCl séché dans une fiole de 1 L, masse molaire 74,55 g/mol), conductivité de référence 1,413 mS/cm à 25 °C (à valider). $K = \sigma_{\mathrm{ref}}\,R_w$. Exemple avec 345 Ω : K = 0,488 cm⁻¹.

3. **Coefficient de température**, de préférence dans la solution nutritive elle-même :

$$\alpha = \frac{\sigma_2 - \sigma_1}{\sigma_1\,(T_2 - 25) - \sigma_2\,(T_1 - 25)}$$

Exemple : 1,413 mS/cm à 25 °C et 1,555 mS/cm à 30 °C donnent α = 0,020 par °C.

## 9. Programme

Note : cette section décrit la première version (l'Arduino renvoie la résistance apparente en ohms, protocole à lignes de texte). Dans le code installé sur le Pi, l'Arduino renvoie deux sommes S1 et S2 et le Pi calcule la résistance de l'eau (voir `RESUME_CODE.md`, partie 4).

L'Arduino reste actionneur : il mesure la résistance apparente et l'envoie. Le Pi fait les conversions.

Fonction Arduino `lireECohm()` (remplace `lireECmV()`) : broches D5 et D6 en sortie, 200 cycles (D5 haut et D6 bas, 100 µs, lecture de A0, inversion, 212 µs), puis retour en haute impédance, renvoie $R_{\mathrm{REF}}\,N/(1024 - N)$ ou NAN si N supérieur ou égal à 1020 ou inférieur ou égal à 3. Durée de mesure 85 ms, très inférieure au chien de garde de 8 s.

Modifications associées : supprimer `BROCHE_EC_ALIM` (D7) et la lecture EC par l'ADS1115 ; appeler `lireECohm()` dans `commandeLecture()` après le pH (jamais pendant) ; le champ `ec=` du protocole série passe en ohms et non en millivolts (mettre à jour `SPEC.md` et `cerveau.py`).

Conversion sur le Pi, dans l'ordre :

$$R_w = \frac{R_{\mathrm{app}} - r_0}{g}$$

$$\sigma_T\ [\mathrm{mS/cm}] = 1000 \times \frac{K}{R_w}$$

$$\sigma_{25} = \frac{\sigma_T}{1 + \alpha\,(T - 25)}$$

Les paramètres g, r₀, K et α sont dans le fichier de configuration du Pi, mis à jour à chaque étalonnage.

## 10. Protocole de fabrication et d'essais

**Fabrication** : imprimer le support en PETG (entraxe 10 mm, logements de mine de 2,1 mm, longueur exposée 15 mm, logements de vis M2 et de presse-étoupe) ; insérer les mines, serrer les vis sur les cosses, sortir le câble ; vérifier au multimètre la continuité fil et mine et l'absence de contact entre mines (à sec : résistance infinie) ; époxyer la surface du corps sans toucher aux 15 mm de mine exposée (tête noyée seulement après E1 et E2) ; câbler R_ref et le point J côté boîtier.

| Essai | Contenu | Critère |
|---|---|---|
| E1 | étalonnage électronique avec 150 Ω et 1 kΩ (valeurs exactes au multimètre, 5 mesures) | g et r₀ |
| E2 | constante de cellule dans le KCl (au moins 0,5 L, sans bulles, 3 mesures) | K |
| E3 | coefficient de température dans la solution nutritive à 25 °C puis environ 30 °C (bain-marie) | α |
| E4 | linéarité : KCl dilué de moitié | conductivité environ moitié, écart de plus de 5 % signale un problème |
| E5 | électrolyse et interférence : 100 mesures de suite | aucune bulle ; écart de pH avec et sans sonde EC inférieur à 0,05 |
| E6 | suivi dans le temps : K dans le KCl toutes les 2 à 4 semaines | dérive de plus de 5 % : nettoyage puis nouvel étalonnage |

Points à vérifier avant mise en service : durée réelle de `analogRead` (mesurée avec `micros()`, délai de la phase 2 ajusté pour t₁ = t₂) ; D5 et D6 en INPUT après chaque mesure ; plage de conductivité de la laitue, conductivité de référence du KCl et coefficient α à valider.

## 11. Synthèse

| Élément | Valeur retenue |
|---|---|
| Électrodes | 2 mines graphite de 2 mm, B à 4B |
| Géométrie | entraxe 10 mm, longueur exposée 15 mm |
| Constante de cellule prévue | 0,489 cm⁻¹ (à étalonner) |
| Résistance de l'eau | 163 à 977 Ω pour 3,0 à 0,5 mS/cm |
| Résistance de référence | 330 Ω, 1 % |
| Brochage | D5, A0, D6 |
| Alimentation | carré ±5 V à moyenne nulle, environ 2,4 kHz |
| Courant maximal | 10,1 mA par broche |
| Résolution | 0,39 % par pas |
| Temps sous tension | environ 0,01 % |
| Corrections | électronique (g, r₀), cellule (K), température (α) |

Conclusion : une sonde en graphite, lue directement par l'Arduino avec une seule résistance de 330 Ω, couvre la plage utile de la laitue avec une résolution meilleure que 0,5 %. L'alimentation en carré de moyenne nulle évite polarisation et électrolyse, et la mesure est indépendante de la tension USB.

## 12. Remerciements de l'étude (contexte)

Étude rédigée au format ENO. Remerciements au tuteur, Monsieur Anthony Utahia. Projet mené seul depuis septembre 2026 : choix et câblage du matériel, programmes de l'Arduino et du Raspberry Pi, dashboard, essais et rapports. Difficulté citée : la perturbation de la sonde pH par la sonde EC.
