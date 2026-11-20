"""Le cerveau de HydroTour : à partir des mesures, décide ce que font les pompes.

Aucun accès au matériel ici (c'est arduino.py) : on peut donc l'essayer sur un PC.

Pompe principale : cycle marche / arrêt réglable dans Paramètres. Elle s'arrête :
  - si le réservoir est presque vide (pour ne pas tourner à sec) ;
  - si la batterie descend au seuil de coupure. Elle reprend au seuil de reprise,
    ou plus tôt si le panneau reçoit assez de soleil : la batterie se charge d'au moins
    SOLEIL_A ampères (de quoi faire tourner la pompe) ET la lumière dépasse SOLEIL_LUMIERE %,
    pendant 5 minutes. Conseillé : couper à 30 %, reprendre à 35 %.
Doseuses (engrais A et B, pH-) : par petites doses, seulement quand la pompe principale
tourne depuis 2 min (l'eau est mélangée), puis on attend MELANGE_MIN avant de revérifier.
Les cibles de pH et d'EC suivent le légume et son stade (tableau PLANTS du dashboard).
"""
import json
import re
from collections import deque
from datetime import date, datetime

# Valeurs par défaut des réglages modifiables dans Paramètres.
REGLAGES = {
    "auto": 1,             # 1 = pilotage automatique, 0 = manuel
    "cycle_on": 15,        # minutes de marche de la pompe principale
    "cycle_off": 15,       # minutes d'arrêt
    "batt_coupure": 30,    # % : la pompe s'arrête à ce niveau de batterie
    "batt_reprise": 35,    # % : elle reprend à ce niveau
    "ph_v7": 1500.0,       # étalonnage pH : tension (mV) dans la solution tampon pH 7,00
    "ph_v4": 2032.0,       #                 tension (mV) dans la solution tampon pH 4,00
    "ec_r1": 340.0,        # ohms : résistance R1 en série avec la sonde graphite (mesurée au multimètre)
    "ec_p": 365.0,         # ohms : P = R1 + rL (rL : résistance de la broche D6 à l'état bas, environ 25 ohms)
    "ec_cellule": 0.489,   # cm-1 : constante de cellule K de la sonde (étude, partie 7.5)
    "ec_alpha": 0.02,      # par °C : variation de la conductivité avec la température (2 % par degré)
    "etape_vide": 2000.0,  # étalonnage du ruban : ohms réservoir vide
    "etape_plein": 400.0,  #                       ohms réservoir plein
}
COUPURE_CONSEIL, REPRISE_CONSEIL = 30, 35
SOLEIL_A = 1.5         # A de charge : la pompe de 19 W tire environ 1,5 A
SOLEIL_LUMIERE = 60    # % de lumière
SOLEIL_DUREE = 300     # s de soleil continu avant de relancer
NIVEAU_MIN = 15        # % : en dessous, pompe et dosage arrêtés
POMPE_DEPUIS = 120     # s de circulation avant d'avoir le droit de doser
MELANGE_MIN = 10       # minutes entre deux dosages
DOSE_PH_S = 2          # secondes de pompe pH- par dose
DOSE_ENGRAIS_S = 3     # secondes de chaque engrais (A puis B) par dose
DOSES_MAX_JOUR = 12    # sécurité : au-delà, plus de dosage automatique ce jour-là
DEBIT_ML_S = 100 / 60  # pompe péristaltique Adafruit : 100 mL/min au maximum
STOCK_BAS_L = 0.2


# ---------- Conversions des valeurs brutes de l'Arduino ----------
def ph_depuis_mv(mv, r):
    return 7.0 + (mv - r["ph_v7"]) * (4.0 - 7.0) / (r["ph_v4"] - r["ph_v7"])


def rapport_ec(s1, s2):
    """x = S1 / S2 = U1 / U2 (rapport des deux tensions lues au point J), ou None si une somme est
    inutilisable : nulle (pas de courant, sonde débranchée) ou à fond d'échelle (64 x 1023 = 65 472)."""
    if not s1 or not s2 or s1 >= 65472 or s2 >= 65472:
        return None
    return s1 / s2


def resistance_eau(x, r):
    """Rw = R1 + P (x - 1), en ohms (rapport, partie 7.6 : x = (Rw + rL) / (R1 + rL))."""
    return r["ec_r1"] + r["ec_p"] * (x - 1)


