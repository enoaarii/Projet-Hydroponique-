#!/usr/bin/env python3
"""Traitement des mesures hydrauliques HydroTour (comparaison theorie / mesure).

Usage :
  python3 traitement_mesures.py            -> lit les fichiers mesure_*.csv (remplis par l'etudiant)
  python3 traitement_mesures.py --exemple  -> genere puis traite des fichiers exemple_*.csv (DONNEES FICTIVES)

Fichiers (separateur ';', virgule ou point decimal acceptes) :
  *_debit.csv    : essai;volume_L;temps_s
  *_jet.csv      : essai;hauteur_jet_cm
  *_niveau.csv   : date;heure;niveau_regle_cm;etape_mV;appoint_L
  *_doseuse.csv  : pompe;duree_ms;volume_mL
  *_melange.csv  : t_pompage_min;EC_mScm   (premiere ligne : t=0 juste avant la dose)
Les figures et le bilan sont ecrits dans le dossier resultats_<prefixe>/.
"""
import csv
import os
import sys
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---- valeurs theoriques de l'etude (Etude_hydraulique.pdf) ----
TH = dict(Q_Lh=494.0, h_jet_cm=34.7, C_pic_Lj=4.1, C_moy_Lj=2.3, q_dos_mLmin=80.0,
          tau_min=18.5, dEC_dose=0.037, V_L=152.0, S_bac_m2=0.38)
ICI = os.path.dirname(os.path.abspath(__file__))


def lire(nom):
    with open(nom, newline="", encoding="utf-8") as f:
        lignes = [l for l in csv.DictReader(f, delimiter=";")]
    for l in lignes:
        for k, v in l.items():
            try:
                l[k] = float(v.replace(",", "."))
            except (ValueError, AttributeError):
                pass
    return lignes


