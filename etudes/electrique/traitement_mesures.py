"""Traitement des mesures electriques HydroTour.
Usage : python3 traitement_mesures.py [fichier_energie.csv] [fichier_ponctuel.csv]
Sans argument : genere puis traite des donnees d'EXEMPLE (exemple_*.csv)."""
import csv, sys, os, math, random
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ICI = os.path.dirname(os.path.abspath(__file__))
E_JOUR_THEO = 226.1   # Wh/j (consommation theorique, etude v2)
E_PROD_THEO = 354.5   # Wh/j (production theorique pire mois, LiFePO4, etude v2)

def heure_en_h(txt):
    h, m = txt.split(":")[:2]
    return int(h) + int(m)/60.0

def trapezes(t, y):
    """Integrale de y(t) par la methode des trapezes (t en h, y en W -> Wh)."""
    return sum((t[i+1]-t[i])*(y[i]+y[i+1])/2.0 for i in range(len(t)-1))

def genere_exemple(chemin_e, chemin_p):
    random.seed(1)
    with open(chemin_e, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["heure", "tension_batterie_V", "courant_batterie_A", "courant_panneau_A",
                    "tension_panneau_V", "etat_circulation", "remarque"])
        soc = 0.6
        for k in range(0, 24*12+1):          # un releve toutes les 5 min
            t = k/12.0
            hh = int(t) % 24; mm = int(round((t-int(t))*60))
            pompe = 1 if ((6 <= hh < 18 and (mm < 15 or 30 <= mm < 45)) or (hh in (21, 0, 3) and mm < 15)) else 0
            g = max(0.0, math.sin(math.pi*(t-6.2)/11.6)) if 6.2 < t < 17.8 else 0.0
            g *= 0.50 + 0.15*random.random()   # journee nuageuse de juin (EXEMPLE)
            ipv = 6.8*g*0.80
            upv = 15.3 if ipv > 0.05 else 19.5
            icons = (3.83 + 19.0*pompe)/12.9
            ich = ipv*upv*0.95/13.2
            ibat = ich - icons
            soc = min(1.0, max(0.1, soc + ibat*(5/60)/23))
            ubat = 13.0 + 0.4*(soc-0.5) + 0.02*ibat
            w.writerow([f"{hh:02d}:{mm:02d}" if k < 24*12 else "24:00", f"{ubat:.3f}", f"{ibat:.3f}",
                        f"{ipv:.3f}", f"{upv:.2f}", pompe, "EXEMPLE"])
    with open(chemin_p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["grandeur", "instrument", "valeur", "unite", "theorique", "unite_theorique", "remarque"])
        for r in [("courant_circulation", "multimetre", 1.52, "A", 1.484, "A"),
                  ("courant_engrais_A", "multimetre", 0.27, "A", 0.30, "A"),
                  ("courant_engrais_B", "multimetre", 0.28, "A", 0.30, "A"),
                  ("courant_pH_moins", "multimetre", 0.26, "A", 0.30, "A"),
                  ("courant_repos_12V", "INA260", 0.33, "A", 0.314, "A"),
                  ("tension_UBEC", "multimetre", 5.08, "V", 5.0, "V"),
                  ("debit_doseuse_A", "eprouvette", 76, "mL/min", 80, "mL/min")]:
            w.writerow(list(r) + ["EXEMPLE"])

def lit(chemin):
    with open(chemin, newline="") as f:
        return list(csv.DictReader(f))

def traite(chemin_e, chemin_p, prefixe):
    lignes = [r for r in lit(chemin_e) if r["tension_batterie_V"]]
    t = [heure_en_h(r["heure"]) for r in lignes]
    u = [float(r["tension_batterie_V"]) for r in lignes]
    i = [float(r["courant_batterie_A"]) for r in lignes]
    ipv = [float(r["courant_panneau_A"] or 0) for r in lignes]
    upv = [float(r["tension_panneau_V"] or 0) for r in lignes]
    p = [a*b for a, b in zip(u, i)]               # W, > 0 en charge
    ppv = [a*b for a, b in zip(upv, ipv)]
    e_net = trapezes(t, p)
    e_ch = trapezes(t, [max(x, 0) for x in p])
    e_dech = -trapezes(t, [min(x, 0) for x in p])
    e_pv = trapezes(t, ppv)
    print(f"Energie nette batterie  : {e_net:8.1f} Wh/j")
    print(f"Energie chargee         : {e_ch:8.1f} Wh/j")
    print(f"Energie dechargee       : {e_dech:8.1f} Wh/j")
    print(f"Energie produite (PV)   : {e_pv:8.1f} Wh/j  (theorique {E_PROD_THEO} Wh/j, ecart {100*(e_pv/E_PROD_THEO-1):+.1f} %)")
    e_cons = e_pv*0.95 - e_net
    print(f"Consommation deduite    : {e_cons:8.1f} Wh/j  (theorique {E_JOUR_THEO} Wh/j, ecart {100*(e_cons/E_JOUR_THEO-1):+.1f} %)")
    print(f"Tension batterie min/max: {min(u):.2f} V / {max(u):.2f} V")
    print("\nMesures ponctuelles :")
    noms, mes, theo = [], [], []
    for r in lit(chemin_p):
        if not r["valeur"]:
            continue
        v, th = float(r["valeur"]), float(r["theorique"])
        print(f"  {r['grandeur']:22s} mesure {v:8.3f} {r['unite']:7s} theorique {th:8.3f}  ecart {100*(v/th-1):+6.1f} %")
        noms.append(r["grandeur"]); mes.append(v); theo.append(th)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    a1.plot(t, ppv, color="#e67e22", label="puissance panneau (W)")
    a1.plot(t, p, color="#2471a3", label="puissance batterie (W, > 0 = charge)")
    a1.axhline(0, color="k", lw=0.6); a1.set_ylabel("Puissance (W)"); a1.grid(ls=":"); a1.legend(fontsize=8)
    a1.set_title(f"Bilan journalier : produit {e_pv:.0f} Wh, consommé {e_cons:.0f} Wh (théorie {E_JOUR_THEO:.0f} Wh)")
    a2.plot(t, u, color="#c0392b"); a2.set_ylabel("Tension batterie (V)"); a2.set_xlabel("Heure"); a2.grid(ls=":")
    fig.tight_layout(); fig.savefig(os.path.join(ICI, prefixe+"bilan_journee.png"), dpi=120); plt.close(fig)
    if noms:
        fig, ax = plt.subplots(figsize=(9, 4))
        ec = [100*(m/th-1) for m, th in zip(mes, theo)]
        ax.barh(noms, ec, color=["#27ae60" if abs(e) <= 10 else "#c0392b" for e in ec])
        ax.axvline(0, color="k"); ax.axvspan(-10, 10, color="#27ae60", alpha=0.08)
        ax.set_xlabel("Écart mesure / théorie (%)"); ax.set_title("Mesures ponctuelles comparées à la théorie (zone verte : ±10 %)")
        fig.tight_layout(); fig.savefig(os.path.join(ICI, prefixe+"ecarts.png"), dpi=120); plt.close(fig)

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        traite(sys.argv[1], sys.argv[2], "")
    else:
        ce, cp = os.path.join(ICI, "exemple_energie.csv"), os.path.join(ICI, "exemple_ponctuel.csv")
        genere_exemple(ce, cp)
        print("=== DONNEES D'EXEMPLE (fictives) ===")
        traite(ce, cp, "exemple_")