def ec_depuis_sommes(s1, s2, temp, r):
    """EC en µS/cm, ramenée à 25 °C, ou None si la mesure est inutilisable.
    Trois temps (rapport, partie 7.7) :
      x = S1 / S2 ;  Rw = R1 + P (x - 1) ;  sigma_T = K / Rw (K en cm-1, Rw en ohms : S/cm) ;
      sigma_25 = sigma_T / (1 + alpha (T - 25)).
    Le facteur 1e6 passe des S/cm aux µS/cm, unité utilisée partout dans le programme."""
    x = rapport_ec(s1, s2)
    if x is None:
        return None
    rw = resistance_eau(x, r)
    if rw <= 0:
        return None
    sigma_t = r["ec_cellule"] / rw * 1e6
    return sigma_t / (1 + r["ec_alpha"] * ((25 if temp is None else temp) - 25))


def etalonnage_ec(x1, x2, sigma1=1413.0, sigma2=12880.0, r1=340.0):
    """(P, K) à partir des rapports x1 et x2 mesurés dans deux solutions étalons (rapport, partie 7.7).
    sigma1 et sigma2 en µS/cm (par défaut 1,413 et 12,88 mS/cm), r1 en ohms.
      P = R1 (sigma2 - sigma1) / (sigma1 (x1 - 1) - sigma2 (x2 - 1))
      K = sigma1 (R1 + P (x1 - 1))      (K en cm-1 une fois sigma en S/cm)
    Renvoie None si le dénominateur est nul ou si le résultat n'a pas de sens (P ou K négatif)."""
    den = sigma1 * (x1 - 1) - sigma2 * (x2 - 1)
    if den == 0:
        return None
    p = r1 * (sigma2 - sigma1) / den
    k = sigma1 * 1e-6 * (r1 + p * (x1 - 1))
    return (p, k) if p > 0 and k > 0 else None


def niveau_depuis_ohm(ohm, r):
    """Niveau en % entre les étalonnages vide et plein (la résistance du ruban baisse quand l'eau monte)."""
    p = (r["etape_vide"] - ohm) / (r["etape_vide"] - r["etape_plein"]) * 100
    return min(100.0, max(0.0, p))


# ---------- Cibles du légume ----------
def charger_plantes(html_path):
    """Lit le tableau PLANTS entre /*<plantes>*/ et /*</plantes>*/ du dashboard : une seule source de vérité."""
    with open(html_path, encoding="utf-8") as f:
        bloc = re.search(r"/\*<plantes>\*/(.*?)/\*</plantes>\*/", f.read(), re.S).group(1)
    js = bloc[bloc.index("{"):bloc.rindex("}") + 1]
    js = re.sub(r"//[^\n]*", "", js)
    js = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', js)  # clés entre guillemets
    js = re.sub(r"'([^']*)'", lambda m: json.dumps(m.group(1)), js)
    return json.loads(js)


def cibles(plantes, culture, aujourd_hui=None):
    """{"nom", "stade", "jour", "ph": [min, max], "ec": [min, max]} pour la culture en cours, ou None."""
    p = plantes.get((culture or {}).get("crop"))
    if p is None:
        return None
    aujourd_hui = aujourd_hui or date.today()
    try:
        t0 = date.fromisoformat(culture.get("date") or "")
    except ValueError:
        t0 = aujourd_hui  # pas de date : comme le dashboard, « planté aujourd'hui »
    jour = max(0, (aujourd_hui - t0).days)
    st = next((s for s in p["stades"] if s["j"][0] <= jour < s["j"][1]), p["stades"][-1])
    return {"nom": p["nom"], "stade": st["nom"], "jour": jour, "ph": st["ph"], "ec": st["ec"]}


