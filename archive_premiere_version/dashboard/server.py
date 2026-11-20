#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HydroTour : serveur du tableau de bord (Flask), version 2.

Compatible avec l'ancien server.py :
  - memes routes /, /api/data (GET/POST), /api/latest, /api/history?hours=
  - meme authentification HTTP Basic (HYDRO_USER / HYDRO_PASS), refus de demarrer sans elles
  - meme base hydrotour.db, table mesures conservee (migration NON destructive)

Ajouts :
  - colonnes mesures.inclinaison (REAL) et mesures.alarmes (TEXT JSON), par ALTER TABLE
  - table journal(t, type, message) + routes GET/POST /api/journal
  - route /api/export.csv (mesures brutes sur une periode)

Compatible Python 3.9 (Raspberry Pi OS Bullseye) et plus recent.
"""

import csv
import hmac
import io
import json
import math
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, jsonify, request, send_from_directory

ICI = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def charger_env_fichier(chemin):
    """Lit un fichier KEY=VALUE (hydro.env) sans ecraser les variables deja definies."""
    if not os.path.isfile(chemin):
        return
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, val = ligne.split("=", 1)
            cle = cle.strip()
            if cle.startswith("export "):
                cle = cle[7:].strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(cle, val)


charger_env_fichier(os.environ.get("HYDRO_ENV", os.path.join(ICI, "hydro.env")))

DB_PATH = os.environ.get("HYDRO_DB", os.path.join(ICI, "hydrotour.db"))
PAGE = os.environ.get("HYDRO_PAGE", "hydrotour.html")
PORT = int(os.environ.get("HYDRO_PORT", "5000"))
HOTE = os.environ.get("HYDRO_HOST", "0.0.0.0")
MAX_POINTS = int(os.environ.get("HYDRO_MAX_POINTS", "1500"))
MAX_HEURES = 24 * 366
# Colonne t : UTC suffixe Z, exactement comme l'ancien serveur ("2026-10-22T08:15:03Z").
FORMAT_T = "%Y-%m-%dT%H:%M:%SZ"
# Heure de Tahiti (UTC-10, pas d'heure d'ete) : affichage et export uniquement.
TAHITI = timezone(timedelta(hours=-10), "Pacific/Tahiti")

USER = os.environ.get("HYDRO_USER", "")
PASS = os.environ.get("HYDRO_PASS", "")

# Champs numeriques de la table mesures (ordre des colonnes de l'export CSV)
CHAMPS_ANCIENS = ["ph", "ec", "temp_eau", "temp_air", "humidite", "lux", "niveau"]
CHAMPS_NUM = CHAMPS_ANCIENS + ["inclinaison"]

# Normalisation des noms de pompes (anciens noms et noms du cerveau)
POMPES = ["circulation", "engrais_a", "engrais_b", "ph_moins"]
ALIAS_POMPES = {
    "circulation": "circulation", "principale": "circulation", "c0": "circulation",
    "pompe_circulation": "circulation", "0": "circulation",
    "engrais_a": "engrais_a", "a": "engrais_a", "c1": "engrais_a", "1": "engrais_a",
    "engrais_b": "engrais_b", "b": "engrais_b", "c2": "engrais_b", "2": "engrais_b",
    "ph_moins": "ph_moins", "ph": "ph_moins", "ph-": "ph_moins", "phmoins": "ph_moins",
    "c3": "ph_moins", "3": "ph_moins",
}

app = Flask(__name__)
verrou_ecriture = threading.Lock()


# --------------------------------------------------------------------------
# Format des horodatages : on imite le format deja present dans la base
# --------------------------------------------------------------------------

def vers_t(dt):
    """datetime -> texte de la colonne t (UTC, suffixe Z)."""
    return dt.astimezone(timezone.utc).strftime(FORMAT_T)


def vers_epoch(t):
    """Texte de la colonne t -> secondes epoch (float) ou None.
    Format normal : UTC avec Z. Par securite : une ligne sans fuseau est lue comme UTC
    (l'ancien serveur ecrivait en UTC), un decalage +HH:MM est respecte, un nombre est un epoch."""
    if t is None:
        return None
    s = str(t).strip()
    try:
        if re.fullmatch(r"\d+(\.\d+)?", s):
            v = float(s)
            return v / 1000.0 if v > 1e11 else v
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


def en_tahiti(ts):
    """Secondes epoch -> texte heure de Tahiti (pour l'export CSV)."""
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=TAHITI).strftime("%Y-%m-%d %H:%M:%S")


