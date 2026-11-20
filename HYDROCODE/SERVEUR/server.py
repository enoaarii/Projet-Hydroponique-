"""Serveur HydroTour : le cerveau du système, prévu pour tourner sur le Raspberry Pi.

Toutes les 10 s, il lit l'Arduino (branché en USB, programme HydroTour_Firmata) : pH, EC,
températures, niveau, air, lumière, batterie, horloge. Puis pilote.py décide de la pompe
principale et des doseuses, et le serveur enregistre les mesures et écrit l'écran OLED.

Lancer :   python server.py          (pip install flask pyfirmata2 pillow)
Dashboard: http://localhost:5000   (ou http://<ip-du-raspberry>:5000 depuis un autre appareil)
Internet : port 5001, publié par Tailscale Funnel (voir INTERNET.md). Connexion obligatoire partout :
           identifiant + mot de passe partagés + captcha (acces.py).
Pompes :   POST /api/pompe?pompe=principale&on=1   (passe en manuel)
           POST /api/pompe?pompe=ph&secondes=3     (dose à la main, 30 s au plus)
Réglages : /api/pilotage   (automatique, cycle, seuils de batterie)
Légume :   /api/culture?crop=tomate&date=2026-10-20
Étalonner: POST /api/etalonner?ph=7  (ou ph=4, niveau=vide, niveau=plein, ec=1, ec=2)
  EC : sonde dans la solution à 1,413 mS/cm puis ec=1, sonde dans la solution à 12,88 mS/cm puis ec=2,
  chaque fois après au moins une minute (la mesure de l'EC a lieu une fois par minute), à 25 °C si possible.
"""
import atexit
import json
import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

import acces
import pilote as pl

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "hydrotour.db")
PERIODE = 10  # secondes entre deux mesures

# Champs attendus (ceux que lit la page). Un champ absent reste vide.
# lux : lumière en % (capteur du Sensor Kit, non étalonné en lux) ; pression en hPa.
FIELDS = ["ph", "ec", "temp_eau", "temp_air", "humidite", "lux", "niveau", "pression",
          "batt_v", "batt_a", "batt_w", "batt_pct"]
PUMPS = ["principale", "engrais_a", "engrais_b", "ph", "eau"]
DOSEUSES = ["engrais_a", "engrais_b", "ph"]
NOMS = {"engrais_a": "engrais A", "engrais_b": "engrais B", "ph": "pH-"}
PILOTAGE = ["auto", "cycle_on", "cycle_off", "batt_coupure", "batt_reprise"]  # réglés depuis Paramètres

app = Flask(__name__)
acces.init(app)
PLANTES = pl.charger_plantes(os.path.join(HERE, "hydrotour.html"))


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


with db() as c:
    c.execute(
        """CREATE TABLE IF NOT EXISTS mesures (
            t TEXT PRIMARY KEY,
            ph REAL, ec REAL, temp_eau REAL, temp_air REAL,
            humidite REAL, lux REAL, niveau REAL,
            pompes TEXT)"""
    )
    # Colonnes ajoutées après coup : on complète les bases déjà créées.
    cols = {r[1] for r in c.execute("PRAGMA table_info(mesures)")}
    for col in ("batt_v", "batt_a", "batt_w", "batt_pct", "pression"):
        if col not in cols:
            c.execute(f"ALTER TABLE mesures ADD COLUMN {col} REAL")
    # Litres d'engrais A et B disponibles, saisis depuis le dashboard au changement de légume.
    c.execute("CREATE TABLE IF NOT EXISTS stock (produit TEXT PRIMARY KEY, litres REAL, t TEXT)")
    # Réglages saisis dans Paramètres (batterie, pilotage, étalonnages).
    c.execute("CREATE TABLE IF NOT EXISTS reglages (cle TEXT PRIMARY KEY, valeur REAL)")
    # Légume cultivé et date de plantation, envoyés par le dashboard.
    c.execute("CREATE TABLE IF NOT EXISTS culture (cle TEXT PRIMARY KEY, valeur TEXT)")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def params():
    src = dict(request.args.to_dict())
    src.update(request.get_json(silent=True) or {})
    return src


def to_json(r):
    d = {"t": r["t"]}
    for k in FIELDS:
        d[k] = r[k]
    d["pompes"] = json.loads(r["pompes"] or "{}")
    return d


