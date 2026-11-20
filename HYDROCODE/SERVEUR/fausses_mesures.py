"""Fausses mesures pour essayer le dashboard sans capteurs.

Joue le rôle de l'Arduino : envoie au serveur toutes les 10 s des valeurs plausibles
(pH, EC, températures, niveau, humidité, lumière, pression, batterie, pompes). Chaque fausse mesure porte
la marque "simulation" dans la colonne pompes, pour pouvoir les effacer toutes ensuite.

Le serveur doit tourner (python server.py).

  python fausses_mesures.py               remplit les 24 dernières heures puis envoie en direct (1 h)
  python fausses_mesures.py --duree 10    envoi en direct pendant 10 minutes
  python fausses_mesures.py --sans-historique
  python fausses_mesures.py --effacer     supprime toutes les fausses mesures de la base
"""
import argparse
import json
import math
import os
import random
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "hydrotour.db")
URL = "http://localhost:5000/api/data"
MARQUE = '"simulation": true'


def batterie_reglee():
    """(capacité en Ah, tension nominale en V) saisies dans Paramètres ; 6 Ah et 12,8 V par défaut."""
    try:
        with sqlite3.connect(DB) as c:
            d = dict(c.execute("SELECT cle, valeur FROM reglages WHERE cle IN ('batt_ah', 'batt_v')").fetchall())
    except sqlite3.Error:  # serveur jamais lancé avec la nouvelle version : pas encore de table
        d = {}
    return d.get("batt_ah", 6.0), d.get("batt_v", 12.8)


class Tour:
    """État simulé : le pH monte doucement, l'EC baisse, le niveau descend ; les pompes corrigent."""

    def __init__(self):
        self.ph, self.ec, self.niveau = 5.85, 1150.0, 82.0
        self.soc = 0.7  # charge de la batterie, de 0 à 1
        self.ah, self.vn = batterie_reglee()
        self.dose = {"engrais_a": 0, "engrais_b": 0, "ph": 0, "eau": 0}  # minutes restantes

    def pas(self, t, minutes):
        h = t.astimezone().hour + t.astimezone().minute / 60  # heure locale du PC
        jour = max(0.0, math.sin(math.pi * (h - 6) / 12)) if 6 < h < 18 else 0.0
        self.ph += 0.002 * minutes + random.gauss(0, 0.004)
        self.ec -= 0.6 * minutes + random.gauss(0, 2)
        self.niveau -= 0.03 * minutes * (0.3 + jour)
        if self.ph > 6.0 and not self.dose["ph"]:
            self.dose["ph"] = 2
        if self.ec < 1020 and not self.dose["engrais_a"]:
            self.dose["engrais_a"] = self.dose["engrais_b"] = 2
        if self.niveau < 65 and not self.dose["eau"]:
            self.dose["eau"] = 4
        for k in self.dose:
            m = min(minutes, self.dose[k])
            if k == "ph":
                self.ph -= 0.08 * m
            elif k == "eau":
                self.niveau += 4.5 * m
            else:
                self.ec += 40 * m
            self.dose[k] = max(0, self.dose[k] - minutes)
        temp_air = 26 + 4 * math.sin(math.pi * (h - 9) / 12) + random.gauss(0, 0.2)
        mesure = {
            "ph": round(self.ph + random.gauss(0, 0.01), 2),
            "ec": round(self.ec + random.gauss(0, 4)),
            "temp_eau": round(20.5 + 1.5 * jour + random.gauss(0, 0.05), 1),
            "temp_air": round(temp_air, 1),
            "humidite": round(min(98, 85 - (temp_air - 24) * 2.5 + random.gauss(0, 1))),
            "lux": round(100 * jour ** 1.4 * random.uniform(0.6, 1.0)),  # lumière en % (Sensor Kit)
            "pression": round(1013 + random.gauss(0, 0.5), 1),
            "niveau": round(self.niveau, 1),
        }
        pompes = {"principale": int(t.timestamp() // 900) % 2 == 0, "simulation": True}
        pompes.update({k: v > 0 for k, v in self.dose.items()})
        # Batterie : panneau 55 W selon le soleil, moins Raspberry + pompe 19 W + doseuses.
        pv = 55 * 0.8 * jour ** 1.4 * random.uniform(0.6, 1.0)
        conso = 4.5 + (19 if pompes["principale"] else 0) + (6 if any(self.dose.values()) else 0)
        w = 0.0 if self.soc >= 1 and pv > conso else pv - conso
        self.soc = min(1.0, max(0.0, self.soc + w * minutes / 60 / (self.ah * self.vn)))
        v = (12.9 + 0.5 * self.soc + 0.012 * w) * self.vn / 12.8 + random.gauss(0, 0.005)
        mesure.update(batt_v=round(v, 3), batt_a=round(w / v, 3), batt_w=round(w, 2), batt_pct=round(self.soc * 100, 1))
        return mesure, pompes


def historique(heures):
    """Écrit directement dans la base, avec des dates passées (l'API, elle, date à l'instant)."""
    tour, maintenant = Tour(), datetime.now(timezone.utc)
    t = maintenant - timedelta(hours=heures)
    with sqlite3.connect(DB) as c:
        while t < maintenant:
            m, p = tour.pas(t, 5)
            cols = ", ".join(m)
            c.execute(f"INSERT OR REPLACE INTO mesures (t, {cols}, pompes) VALUES ({', '.join('?' * (len(m) + 2))})",
                      (t.strftime("%Y-%m-%dT%H:%M:%SZ"), *m.values(), json.dumps(p)))
            t += timedelta(minutes=5)
    print(f"Historique : {heures} h de fausses mesures écrites (une toutes les 5 min).")
    return tour


def direct(tour, minutes):
    fin = time.time() + minutes * 60
    print(f"Envoi en direct vers {URL} toutes les 10 s pendant {minutes} min (Ctrl+C pour arrêter).")
    while time.time() < fin:
        m, p = tour.pas(datetime.now(timezone.utc), 10 / 60)
        req = urllib.request.Request(URL, data=json.dumps({**m, "pompes": p}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
            print(datetime.now().strftime("%H:%M:%S"), m)
        except OSError as e:
            print("Serveur injoignable :", e)
        time.sleep(10)


def effacer():
    with sqlite3.connect(DB) as c:
        n = c.execute("DELETE FROM mesures WHERE pompes LIKE ?", (f"%{MARQUE}%",)).rowcount
    print(f"{n} fausses mesures supprimées. Les vraies mesures sont conservées.")


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--duree", type=float, default=60, help="minutes d'envoi en direct (défaut 60)")
    a.add_argument("--sans-historique", action="store_true")
    a.add_argument("--effacer", action="store_true")
    o = a.parse_args()
    if o.effacer:
        effacer()
    else:
        tour = Tour() if o.sans_historique else historique(24)
        direct(tour, o.duree)
