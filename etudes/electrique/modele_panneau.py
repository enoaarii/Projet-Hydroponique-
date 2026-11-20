"""Modele a une diode des panneaux SLP055 (validation) et TE1250 (hypotheses).
Genere les figures du chapitre Dimensionnement du panneau."""
import numpy as np
from scipy.optimize import brentq, fsolve
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
k, q = 1.380649e-23, 1.602176634e-19

def vt(Tc):
    return k*(Tc+273.15)/q

class Panneau:
    def __init__(s, nom, Ns, Voc, Isc, Vmp, Imp, bVoc, aIsc, Rsh=300.0):
        s.nom, s.Ns, s.Voc, s.Isc, s.Vmp, s.Imp = nom, Ns, Voc, Isc, Vmp, Imp
        s.bVoc, s.aIsc, s.Rsh = bVoc, aIsc, Rsh
        s.ajuste()
    def params(s, n, Rs, Tc, G=1000.0):
        dT = Tc-25.0
        a = n*s.Ns*vt(Tc)
        Isc = s.Isc*(1+s.aIsc*dT)*G/1000.0
        Voc = s.Voc + s.bVoc*dT
        # I0 tel que I(Voc)=0 et Iph tel que I(0)=Isc
        Iph = Isc*(1+Rs/s.Rsh)  # approx : diode bloquee en court-circuit
        I0 = (Iph - Voc/s.Rsh)/(np.exp(Voc/a)-1)
        return Iph, I0, a, Rs
    def courant(s, V, p):
        Iph, I0, a, Rs = p
        f = lambda I: Iph - I0*(np.exp((V+Rs*I)/a)-1) - (V+Rs*I)/s.Rsh - I
        return brentq(f, -2*Iph-1, Iph+1)
    def ajuste(s):
        def eqs(x):
            n, Rs = x
            p = s.params(n, Rs, 25.0)
            I = s.courant(s.Vmp, p)
            # dP/dV = 0 au point Vmp (difference finie)
            h = 1e-3
            dP = ((s.Vmp+h)*s.courant(s.Vmp+h, p) - (s.Vmp-h)*s.courant(s.Vmp-h, p))/(2*h)
            return [I - s.Imp, dP]
        s.n, s.Rs = fsolve(eqs, [1.2, 0.2])
    def courbe(s, Tc, G=1000.0, N=600):
        p = s.params(s.n, s.Rs, Tc, G)
        Voc = s.Voc + s.bVoc*(Tc-25.0)  # par construction I(Voc) = 0
        V = np.linspace(0, Voc, N)
        I = np.array([s.courant(v, p) for v in V])
        return V, I
    def mpp(s, Tc, G=1000.0):
        V, I = s.courbe(Tc, G, 2000)
        P = V*I; i = np.argmax(P)
        return V[i], I[i], P[i], V[-1], I[0]

slp = Panneau("SLP055-12U", 36, 21.6, 3.56, 17.2, 3.20, -0.080, 0.00065)
te = Panneau("TE1250", 36, 22.0, 7.30, 17.6, 6.80, -0.080, 0.00065, Rsh=200.0)

if __name__ == "__main__":
    temps = [25, 47, 50, 54, 75]
    lignes = []
    for pan in (slp, te):
        lignes.append(f"{pan.nom}: n={pan.n:.4f}, Rs={pan.Rs:.4f} ohm, Rsh={pan.Rsh} ohm")
        for T in temps:
            Vm, Im, Pm, Voc, Isc = pan.mpp(T)
            lignes.append(f"  T={T} C : Vmp={Vm:.2f} V Imp={Im:.3f} A Pmax={Pm:.2f} W Voc={Voc:.2f} V Isc={Isc:.3f} A")
    p = te.params(te.n, te.Rs, 25.0)
    lignes.append(f"TE1250 STC: Iph={p[0]:.4f} A, I0={p[1]:.3e} A, a={p[2]:.4f} V")
    p = slp.params(slp.n, slp.Rs, 25.0)
    lignes.append(f"SLP055 STC: Iph={p[0]:.4f} A, I0={p[1]:.3e} A, a={p[2]:.4f} V")
    txt = "\n".join(lignes); print(txt)
    open(os.path.join(OUT, "resultats_modele.txt"), "w").write(txt+"\n")

    coul = {25: "#c0392b", 47: "#e67e22", 50: "#2471a3", 75: "#27ae60"}
    # Figure 1 : validation SLP055
    ref = {25: (17.2, 55.0), 47: (15.6, 50.1), 50: (15.4, 49.5), 75: (13.6, 43.8)}
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for T, c in coul.items():
        V, I = slp.courbe(T)
        ax.plot(V, V*I, color=c, lw=1.8, label=f"modèle {T} °C")
        ax.plot(*ref[T], "o", ms=8, mfc="none", mec=c, mew=2)
    ax.plot([], [], "o", mfc="none", mec="k", label="points lus sur les courbes fournies")
    ax.set_xlabel("Tension U (V)"); ax.set_ylabel("Puissance P (W)")
    ax.set_title("SLP055 : modèle à une diode comparé aux points de puissance maximale")
    ax.grid(ls=":"); ax.legend(fontsize=8); ax.set_xlim(0, 23); ax.set_ylim(0, 62)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "validation_slp055.pdf")); plt.close(fig)

    # Figure 2 : TE1250 I(U) et P(U)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.5, 7.5), sharex=True)
    for T, c in coul.items():
        V, I = te.courbe(T)
        Vm, Im, Pm, *_ = te.mpp(T)
        a1.plot(V, I, color=c, lw=1.8, label=f"{T} °C")
        a2.plot(V, V*I, color=c, lw=1.8, label=f"{T} °C : Pmax ≈ {Pm:.1f} W à {Vm:.1f} V")
        a2.plot(Vm, Pm, "o", color=c)
    a1.set_ylabel("Courant I (A)"); a1.set_title("TE1250 120 Wc (étiquette) : caractéristique I(U), 1000 W/m²")
    a2.set_ylabel("Puissance P (W)"); a2.set_xlabel("Tension U (V)"); a2.set_title("Caractéristique P(U)")
    for a in (a1, a2): a.grid(ls=":"); a.legend(fontsize=8, loc="lower left" if a is a1 else "upper left")
    a1.set_ylim(0, 8.2); a2.set_ylim(0, 140); a2.set_xlim(0, 24)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "te1250_courbes.pdf")); plt.close(fig)