def reglages():
    d = dict(pl.REGLAGES)
    with db() as c:
        d.update({r["cle"]: r["valeur"] for r in c.execute("SELECT * FROM reglages")})
    return d


def regler(**valeurs):
    with db() as c:
        for k, v in valeurs.items():
            c.execute("INSERT OR REPLACE INTO reglages VALUES (?, ?)", (k, v))


def culture():
    with db() as c:
        return {r["cle"]: r["valeur"] for r in c.execute("SELECT * FROM culture")}


def stock_litres():
    with db() as c:
        return {r["produit"]: r["litres"] for r in c.execute("SELECT * FROM stock")}


def retirer_stock(conso):
    with db() as c:
        for p, litres in conso.items():
            c.execute("UPDATE stock SET litres = MAX(0, litres - ?) WHERE produit = ?", (litres, p))


# Sans Internet : (heure lue sur l'horloge de l'Arduino, time.monotonic() au moment de la lecture).
# On compte le temps écoulé depuis cette lecture : si le Raspberry se remet à l'heure entre-temps,
# l'heure du serveur ne fait pas de saut. None = on se fie à l'heure du Raspberry.
heure_ref = None
horloge_lue = False  # vrai après la première lecture de l'horloge (lue une seule fois sans Internet)


def maintenant():
    if heure_ref is None:
        return datetime.now(timezone.utc)
    rtc, t0 = heure_ref
    return rtc + timedelta(seconds=time.monotonic() - t0)


def enregistrer(row, pompes):
    t = maintenant().strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as c:
        c.execute(
            f"INSERT OR REPLACE INTO mesures (t, {', '.join(FIELDS)}, pompes) VALUES ({', '.join('?' * (len(FIELDS) + 2))})",
            (t, *[row.get(k) for k in FIELDS], json.dumps(pompes)),
        )
    print(t, {k: v for k, v in row.items() if v is not None})


carte = None    # l'Arduino, si on a pu s'y connecter
pilote = None   # les décisions (pilote.py)
brut = {}       # dernières valeurs brutes (mV, ohms), pour l'étalonnage

# ---------- Pourcentage de batterie (LiFePO4) ----------
# La tension d'une LiFePO4 bouge à peine entre 20 et 90 % : on compte plutôt les ampères-heures
# qui entrent et sortent (courant de l'INA260 × temps). On démarre d'une estimation par la
# tension au repos, et on se recale à 100 % quand le contrôleur a fini de charger.
# Capacité et tension nominale : saisies dans Paramètres (par défaut 6 Ah, 12,8 V).
def batterie():
    with db() as c:
        d = {r["cle"]: r["valeur"] for r in c.execute("SELECT * FROM reglages WHERE cle IN ('batt_ah', 'batt_v')")}
    return {"ah": d.get("batt_ah", 6.0), "v": d.get("batt_v", 12.8)}


OCV = [(12.0, 0), (12.5, 10), (12.8, 20), (12.9, 30), (13.0, 40), (13.05, 50),
       (13.1, 60), (13.2, 70), (13.3, 80), (13.35, 90), (13.6, 100)]  # pour 12,8 V : tension au repos -> %


def pct_depuis_tension(v, nominale=12.8):
    v = v * 12.8 / nominale  # une batterie 25,6 V a deux fois plus d'éléments : on ramène à 12,8 V
    if v <= OCV[0][0]:
        return 0.0
    for (v0, p0), (v1, p1) in zip(OCV, OCV[1:]):
        if v <= v1:
            return p0 + (p1 - p0) * (v - v0) / (v1 - v0)
    return 100.0


class Jauge:
    def __init__(self):
        with db() as c:  # dernière valeur réelle (hors fausses mesures), pour reprendre après un redémarrage
            r = c.execute("SELECT batt_pct FROM mesures WHERE batt_pct IS NOT NULL "
                          "AND pompes NOT LIKE '%simulation%' ORDER BY t DESC LIMIT 1").fetchone()
        self.pct = r[0] if r else None
        self.t = None

    def maj(self, v, a):
        t, b = time.monotonic(), batterie()
        if self.pct is None and abs(a) < 0.2:  # au repos : la tension donne une bonne estimation
            self.pct = pct_depuis_tension(v, b["v"])
        if self.pct is not None and self.t is not None:
            self.pct += a * min(t - self.t, 120) / 3600 / b["ah"] * 100
        # Fin de charge : 14 V et plus (pour 12,8 V) avec un courant presque nul (moins de C/20).
        if v >= 14.0 * b["v"] / 12.8 and abs(a) < b["ah"] / 20:
            self.pct = 100.0
        self.t = t
        if self.pct is None:
            return None
        self.pct = min(100.0, max(0.0, self.pct))
        return round(self.pct, 1)