def lire_instant(valeur, naif_tahiti=False):
    """Instant fourni par le client -> datetime UTC, ou None.
    Sans fuseau : UTC, sauf naif_tahiti=True (dates tapees par l'humain pour l'export)."""
    if valeur in (None, ""):
        return None
    s = str(valeur).strip()
    if naif_tahiti and not re.fullmatch(r"\d+(\.\d+)?", s) and not re.search(r"(Z|z|[+-]\d\d:?\d\d)$", s[10:]):
        try:
            return datetime.fromisoformat(s).replace(tzinfo=TAHITI).astimezone(timezone.utc)
        except ValueError:
            return None
    e = vers_epoch(s)
    if e is None:
        return None
    return datetime.fromtimestamp(e, tz=timezone.utc)


# --------------------------------------------------------------------------
# Base de donnees et migration non destructive
# --------------------------------------------------------------------------

def connexion():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def colonnes(c, table):
    return [r["name"] for r in c.execute("PRAGMA table_info({})".format(table))]


def sauvegarde_avant_migration():
    """Copie coherente de la base avant toute modification de schema."""
    horo = datetime.now(TAHITI).strftime("%Y%m%d_%H%M%S")
    dest = DB_PATH + ".avant_migration_" + horo
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return dest


def migrer():
    """Cree ce qui manque, ne supprime jamais rien. Renvoie la liste des actions."""
    actions = []
    existe = os.path.isfile(DB_PATH) and os.path.getsize(DB_PATH) > 0
    c = connexion()
    try:
        tables = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        a_faire = []
        if "mesures" in tables:
            cols = colonnes(c, "mesures")
            for nom in CHAMPS_ANCIENS + ["inclinaison"]:
                if nom not in cols:
                    a_faire.append("ALTER TABLE mesures ADD COLUMN {} REAL".format(nom))
            for nom in ("pompes", "alarmes"):
                if nom not in cols:
                    a_faire.append("ALTER TABLE mesures ADD COLUMN {} TEXT".format(nom))
        if existe and "mesures" in tables and (a_faire or "journal" not in tables):
            actions.append("sauvegarde : " + sauvegarde_avant_migration())
        c.execute(
            "CREATE TABLE IF NOT EXISTS mesures (t TEXT PRIMARY KEY, ph REAL, ec REAL, "
            "temp_eau REAL, temp_air REAL, humidite REAL, lux REAL, niveau REAL, "
            "pompes TEXT, inclinaison REAL, alarmes TEXT)")
        for sql in a_faire:
            c.execute(sql)
            actions.append(sql)
        if "journal" not in tables:
            c.execute("CREATE TABLE IF NOT EXISTS journal (t TEXT, type TEXT, message TEXT)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_journal_t ON journal(t)")
            actions.append("CREATE TABLE journal")
        c.commit()
    finally:
        c.close()
    return actions


class Temps:
    """Expressions SQL sur la colonne t.
    Si toutes les lignes sont au format UTC 'Z' (cas normal), comparaison texte directe
    (rapide, utilise l'index de la cle primaire). S'il reste des lignes dans un autre format,
    on passe par julianday() pour comparer et trier correctement."""

    _cache = {}  # resultat du controle, calcule une seule fois par table (le Pi 3 est lent)

    def __init__(self, c, table="mesures"):
        if table not in Temps._cache:
            Temps._cache[table] = self._controler(c, table)
        self.mixte = Temps._cache[table]
        self.ordre = "julianday(t)" if self.mixte else "t"

    @staticmethod
    def _controler(c, table):
        # Les nouvelles lignes sont toujours ecrites au format Z : ce controle ne
        # change donc pas pendant que le serveur tourne.
        n = c.execute("SELECT COUNT(*) FROM {} WHERE t IS NOT NULL AND t NOT GLOB "
                      "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'"
                      .format(table)).fetchone()[0]
        return n > 0

    def apres(self, dt):
        """(clause, parametre) pour t >= dt."""
        if self.mixte:
            return "julianday(t) >= julianday(?)", vers_t(dt)
        return "t >= ?", vers_t(dt)

    def avant(self, dt):
        if self.mixte:
            return "julianday(t) < julianday(?)", vers_t(dt)
        return "t < ?", vers_t(dt)


