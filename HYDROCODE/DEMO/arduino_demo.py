"""Faux Arduino pour la démo HydroTour : même interface que arduino.py, sans aucun matériel.

Le serveur de démo (server.py) est celui de la vraie tour : seule la carte change. Cette classe simule
une tour qui vit (pH qui monte, EC qui baisse, eau qui s'évapore, soleil, batterie) et renvoie des valeurs
BRUTES (millivolts, ohms) : les conversions, l'étalonnage, la jauge de batterie et le pilote
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
        self._avancer()
        r = pl.REGLAGES
        ph = self.ph + random.gauss(0, 0.01)
        mv_ph = r["ph_v7"] + (ph - 7.0) * (r["ph_v4"] - r["ph_v7"]) / (4.0 - 7.0)
        mv_ec = None
        if avec_ec:
            ec = self.ec + random.gauss(0, 3)
            mv_ec = ec * (1 + 0.0185 * (self.temp_eau - 25)) * 820 * 200 / 1e6 / r["ec_k"]
        ohm = r["etape_vide"] - (self.niveau + random.gauss(0, 0.2)) / 100 * (r["etape_vide"] - r["etape_plein"])
        return {"ph_mv": mv_ph, "ec_mv": mv_ec, "etape_ohm": ohm}

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
