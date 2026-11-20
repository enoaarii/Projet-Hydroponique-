"""Calculs de l'etude electrique HydroTour, version 2. Ecrit resultats.json."""
import json, os
R = {}
U5 = 5.0; eta = 0.83; Ub = 12.8; UbAGM = 12.0
# Electronique 5 V : courants moyens (A)
c5 = [("Raspberry Pi 3 Model B (Wi-Fi interne coupé ou non, sans écran)", 0.450),
      ("Dongle Wi-Fi USB à antenne externe", 0.120),
      ("Arduino Uno R3 (alimenté par l'USB du Pi)", 0.050),
      ("Base Grove (LED témoin)", 0.003),
      ("Carte pH Gravity V2.0", 0.005),
      ("Carte EC DFR0300 (alimentée 2 s par minute)", 0.0002),
      ("eTape 30 cm + résistance de référence", 0.002),
      ("ADS1115", 0.0002),
      ("DS18B20", 0.0005),
      ("DHT11", 0.0003),
      ("Capteur de lumière (analogique)", 0.0005),
      ("Accéléromètre LIS3DHTR", 0.00002),
      ("Module RTC", 0.0002),
      ("INA260 (logique)", 0.0011),
      ("Carte 6318 : MCP23017 + LED témoin", 0.0020)]
I5 = sum(i for _, i in c5); P5 = I5*U5
P12e = P5/eta; Pconv = P12e-P5
R["elec"] = [(n, i, i*U5, i*U5*24) for n, i in c5]
R.update(I5=I5, P5=P5, E5=P5*24, P12e=P12e, Pconv=Pconv, Econv=Pconv*24, Eelec12=P12e*24, I12e=P12e/Ub)
# Circulation
Pc = 19.0; tc = 12*2*0.25 + 3*0.25
Ic = Pc/Ub; Rds = 0.070
Pmos2 = Rds*Ic**2/2; Pmos1 = Rds*Ic**2
R.update(tc=tc, Ec=Pc*tc, Ic=Ic, Pmos2=Pmos2, Pmos1=Pmos1, Emos=Pmos2*tc)
# Doseuses
Id = 0.30; Pd = Id*Ub; Q = 80.0  # mL/min
sens = 0.56  # mS/cm par mL/L de A (et autant de B)
dEC = 0.05; Vbac = 152.0
VA = dEC*Vbac/sens
Vdose = {"A": VA, "B": VA, "pH": 6.0}
R.update(VA=VA)
td = {k: v/Q*60 for k, v in Vdose.items()}  # s
Edos_est = sum(td.values())*Pd/3600
Edos_max = 3*10*30*Pd/3600
R.update(Pd=Pd, td=td, Edos_est=Edos_est, Edos_max=Edos_max, Emosdos=Rds*Id**2*sum(td.values())/3600)
# MPPT autoconsommation
Imppt = 0.015; Pmppt = Imppt*Ub
R.update(Pmppt=Pmppt, Emppt=Pmppt*24)
Ejour = R["Eelec12"] + R["Ec"] + R["Emos"] + Edos_max + R["Emppt"]
R["Ejour"] = Ejour
# Production
Pcrete = 120.0; H = 4.2
Ta = 27.0; G = 800.0; NOCT = 47.0
Tc = Ta + (NOCT-20)/800*G
kT = 1 - 0.005*(Tc-25)
kT_courbe = (49.5 + (43.8-49.5)*(Tc-50)/25)/55.0
ks, km, kc = 0.95, 0.95, 0.98
ktol = 117.5/120.0
R['ktol']=ktol
kb = {"LFP": 0.95, "AGM": 0.85}
PR = {k: kT*ktol*ks*km*kc*v for k, v in kb.items()}
Eth = Pcrete*H
Eprod = {k: Eth*v for k, v in PR.items()}
marge = {k: Eprod[k]/Ejour - 1 for k in PR}
R.update(Tc=Tc, kT=kT, kT_courbe=kT_courbe, PR=PR, Eth=Eth, Eprod=Eprod, marge=marge)
# Batterie
C = 23.0
bat = {"LFP": dict(U=12.8, DoD=0.80, eta=0.95, Ich=0.5, Uch="14,2 à 14,6"),
       "AGM": dict(U=12.0, DoD=0.50, eta=0.85, Ich=0.25, Uch="14,4 à 14,7")}
for k, b in bat.items():
    b["Enom"] = C*b["U"]; b["Eu"] = b["Enom"]*b["DoD"]; b["aut"] = b["Eu"]/Ejour
    b["C2j"] = 2*Ejour/(b["U"]*b["DoD"])
# nuit 17h -> 7h : 14 h d'electronique + circulation 17:00,17:30,21,00,03,06:00,06:30 = 7 x 15 min
tn = 14.0; tcn = 7*0.25
En = (R["P12e"]+Pmppt)*tn + Pc*tcn + Pmos2*tcn
R.update(En=En, tcn=tcn)
for k, b in bat.items(): b["frac_nuit"] = En/b["Eu"]
Ich = Pcrete*km/Ub
R.update(Ich=Ich, I6=Ich*6/23, I17=Ich*17/23, bat=bat)
R["Icirc_par"] = 0.3/(0.060+0.060*6/17)
# Cables
rho = 0.0172*(1+0.00393*(60-20))
R["rho"] = rho
seg = [("Panneau -> MPPT (PV)", 5.0, 6.83, 15.26, 0.03, 4.0),
       ("MPPT -> INA260 -> bus batteries", 0.5, Ich, Ub, 0.01, 4.0),
       ("Bus -> batterie 6 Ah", 0.3, R["I6"], Ub, 0.005, 2.5),
       ("Bus -> batterie 17 Ah", 0.3, R["I17"], Ub, 0.005, 2.5),
       ("Sortie LOAD -> bornier 12 V", 0.5, 2.70, Ub, 0.01, 1.5),
       ("Bornier -> pompe de circulation", 3.0, Ic, Ub, 0.03, 1.5),
       ("Bornier -> pompe doseuse", 1.0, Id, Ub, 0.03, 0.5),
       ("UBEC -> Raspberry Pi (5 V)", 0.3, 1.0, U5, 0.02, 0.5)]
R["cables"] = []
for n, L, I, U, e, S in seg:
    dUm = e*U; Smin = 2*rho*L*I/dUm; dU = 2*rho*L*I/S
    R["cables"].append(dict(n=n, L=L, I=I, U=U, e=e, dUm=dUm, Smin=Smin, S=S, dU=dU, pc=100*dU/U))
json.dump(R, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultats.json"), "w"), indent=1, ensure_ascii=False)
for k, v in R.items():
    if k not in ("elec", "cables"): print(k, v)
for c in R["cables"]: print(c)
for e in R["elec"]: print(e)

Hc = 1.2
R["Ecouv"] = {k: Pcrete*Hc*v for k, v in PR.items()}
R["deficit_couv"] = {k: Ejour - R["Ecouv"][k] for k in PR}
R["jours_couv"] = {k: bat[k]["Eu"]/R["deficit_couv"][k] for k in PR}
R["E39"] = {k: Pcrete*3.9*v for k, v in PR.items()}
json.dump(R, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultats.json"), "w"), indent=1, ensure_ascii=False)
print("PR",PR,"Eprod",Eprod,"marge",marge,"couv",R["Ecouv"],R["deficit_couv"],R["jours_couv"],"E39",R["E39"])
