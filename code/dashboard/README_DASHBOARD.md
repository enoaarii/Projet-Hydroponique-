# HydroTour : installer le nouveau dashboard sur le Raspberry Pi

Fichiers livrés : `server.py` (serveur Flask, version 2) et `hydrotour.html` (page du tableau de bord).

## IMPORTANT avant tout : l'ancien hydrotour.html

L'ancien `hydrotour.html` du Pi contenait des fonctions que nous n'avons PAS pu voir
(réglage des seuils, commande des pompes, schéma de la tour, peut-être d'autres).
La nouvelle page ne les reprend pas.

- Garde ABSOLUMENT la sauvegarde de l'ancien fichier (étape 2 ci-dessous).
- Envoie-nous cet ancien `hydrotour.html` (et l'ancien `server.py`) si tu veux qu'on fusionne ces fonctions dans la nouvelle page.

## Ce qui change

- Mêmes routes qu'avant : `/`, `/api/data` (GET/POST), `/api/latest`, `/api/history?hours=`.
- Même authentification HTTP Basic (`HYDRO_USER` / `HYDRO_PASS` dans `hydro.env`) sur toutes les routes ; le serveur refuse de démarrer si elles manquent.
- Même base `hydrotour.db`. Au premier démarrage, le serveur fait une copie automatique de la base (`hydrotour.db.avant_migration_<date>`), puis ajoute sans rien effacer :
  les colonnes `inclinaison` et `alarmes` à la table `mesures`, et une table `journal (t, type, message)`.
- Nouvelles routes : `GET/POST /api/journal` (journal des actions du cerveau) et `GET /api/export.csv` (téléchargement des mesures).
- `/api/history` renvoie au plus 1500 points (moyennes par tranche) pour ménager le Pi 3.
- Heures : comme l'ancien serveur, la colonne `t` reste en UTC au format exact `2026-10-22T08:15:03Z` (aucun réglage à faire). La conversion en heure de Tahiti (UTC-10) se fait uniquement à l'affichage et dans l'export CSV. Par sécurité, une éventuelle ligne ancienne sans `Z` est lue comme de l'UTC.

## Mise en place (commandes à taper sur le Pi)

On suppose que le dossier est `~/hydro`. Remplace-le par le bon dossier si besoin.

### 1. Aller dans le dossier du projet

```bash
cd ~/hydro
```
Se place dans le dossier où tournent `server.py`, `hydrotour.html` et `hydrotour.db`.

```bash
ls -l server.py hydrotour.html hydrotour.db hydro.env
```
Vérifie que les quatre fichiers sont bien là avant de toucher à quoi que ce soit.

### 2. Arrêter le service et faire la sauvegarde

```bash
sudo systemctl stop hydrotour
```
Arrête le serveur actuel pour que la base ne soit pas en cours d'écriture pendant la copie.

```bash
mkdir -p ~/sauvegarde_hydro_$(date +%Y%m%d)
```
Crée un dossier de sauvegarde daté du jour.

```bash
cp -p hydrotour.db server.py hydrotour.html hydro.env ~/sauvegarde_hydro_$(date +%Y%m%d)/
```
Copie la base, l'ancien serveur, l'ancienne page et le fichier d'identifiants dans ce dossier (`-p` garde les dates d'origine).

```bash
ls -l ~/sauvegarde_hydro_$(date +%Y%m%d)/
```
Vérifie que les quatre copies existent et ont la même taille que les originaux.

### 3. Copier les nouveaux fichiers

Depuis ton ordinateur (dans le dossier où tu as les nouveaux fichiers) :

```bash
scp server.py hydrotour.html <utilisateur>@hydro-info:~/hydro/
```
Envoie les deux nouveaux fichiers sur le Pi via Tailscale (remplace `<utilisateur>` par ton nom d'utilisateur sur le Pi), en écrasant les anciens qui sont déjà sauvegardés.

(Variante : copier les fichiers sur une clé USB puis `cp /media/<utilisateur>/<cle>/server.py /media/<utilisateur>/<cle>/hydrotour.html ~/hydro/`, qui fait la même chose depuis la clé.)

### 4. Tester à la main avant de relancer le service

```bash
cd ~/hydro && set -a && . ./hydro.env && set +a && python3 server.py
```
Charge les identifiants de `hydro.env` puis lance le nouveau serveur au premier plan : les lignes `migration : ...` affichent la sauvegarde automatique et les colonnes ajoutées.

Ouvre ensuite `http://hydro-info:5000/` dans le navigateur (identifiants habituels) et vérifie que l'historique de pH s'affiche. Puis tape `Ctrl+C` dans le terminal, ce qui arrête ce serveur de test.

```bash
sqlite3 hydrotour.db "SELECT COUNT(*) FROM mesures;"
```
Compte les mesures : le nombre doit être le même qu'avant (environ 3800), preuve qu'aucune ligne n'a été perdue. (Si `sqlite3` manque : `sudo apt install sqlite3`, qui installe l'outil.)

### 5. Relancer le service

```bash
sudo systemctl start hydrotour
```
Redémarre le service habituel, qui utilise maintenant le nouveau `server.py`.

```bash
systemctl status hydrotour --no-pager
```
Vérifie que le service est `active (running)`.

```bash
journalctl -u hydrotour -n 30 --no-pager
```
Affiche les 30 dernières lignes du journal du service pour repérer une éventuelle erreur.

## Revenir en arrière en cas de problème

```bash
sudo systemctl stop hydrotour
```
Arrête le nouveau serveur.

```bash
cp -p ~/sauvegarde_hydro_<date>/server.py ~/sauvegarde_hydro_<date>/hydrotour.html ~/hydro/
```
Remet l'ancien serveur et l'ancienne page (remplace `<date>` par la date du dossier de sauvegarde).

```bash
sudo systemctl start hydrotour
```
Relance le service avec l'ancienne version. La base migrée reste lisible par l'ancien serveur (les colonnes ajoutées sont simplement ignorées). Pour retrouver la base d'origine exacte : `cp -p ~/sauvegarde_hydro_<date>/hydrotour.db ~/hydro/` (service arrêté), qui remet la copie faite à l'étape 2.

## Utiliser les nouvelles routes

```bash
curl -u UTIL:MDP "http://hydro-info:5000/api/export.csv?hours=168" -o mesures_7j.csv
```
Télécharge les mesures brutes des 7 derniers jours dans un fichier CSV (séparateur virgule, point décimal, idéal pour Python). Colonnes : `t_utc` (heure UTC telle que stockée), `heure_tahiti`, `epoch`, puis les mesures, l'état des 4 pompes et les alarmes.

```bash
curl -u UTIL:MDP "http://hydro-info:5000/api/export.csv?debut=2026-11-01&fin=2026-11-15&sep=;" -o mesures_nov.csv
```
Télécharge une période précise (dates en heure de Tahiti, `fin` incluse) au format tableur français (point-virgule, virgule décimale).

Le cerveau envoie ses mesures et son journal ainsi (JSON) :

```bash
curl -u UTIL:MDP -H "Content-Type: application/json" -d '{"ph":6.1,"ec":1.4,"temp_eau":22.5,"temp_air":27,"humidite":75,"lux":600,"niveau":80,"inclinaison":2,"alarmes":["niveau_bas"],"pompes":{"circulation":1,"engrais_a":0,"engrais_b":0,"ph_moins":0}}' http://127.0.0.1:5000/api/data
```
Enregistre une mesure complète (les anciens formats `p_principale=1` etc. restent acceptés).

```bash
curl -u UTIL:MDP -H "Content-Type: application/json" -d '{"type":"dosage","message":"Engrais A+B 5 mL"}' http://127.0.0.1:5000/api/journal
```
Ajoute une ligne au journal des actions (types conseillés : `info`, `dosage`, `alarme`, `pompe`).

Noms d'alarmes reconnus par la page : `chute`, `niveau_bas`, `temp_eau_haute`, `ph_haut`, `ph_bas`, `ec_haute`, `ec_basse`, `secours`, `arduino`, `capteur` (un autre nom s'affiche tel quel).

## Réglages facultatifs (dans hydro.env)

- `HYDRO_MAX_POINTS=1500` : nombre maximal de points par graphique.
- `HYDRO_PORT=5000` : port du serveur.

## À savoir

- Les graphiques utilisent la bibliothèque uPlot chargée depuis internet (cdn.jsdelivr.net). Sans internet, la page reste utilisable : cartes de valeurs, pompes, alarmes, journal et résumés min / moyenne / max restent affichés en texte.
- La page se rafraîchit seule : dernière mesure toutes les 30 s, historique toutes les 3 min, journal toutes les minutes.
- Le serveur ne supprime jamais de données ; chaque migration crée sa propre copie de la base à côté de `hydrotour.db`.