# --------------------------------------------------------------------------
# Normalisation des valeurs recues
# --------------------------------------------------------------------------

def nombre(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "."))
    except ValueError:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def vrai(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("1", "true", "on", "oui", "marche", "yes")


def etat_pompes(brut):
    """Valeur pompes (dict, liste, '1000', texte JSON) -> dict des 4 pompes (0/1)."""
    etat = {p: None for p in POMPES}
    if brut is None or brut == "":
        return etat
    v = brut
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"[01]{4}", s):
            v = [int(ch) for ch in s]
        else:
            try:
                v = json.loads(s)
            except ValueError:
                return etat
    if isinstance(v, str) and re.fullmatch(r"[01]{4}", v.strip()):
        v = [int(ch) for ch in v.strip()]
    if isinstance(v, (list, tuple)):
        for i, p in enumerate(POMPES):
            if i < len(v):
                etat[p] = 1 if vrai(v[i]) else 0
    elif isinstance(v, dict):
        for cle, val in v.items():
            nom = ALIAS_POMPES.get(str(cle).strip().lower().replace("p_", "", 1))
            if nom:
                etat[nom] = 1 if vrai(val) else 0
    return etat


def liste_alarmes(brut):
    """Valeur alarmes (liste, dict, texte JSON ou 'a,b') -> liste de noms actifs."""
    if brut is None or brut == "":
        return []
    v = brut
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = [x for x in re.split(r"[,; ]+", v) if x]
    if isinstance(v, dict):
        return [str(k) for k, val in v.items() if vrai(val)]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x not in (None, "", 0, False)]
    if isinstance(v, str):
        return [v]
    return []


def pompes_depuis_requete(source):
    """Champ 'pompes' (JSON) ou champs p_<nom>=1 (ancien format)."""
    if "pompes" in source and source.get("pompes") not in (None, ""):
        v = source.get("pompes")
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                pass
        return v
    p = {}
    for cle in source.keys():
        if str(cle).startswith("p_"):
            p[str(cle)[2:]] = 1 if vrai(source.get(cle)) else 0
    return p or None


def ligne_vers_dict(r, maintenant=None):
    d = {"t": r["t"], "ts": vers_epoch(r["t"])}
    cles = r.keys()
    for ch in CHAMPS_NUM:
        d[ch] = nombre(r[ch]) if ch in cles else None
    brut_p = r["pompes"] if "pompes" in cles else None
    try:
        d["pompes"] = json.loads(brut_p) if isinstance(brut_p, str) else brut_p
    except ValueError:
        d["pompes"] = brut_p
    d["pompes_etat"] = etat_pompes(brut_p)
    d["alarmes"] = liste_alarmes(r["alarmes"] if "alarmes" in cles else None)
    if maintenant is not None and d["ts"] is not None:
        d["age_s"] = round(maintenant - d["ts"], 1)
    return d


# --------------------------------------------------------------------------
# Authentification HTTP Basic sur toutes les routes
# --------------------------------------------------------------------------

@app.before_request
def verifier_auth():
    a = request.authorization
    ok = (a is not None
          and hmac.compare_digest((a.username or "").encode("utf-8"), USER.encode("utf-8"))
          and hmac.compare_digest((a.password or "").encode("utf-8"), PASS.encode("utf-8")))
    if not ok:
        return Response("Authentification requise\n", 401,
                        {"WWW-Authenticate": 'Basic realm="HydroTour"'})
    return None


@app.after_request
def entetes(rep):
    rep.headers.setdefault("Cache-Control", "no-store")
    return rep


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(ICI, PAGE)


def lire_source():
    """Fusionne JSON, formulaire et parametres d'URL (comme l'ancien serveur)."""
    src = {}
    src.update(request.args.to_dict())
    if request.form:
        src.update(request.form.to_dict())
    js = request.get_json(silent=True)
    if isinstance(js, dict):
        src.update(js)
    return src