jauge = None


def heure_internet():
    """Vrai si le Raspberry a pris l'heure sur Internet (NTP) depuis son démarrage."""
    try:
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() == "yes"
    except (OSError, subprocess.SubprocessError):  # pas Linux (test sur PC)
        return False


# Sans Internet, le Raspberry repart d'une heure fausse après une coupure : on prend celle
# de l'horloge à pile. Avec Internet, c'est l'inverse : on remet l'horloge à l'heure.
# Renvoie vrai quand on a l'heure d'Internet.
def synchroniser_heure():
    global heure_ref, horloge_lue
    if heure_internet():
        if heure_ref is not None or not horloge_lue:
            print("Heure d'Internet reçue :", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
        heure_ref, horloge_lue = None, True
        carte.regler_horloge(datetime.now(timezone.utc))
        print("Horloge de l'Arduino remise à l'heure d'Internet.")
        return True
    if not horloge_lue:  # une seule lecture : ensuite on compte le temps écoulé
        horloge_lue = True
        rtc = carte.lire_horloge()
        if rtc is None:
            print("Horloge de l'Arduino muette ou jamais réglée : on garde l'heure du Raspberry "
                  "en attendant Internet.")
        else:
            heure_ref = (rtc, time.monotonic())
            print(f"Heure prise sur l'horloge de l'Arduino : {rtc:%Y-%m-%d %H:%M:%S} UTC "
                  "(en attendant Internet)")
    return False


# ---------- Doseuses : une dose à la fois, la pompe s'arrête toujours à la fin ----------
dose_lock = threading.Lock()


def doser(liste):
    def run():
        with dose_lock:
            for nom, secondes in liste:
                try:
                    carte.set_pompe(nom, True)
                    time.sleep(secondes)
                finally:
                    carte.set_pompe(nom, False)
    threading.Thread(target=run, daemon=True).start()


# L'EC n'est lue qu'une mesure sur EC_TOUTES (une fois par minute) : la sonde EC, qui perturbe
# le pH, reste éteinte le reste du temps. Entre deux lectures, on garde la dernière valeur.
EC_TOUTES = 6
dernier_ec = None  # (µS/cm, heure de la lecture)


def mesurer(n):
    global dernier_ec
    r, row = reglages(), {}
    temp = carte.lire_temp_eau()
    row["temp_eau"] = temp
    an = carte.lire_analogiques(avec_ec=n % EC_TOUTES == 0)
    brut.update({k: v for k, v in an.items() if v is not None})
    if an["ph_mv"] is not None:
        print(f"[pH] tension = {an['ph_mv']:.0f} mV")
        row["ph"] = round(pl.ph_depuis_mv(an["ph_mv"], r), 2)
    if an["ec_s1"] is not None:
        x = pl.rapport_ec(an["ec_s1"], an["ec_s2"])
        print(f"[EC] S1 = {an['ec_s1']}, S2 = {an['ec_s2']}" + ("" if x is None else f", x = {x:.3f}"))
        brut["ec_x"] = x  # gardé pour l'étalonnage (/api/etalonner?ec=1 ou ec=2)
        ec = pl.ec_depuis_sommes(an["ec_s1"], an["ec_s2"], temp, r)
        if ec is not None:
            dernier_ec = (round(ec), time.monotonic())
    if dernier_ec and time.monotonic() - dernier_ec[1] < 150:
        row["ec"] = dernier_ec[0]
    if an["etape_ohm"] is not None:
        print(f"[niveau] ruban = {an['etape_ohm']:.0f} ohms")
        row["niveau"] = round(pl.niveau_depuis_ohm(an["etape_ohm"], r), 1)
    air = carte.lire_air()
    if air is not None:
        row["temp_air"], row["humidite"] = air
    row["pression"] = carte.lire_pression()
    row["lux"] = carte.lire_lumiere()
    batt = carte.lire_batterie()
    if batt is not None:
        row["batt_v"], row["batt_a"], row["batt_w"] = batt
        row["batt_pct"] = jauge.maj(batt[0], batt[1])
    return {k: v for k, v in row.items() if v is not None}


def ecran(row, page):
    """Écran OLED : toujours l'heure et le pH, puis seulement les capteurs qui répondent.
    6 lignes au plus : s'il y en a davantage, les 4 du bas changent à chaque mesure (10 s).
    La lumière (A3) n'y est pas : une entrée analogique sans capteur donne quand même une valeur."""
    f = lambda k, d=1: "--" if row.get(k) is None else f"{row[k]:.{d}f}"
    lignes = [f"Heure   {maintenant().astimezone():%H:%M}", f"pH      {f('ph', 2)}"]
    autres = []
    if row.get("ec") is not None:
        autres.append(f"EC      {f('ec', 0)} uS/cm")
    if row.get("temp_eau") is not None:
        autres.append(f"Eau     {f('temp_eau')} C")
    if row.get("niveau") is not None:
        autres.append(f"Niveau  {f('niveau', 0)} %")
    if row.get("batt_v") is not None:
        autres.append(f"Batt    {f('batt_pct', 0)} %  {f('batt_v', 2)} V")
    if row.get("temp_air") is not None:
        autres.append(f"Air     {f('temp_air')} C  {f('humidite', 0)} %")
    if row.get("pression") is not None:
        autres.append(f"Press.  {f('pression', 0)} hPa")
    if carte.carte_pompes_branchee():
        p = carte.pompes()
        autres += [f"Pompe   {'MARCHE' if p['principale'] else 'arret'}",
                   "Dose    " + (" ".join(n for n in ("engrais_a", "engrais_b", "ph") if p[n]) or "-")]
    if pilote.alertes:
        autres.append("! " + pilote.alertes[0]["texte"][:20])
    pages = [autres[i:i + 4] for i in range(0, len(autres), 4)] or [[]]
    carte.afficher(lignes + pages[page % len(pages)])


def boucle_mesures():
    n = 0
    heure_ok = False
    while True:
        try:
            # Sans l'heure d'Internet : on regarde à chaque mesure (10 s) si elle est arrivée.
            # Ensuite, une fois par heure, pour garder l'horloge de l'Arduino à l'heure.
            if not heure_ok or n % 360 == 0:
                heure_ok = synchroniser_heure()
            row = mesurer(n)
            cible = pl.cibles(PLANTES, culture(), maintenant().astimezone().date())
            retirer_stock(pilote.tic(row, reglages(), cible, stock_litres()))
            carte.rafraichir_pompes()  # au cas où l'Arduino aurait tout coupé (sécurité 30 s)
            if row:
                enregistrer(row, carte.pompes())
            ecran(row, n)
        except Exception as e:  # un capteur qui déraille ne doit pas arrêter le pilotage
            print("Erreur dans la boucle :", e)
        n += 1
        time.sleep(PERIODE)


@app.after_request
def entetes(resp):
    resp.headers["Cache-Control"] = "no-cache"  # le navigateur revérifie : toujours la dernière version du dashboard
    resp.headers["X-Frame-Options"] = "DENY"    # personne ne peut afficher le dashboard dans son site
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/")
def index():
    # La page sait qu'elle vient du Raspberry (connecté) et reçoit son légume dès l'ouverture.
    with open(os.path.join(HERE, "hydrotour.html"), encoding="utf-8") as f:
        html = f.read()
    moi = {"culture": culture()}
    moi = json.dumps(moi, ensure_ascii=False).replace("<", "\\u003c")
    return html.replace('<script id="ht-moi" type="application/json">null</script>',
                        f'<script id="ht-moi" type="application/json">{moi}</script>', 1)


# Entrée manuelle ou ancien Arduino WiFi :  /api/data?ph=6.21   (les autres champs sont facultatifs)
@app.route("/api/data", methods=["GET", "POST"])
def data():
    src = params()
    row = {k: num(src.get(k)) for k in FIELDS}
    if all(v is None for v in row.values()):
        return "aucune mesure reçue", 400
    pompes = src.get("pompes")
    if not isinstance(pompes, dict):
        pompes = {p: str(src.get("p_" + p, "0")) in ("1", "true") for p in PUMPS}
    enregistrer(row, pompes)
    return "OK"


@app.route("/api/pompe", methods=["POST"])
def pompe():
    if carte is None:
        return jsonify({"erreur": "Arduino non connecté"}), 503
    src = params()
    nom = src.get("pompe", "principale")
    if nom == "principale" and "on" in src:
        on = str(src["on"]).lower() in ("1", "true", "on")
        regler(auto=0)  # commande à la main : l'automatique se met en pause
        pilote.manuel(on)
        pilote.noter(f"Pompe principale : {'démarrage' if on else 'arrêt'} manuel, pilotage automatique en pause")
    elif nom in DOSEUSES and "secondes" in src:
        s = num(src["secondes"])
        if s is None or not 0.5 <= s <= 30:
            return jsonify({"erreur": "durée entre 0,5 et 30 s"}), 400
        doser([(nom, s)])
        pilote.noter(f"Dose manuelle : {NOMS[nom]} pendant {s:g} s", "dose")
    elif nom not in ["principale"] + DOSEUSES:
        return jsonify({"erreur": "pompe inconnue"}), 400
    p = carte.pompes()
    return jsonify({"on": p["principale"], "pompes": p, "auto": bool(reglages()["auto"])})


@app.route("/api/pilotage", methods=["GET", "POST"])
def pilotage():
    if request.method == "POST":
        src, r = params(), reglages()
        new = {k: num(src[k]) for k in PILOTAGE if k in src and num(src[k]) is not None}
        r.update(new)
        erreurs = []
        if not 1 <= r["cycle_on"] <= 240 or not 0 <= r["cycle_off"] <= 240:
            erreurs.append("Cycle : marche de 1 à 240 min, arrêt de 0 à 240 min.")
        if not 5 <= r["batt_coupure"] <= 90:
            erreurs.append("Coupure : entre 5 et 90 %.")
        if not r["batt_coupure"] + 2 <= r["batt_reprise"] <= 100:
            erreurs.append("La reprise doit être au moins 2 % au-dessus de la coupure.")
        if erreurs:
            return jsonify({"erreurs": erreurs}), 400
        if "auto" in new:
            new["auto"] = 1 if new["auto"] else 0
        regler(**new)
        print("Pilotage :", new)
    r = reglages()
    return jsonify({**{k: r[k] for k in PILOTAGE}, "auto": bool(r["auto"]),
                    "conseil": {"batt_coupure": pl.COUPURE_CONSEIL, "batt_reprise": pl.REPRISE_CONSEIL}})


@app.route("/api/culture", methods=["GET", "POST"])
def route_culture():
    if request.method == "POST":
        src = params()
        if src.get("crop") not in PLANTES:
            return jsonify({"erreur": "légume inconnu"}), 400
        with db() as c:
            c.execute("INSERT OR REPLACE INTO culture VALUES ('crop', ?)", (src["crop"],))
            c.execute("INSERT OR REPLACE INTO culture VALUES ('date', ?)", (src.get("date") or "",))
    cu = culture()
    return jsonify({**cu, "cible": pl.cibles(PLANTES, cu, maintenant().astimezone().date())})


def etalonner_ec(numero):
    """Étalonnage de l'EC en deux points : garde x1 (solution 1,413 mS/cm) puis x2 (12,88 mS/cm),
    et dès qu'on a les deux calcule P et K (formules de pilote.etalonnage_ec)."""
    x = brut.get("ec_x")
    if x is None:
        return jsonify({"erreur": "pas de mesure d'EC utilisable pour l'instant"}), 503
    regler(**{"ec_x" + numero: round(x, 4)})
    r = reglages()
    print(f"Étalonnage EC : x{numero} =", round(x, 4))
    rep = {"ec_x" + numero: round(x, 4)}
    if r.get("ec_x1") is not None and r.get("ec_x2") is not None:
        res = pl.etalonnage_ec(r["ec_x1"], r["ec_x2"], r1=r["ec_r1"])
        if res is None:
            rep["erreur"] = "étalonnage incohérent (P ou K négatif) : refaire les deux mesures"
            return jsonify(rep), 422
        p, k = res
        regler(ec_p=round(p, 2), ec_cellule=round(k, 4))
        print(f"Étalonnage EC : P = {p:.1f} ohms, K = {k:.4f} cm-1")
        rep.update({"ec_p": round(p, 2), "ec_cellule": round(k, 4)})
    return jsonify(rep)


@app.route("/api/etalonner", methods=["POST"])
def etalonner():
    src = params()
    if src.get("ph") in ("7", "4") and brut.get("ph_mv") is not None:
        cle, v = "ph_v" + src["ph"], brut["ph_mv"]
    elif src.get("niveau") in ("vide", "plein") and brut.get("etape_ohm") is not None:
        cle, v = "etape_" + src["niveau"], brut["etape_ohm"]
    elif src.get("ec") in ("1", "2"):
        return etalonner_ec(src["ec"])
    else:
        return jsonify({"erreur": "pas de mesure de ce capteur pour l'instant"}), 503
    regler(**{cle: round(v, 1)})
    print("Étalonnage :", cle, "=", round(v, 1))
    return jsonify({cle: round(v, 1)})


@app.route("/api/stock", methods=["GET", "POST"])
def stock():
    if request.method == "POST":
        src = params()
        t = maintenant().strftime("%Y-%m-%dT%H:%M:%SZ")
        with db() as c:
            for p in ("a", "b"):
                v = num(src.get(p))
                if v is not None and 0 <= v <= 1000:
                    c.execute("INSERT OR REPLACE INTO stock VALUES (?,?,?)", (p, v, t))
        print("Stock d'engrais :", {p: src.get(p) for p in ("a", "b")})
    with db() as c:
        rows = c.execute("SELECT * FROM stock").fetchall()
    d = {r["produit"]: r["litres"] for r in rows}
    d["t"] = max((r["t"] for r in rows), default=None)
    return jsonify(d)


@app.route("/api/batterie", methods=["GET", "POST"])
def reglage_batterie():
    if request.method == "POST":
        src = params()
        ah, v = num(src.get("ah")), num(src.get("v"))
        if ah is not None and 0.5 <= ah <= 1000:
            regler(batt_ah=ah)
        if v is not None and 3 <= v <= 60:
            regler(batt_v=v)
        print("Batterie :", batterie())
    return jsonify(batterie())


@app.route("/api/latest")
def latest():
    with db() as c:
        r = c.execute("SELECT * FROM mesures ORDER BY t DESC LIMIT 1").fetchone()
    d = to_json(r) if r else {"t": None, "pompes": {}}
    if carte is not None:  # état réel des pompes, sans attendre la prochaine mesure
        d["pompes"].update(carte.pompes())
        d["alertes"] = pilote.alertes
        d["evenements"] = list(pilote.evenements)
    d["auto"] = bool(reglages()["auto"])
    return jsonify(d)


@app.route("/api/history")
def history():
    hours = min(max(request.args.get("hours", 24, type=float), 0.1), 24 * 365)
    since = (maintenant() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as c:
        rows = c.execute("SELECT * FROM mesures WHERE t >= ? ORDER BY t", (since,)).fetchall()
    # au plus ~1500 points pour les courbes ; full=1 renvoie tout (export CSV du journal)
    step = 1 if request.args.get("full") == "1" else max(1, -(-len(rows) // 1500))
    return jsonify([to_json(r) for r in rows[::step]])


if __name__ == "__main__":
    try:
        from arduino import Arduino
        carte = Arduino()
        jauge = Jauge()
        pilote = pl.Pilote(carte.set_pompe, doser)
        atexit.register(carte.fermer)  # pompes coupées quand on arrête le serveur
        threading.Thread(target=boucle_mesures, daemon=True).start()
        print("Arduino connecté.")
    except Exception as e:
        print("Arduino introuvable, le serveur tourne sans :", e)
    # Port pour Internet : seulement en 127.0.0.1, Tailscale Funnel le publie en https.
    from werkzeug.serving import make_server
    internet = make_server("127.0.0.1", acces.PORT_INTERNET, app, threaded=True)
    threading.Thread(target=internet.serve_forever, daemon=True).start()
    print(f"Dashboard : http://localhost:5000  (Internet : port {acces.PORT_INTERNET} via Tailscale Funnel)")
    app.run(host="0.0.0.0", port=5000)
