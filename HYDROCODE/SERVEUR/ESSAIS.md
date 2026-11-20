# Essais de HydroTour sur le vrai matériel

Ce guide sert à tout câbler, tester d'un coup avec `essai_materiel.py`, puis à lancer le pilotage.
Compte environ 1 h, étalonnage compris.

## 1. Préparer l'Arduino (une seule fois, depuis le PC)

1. Arduino IDE > Outils > Gérer les bibliothèques : installer **ConfigurableFirmata** (version 3.x).
2. Ouvrir `HYDROCODE/ARDUINO/HydroTour_Firmata/HydroTour_Firmata.ino` et le téléverser.
   - S'il ne compile pas, recopie le message d'erreur : on corrigera ensemble.
   - Il ne faut pas StandardFirmata ni l'ancien `HydroTour_pH.ino` : sans HydroTour_Firmata, il n'y a ni sonde de température ni sécurité.
3. Retirer le module Wi-Fi Grove (D2/D3) s'il est encore branché : D2 sert maintenant à la sonde de température.

## 2. Câbler

| Élément | Où |
|---|---|
| Carte 8 MOSFET (0x20) | I2C, Vcc 5 V ; V+ = 12 V batterie après le fusible |
| Sortie 0 | fil − de la pompe principale (son + au 12 V) |
| Sorties 1, 2, 3 | fil − des doseuses engrais A, engrais B, pH- |
| Sortie 4 | GND de la carte de la sonde pH (SEN0161-V2) |
| Sortie 5 | GND de la carte de la sonde EC (DFR0300) |
| + des cartes pH et EC | **5 V de l'Arduino**, jamais le + 12 V de la carte MOSFET |
| ADS1115 (0x48) | I2C, VDD 5 V, ADDR à GND ; A0 = signal pH, A1 = signal EC, A2 = ruban |
| Ruban eTape | 5 V → résistance 560 Ω → A2 de l'ADS → ruban → GND |
| DS18B20 | D2, résistance 4,7 kΩ entre D2 et 5 V |
| INA260 (0x40) | I2C ; VIN+ côté contrôleur de charge, VIN− côté batterie |
| Sensor Kit | DHT20, BMP280 et écran sur les ports I2C ; capteur de lumière sur A3 |

Les sondes pH et EC ne sont jamais allumées en même temps : la sonde EC envoie un courant dans l'eau qui fausse le pH.
Le pH est lu à chaque mesure, la sonde EC étant éteinte depuis au moins 5 s. Une fois par minute, le Raspberry éteint le pH, allume l'EC 2 s, la lit, puis revient au pH.

## 3. Préparer le Raspberry

```bash
pip install flask pyfirmata2 pillow
```

```bash
sudo usermod -aG dialout $USER
```

Après la deuxième commande, il faut se déconnecter puis se reconnecter. Il faut aussi copier le dossier `HYDROCODE/SERVEUR` sur le Raspberry.

## 4. Lancer l'essai (le serveur doit être arrêté)

```bash
cd SERVEUR && python essai_materiel.py
```

Les sondes pH et EC doivent être dans l'eau du réservoir. Pour les doseuses, mets leurs tuyaux dans un verre d'eau.
Le script se déroule en 6 parties et affiche OK / ÉCHEC avec un conseil pour chaque élément :

1. **Modules I2C** : chaque module répond-il à son adresse ?
2. **Capteurs** : valeurs à comparer avec la réalité (thermomètre, cacher le capteur de lumière...). pH et niveau ne sont pas encore étalonnés.
3. **Alternance pH / EC** : montre le pH avec la sonde EC éteinte puis allumée. Un grand écart montre que l'alternance est utile.
4. **Écran OLED** : il affiche « ESSAI HYDROTOUR ».
5. **Pompes** : chacune tourne 2 à 5 s. Tu réponds o/n.
6. **Sécurité** : la pompe principale tourne, le Raspberry se tait, et l'Arduino doit l'arrêter seul après 30 s.

Options : `--sans-pompes`, `--sans-securite`. Envoie-moi le **résumé** de la fin si quelque chose échoue.

## 5. Lancer le serveur et étalonner

```bash
python server.py
```

Ouvre `http://<ip-du-raspberry>:5000`, puis va dans **Paramètres** :

1. **pH** : sonde dans le tampon pH 7,00, attendre 1 min, appuyer sur « pH 7,00 ». Rincer, puis faire de même avec le tampon pH 4,00.
2. **Niveau** : réservoir vide, appuyer sur « Réservoir vide », puis réservoir plein, appuyer sur « Réservoir plein ».
3. **Légume** : vérifier qu'il est choisi, avec sa date de plantation (le Raspberry dose selon lui).

## 6. Vérifier le pilotage

| Essai | Comment | Résultat attendu |
|---|---|---|
| Cycle | Paramètres : marche 1 min, arrêt 1 min | la circulation alterne chaque minute (carte Pompes, onglet Installation) |
| Coupure batterie | coupure réglée au-dessus du % actuel (ex. 90 %, reprise 95 %) | la pompe s'arrête, alarme dans le bandeau et le journal |
| Conseil | coupure sous 30 % | message « Conseil : couper à 30 % » |
| Dose manuelle | « Doser 3 s » sur une doseuse | elle tourne 3 s, ligne dans le journal |
| Mode manuel | « Arrêter » la circulation | « automatique en pause » ; recocher « Automatique » dans Paramètres |
| Dosage auto | laisser tourner | quand l'EC est sous la cible ou le pH au-dessus : une dose, puis 10 min d'attente |
| Sécurité | débrancher l'USB pendant que la pompe tourne | arrêt après 30 s |

Remets ensuite tes vrais réglages : cycle 15/15 min, coupure 30 %, reprise 35 %.

## Pannes fréquentes

- **Arduino introuvable** : câble USB, `ls /dev/ttyACM*`, groupe dialout, serveur déjà lancé (un seul programme à la fois).
- **Rien ne répond en I2C** : SDA/SCL inversés, pas de masse commune, ou HydroTour_Firmata non téléversé.
- **Batterie en négatif au soleil** : mettre `INA_SENS = -1` dans `arduino.py`.
- **pH qui ne revient pas en 5 s** après la lecture de l'EC : augmenter `ATTENTE_PH` dans `arduino.py`.
- **Doses trop fortes ou trop faibles** : `DOSE_PH_S`, `DOSE_ENGRAIS_S` et `MELANGE_MIN` dans `pilote.py`.
