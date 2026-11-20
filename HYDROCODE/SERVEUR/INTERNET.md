# Mettre HydroTour sur Internet

Le site est protégé par un seul identifiant et un seul mot de passe partagés, plus un captcha.
Toute personne qui a le mot de passe a tous les droits. La connexion est demandée partout, à la maison comme depuis Internet.

Le serveur écoute sur deux ports :

- **5000** : réseau de la maison (`http://<ip-du-raspberry>:5000`).
- **5001** : seulement en interne (127.0.0.1). **Tailscale Funnel** le publie sur Internet, en https.

## 1. Premier lancement

```bash
cd HYDROCODE/SERVEUR
python server.py
```

Au premier lancement, le terminal affiche l'accès provisoire. Il est aussi écrit dans `PREMIER_ACCES.txt` :

```
Accès provisoire : identifiant « hydrotour », mot de passe « k7mq3xra9p »
```

1. Ouvre `http://<ip-du-raspberry>:5000`, connecte-toi avec ces valeurs et recopie le captcha.
2. Va dans **Paramètres > Accès** et choisis ton identifiant et ton mot de passe (8 caractères au moins).
   Pour confirmer, il faut donner le mot de passe actuel. `PREMIER_ACCES.txt` s'efface alors tout seul.
3. Donne l'identifiant et le mot de passe aux personnes qui doivent accéder à la tour.

**Changer le mot de passe** (par exemple si quelqu'un ne doit plus avoir accès) : passe par Paramètres > Accès.
Tous les autres appareils sont alors déconnectés.

**Mot de passe oublié** : sur le Raspberry, arrête le serveur, puis lance

```bash
python acces.py secours
```

Cette commande crée un nouveau mot de passe provisoire, affiché et écrit dans `PREMIER_ACCES.txt`. L'identifiant ne change pas.

**Ne partage jamais** `secret.key` ni `PREMIER_ACCES.txt`. `secret.key` signe les sessions : si tu le supprimes, tout le monde est déconnecté.

## 2. Tailscale Funnel (adresse https fixe, rien à ouvrir sur la box)

**Tailscale déjà installé** (avec un ancien `tailscale serve` ou `funnel` sur le port 5000) : il faut le repointer
sur 5001. Sinon, les requêtes d'Internet arrivent sur le port de la maison et passent pour locales.

```bash
tailscale serve status
sudo tailscale serve reset
sudo tailscale funnel --bg 5001
```

La première commande montre la configuration actuelle. `reset` efface l'ancienne publication (serve et funnel).
Passe ensuite directement aux vérifications plus bas.

**Première installation**, sur le Raspberry :

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Ouvre le lien affiché et connecte-toi : un compte Tailscale gratuit suffit, par exemple avec le Gmail du projet.
Dans la console Tailscale, onglet *Machines*, tu peux renommer le Raspberry en `hydrotour`.

Ensuite, publie le port 5001 :

```bash
sudo tailscale funnel --bg 5001
```

La première fois, la commande donne un lien pour autoriser HTTPS et Funnel. Ouvre-le, accepte, puis relance la commande.
Elle affiche alors l'adresse publique, du genre `https://hydrotour.tail1234.ts.net`.

Vérifications :

```bash
tailscale funnel status
```

Ouvre ensuite l'adresse sur ton téléphone **en 4G** (Wi-Fi coupé) : la page de connexion doit s'afficher.

Pour arrêter la publication sur Internet :

```bash
sudo tailscale funnel --https=443 off
```

## Ce qui est protégé

- Sans connexion, seuls la page de connexion et le captcha répondent. Tout le reste renvoie vers la connexion.
- `/api/data` (ancien Arduino WiFi, `fausses_mesures.py`) n'est accepté que depuis le réseau de la maison, jamais par Internet.
- Le captcha change à chaque essai, et chaque image ne sert qu'une fois. Le nombre d'essais n'est pas limité.
- Le mot de passe est stocké haché, jamais en clair. La session dure 30 jours, ou jusqu'à « Se déconnecter ».
