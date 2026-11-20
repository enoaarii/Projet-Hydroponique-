#!/usr/bin/env python3
"""Calculs de l'etude hydraulique HydroTour et figures du rapport.
Toutes les valeurs du PDF viennent de ce script (python3 calculs.py)."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import brentq

C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
                     "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
                     "axes.spines.right": False, "lines.linewidth": 2})

# ---------------- Donnees et hypotheses ----------------
g = 9.81            # m/s2
rho = 997.0         # kg/m3 (eau a 25 C)
nu = 0.893e-6       # m2/s (eau a 25 C)
Qmax = 800 / 3.6e6  # m3/s
Hmax = 5.0          # m
D = 0.013           # m, diametre interieur du tuyau (1/2 pouce)
L = 1.8             # m, longueur de la conduite de montee
Hg = 1.2            # m, hauteur geometrique
K = 0.5 + 2 * 0.9 + 0.5   # entree + 2 coudes 90 + raccord pomme
n_tr, d_tr, Cd = 12, 0.003, 0.62   # pomme de douche : 12 trous de 3 mm
A = np.pi * D**2 / 4
a_eff = n_tr * Cd * np.pi * d_tr**2 / 4


def Hp(Q):
    return Hmax * (1 - Q / Qmax)


def parts(Q, D=D, pomme=True):
    A_ = np.pi * D**2 / 4
    v = Q / A_
    Re = v * D / nu
    lam = 0.316 * Re**-0.25
    hr = lam * L / D * v**2 / (2 * g)
    hs = K * v**2 / (2 * g)
    if pomme:
        vj = Q / a_eff
    else:
        vj = v
    hj = vj**2 / (2 * g)
    return dict(v=v, Re=Re, lam=lam, hr=hr, hs=hs, vj=vj, hj=hj, H=Hg + hr + hs + hj)


def Hr(Q, D=D, pomme=True):
    return parts(np.maximum(Q, 1e-9), D, pomme)["H"]


Q0 = brentq(lambda q: Hp(q) - Hr(q), 1e-7, Qmax)
P = parts(Q0)
p_pomme = rho * (P["vj"]**2 - P["v"]**2) / 2
res = dict(A=A, a_eff=a_eff, Q_m3s=Q0, Q_Lh=Q0 * 3.6e6, H=Hp(Q0), p_pomme=p_pomme,
           Phyd=rho * g * Q0 * Hp(Q0), **{k: v for k, v in P.items() if k != "H"})

# sensibilite
sens = []
for Dd in [0.010, 0.013, 0.016, 0.019]:
    for pm in [True, False]:
        q = brentq(lambda x: Hp(x) - Hr(x, Dd, pm), 1e-7, Qmax)
        pp = parts(q, Dd, pm)
        sens.append(dict(D_mm=Dd * 1e3, pomme=pm, Q_Lh=q * 3.6e6, v=pp["v"], H=Hp(q), vj=pp["vj"]))
res["sens"] = sens

# ---------------- Bac, renouvellement, bilan ----------------
V = 152.0                  # L
Q_Lh = res["Q_Lh"]
tau_min = V / Q_Lh * 60
res["tau_min"] = tau_min
res["tours_jour"] = Q_Lh * 6.75 / V
res["Q_plant"] = Q_Lh / 12
res["vol_jour"] = Q_Lh * 6.75
n_pl = 12
c_pic, c_moy = 0.30, 0.15  # L/j/plant
S_evap, e_evap = 0.10, 5.0  # m2, mm/j
E = S_evap * e_evap        # L/j (1 mm sur 1 m2 = 1 L)
C_pic = n_pl * c_pic + E
C_moy = n_pl * c_moy + E
tol = 0.10 * V
res.update(E=E, C_pic=C_pic, C_moy=C_moy, tol=tol, T_pic=tol / C_pic, T_moy=tol / C_moy,
           abs_pic=14 * C_pic, abs_moy=14 * C_moy)
S_bac = V / 1000 / 0.40    # m2 si hauteur d'eau 0,40 m
res["S_bac"] = S_bac
res["dh_tol_cm"] = tol / 1000 / S_bac * 100
res["dh_pic_cm"] = C_pic / 1000 / S_bac * 100

# ---------------- Dosage ----------------
q_dos = 80.0               # mL/min (en charge, coherent etude electrique)
beta_EC = 0.56             # mS/cm pour 1 mL/L de A + 1 mL/L de B
vA = 10.0                  # mL de A (et 10 mL de B)
res["t_A_ms"] = vA / q_dos * 60e3
res["dEC"] = beta_EC * vA / V
CP = 1.6                   # mmol/L de phosphore
pKa2 = 7.2
alpha = 1 / (1 + 10**(pKa2 - 6.0))
betaP = np.log(10) * CP * alpha * (1 - alpha)
c_acide = 0.5              # mol/L de H+ cedes
v_ph = 4.0                 # mL
ca = c_acide * v_ph / V    # mmol/L (mol/L * mL / L = mmol/L)
res.update(alpha=alpha, betaP=betaP, ca=ca, dpH=ca / betaP, t_ph_ms=v_ph / q_dos * 60e3)
EC_c = 1.4
res["A_par_L"] = EC_c / beta_EC
res["A_rempl"] = V * EC_c / beta_EC
res["conso_A_pic"] = C_pic * EC_c / beta_EC
res["conso_A_moy"] = C_moy * EC_c / beta_EC
res["dEC_appoint"] = EC_c * (1 - 0.9)
res["n_dose_appoint"] = res["dEC_appoint"] / res["dEC"]
res["EC_absence_max"] = EC_c * V / (V - res["abs_pic"])
res["beta_tab"] = {}
for ph in [5.5, 6.0, 6.3, 6.5]:
    al = 1 / (1 + 10**(pKa2 - ph)); b = np.log(10) * CP * al * (1 - al)
    res["beta_tab"][ph] = dict(alpha=al, beta=b, dpH=ca / b)
# pompe parabolique pour comparaison
Q2 = brentq(lambda q: Hmax * (1 - (q / Qmax)**2) - Hr(q), 1e-7, Qmax)
res["Q_parab_Lh"] = Q2 * 3.6e6
res["t95_min"] = 3 * tau_min

with open("resultats.json", "w") as f:
    json.dump(res, f, indent=1, default=float)
for k, v in res.items():
    if k != "sens":
        print(f"{k:12s} {v}")
for s in sens:
    print(s)

# ---------------- Figures ----------------
Q = np.linspace(1e-7, Qmax, 400)
Ql = Q * 3.6e6
fig, ax = plt.subplots(figsize=(6.4, 4.2))
ax.plot(Ql, Hp(Q), color=C1, label="Pompe (modèle linéaire)")
ax.plot(Ql, Hr(Q), color=C2, label="Réseau (montée + pomme)")
ax.plot(Ql, Hr(Q, pomme=False), color=C2, ls="--", lw=1.5, label="Réseau sans pomme (tuyau ouvert)")
ax.axhline(Hg, color=INK2, lw=1, ls=":")
ax.text(20, Hg + 0.08, "hauteur géométrique 1,2 m", color=INK2, fontsize=8)
ax.plot([Q_Lh], [res["H"]], "o", color=INK, ms=8, mec="white", mew=2, zorder=5)
ax.annotate(f"point de fonctionnement\nQ ≈ {Q_Lh:.0f} L/h ; H ≈ {res['H']:.2f} m".replace(".", ","),
            (Q_Lh, res["H"]), (560, 3.3), fontsize=9, color=INK,
            arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
ax.set_xlim(0, 820); ax.set_ylim(0, 5.3)
ax.set_xlabel("Débit Q (L/h)"); ax.set_ylabel("Hauteur manométrique H (m)")
ax.legend(frameon=False, fontsize=8, loc="upper right", bbox_to_anchor=(1, 1))
fig.tight_layout(); fig.savefig("figures/point_fonctionnement.pdf"); plt.close(fig)

fig, ax = plt.subplots(figsize=(6.4, 4.0))
ax.plot(Ql, Hp(Q), color=C1, label="Pompe")
cols = [C2, C3, C4, "#e87ba4"]
for Dd, c in zip([0.010, 0.013, 0.016, 0.019], cols):
    ax.plot(Ql, Hr(Q, Dd), color=c, lw=1.6, label=f"Réseau, D = {Dd*1e3:.0f} mm")
ax.set_xlim(0, 820); ax.set_ylim(0, 5.3)
ax.set_xlabel("Débit Q (L/h)"); ax.set_ylabel("H (m)")
ax.legend(frameon=False, fontsize=8)
fig.tight_layout(); fig.savefig("figures/sensibilite_diametre.pdf"); plt.close(fig)

j = np.linspace(0, 16, 200)
fig, ax = plt.subplots(figsize=(6.4, 3.8))
ax.plot(j, V - C_pic * j, color=C2, label=f"Pointe : {C_pic:.1f} L/j".replace(".", ","))
ax.plot(j, V - C_moy * j, color=C1, label=f"Moyenne de cycle : {C_moy:.1f} L/j".replace(".", ","))
ax.axhline(V - tol, color=INK2, ls="--", lw=1)
ax.text(10.3, V - tol + 2, "seuil d'appoint (−10 % : 136,8 L)", color=INK2, fontsize=8)
ax.axvline(14, color=INK2, ls=":", lw=1)
ax.text(14.1, 100, "14 jours", color=INK2, fontsize=8, rotation=90)
ax.set_xlabel("Jours sans appoint"); ax.set_ylabel("Volume dans le bac (L)")
ax.set_xlim(0, 16); ax.set_ylim(80, 156)
ax.legend(frameon=False, fontsize=8, loc="lower left")
fig.tight_layout(); fig.savefig("figures/bilan_hydrique.pdf"); plt.close(fig)

t = np.linspace(0, 90, 300)
fig, ax = plt.subplots(figsize=(6.4, 3.6))
ax.plot(t, 100 * (1 - np.exp(-t / tau_min)), color=C1)
for N in [1, 2, 3]:
    ax.plot([N * tau_min], [100 * (1 - np.exp(-N))], "o", color=C1, ms=7, mec="white", mew=2)
    ax.annotate(f"{N} renouvellement{'s' if N > 1 else ''} : {100*(1-np.exp(-N)):.0f} %",
                (N * tau_min, 100 * (1 - np.exp(-N))), (N * tau_min + 3, 100 * (1 - np.exp(-N)) - 14),
                fontsize=8, color=INK)
ax.set_xlabel("Temps de pompage cumulé depuis la dose (min)")
ax.set_ylabel("Volume du bac déjà brassé (%)")
ax.set_ylim(0, 105); ax.set_xlim(0, 90)
fig.tight_layout(); fig.savefig("figures/melange.pdf"); plt.close(fig)
print("figures ok")