def inserer_mesure(src):
    vals = {ch: nombre(src.get(ch)) for ch in CHAMPS_NUM}
    pompes = pompes_depuis_requete(src)
    alarmes = src.get("alarmes")
    if isinstance(alarmes, str):
        try:
            alarmes = json.loads(alarmes)
        except ValueError:
            alarmes = liste_alarmes(alarmes)
    with verrou_ecriture:
        c = connexion()
        try:
            instant = lire_instant(src.get("t")) or datetime.now(timezone.utc)
            t = vers_t(instant)
            cols = ["t"] + CHAMPS_NUM + ["pompes", "alarmes"]
            params = [t] + [vals[ch] for ch in CHAMPS_NUM] + [
                json.dumps(pompes, ensure_ascii=False) if pompes is not None else None,
                json.dumps(alarmes, ensure_ascii=False) if alarmes is not None else None,
            ]
            maj = ", ".join("{0}=COALESCE(excluded.{0}, {0})".format(x) for x in cols[1:])
            base = "INSERT INTO mesures ({}) VALUES ({})".format(
                ", ".join(cols), ", ".join("?" * len(cols)))
            try:
                c.execute(base + " ON CONFLICT(t) DO UPDATE SET " + maj, params)
            except sqlite3.OperationalError:
                c.execute(base, params)  # t sans contrainte d'unicite : simple ajout
            c.commit()
        finally:
            c.close()
    return t


@app.route("/api/data", methods=["GET", "POST"])
def api_data():
    src = lire_source()
    a_des_mesures = any(k in src for k in CHAMPS_NUM + ["pompes", "alarmes"]) or any(
        str(k).startswith("p_") for k in src)
    if request.method == "GET" and not a_des_mesures:
        return api_latest()
    if not a_des_mesures:
        return jsonify({"ok": False, "erreur": "aucun champ reconnu"}), 400
    t = inserer_mesure(src)
    return jsonify({"ok": True, "t": t})


@app.route("/api/latest")
def api_latest():
    c = connexion()
    try:
        tp = Temps(c)
        r = c.execute("SELECT * FROM mesures ORDER BY {} DESC LIMIT 1".format(tp.ordre)).fetchone()
    finally:
        c.close()
    if r is None:
        return jsonify({})
    return jsonify(ligne_vers_dict(r, datetime.now(timezone.utc).timestamp()))


def heures_demandees(defaut=24.0):
    h = nombre(request.args.get("hours", defaut))
    if h is None or h <= 0:
        h = defaut
    return min(h, MAX_HEURES)


@app.route("/api/history")
def api_history():
    """Historique sous-echantillonne (moyennes par tranche), au plus MAX_POINTS points."""
    heures = heures_demandees()
    n_max = int(nombre(request.args.get("points")) or MAX_POINTS)
    n_max = max(10, min(n_max, MAX_POINTS))
    c = connexion()
    try:
        tp = Temps(c)
        debut = datetime.now(timezone.utc) - timedelta(hours=heures)
        clause, borne = tp.apres(debut)
        n = c.execute("SELECT COUNT(*) FROM mesures WHERE " + clause, (borne,)).fetchone()[0]
        if n <= n_max:
            rows = c.execute("SELECT * FROM mesures WHERE {} ORDER BY {}".format(clause, tp.ordre),
                             (borne,)).fetchall()
        else:
            largeur = heures * 86400.0 / 24.0 / n_max
            moyennes = ", ".join("AVG({0}) AS {0}".format(ch) for ch in CHAMPS_NUM)
            # MAX(julianday(t)) seul agregat min/max : t, pompes et alarmes viennent
            # de la derniere ligne de chaque tranche
            sql = ("SELECT t, MAX(julianday(t)) AS jd, {m}, pompes, alarmes FROM mesures WHERE {w} "
                   "GROUP BY CAST((julianday(t) - julianday(?)) * 86400.0 / ? AS INTEGER) "
                   "ORDER BY jd").format(m=moyennes, w=clause)
            rows = c.execute(sql, (borne, vers_t(debut), largeur)).fetchall()
    finally:
        c.close()
    return jsonify([ligne_vers_dict(r) for r in rows])


