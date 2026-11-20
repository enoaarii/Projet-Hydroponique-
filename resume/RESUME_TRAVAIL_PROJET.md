# HydroTour : résumé du travail effectué

Index du projet. Chaque étude et chaque partie du code ont leur propre résumé détaillé.

## 1. Le projet en bref

Tour hydroponique verticale autonome (projet tutoré L3 SPI, UPF) : 12 plants de laitue, réservoir de 152 L, circuit fermé, alimentation 100 % solaire, dosage automatique des engrais A et B et du pH-, surveillance par un tableau de bord. Un capteur maison de conductivité remplace la sonde commerciale.

## 2. Architecture en une page

- Raspberry Pi 3 B : cerveau (mesures, décisions, base SQLite, dashboard Flask).
- Arduino Uno R3 : carte d'entrées/sorties (Firmata), coupe les pompes si le Pi se tait 30 s.
- Liaison USB 115200 bauds, protocole Firmata.
- Matériel principal : panneau 120 Wc, MPPT 20 A, batteries 23 Ah, pompe 800 L/h 19 W, doseuses, carte pompes Adafruit 6318.

## 3. Résultats clés

| Domaine | Résultat |
|---|---|
| Consommation | 226,1 Wh/j |
| Production | 354,5 Wh/j (LFP) ou 317,2 Wh/j (AGM) |
| Marge | +57 % ou +40 % |
| Autonomie | 1,04 ou 0,61 jour |
| Point de fonctionnement hydraulique | 494 L/h sous 1,914 m |
| Débit par plant | 41 L/h |
| Temps de renouvellement | 18,5 min |
| Consommation d'eau | 4,1 L/j au pic, 2,3 L/j en moyenne |
| Appoint | tous les 3,7 ou 6,6 jours |
| Sonde EC | constante de cellule 0,489 cm-1, résolution 0,39 % |

## 4. Avancement

- Études électrique, hydraulique et sonde EC : rédigées.
- Code du Pi (Firmata, server.py, pilote.py, arduino.py) : en service. Sonde EC graphite ajoutée dans le code (`HYDROCODE/`), à compiler et essayer sur la carte.
- Première version (cerveau.py) : rangée dans `archive_premiere_version/`.
- Matériel : tour montée le 12 novembre 2026, commande Adafruit en attente.

## 5. Points ouverts

Mesures réelles, incohérence de broche DS18B20 (D2 contre D8), champ EC en ohms, reste du code, technologie des batteries à confirmer. Détail dans `RESUME_DECISIONS_ET_MATERIEL.md`.

## 6. Autres fichiers

| Fichier | Contenu |
|---|---|
| `RESUME_ETUDE_ELECTRIQUE.md` | Étude électrique complète |
| `RESUME_ETUDE_HYDRAULIQUE.md` | Étude hydraulique complète |
| `RESUME_ETUDE_SONDE_EC.md` | Étude de la sonde de conductivité |
| `RESUME_CODE.md` | Code installé sur le Pi : fichiers, bus I2C, sonde EC, réglages, routes, points ouverts |
| `RESUME_DECISIONS_ET_MATERIEL.md` | Décisions, matériel, organisation, points ouverts |