def ecrire(nom, entete, lignes):
    with open(nom, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(entete)
        w.writerows(lignes)


def generer_exemple():
    """Donnees FICTIVES pour prouver que le script fonctionne."""
    r = np.random.default_rng(1)
    ecrire("exemple_debit.csv", ["essai", "volume_L", "temps_s"],
           [[i + 1, 10.0, round(10 / 470 * 3600 + r.normal(0, 1.2), 1)] for i in range(5)])
    ecrire("exemple_jet.csv", ["essai", "hauteur_jet_cm"],
           [[i + 1, round(30 + r.normal(0, 1.5), 1)] for i in range(5)])
    rows, niv = [], 30.0
    for j in range(8):
        app = 0.0
        if j == 4:
            app, niv = 13.0, niv + 13.0 / 1000 / TH["S_bac_m2"] * 100
        rows.append([f"2027-01-{10+j:02d}", "07:00", round(niv, 2), round(1500 - 30 * niv, 0), app])
        niv -= 3.2 / 1000 / TH["S_bac_m2"] * 100 + r.normal(0, 0.05)
    ecrire("exemple_niveau.csv", ["date", "heure", "niveau_regle_cm", "etape_mV", "appoint_L"], rows)
    ecrire("exemple_doseuse.csv", ["pompe", "duree_ms", "volume_mL"],
           [[p, d, round(d / 60000 * q + r.normal(0, 0.3), 1)] for p, q in (("A", 76), ("B", 78), ("pH-", 82))
            for d in (7500, 15000, 30000)])
    t = np.array([0, 2, 5, 10, 15, 20, 30, 45, 60])
    ec = 1.30 + 0.037 * (1 - np.exp(-t / 22)) + r.normal(0, 0.003, t.size)
    ecrire("exemple_melange.csv", ["t_pompage_min", "EC_mScm"], [[a, round(b, 3)] for a, b in zip(t, ec)])


def ecart(m, th):
    return f"{100 * (m - th) / th:+.0f} %"


def main(prefixe):
    out = os.path.join(ICI, f"resultats_{prefixe}")
    os.makedirs(out, exist_ok=True)
    bilan = []
    if prefixe == "exemple":
        bilan.append("ATTENTION : DONNEES D'EXEMPLE FICTIVES, pas des mesures reelles.")

    # 1. debit
    d = lire(f"{prefixe}_debit.csv")
    Q = np.array([l["volume_L"] / l["temps_s"] * 3600 for l in d])
    bilan.append(f"Debit : {Q.mean():.0f} L/h (ecart-type {Q.std(ddof=1):.0f}) ; theorie {TH['Q_Lh']:.0f} L/h ; ecart {ecart(Q.mean(), TH['Q_Lh'])}")
    bilan.append(f"  -> temps de renouvellement mesure : {TH['V_L'] / Q.mean() * 60:.1f} min")

    # 2. jet
    h = np.array([l["hauteur_jet_cm"] for l in lire(f"{prefixe}_jet.csv")])
    bilan.append(f"Hauteur du jet : {h.mean():.1f} cm ; theorie (sans frottement de l'air) {TH['h_jet_cm']:.1f} cm ; ecart {ecart(h.mean(), TH['h_jet_cm'])}")
    bilan.append(f"  -> vitesse de sortie deduite : {np.sqrt(2 * 9.81 * h.mean() / 100):.2f} m/s")

    # 3. consommation journaliere (on retire les jours avec appoint de l'ajustement)
    n = lire(f"{prefixe}_niveau.csv")
    t = np.array([(datetime.strptime(f"{l['date']} {l['heure']}", "%Y-%m-%d %H:%M") -
                   datetime.strptime(f"{n[0]['date']} {n[0]['heure']}", "%Y-%m-%d %H:%M")).total_seconds() / 86400 for l in n])
    niv = np.array([l["niveau_regle_cm"] for l in n])
    app = np.array([l["appoint_L"] for l in n])
    # volume "corrige" : on retranche les appoints cumules pour obtenir une droite continue
    Vcorr = niv / 100 * TH["S_bac_m2"] * 1000 - np.cumsum(app)
    pente = np.polyfit(t, Vcorr, 1)[0]
    C = -pente
    bilan.append(f"Consommation : {C:.2f} L/j ; theorie {TH['C_moy_Lj']} L/j (moyenne) a {TH['C_pic_Lj']} L/j (pointe)")
    bilan.append(f"  -> intervalle d'appoint (baisse de 10 % = 15,2 L) : {15.2 / C:.1f} jours")
    etape = np.array([l["etape_mV"] for l in n])
    k = np.polyfit(niv, etape, 1)
    bilan.append(f"Etalonnage eTape : U(mV) = {k[0]:.1f} x niveau(cm) + {k[1]:.0f}")

    # 4. doseuses
    ds = lire(f"{prefixe}_doseuse.csv")
    for p in sorted({l["pompe"] for l in ds}):
        x = np.array([l["duree_ms"] / 60000 for l in ds if l["pompe"] == p])
        y = np.array([l["volume_mL"] for l in ds if l["pompe"] == p])
        q = np.sum(x * y) / np.sum(x * x)  # droite passant par 0
        bilan.append(f"Doseuse {p} : {q:.1f} mL/min ; theorie {TH['q_dos_mLmin']:.0f} ; ecart {ecart(q, TH['q_dos_mLmin'])} ; "
                     f"duree pour 10 mL = {10 / q * 60000:.0f} ms")

    # 5. melange
    m = lire(f"{prefixe}_melange.csv")
    tm = np.array([l["t_pompage_min"] for l in m])
    ec = np.array([l["EC_mScm"] for l in m])
    dEC = ec[-1] - ec[0]
    f = (ec - ec[0]) / dEC
    ok = (f > 0.02) & (f < 0.98)
    tau = -1 / np.polyfit(tm[ok], np.log(1 - f[ok]), 1)[0] if ok.sum() >= 2 else float("nan")
    bilan.append(f"Effet d'une dose (10 mL A + 10 mL B) : {dEC:.3f} mS/cm ; theorie {TH['dEC_dose']:.3f} ; ecart {ecart(dEC, TH['dEC_dose'])}")
    bilan.append(f"Constante de melange : {tau:.1f} min ; theorie {TH['tau_min']} min ; 95 % atteint apres {3 * tau:.0f} min de pompage")

    # figures
    fig, ax = plt.subplots(2, 2, figsize=(10, 7))
    ax[0, 0].bar(range(1, len(Q) + 1), Q, color="#2a78d6")
    ax[0, 0].axhline(TH["Q_Lh"], color="#eb6834", ls="--", label="theorie")
    ax[0, 0].set_title("Debit par essai (L/h)"); ax[0, 0].legend(frameon=False)
    ax[0, 1].plot(t, Vcorr, "o", color="#2a78d6", label="mesure (appoints retires)")
    ax[0, 1].plot(t, np.polyval(np.polyfit(t, Vcorr, 1), t), color="#2a78d6")
    ax[0, 1].plot(t, Vcorr[0] - TH["C_pic_Lj"] * t, "--", color="#eb6834", label="theorie pointe")
    ax[0, 1].set_title("Volume du bac (L)"); ax[0, 1].set_xlabel("jours"); ax[0, 1].legend(frameon=False)
    for p, c in zip(sorted({l["pompe"] for l in ds}), ["#2a78d6", "#1baf7a", "#eda100"]):
        x = [l["duree_ms"] / 1000 for l in ds if l["pompe"] == p]
        y = [l["volume_mL"] for l in ds if l["pompe"] == p]
        ax[1, 0].plot(x, y, "o", color=c, label=p)
    xs = np.linspace(0, 30, 10)
    ax[1, 0].plot(xs, xs / 60 * TH["q_dos_mLmin"], "--", color="#52514e", label="theorie 80 mL/min")
    ax[1, 0].set_title("Volume dose (mL)"); ax[1, 0].set_xlabel("duree (s)"); ax[1, 0].legend(frameon=False)
    tt = np.linspace(0, tm.max(), 100)
    ax[1, 1].plot(tm, ec, "o", color="#2a78d6", label="mesure")
    ax[1, 1].plot(tt, ec[0] + TH["dEC_dose"] * (1 - np.exp(-tt / TH["tau_min"])), "--", color="#eb6834", label="theorie")
    ax[1, 1].set_title("EC apres une dose (mS/cm)"); ax[1, 1].set_xlabel("temps de pompage (min)"); ax[1, 1].legend(frameon=False)
    if prefixe == "exemple":
        fig.suptitle("EXEMPLE : donnees fictives", color="#e34948")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "comparaison.png"), dpi=120)
    with open(os.path.join(out, "bilan.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(bilan) + "\n")
    print("\n".join(bilan))


if __name__ == "__main__":
    os.chdir(ICI)
    if "--exemple" in sys.argv:
        generer_exemple()
        main("exemple")
    else:
        main("mesure")