@app.route("/api/journal", methods=["GET", "POST"])
def api_journal():
    if request.method == "POST":
        js = request.get_json(silent=True)
        if js is None:
            js = lire_source()
        entrees = js if isinstance(js, list) else [js]
        lignes = []
        for e in entrees:
            if not isinstance(e, dict) or not str(e.get("message", "")).strip():
                return jsonify({"ok": False, "erreur": "champ message manquant"}), 400
            lignes.append(e)
        with verrou_ecriture:
            c = connexion()
            try:
                for e in lignes:
                    instant = lire_instant(e.get("t")) or datetime.now(timezone.utc)
                    c.execute("INSERT INTO journal (t, type, message) VALUES (?, ?, ?)",
                              (vers_t(instant), str(e.get("type") or "info")[:40],
                               str(e["message"])[:2000]))
                c.commit()
            finally:
                c.close()
        return jsonify({"ok": True, "n": len(lignes)})

    heures = heures_demandees(24.0 * 7)
    limite = int(nombre(request.args.get("limit")) or 200)
    limite = max(1, min(limite, 2000))
    type_ = request.args.get("type")
    c = connexion()
    try:
        tp = Temps(c, "journal")
        clause, borne = tp.apres(datetime.now(timezone.utc) - timedelta(hours=heures))
        sql = "SELECT t, type, message FROM journal WHERE " + clause
        params = [borne]
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        sql += " ORDER BY {} DESC, rowid DESC LIMIT ?".format(tp.ordre)
        params.append(limite)
        rows = c.execute(sql, params).fetchall()
    finally:
        c.close()
    return jsonify([{"t": r["t"], "ts": vers_epoch(r["t"]), "type": r["type"],
                     "message": r["message"]} for r in rows])


@app.route("/api/export.csv")
def api_export():
    """Mesures brutes (sans sous-echantillonnage).
    Periode : ?hours=N, ou ?debut=AAAA-MM-JJ[ HH:MM]&fin=AAAA-MM-JJ[ HH:MM] (heure de Tahiti).
    Colonnes : t (UTC, tel que stocke), heure_tahiti, epoch, puis les mesures.
    Option ?sep=; pour un tableur reglé en francais (virgule decimale)."""
    sep = request.args.get("sep", ",")
    sep = ";" if sep == ";" else ","
    c = connexion()
    try:
        tp = Temps(c)
    finally:
        c.close()
    debut = lire_instant(request.args.get("debut"), naif_tahiti=True)
    fin = lire_instant(request.args.get("fin"), naif_tahiti=True)
    if request.args.get("fin") and fin is not None and len(request.args["fin"].strip()) == 10:
        fin = fin + timedelta(days=1)  # date seule : journee complete incluse
    if debut is None:
        debut = datetime.now(timezone.utc) - timedelta(hours=heures_demandees(24.0))
    clause, borne = tp.apres(debut)
    sql = "SELECT * FROM mesures WHERE " + clause
    params = [borne]
    if fin is not None:
        clause, borne = tp.avant(fin)
        sql += " AND " + clause
        params.append(borne)
    sql += " ORDER BY " + tp.ordre

    def generer():
        c = connexion()
        try:
            tampon = io.StringIO()
            w = csv.writer(tampon, delimiter=sep, lineterminator="\n")
            w.writerow(["t_utc", "heure_tahiti", "epoch"] + CHAMPS_NUM + ["pompe_" + p for p in POMPES] + ["alarmes"])
            yield tampon.getvalue()
            for r in c.execute(sql, params):
                d = ligne_vers_dict(r)
                tampon.seek(0)
                tampon.truncate()
                ligne = [d["t"], en_tahiti(d["ts"]), "" if d["ts"] is None else int(d["ts"])]
                for ch in CHAMPS_NUM:
                    v = d[ch]
                    if v is None:
                        ligne.append("")
                    else:
                        s = repr(round(v, 4))
                        ligne.append(s.replace(".", ",") if sep == ";" else s)
                ligne += ["" if d["pompes_etat"][p] is None else d["pompes_etat"][p] for p in POMPES]
                ligne.append(" ".join(d["alarmes"]))
                w.writerow(ligne)
                yield tampon.getvalue()
        finally:
            c.close()

    nom = "hydrotour_mesures_{}.csv".format(datetime.now(TAHITI).strftime("%Y%m%d_%H%M"))
    return Response(generer(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="{}"'.format(nom)})


# --------------------------------------------------------------------------
# Demarrage
# --------------------------------------------------------------------------

def main():
    if not USER or not PASS:
        sys.stderr.write("ERREUR : HYDRO_USER et HYDRO_PASS doivent etre definies "
                         "(fichier hydro.env ou variables d'environnement). Arret.\n")
        sys.exit(1)
    for a in migrer():
        print("migration :", a, flush=True)
    app.run(host=HOTE, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
