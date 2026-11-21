"""Faux Arduino pour la démo HydroTour : même interface que arduino.py, sans aucun matériel.

Le serveur de démo (server.py) est celui de la vraie tour : seule la carte change. Cette classe simule
une tour qui vit (pH qui monte, EC qui baisse, eau qui s'évapore, soleil, batterie) et renvoie des valeurs
BRUTES (millivolts, ohms, sommes de la sonde EC) : les conversions, l'étalonnage, la jauge de batterie et le pilote
(cycle de la pompe, coupure batterie, dosage) sont donc exactement ceux de la vraie tour.
Les pompes font réellement réagir la simulation : l'engrais fait monter l'EC, le pH- fait baisser le pH.
"""
import math
import random
import threading
import time
from datetime import datetime, timezone

import pilote as pl

POMPES = ["principale", "engrais_a", "engrais_b", "ph"]
DEBIT_ML_S = pl.DEBIT_ML_S
VOLUME_L = 40.0  # eau du réservoir simulé


class Arduino:
    def __init__(self):
        self._lock = threading.Lock()
        self._sorties = 0
        self.ph, self.ec, self.niveau = 5.9, 1150.0, 78.0
        self.soc = 0.70  # charge de la batterie, de 0 à 1
        self.ah, self.vn = 6.0, 12.8
        self.temp_eau = 21.0
        self._t = time.monotonic()
        self._w = 0.0
        self._ecran = []
        print("Démo : faux Arduino démarré (aucun matériel branché).")

    # ---------- Simulation ----------
    def _soleil(self):
        t = datetime.now().astimezone()
        h = t.hour + t.minute / 60
        return max(0.0, math.sin(math.pi * (h - 6) / 12)) if 6 < h < 18 else 0.0

    def _avancer(self):
        now = time.monotonic()
        dt = min(now - self._t, 60)
        self._t = now
        if dt <= 0:
            return
        mn, jour = dt / 60, self._soleil()
        with self._lock:
            on = [bool(self._sorties >> i & 1) for i in range(4)]
        self.ph += 0.002 * mn + random.gauss(0, 0.0015)
        self.ec -= 0.6 * mn + random.gauss(0, 0.3)
        self.niveau -= 0.03 * mn * (0.3 + jour)
        if self.niveau < 35:  # le jardinier remet de l'eau : le niveau reste intéressant à regarder
            self.niveau += 40
            self.ec -= 120
        ml = DEBIT_ML_S * dt
        if on[1] or on[2]:  # engrais A ou B : 1 mL dans 40 L ~ +6 µS/cm
            self.ec += 6.0 * ml * (on[1] + on[2]) / 2
        if on[3]:  # pH- : 1 mL ~ -0,03 unité de pH
            self.ph -= 0.03 * ml
        self.ph = min(8.5, max(4.0, self.ph))
        self.temp_eau = 20.5 + 1.8 * jour + random.gauss(0, 0.03)
        # Batterie : panneau 55 W selon le soleil, moins Raspberry + pompes.
        pv = 55 * 0.8 * jour ** 1.4 * random.uniform(0.7, 1.0)
        conso = 4.5 + (19 if on[0] else 0) + (6 if any(on[1:]) else 0)
        w = 0.0 if self.soc >= 1 and pv > conso else pv - conso
        self.soc = min(1.0, max(0.0, self.soc + w * dt / 3600 / (self.ah * self.vn)))
        self._w = w

    # ---------- Pompes ----------
    def set_pompe(self, nom, on):
        self._sortie(POMPES.index(nom), on)

    def _sortie(self, n, on):
        bit = 1 << n
        with self._lock:
            self._sorties = self._sorties | bit if on else self._sorties & ~bit

    def rafraichir_pompes(self):
        pass  # pas de sécurité 30 s à réarmer en démo

    def pompes(self):
        return {nom: bool(self._sorties >> i & 1) for i, nom in enumerate(POMPES)}

    def carte_pompes_branchee(self):
        return True

    def eteindre_pompes(self):
        for nom in POMPES:
            self.set_pompe(nom, False)

    # ---------- Capteurs (valeurs brutes, comme la vraie carte) ----------
    def lire_analogiques(self, avec_ec=True):
        """Mêmes valeurs brutes que la vraie carte : millivolts pour le pH, ohms pour le ruban,
        et les deux sommes S1 et S2 pour la sonde EC en graphite."""
        self._avancer()
        r = pl.REGLAGES
        ph = self.ph + random.gauss(0, 0.01)
        # On part du pH voulu et on remonte à la tension, en inversant la droite d'étalonnage.
        pente = (r["ph_ref2"] - r["ph_ref1"]) / (r["ph_mv2"] - r["ph_mv1"])
        mv_ph = r["ph_mv1"] + (ph - r["ph_ref1"]) / pente
        s1, s2 = self._sommes_ec() if avec_ec else (None, None)
        ohm = r["etape_vide"] - (self.niveau + random.gauss(0, 0.2)) / 100 * (r["etape_vide"] - r["etape_plein"])
        return {"ph_mv": mv_ph, "ec_s1": s1, "ec_s2": s2, "etape_ohm": ohm}

    def _sommes_ec(self):
        """Les deux sommes de la mesure EC, reconstruites à l'envers du calcul de pilote.py.

        Le programme du Pi fait, dans l'ordre : x = S1/S2, puis Rw = R1 + P (x - 1),
        puis sigma_T = K / Rw, ramenée à 25 °C. Ici on part de l'EC voulue et on remonte :
          sigma_T = sigma_25 (1 + alpha (T - 25))   conductivité à la température de l'eau
          Rw = K / sigma_T                          résistance de l'eau entre les mines
          x = (Rw + rL) / (R1 + rL) = (Rw - R1 + P) / P   puisque P = R1 + rL
        Chaque somme vaut 64 lectures du convertisseur 10 bits, donc au plus 64 x 1023 = 65 472.
        On fixe S2 et on en déduit S1, en restant sous ce maximum."""
        r = pl.REGLAGES
        ec = max(1.0, self.ec + random.gauss(0, 3))            # µS/cm à 25 °C
        sigma_t = ec * (1 + r["ec_alpha"] * (self.temp_eau - 25)) * 1e-6   # S/cm
        rw = r["ec_cellule"] / sigma_t                          # ohms
        x = (rw - r["ec_r1"] + r["ec_p"]) / r["ec_p"]
        s2 = 20000 if x >= 1 else int(60000 / max(x, 0.05))
        s2 = min(s2, 65000)
        s1 = int(round(x * s2))
        if s1 > 65472:                                          # saturation, comme sur la vraie carte
            s1, s2 = 65472, int(round(65472 / x))
        return s1, s2

    def mesurer_ec(self):
        """Comme la vraie carte : les deux sommes brutes de la sonde EC, ou None."""
        return self._sommes_ec()

    def mesurer_ec_sur(self, essais=2):
        return self._sommes_ec()

    def lire_temp_eau(self):
        return round(self.temp_eau, 1)

    def lire_air(self):
        h = datetime.now().astimezone()
        hh = h.hour + h.minute / 60
        t = 24 + 4 * math.sin(math.pi * (hh - 9) / 12) + random.gauss(0, 0.1)
        return round(t, 1), round(min(98, 80 - (t - 24) * 2.5 + random.gauss(0, 0.5)))

    def lire_pression(self):
        return round(1013 + random.gauss(0, 0.3), 1)

    def lire_lumiere(self):
        return round(100 * self._soleil() ** 1.4 * random.uniform(0.8, 1.0), 1)

    def lire_batterie(self):
        v = (12.9 + 0.5 * self.soc + 0.012 * self._w) * self.vn / 12.8 + random.gauss(0, 0.004)
        return round(v, 3), round(self._w / v, 3), round(self._w, 2)

    def lire_horloge(self):
        return datetime.now(timezone.utc).replace(tzinfo=timezone.utc)

    def regler_horloge(self, dt):
        pass

    def afficher(self, lignes):
        self._ecran = list(lignes)

    def fermer(self):
        self.eteindre_pompes()
