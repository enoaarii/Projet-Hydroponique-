"""Accès HydroTour : un seul identifiant + mot de passe partagés, avec un captcha.

Qui connaît le mot de passe a tous les droits. La connexion est demandée partout,
sur le Wi-Fi de la maison comme depuis Internet.

Au tout premier lancement, le serveur crée l'identifiant « hydrotour » avec un mot de passe provisoire,
qu'il écrit dans le terminal et dans PREMIER_ACCES.txt. Change-les dans Paramètres > Accès : le fichier
s'efface alors tout seul.

Le serveur écoute sur deux ports : 5000 pour le réseau de la maison, et 5001 (127.0.0.1 seulement)
pour Internet, publié par Tailscale Funnel (voir INTERNET.md).

Mot de passe oublié :  python acces.py secours   (sur le Raspberry : nouveau mot de passe provisoire)
"""
import hashlib
import io
import ipaddress
import os
import random
import re
import secrets
import sqlite3
import sys
import threading
import time
from datetime import timedelta

from flask import Blueprint, Response, g, jsonify, redirect, render_template_string, request, session
from werkzeug.security import check_password_hash, generate_password_hash

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "hydrotour.db")
SECRET = os.path.join(HERE, "secret.key")
PREMIER = os.path.join(HERE, "PREMIER_ACCES.txt")
PORT_INTERNET = 5001  # celui que Tailscale Funnel publie sur Internet
ALPHA = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sans 0/O, 1/I/L : lisible sur le captcha et à recopier

bp = Blueprint("acces", __name__)
rnd = random.SystemRandom()


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def lire():
    with db() as c:
        return c.execute("SELECT * FROM acces WHERE id = 1").fetchone()


def version(r):
    """Change avec l'identifiant ou le mot de passe : les autres appareils connectés sont alors déconnectés."""
    return hashlib.sha256((r["identifiant"] + r["hash"]).encode()).hexdigest()[:16]


def provisoire():
    """Mot de passe provisoire dans PREMIER_ACCES.txt (au premier lancement, ou après un oubli)."""
    mdp = "".join(rnd.choice(ALPHA.lower()) for _ in range(10))
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS acces (id INTEGER PRIMARY KEY CHECK (id = 1), identifiant TEXT, hash TEXT)")
        r = c.execute("SELECT identifiant FROM acces WHERE id = 1").fetchone()
        ident = r["identifiant"] if r else "hydrotour"
        c.execute("INSERT OR REPLACE INTO acces VALUES (1, ?, ?)", (ident, generate_password_hash(mdp)))
    with open(PREMIER, "w", encoding="utf-8") as f:
        f.write(f"Accès HydroTour\nIdentifiant : {ident}\nMot de passe provisoire : {mdp}\n\n"
                "Change-les dans Paramètres > Accès. Ce fichier s'efface tout seul ensuite.\n")
    print(f"Accès provisoire : identifiant « {ident} », mot de passe « {mdp} » (aussi dans PREMIER_ACCES.txt)")


def init(app):
    """Branche l'accès sur l'application Flask : clé secrète, sessions de 30 jours, garde des pages."""
    if not os.path.exists(SECRET):
        with open(SECRET, "w") as f:
            f.write(secrets.token_hex(32))
    with open(SECRET) as f:
        app.secret_key = f.read().strip()
    app.permanent_session_lifetime = timedelta(days=30)
    # Lax : un autre site ne peut pas envoyer de commande (POST) avec ta session.
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_NAME="hydrotour")
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS acces (id INTEGER PRIMARY KEY CHECK (id = 1), identifiant TEXT, hash TEXT)")
    if lire() is None:
        provisoire()
    elif os.path.exists(PREMIER):
        print("Le mot de passe provisoire n'a pas encore été changé : voir PREMIER_ACCES.txt")
    app.register_blueprint(bp)
    app.before_request(garde)


def connecte():
    if "ok" not in g:
        r = lire()
        g.ok = r is not None and session.get("v") == version(r)
    return g.ok


def local():
    """Vrai pour une requête du réseau de la maison (pas venue d'Internet par Tailscale Funnel)."""
    if str(request.environ.get("SERVER_PORT")) == str(PORT_INTERNET):
        return False
    try:
        ip = ipaddress.ip_address(request.remote_addr or "")
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


PUBLIC = {"acces.connexion", "acces.captcha"}