class Pilote:
    """Appeler tic() toutes les 10 s avec les dernières mesures. Les doses passent par doser(nom, secondes)."""

    def __init__(self, set_pompe, doser):
        self.set_pompe = set_pompe   # set_pompe("principale", True)
        self.doser = doser           # doser([("engrais_a", 3), ("engrais_b", 3)]) : fait tourner puis arrête
        self.principale = False
        self.batterie = "normal"     # "normal", "coupee" ou "soleil" (relancée par le soleil)
        self.soleil_depuis = None
        self.ombre_depuis = None
        self.cycle_t0 = None
        self.pompe_depuis = None
        self.dernier_dosage = None
        self.dernier_produit = None  # "engrais" ou "ph"
        self.doses_jour = {}         # (date, produit) -> nombre de doses
        self.alertes = []
        self.evenements = deque(maxlen=40)
        self._vu = set()             # alertes déjà notées dans le journal

    def noter(self, texte, type_="info", t=None):
        self.evenements.appendleft({"t": (t or datetime.now()).isoformat(timespec="seconds"), "type": type_, "texte": texte})
        print("[pilote]", texte)

    def alerte(self, niveau, texte, cle=None):
        """cle : pour une alerte dont le texte change (valeur mesurée), notée une seule fois au journal."""
        self.alertes.append({"niveau": niveau, "texte": texte, "cle": cle or texte})

    def manuel(self, on, t=None):
        """La pompe principale a été commandée à la main depuis le dashboard."""
        self._pompe(on, t or datetime.now())

    def _pompe(self, on, t):
        if on != self.principale:
            self.principale = on
            self.pompe_depuis = t if on else None
            self.set_pompe("principale", on)

    # ---------- Batterie ----------
    def _etat_batterie(self, m, r, t):
        pct, amp, lum = m.get("batt_pct"), m.get("batt_a"), m.get("lux")
        if pct is None:
            return
        coupure, reprise = r["batt_coupure"], r["batt_reprise"]
        if self.batterie == "normal":
            if pct <= coupure:
                self.batterie, self.soleil_depuis = "coupee", None
                self.noter(f"Batterie à {pct:.0f} % : pompe principale arrêtée (coupure à {coupure:.0f} %)", "alarme", t)
        elif self.batterie == "coupee":
            soleil = amp is not None and lum is not None and amp >= SOLEIL_A and lum >= SOLEIL_LUMIERE
            self.soleil_depuis = (self.soleil_depuis or t) if soleil else None
            if pct >= reprise:
                self.batterie = "normal"
                self.noter(f"Batterie à {pct:.0f} % : la pompe principale reprend", "retour", t)
            elif self.soleil_depuis and (t - self.soleil_depuis).total_seconds() >= SOLEIL_DUREE:
                self.batterie, self.ombre_depuis = "soleil", None
                self.noter(f"Assez de soleil ({amp:.1f} A de charge, lumière {lum:.0f} %) : "
                           f"la pompe reprend avant {reprise:.0f} %", "retour", t)
        else:  # relancée par le soleil : on recoupe si le soleil s'en va pendant 2 min
            if pct >= reprise:
                self.batterie = "normal"
                return
            ombre = (lum is None or lum < SOLEIL_LUMIERE) or (self.principale and amp is not None and amp < 0)
            self.ombre_depuis = (self.ombre_depuis or t) if ombre else None
            if self.ombre_depuis and (t - self.ombre_depuis).total_seconds() >= 120:
                self.batterie, self.soleil_depuis = "coupee", None
                self.noter(f"Plus assez de soleil, batterie à {pct:.0f} % : pompe principale arrêtée", "alarme", t)

    # ---------- Un tour de décision ----------
    def tic(self, m, r, cible, stock, t=None):
        """m : mesures converties ; r : réglages ; cible : cibles() ; stock : {"a": L, "b": L}.
        Renvoie les litres d'engrais consommés {"a": .., "b": ..} pour mettre le stock à jour."""
        t = t or datetime.now()
        self.alertes = []
        conso = {}
        self._conseils(r)
        self._etat_batterie(m, r, t)
        niveau = m.get("niveau")
        a_sec = niveau is not None and niveau < NIVEAU_MIN
        if a_sec:
            self.alerte("crit", f"Réservoir presque vide ({niveau:.0f} %) : pompe et dosage arrêtés, ajouter de l'eau", "niveau")
        if self.batterie == "coupee":
            self.alerte("crit", f"Pompe arrêtée : batterie à {m.get('batt_pct', 0):.0f} % "
                                f"(coupure à {r['batt_coupure']:.0f} %). Reprise à {r['batt_reprise']:.0f} % "
                                "ou dès qu'il y a assez de soleil.", "batterie")
        elif self.batterie == "soleil":
            self.alerte("warn", "Batterie sous le seuil de reprise : la pompe tourne grâce au soleil")
        if not r["auto"]:
            self.alerte("warn", "Pilotage automatique en pause (mode manuel)")
            self._noter_alertes(t)
            return conso
        # Cycle de la pompe principale.
        if self.cycle_t0 is None:
            self.cycle_t0 = t
        on_s, off_s = r["cycle_on"] * 60, r["cycle_off"] * 60
        dans_cycle = (t - self.cycle_t0).total_seconds() % max(1, on_s + off_s) < on_s
        self._pompe(dans_cycle and not a_sec and self.batterie != "coupee", t)
        if cible:
            conso = self._dosage(m, cible, stock, a_sec, t)
        else:
            self.alerte("warn", "Aucun légume choisi : pas de dosage automatique")
        self._noter_alertes(t)
        return conso

    def _conseils(self, r):
        if r["batt_coupure"] < COUPURE_CONSEIL:
            self.alerte("warn", f"Coupure batterie réglée à {r['batt_coupure']:.0f} % : "
                                f"il est conseillé de couper à {COUPURE_CONSEIL} % pour protéger la batterie")
        if r["batt_reprise"] < REPRISE_CONSEIL:
            self.alerte("warn", f"Reprise réglée à {r['batt_reprise']:.0f} % : il est conseillé de reprendre "
                                f"à {REPRISE_CONSEIL} % (ou plus tôt s'il y a assez de soleil)")

    def _dosage(self, m, cible, stock, a_sec, t):
        ph, ec = m.get("ph"), m.get("ec")
        (ph_min, ph_max), (ec_min, ec_max) = cible["ph"], cible["ec"]
        if ph is not None and ph < ph_min:
            self.alerte("warn", f"pH trop bas ({ph:.2f}, cible {ph_min}–{ph_max}) : pas de pH+, corriger à la main")
        if ec is not None and ec > ec_max:
            self.alerte("warn", f"EC trop haute ({ec:.0f} µS/cm, cible {ec_min}–{ec_max}) : ajouter de l'eau claire")
        for p in ("a", "b"):
            if stock.get(p) is not None and stock[p] <= STOCK_BAS_L:
                self.alerte("warn", f"Stock d'engrais {p.upper()} presque vide ({stock[p]:.2f} L)")
        if a_sec or not self.principale or (t - self.pompe_depuis).total_seconds() < POMPE_DEPUIS:
            return {}
        if self.dernier_dosage and (t - self.dernier_dosage).total_seconds() < MELANGE_MIN * 60:
            return {}
        # L'EC d'abord : les engrais font bouger le pH, on le corrige ensuite.
        # Si les deux sont hors cible, on alterne : une EC qui ne remonte pas ne bloque pas le pH.
        besoin_ec = ec is not None and ec < ec_min
        besoin_ph = ph is not None and ph > ph_max
        if besoin_ec and not (besoin_ph and self.dernier_produit == "engrais"):
            if self._permis("engrais", t):
                self.dernier_dosage, self.dernier_produit = t, "engrais"
                self.doser([("engrais_a", DOSE_ENGRAIS_S), ("engrais_b", DOSE_ENGRAIS_S)])
                self.noter(f"EC {ec:.0f} µS/cm < {ec_min} : dose d'engrais A et B ({DOSE_ENGRAIS_S} s chacun)", "dose", t)
                litres = DOSE_ENGRAIS_S * DEBIT_ML_S / 1000
                return {"a": litres, "b": litres}
        elif besoin_ph:
            if self._permis("ph", t):
                self.dernier_dosage, self.dernier_produit = t, "ph"
                self.doser([("ph", DOSE_PH_S)])
                self.noter(f"pH {ph:.2f} > {ph_max} : dose de pH- ({DOSE_PH_S} s)", "dose", t)
        return {}

    def _permis(self, produit, t):
        cle = (t.date(), produit)
        n = self.doses_jour.get(cle, 0)
        if n >= DOSES_MAX_JOUR:
            self.alerte("crit", f"{DOSES_MAX_JOUR} doses de {'engrais' if produit == 'engrais' else 'pH-'} aujourd'hui : "
                                "dosage automatique bloqué jusqu'à demain, vérifier la sonde")
            return False
        self.doses_jour = {k: v for k, v in self.doses_jour.items() if k[0] == t.date()}
        self.doses_jour[cle] = n + 1
        return True

    def _noter_alertes(self, t):
        for a in self.alertes:
            if a["cle"] not in self._vu and a["niveau"] == "crit" and a["cle"] != "batterie":  # batterie : déjà notée
                self.noter(a["texte"], "alarme", t)
        self._vu = {a["cle"] for a in self.alertes}