def garde():
    ep = request.endpoint
    if ep == "data":  # ancien Arduino WiFi et fausses mesures : sans mot de passe, mais seulement depuis la maison
        return None if local() else (jsonify({"erreur": "réservé au réseau local"}), 403)
    if ep in PUBLIC or connecte():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"erreur": "connexion nécessaire"}), 401
    return redirect("/connexion")


# ---------- Captcha maison ----------
CAPTCHAS = {}  # numéro -> (réponse, expiration) ; en mémoire : chaque image ne sert qu'une fois
captcha_lock = threading.Lock()


def police(taille):
    from PIL import ImageFont
    for nom in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    return ImageFont.load_default(taille)


def dessiner(texte):
    from PIL import Image, ImageDraw
    w, h = 220, 80
    img = Image.new("RGB", (w, h), (244, 246, 245))
    d = ImageDraw.Draw(img)
    for _ in range(700):  # grain de fond
        v = rnd.randint(150, 220)
        d.point((rnd.randrange(w), rnd.randrange(h)), fill=(v, v, v))
    x = 12
    for ch in texte:  # chaque lettre penchée, décalée, de couleur sombre différente
        lettre = Image.new("RGBA", (60, 70), (0, 0, 0, 0))
        couleur = (rnd.randint(0, 90), rnd.randint(30, 110), rnd.randint(30, 120))
        ImageDraw.Draw(lettre).text((10, 6), ch, font=police(rnd.randint(36, 44)), fill=couleur)
        lettre = lettre.rotate(rnd.uniform(-30, 30), resample=Image.BICUBIC)
        img.paste(lettre, (x, rnd.randint(-2, 12)), lettre)
        x += rnd.randint(36, 40)
    for _ in range(5):  # traits qui barrent les lettres
        v = rnd.randint(60, 140)
        d.line([(rnd.randrange(w), rnd.randrange(h)) for _ in range(3)], fill=(v, v + 20, v), width=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@bp.route("/captcha.png")
def captcha():
    texte = "".join(rnd.choice(ALPHA) for _ in range(5))
    num, t = secrets.token_urlsafe(12), time.time()
    with captcha_lock:
        for k in [k for k, (_, exp) in CAPTCHAS.items() if exp < t]:
            del CAPTCHAS[k]
        if len(CAPTCHAS) > 2000:  # quelqu'un en demande en rafale : on oublie les plus vieux
            CAPTCHAS.clear()
        CAPTCHAS[num] = (texte, t + 600)
    session["captcha"] = num
    return Response(dessiner(texte), mimetype="image/png", headers={"Cache-Control": "no-store"})


def captcha_ok(reponse):
    num = session.pop("captcha", None)
    with captcha_lock:
        texte, exp = CAPTCHAS.pop(num, (None, 0))
    return texte is not None and exp > time.time() and (reponse or "").strip().upper() == texte


# ---------- Page de connexion ----------
PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connexion · HydroTour</title>
<style>
:root{--bg:#f2f2f7;--surface:#fff;--ink:#1d1d1f;--muted:#6e6e73;--fill:rgba(118,118,128,.12);--accent:#00897f;--accent-ink:#fff;--crit:#d70015;
  --f:-apple-system,BlinkMacSystemFont,'Segoe UI Variable Text','Segoe UI',system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#000;--surface:#1c1c1e;--ink:#f5f5f7;--muted:#98989d;--fill:rgba(118,118,128,.24);--accent:#40d4c4;--accent-ink:#00201d;--crit:#ff453a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#000;--surface:#1c1c1e;--ink:#f5f5f7;--muted:#98989d;--fill:rgba(118,118,128,.24);--accent:#40d4c4;--accent-ink:#00201d;--crit:#ff453a;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px 16px;background:var(--bg);color:var(--ink);font:15px/1.47 var(--f)}
.card{width:min(400px,100%);background:var(--surface);border-radius:22px;padding:26px 22px;box-shadow:0 1px 2px rgba(0,0,0,.04),0 6px 20px rgba(0,0,0,.05)}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.02em}
.sub{margin:0 0 18px;color:var(--muted);font-size:14px}
label{display:block;font-size:13.5px;font-weight:600;margin:14px 0 6px}
input{width:100%;font:inherit;background:var(--fill);color:var(--ink);border:0;border-radius:10px;padding:10px 12px}
input:focus{outline:0;box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 35%,transparent)}
@media (pointer:coarse){input{font-size:16px}}
.cap{display:flex;gap:10px;align-items:center;margin-bottom:10px}
.cap img{border-radius:10px;width:220px;max-width:100%;height:auto;display:block}
.btn{appearance:none;border:0;background:var(--fill);color:var(--accent);font:600 14px var(--f);padding:10px 16px;border-radius:99px;cursor:pointer}
.btn.primary{background:var(--accent);color:var(--accent-ink);width:100%;margin-top:20px;padding:12px}
.err{color:var(--crit);font-size:14px;margin:12px 0 0}
</style></head><body><main class="card">
<h1>HydroTour</h1>
<p class="sub">Connecte-toi pour voir la tour.</p>
<form method="post">
<label for="id">Identifiant</label><input id="id" name="identifiant" value="{{ identifiant }}" autocomplete="username" autocapitalize="none" required autofocus>
<label for="mdp">Mot de passe</label><input id="mdp" name="mdp" type="password" autocomplete="current-password" required>
<label for="captcha">Recopie les 5 caractères</label>
<div class="cap"><img id="cap-img" src="/captcha.png?{{ range(10**9)|random }}" alt="Captcha : 5 lettres et chiffres déformés" width="220" height="80">
<button class="btn" type="button" id="autre">Autre image</button></div>
<input id="captcha" name="captcha" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="5" required>
{% if erreur %}<p class="err" role="alert">{{ erreur }}</p>{% endif %}
<button class="btn primary">Se connecter</button>
</form>
</main>
<script>document.getElementById('autre').addEventListener('click',()=>{
  document.getElementById('cap-img').src='/captcha.png?'+Date.now();const c=document.getElementById('captcha');c.value='';c.focus();});</script>
</body></html>"""


def ouvrir_session(r):
    session.clear()
    session.permanent = True
    session["v"] = version(r)


@bp.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "GET":
        return redirect("/") if connecte() else render_template_string(PAGE, identifiant="", erreur="")
    f = request.form
    ident = f.get("identifiant", "").strip()
    if not captcha_ok(f.get("captcha")):
        return render_template_string(PAGE, identifiant=ident, erreur="Captcha incorrect, essaie avec la nouvelle image.")
    r = lire()
    # On vérifie toujours le mot de passe, même si l'identifiant est faux : même temps de réponse.
    bon_mdp = check_password_hash(r["hash"], f.get("mdp", ""))
    if not (bon_mdp and ident.lower() == r["identifiant"].lower()):
        return render_template_string(PAGE, identifiant=ident, erreur="Identifiant ou mot de passe incorrect.")
    ouvrir_session(r)
    print(f"Connexion depuis {'Internet' if not local() else 'le réseau local'}")
    return redirect("/")


@bp.route("/deconnexion", methods=["POST"])
def deconnexion():
    session.clear()
    return redirect("/connexion")


IDENT = re.compile(r"^[A-Za-z0-9._@-]{3,64}$")


@bp.route("/api/acces", methods=["GET", "POST"], endpoint="reglage")
def reglage():
    """Paramètres > Accès : changer l'identifiant et le mot de passe partagés (l'ancien mot de passe est demandé)."""
    r = lire()
    if request.method == "GET":
        return jsonify({"identifiant": r["identifiant"], "provisoire": os.path.exists(PREMIER)})
    f = request.values
    ident, mdp = f.get("identifiant", "").strip(), f.get("mdp", "")
    if not check_password_hash(r["hash"], f.get("actuel", "")):
        erreur = "Mot de passe actuel incorrect."
    elif not IDENT.match(ident):
        erreur = "Identifiant : 3 à 64 caractères, lettres, chiffres, point, tiret ou @."
    elif mdp and len(mdp) < 8:
        erreur = "Le nouveau mot de passe doit faire 8 caractères au moins."
    elif mdp != f.get("mdp2", ""):
        erreur = "Les deux nouveaux mots de passe ne sont pas pareils."
    elif mdp and mdp.lower() == ident.lower():
        erreur = "Le mot de passe ne doit pas être l'identifiant."
    else:
        erreur = None
    if erreur:
        return jsonify({"erreur": erreur}), 400
    h = generate_password_hash(mdp) if mdp else r["hash"]
    with db() as c:
        c.execute("UPDATE acces SET identifiant = ?, hash = ? WHERE id = 1", (ident, h))
    if mdp and os.path.exists(PREMIER):
        os.remove(PREMIER)
    ouvrir_session(lire())  # on garde cet appareil connecté, les autres devront se reconnecter
    print("Accès modifié (identifiant ou mot de passe)")
    return jsonify({"identifiant": ident, "provisoire": os.path.exists(PREMIER)})


if __name__ == "__main__":
    if sys.argv[1:2] == ["secours"]:
        provisoire()
    else:
        print(__doc__)
