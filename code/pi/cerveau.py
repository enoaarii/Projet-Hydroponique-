#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cerveau.py : cerveau de la tour hydroponique HydroTour (Raspberry Pi 3).

Remplace l'ancien pont_usb.py. Le Pi décide (planning, conversions, filtrage,
dosage, envoi au serveur), l'Arduino exécute (capteurs bruts, pompes) et garde
ses sécurités matérielles.

Dépendances : bibliothèque standard Python 3 (3.9 ou plus) + pyserial.

Organisation du fichier :
  1. Réglages par défaut et chargement des fichiers JSON
  2. Horloges (réelle, accélérée, manuelle) : injectables pour les tests
  3. Planning de circulation (fonctions pures)
  4. Conversions des mesures brutes (fonctions pures, formules démontrées)
  5. Filtrage des mesures (médiane glissante, conditions de validité)
  6. Alertes et décision de dosage (fonctions pures)
  7. Liaison série avec l'Arduino
  8. Journal CSV et envoi au serveur avec file d'attente
  9. Classe Cerveau (boucle principale)
 10. Programme principal
"""

import argparse
import base64
import copy
import csv
import glob
import json
import logging
import math
import os
import signal
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    import serial  # pyserial
except ImportError:  # permet de lancer les tests de logique sans pyserial
    serial = None

LOG = logging.getLogger("cerveau")

# Numéros de pompes du protocole série (section 4 du cahier commun)
POMPE_CIRCULATION = 0
POMPE_ENGRAIS_A = 1
POMPE_ENGRAIS_B = 2
POMPE_PH_MOINS = 3
NOMS_POMPES = {0: "circulation", 1: "engrais A", 2: "engrais B", 3: "pH-"}

# Correspondance alarme interne -> nom attendu par le dashboard (None : non transmise,
# mais toujours écrite dans le journal)
ALARMES_SERVEUR = {
    "chute": "chute", "niveau_bas": "niveau_bas", "temp_eau_haute": "temp_eau_haute",
    "ph_haut": "ph_haut", "ph_bas": "ph_bas", "ec_haute": "ec_haute", "ec_basse": "ec_basse",
    "secours": "secours", "liaison_arduino": "arduino",
    "capteur_ph": "capteur", "capteur_ec": "capteur", "capteur_temp_eau": "capteur",
    "capteur_niveau": "capteur",
}


def alarmes_pour_serveur(noms):
    """Liste triée, sans doublon, des noms d'alarmes compris par le dashboard."""
    return sorted({ALARMES_SERVEUR[n] for n in noms if ALARMES_SERVEUR.get(n)})

# =============================================================================
# 1. Réglages par défaut
# =============================================================================

CONFIG_DEFAUT = {
    "fuseau": "Pacific/Tahiti",
    "tick_s": 1.0,
    "serie": {
        "port": "auto",
        "vitesse": 115200,
        "timeout_reponse_s": 1.5,
        "timeout_lecture_s": 5.0,
        "attente_pret_s": 8.0,
        "echecs_avant_reconnexion": 3,
        "pause_reconnexion_s": 5.0,
    },
    "serveur": {
        "url": "http://127.0.0.1:5000/api/data",
        "url_journal": "http://127.0.0.1:5000/api/journal",
        "envoyer_journal": True,
        "timeout_s": 5.0,
        "periode_envoi_s": 60,
        "max_par_vidage": 20,
        "max_file": 100000,
        "envoyer_horodatage": True,
    },
    "repetition_messages_info_s": 3600,
    "relance_circulation_refusee_s": 10,
    "planning": {
        "jour_debut": "06:00",
        "jour_fin": "18:00",
        "jour_marche_min": 15,
        "jour_periode_min": 30,
        "nuit_demarrages": ["21:00", "00:00", "03:00"],
        "nuit_marche_min": 15,
    },
    "circulation": {"bail_ms": 90000, "renouvellement_s": 60},
    "mesure": {
        "periode_lecture_s": 30,
        "stabilisation_s": 120,
        "attente_apres_dose_s": 120,
        "exiger_brassage_apres_dose": True,
        "taille_mediane": 5,
        "lectures_invalides_avant_alarme": 3,
    },
    "plages": {
        "ph_min": 5.5, "ph_cible": 6.0, "ph_max": 6.5,
        "ec_min": 1.2, "ec_cible": 1.4, "ec_max": 1.8,
        "temp_eau_min": 18.0, "temp_eau_max": 24.0, "temp_eau_alarme": 28.0,
    },
    "dosage": {
        "actif": True,
        "ec_dose_si_inferieure_a": 1.3,
        "ph_dose_si_superieur_a": 6.3,
        "dose_engrais_ms": 3000,
        "dose_ph_ms": 1000,
        "pause_entre_pompes_s": 5,
        "delai_apres_arret_s": 540,
        "marge_avant_demarrage_s": 300,
        "max_corrections_engrais_jour": 6,
        "max_corrections_ph_jour": 6,
        "niveau_min_pct": 20,
        "debit_doseuse_ml_min": 100,
    },
    "niveau": {"seuil_bas_pct": 15},
    "alarmes_bloquant_dosage": [
        "chute", "niveau_bas", "secours", "liaison_arduino", "niveau_faible",
        "capteur_ph", "capteur_ec", "capteur_temp_eau", "capteur_niveau",
    ],
    "fichiers": {
        "calibration": "calibration.json",
        "journal": "journal.csv",
        "file_attente": "file_attente.jsonl",
        "file_journal": "file_journal.jsonl",
        "rejets": "rejets.jsonl",
        "etat": "etat.json",
    },
}

CALIBRATION_DEFAUT = {
    "ph": {"tampon_1": 7.0, "u_1_mV": 1500.0, "tampon_2": 4.0, "u_2_mV": 2032.44, "date": None},
    "ec": {"gain_mV_par_mScm": 164.0, "k": 1.0, "alpha_par_C": 0.0185,
           "reference_mScm": 1.413, "date": None},
    "etape": {"montage": "etape_vers_masse", "r_fixe_ohm": 560.0, "vcc_mV": 5000.0,
              "r_vide_ohm": 2000.0, "h_vide_cm": 2.5,
              "r_plein_ohm": 400.0, "h_plein_cm": 30.0,
              "h_0pct_cm": 5.0, "h_100pct_cm": 30.0, "date": None},
}


def fusion(defaut, perso):
    """Fusionne récursivement un dictionnaire personnel sur les valeurs par défaut."""
    resultat = copy.deepcopy(defaut)
    for cle, valeur in (perso or {}).items():
        if isinstance(valeur, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = fusion(resultat[cle], valeur)
        else:
            resultat[cle] = valeur
    return resultat


def charger_json(chemin, defaut):
    """Lit un fichier JSON et complète les clés manquantes par les valeurs par défaut."""
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return fusion(defaut, json.load(f))
    except FileNotFoundError:
        return copy.deepcopy(defaut)


def ecrire_json_atomique(chemin, donnees):
    """Écrit un JSON via un fichier temporaire puis renommage (pas de fichier à moitié écrit)."""
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, chemin)


# =============================================================================
# 2. Horloges injectables
# =============================================================================

class Horloge:
    """Horloge réelle. t() : secondes depuis 1970 ; maintenant() : date locale."""

    def __init__(self, fuseau="Pacific/Tahiti"):
        self.tz = ZoneInfo(fuseau)

    def t(self):
        return time.time()

    def maintenant(self):
        return datetime.fromtimestamp(self.t(), self.tz)

    def utc_z(self):
        """Horodatage UTC au format du serveur : '2026-10-22T08:15:03Z'."""
        return datetime.fromtimestamp(self.t(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def dormir(self, secondes):
        time.sleep(max(0.0, secondes))


class HorlogeAcceleree(Horloge):
    """Horloge qui avance 'facteur' fois plus vite que le temps réel (tests, démonstrations)."""

    def __init__(self, debut, facteur, fuseau="Pacific/Tahiti"):
        Horloge.__init__(self, fuseau)
        self.t0 = float(debut)
        self.m0 = time.monotonic()
        self.facteur = float(facteur)

    def t(self):
        return self.t0 + (time.monotonic() - self.m0) * self.facteur

    def dormir(self, secondes):
        time.sleep(max(0.0, secondes) / self.facteur)


class HorlogeManuelle(Horloge):
    """Horloge pilotée à la main (tests unitaires) : dormir() fait avancer le temps."""

    def __init__(self, debut, fuseau="Pacific/Tahiti"):
        Horloge.__init__(self, fuseau)
        self.valeur = float(debut)

    def t(self):
        return self.valeur

    def dormir(self, secondes):
        self.valeur += max(0.0, secondes)


# =============================================================================
# 3. Planning de circulation (fonctions pures)
# =============================================================================

def _minutes(texte_hhmm):
    """'06:30' -> 390 minutes depuis minuit."""
    h, m = texte_hhmm.split(":")
    return int(h) * 60 + int(m)


def creneaux_du_jour(planning):
    """Liste triée des créneaux de marche (début, fin) en minutes depuis minuit.

    Jour : marche de 'jour_marche_min' toutes les 'jour_periode_min' minutes,
    de 'jour_debut' (inclus) à 'jour_fin' (exclu pour les départs).
    Nuit : un créneau de 'nuit_marche_min' à chaque heure de 'nuit_demarrages'.
    """
    creneaux = []
    debut = _minutes(planning["jour_debut"])
    fin = _minutes(planning["jour_fin"])
    depart = debut
    while depart < fin:
        creneaux.append((depart, depart + planning["jour_marche_min"]))
        depart += planning["jour_periode_min"]
    for texte in planning["nuit_demarrages"]:
        depart = _minutes(texte)
        creneaux.append((depart, depart + planning["nuit_marche_min"]))
    return sorted(creneaux)


def etat_planning(dt_local, creneaux):
    """État du planning à l'instant dt_local (datetime avec fuseau).

    Renvoie un dictionnaire :
      en_marche          : la pompe doit tourner
      fin_creneau        : fin du créneau en cours (datetime) ou None
      debut_arret        : début de l'arrêt en cours (fin du dernier créneau) ou None
      prochain_demarrage : début du prochain créneau (datetime)
    Les créneaux de la veille et du lendemain sont pris en compte (passage de minuit).
    """
    minuit = dt_local.replace(hour=0, minute=0, second=0, microsecond=0)
    m = (dt_local - minuit).total_seconds() / 60.0
    etendus = sorted((a + k * 1440, b + k * 1440) for k in (-1, 0, 1) for a, b in creneaux)
    fin_en_cours = None
    for a, b in etendus:
        if a <= m < b:
            fin_en_cours = b if fin_en_cours is None else max(fin_en_cours, b)
    prochain = min(a for a, b in etendus if a > m)
    if fin_en_cours is not None:
        return {"en_marche": True,
                "fin_creneau": minuit + timedelta(minutes=fin_en_cours),
                "debut_arret": None,
                "prochain_demarrage": minuit + timedelta(minutes=prochain)}
    derniere_fin = max(b for a, b in etendus if b <= m)
    return {"en_marche": False,
            "fin_creneau": None,
            "debut_arret": minuit + timedelta(minutes=derniere_fin),
            "prochain_demarrage": minuit + timedelta(minutes=prochain)}


def duree_bail_ms(t, fin_creneau_t, bail_max_ms):
    """Durée du bail envoyé à l'Arduino : jamais au-delà de la fin du créneau.

    Ainsi, même si l'ordre d'arrêt 'D 0 0' se perd, la pompe s'arrête à l'heure.
    """
    reste_ms = int((fin_creneau_t - t) * 1000)
    return max(0, min(int(bail_max_ms), reste_ms))


# =============================================================================
# 4. Conversions des mesures brutes (fonctions pures)
# =============================================================================
#
# --- 4.1 pH par étalonnage 2 points ---------------------------------------
# Hypothèse : la tension U de la sonde est une fonction affine du pH :
#     U = a + b \cdot \mathrm{pH}
# Dans le tampon 1 (pH_1 = 7,0) on mesure U_1 :
#     U_1 = a + b \cdot \mathrm{pH}_1
# Dans le tampon 2 (pH_2 = 4,0) on mesure U_2 :
#     U_2 = a + b \cdot \mathrm{pH}_2
# On soustrait la deuxième égalité de la première :
#     U_1 - U_2 = b \cdot (\mathrm{pH}_1 - \mathrm{pH}_2)
# d'où la pente :
#     b = \frac{U_1 - U_2}{\mathrm{pH}_1 - \mathrm{pH}_2}
# On soustrait l'égalité du tampon 1 de l'égalité générale :
#     U - U_1 = b \cdot (\mathrm{pH} - \mathrm{pH}_1)
# On isole le pH :
#     \mathrm{pH} = \mathrm{pH}_1 + \frac{U - U_1}{b}
# On remplace b :
#     \mathrm{pH} = \mathrm{pH}_1 + (\mathrm{pH}_1 - \mathrm{pH}_2) \cdot \frac{U - U_1}{U_1 - U_2}
# Vérification en U = U_2 :
#     \mathrm{pH} = \mathrm{pH}_1 - (\mathrm{pH}_1 - \mathrm{pH}_2) = \mathrm{pH}_2


def ph_depuis_mV(u_mV, cal_ph):
    """pH à partir de la tension de la sonde (mV), étalonnage 2 points."""
    if u_mV is None:
        return None
    p1, u1 = cal_ph["tampon_1"], cal_ph["u_1_mV"]
    p2, u2 = cal_ph["tampon_2"], cal_ph["u_2_mV"]
    if u1 == u2:
        return None
    return p1 + (p1 - p2) * (u_mV - u1) / (u1 - u2)


def etalonnage_ph(u1_mV, u2_mV, tampon_1=7.0, tampon_2=4.0):
    """Paramètres pH à enregistrer après la mesure des deux tampons."""
    return {"tampon_1": tampon_1, "u_1_mV": round(u1_mV, 2),
            "tampon_2": tampon_2, "u_2_mV": round(u2_mV, 2)}


# --- 4.2 EC compensée à 25 °C, étalonnage 1 point ---------------------------
# Hypothèse 1 : la tension U du module est proportionnelle à la conductivité
# réelle sigma_T de l'eau à sa température T. On note G le gain nominal du
# module (mV par mS/cm) et k le facteur correctif de la cellule :
#     \sigma_T = \frac{k \cdot U}{G}
# Hypothèse 2 : la conductivité varie linéairement avec la température,
# avec le coefficient alpha = 0,0185 /°C :
#     \sigma_T = \sigma_{25} \cdot \left(1 + \alpha \,(T - 25)\right)
# On divise les deux membres par (1 + alpha (T - 25)), non nul :
#     \sigma_{25} = \frac{\sigma_T}{1 + \alpha \,(T - 25)}
# On remplace sigma_T :
#     \sigma_{25} = \frac{k \cdot U}{G \cdot \left(1 + \alpha \,(T - 25)\right)}
# Étalonnage : solution de référence sigma_ref = 1,413 mS/cm à 25 °C, à la
# température T_e on mesure U_e. Sa conductivité réelle à T_e est :
#     \sigma_{T_e} = \sigma_{ref} \cdot \left(1 + \alpha \,(T_e - 25)\right)
# L'hypothèse 1 appliquée à cette mesure donne :
#     \frac{k \cdot U_e}{G} = \sigma_{ref} \cdot \left(1 + \alpha \,(T_e - 25)\right)
# On isole k :
#     k = \frac{\sigma_{ref} \cdot G \cdot \left(1 + \alpha \,(T_e - 25)\right)}{U_e}


def facteur_temperature(t_c, alpha):
    """Facteur (1 + alpha (T - 25))."""
    return 1.0 + alpha * (t_c - 25.0)


def ec25_depuis_mV(u_mV, t_c, cal_ec):
    """EC compensée à 25 °C (mS/cm) à partir de la tension (mV) et de la température (°C)."""
    if u_mV is None or t_c is None:
        return None
    f = facteur_temperature(t_c, cal_ec["alpha_par_C"])
    if f <= 0:
        return None
    sigma_t = cal_ec["k"] * u_mV / cal_ec["gain_mV_par_mScm"]
    return sigma_t / f


def etalonnage_ec(u_mV, t_c, cal_ec):
    """Facteur k obtenu dans la solution de référence (1,413 mS/cm à 25 °C)."""
    if u_mV is None or u_mV <= 0 or t_c is None:
        return None
    f = facteur_temperature(t_c, cal_ec["alpha_par_C"])
    return cal_ec["reference_mScm"] * cal_ec["gain_mV_par_mScm"] * f / u_mV


# --- 4.3 Niveau d'eau (eTape) ---------------------------------------------
# Montage "etape_vers_masse" : résistance fixe R_f entre Vcc et le point de
# mesure, eTape (résistance R_e) entre le point de mesure et la masse.
# Le même courant I traverse les deux résistances en série :
#     I = \frac{V_{cc}}{R_f + R_e}
# La tension mesurée est celle aux bornes de l'eTape :
#     U = R_e \cdot I
#     U = \frac{V_{cc} \cdot R_e}{R_f + R_e}
# On multiplie par (R_f + R_e) :
#     U \cdot R_f + U \cdot R_e = V_{cc} \cdot R_e
# On regroupe les termes en R_e :
#     U \cdot R_f = R_e \cdot (V_{cc} - U)
# On isole R_e (U < V_cc) :
#     R_e = \frac{R_f \cdot U}{V_{cc} - U}
# Montage "etape_vers_vcc" (résistances inversées), la tension mesurée est
# celle aux bornes de R_f :
#     U = \frac{V_{cc} \cdot R_f}{R_f + R_e}
#     U \cdot R_f + U \cdot R_e = V_{cc} \cdot R_f
#     R_e = \frac{R_f \cdot (V_{cc} - U)}{U}
# Hypothèse : la résistance de l'eTape est une fonction affine de la hauteur
# d'eau h. Elle passe par les deux points (h_v, R_v) "vide" et (h_p, R_p) "plein" :
#     R_e = R_v + (R_p - R_v) \cdot \frac{h - h_v}{h_p - h_v}
# On isole h :
#     R_e - R_v = (R_p - R_v) \cdot \frac{h - h_v}{h_p - h_v}
#     h = h_v + (h_p - h_v) \cdot \frac{R_e - R_v}{R_p - R_v}
# Pourcentage entre la hauteur h_0 (0 %) et la hauteur h_100 (100 %) :
#     p = 100 \cdot \frac{h - h_0}{h_{100} - h_0}
# Seuil niveau bas envoyé à l'Arduino pour p_s % : on inverse la chaîne.
#     h_s = h_0 + \frac{p_s}{100} \cdot (h_{100} - h_0)
#     R_s = R_v + (R_p - R_v) \cdot \frac{h_s - h_v}{h_p - h_v}
#     U_s = \frac{V_{cc} \cdot R_s}{R_f + R_s}
# Sens : U croît quand R_e croît, car
#     \frac{dU}{dR_e} = \frac{V_{cc} \cdot R_f}{(R_f + R_e)^2} > 0
# et R_e croît quand le niveau baisse, donc niveau bas si U > U_s (sens = 1).
# Dans le montage inversé, U décroît quand R_e croît : niveau bas si U < U_s (sens = -1).


def resistance_etape(u_mV, cal_et):
    """Résistance de l'eTape (ohm) calculée par le pont diviseur."""
    if u_mV is None:
        return None
    vcc, rf = cal_et["vcc_mV"], cal_et["r_fixe_ohm"]
    if cal_et.get("montage", "etape_vers_masse") == "etape_vers_masse":
        if u_mV <= 0 or u_mV >= vcc:
            return None
        return rf * u_mV / (vcc - u_mV)
    if u_mV <= 0 or u_mV >= vcc:
        return None
    return rf * (vcc - u_mV) / u_mV


def tension_etape(r_ohm, cal_et):
    """Tension attendue (mV) pour une résistance d'eTape donnée (inverse de resistance_etape)."""
    vcc, rf = cal_et["vcc_mV"], cal_et["r_fixe_ohm"]
    if cal_et.get("montage", "etape_vers_masse") == "etape_vers_masse":
        return vcc * r_ohm / (rf + r_ohm)
    return vcc * rf / (rf + r_ohm)


def hauteur_depuis_resistance(r_ohm, cal_et):
    if r_ohm is None or cal_et["r_plein_ohm"] == cal_et["r_vide_ohm"]:
        return None
    hv, hp = cal_et["h_vide_cm"], cal_et["h_plein_cm"]
    rv, rp = cal_et["r_vide_ohm"], cal_et["r_plein_ohm"]
    return hv + (hp - hv) * (r_ohm - rv) / (rp - rv)


def resistance_depuis_hauteur(h_cm, cal_et):
    hv, hp = cal_et["h_vide_cm"], cal_et["h_plein_cm"]
    rv, rp = cal_et["r_vide_ohm"], cal_et["r_plein_ohm"]
    return rv + (rp - rv) * (h_cm - hv) / (hp - hv)


def niveau_cm_depuis_mV(u_mV, cal_et):
    return hauteur_depuis_resistance(resistance_etape(u_mV, cal_et), cal_et)


def niveau_pct(h_cm, cal_et):
    """Niveau en % (borné entre 0 et 100)."""
    if h_cm is None:
        return None
    h0, h100 = cal_et["h_0pct_cm"], cal_et["h_100pct_cm"]
    if h100 == h0:
        return None
    return max(0.0, min(100.0, 100.0 * (h_cm - h0) / (h100 - h0)))


def seuil_niveau_bas(cal_et, pct):
    """(seuil en mV, sens) à envoyer par la commande 'N' pour un niveau bas de pct %."""
    h0, h100 = cal_et["h_0pct_cm"], cal_et["h_100pct_cm"]
    h_s = h0 + pct / 100.0 * (h100 - h0)
    r_s = resistance_depuis_hauteur(h_s, cal_et)
    u_s = tension_etape(r_s, cal_et)
    sens = 1 if cal_et.get("montage", "etape_vers_masse") == "etape_vers_masse" else -1
    return int(round(u_s)), sens


def etalonnage_etape(u_vide_mV, h_vide_cm, u_plein_mV, h_plein_cm, cal_et):
    """Nouveaux paramètres eTape après les mesures vide / plein (2 points)."""
    nouv = dict(cal_et)
    rv = resistance_etape(u_vide_mV, cal_et)
    rp = resistance_etape(u_plein_mV, cal_et)
    if rv is None or rp is None or rv == rp:
        return None
    nouv.update({"r_vide_ohm": round(rv, 1), "h_vide_cm": h_vide_cm,
                 "r_plein_ohm": round(rp, 1), "h_plein_cm": h_plein_cm,
                 "h_0pct_cm": h_vide_cm, "h_100pct_cm": h_plein_cm})
    return nouv


# --- 4.4 Lecture des lignes du protocole -------------------------------------

def _nombre(texte):
    try:
        v = float(texte)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _cles_valeurs(texte):
    d = {}
    for morceau in texte.split(","):
        cle, _, valeur = morceau.strip().partition("=")
        if cle:
            d[cle.strip()] = valeur.strip()
    return d


def parser_mesure(ligne):
    """'M ph=..,ec=..,...' -> dictionnaire de flottants (None si 'nan' ou absent)."""
    if not ligne or not ligne.startswith("M "):
        return None
    brut = _cles_valeurs(ligne[2:])
    return {cle: _nombre(brut.get(cle)) for cle in ("ph", "ec", "niv", "te", "ta", "hu", "lux", "inc")}


def parser_etat(ligne):
    """'E pompes=1000,secours=0,chute=0,niv_bas=0,inc=2.1' -> dictionnaire."""
    if not ligne or not ligne.startswith("E "):
        return None
    brut = _cles_valeurs(ligne[2:])
    bits = (brut.get("pompes", "") + "0000")[:4]
    return {"pompes": [c == "1" for c in bits],
            "secours": brut.get("secours") == "1",
            "chute": brut.get("chute") == "1",
            "niv_bas": brut.get("niv_bas") == "1",
            "inc": _nombre(brut.get("inc"))}


def valeur_plausible(nom, v):
    """Rejette les valeurs physiquement impossibles (sonde débranchée, code d'erreur)."""
    if v is None:
        return False
    bornes = {"ph": (0.0, 14.0), "ec": (0.0, 10.0), "te": (0.0, 50.0)}
    lo, hi = bornes[nom]
    return lo <= v <= hi


# =============================================================================
# 5. Filtrage
# =============================================================================

class FiltreMedian:
    """Médiane glissante des n dernières valeurs retenues ; garde la dernière valeur valide."""

    def __init__(self, n=5):
        self.valeurs = deque(maxlen=n)
        self.derniere = None
        self.t_dernier = None

    def ajouter(self, v, t):
        self.valeurs.append(v)
        self.derniere = statistics.median(self.valeurs)
        self.t_dernier = t
        return self.derniere

    def vider(self):
        """Vide la fenêtre (nouveau brassage) mais garde la dernière valeur valide."""
        self.valeurs.clear()

    def plein(self):
        return len(self.valeurs) == self.valeurs.maxlen


def mesure_eau_valide(t, t_derniere_circulation, t_fin_dose, circulation_en_marche, cfg_mesure):
    """Vrai si pH, EC et température de l'eau peuvent être retenus à l'instant t.

    Conditions : circulation arrêtée depuis au moins 'stabilisation_s', aucune dose
    depuis 'attente_apres_dose_s' et, si 'exiger_brassage_apres_dose', la circulation
    a tourné depuis la dernière dose (sinon la dose n'est pas encore mélangée).
    """
    if circulation_en_marche:
        return False
    if t_derniere_circulation is not None and t - t_derniere_circulation < cfg_mesure["stabilisation_s"]:
        return False
    if t_fin_dose is not None:
        if t - t_fin_dose < cfg_mesure["attente_apres_dose_s"]:
            return False
        if cfg_mesure.get("exiger_brassage_apres_dose", True):
            if t_derniere_circulation is None or t_derniere_circulation < t_fin_dose:
                return False
    return True


# =============================================================================
# 6. Alertes et décision de dosage (fonctions pures)
# =============================================================================

def evaluer_alertes(ph, ec, temp_eau, plages):
    """Alertes de qualité de l'eau (n'empêchent pas le dosage) : nom -> message."""
    a = {}
    if ph is not None and ph < plages["ph_min"]:
        a["ph_bas"] = ("pH trop bas (%.2f < %.2f) : la tour n'a pas de pH+, corriger à la main"
                       % (ph, plages["ph_min"]))
    if ph is not None and ph > plages["ph_max"]:
        a["ph_haut"] = "pH haut (%.2f > %.2f)" % (ph, plages["ph_max"])
    if ec is not None and ec > plages["ec_max"]:
        a["ec_haute"] = ("EC trop haute (%.2f > %.2f mS/cm) : ajouter de l'eau claire dans le bac"
                         % (ec, plages["ec_max"]))
    if ec is not None and ec < plages["ec_min"]:
        a["ec_basse"] = "EC basse (%.2f < %.2f mS/cm)" % (ec, plages["ec_min"])
    if temp_eau is not None and temp_eau > plages["temp_eau_alarme"]:
        a["temp_eau_haute"] = ("Eau trop chaude (%.1f > %.1f °C) : ombrer le bac"
                               % (temp_eau, plages["temp_eau_alarme"]))
    return a


def decider_dosage(ctx, cfg):
    """Décide la correction à faire pendant l'arrêt en cours.

    ctx : dictionnaire avec
      t, debut_arret (s), prochain_demarrage (s), circulation_en_marche,
      derniere_correction (s ou None), nb_engrais_jour, nb_ph_jour,
      alarmes (ensemble de noms), ph, ec, mesures_fraiches
    Renvoie {"actions": [(pompe, ms), ...], "type": "engrais"|"ph"|None,
             "raison": texte, "plafond": None|"engrais"|"ph"}.
    """
    d = cfg["dosage"]
    res = {"actions": [], "type": None, "raison": "", "plafond": None}

    def refus(raison):
        res["raison"] = raison
        return res

    if not d["actif"]:
        return refus("dosage désactivé")
    if ctx["circulation_en_marche"] or ctx["debut_arret"] is None:
        return refus("circulation en marche")
    bloquantes = set(ctx["alarmes"]) & set(cfg["alarmes_bloquant_dosage"])
    if bloquantes:
        return refus("alarme : " + ", ".join(sorted(bloquantes)))
    if ctx["derniere_correction"] is not None and ctx["derniere_correction"] >= ctx["debut_arret"]:
        return refus("déjà une correction pendant cet arrêt")
    if ctx["t"] < ctx["debut_arret"] + d["delai_apres_arret_s"]:
        return refus("trop tôt après l'arrêt")
    if not ctx["mesures_fraiches"] or ctx["ph"] is None or ctx["ec"] is None:
        return refus("mesures pas encore stabilisées")

    limite = ctx["prochain_demarrage"] - d["marge_avant_demarrage_s"]

    def tient_avant_redemarrage(duree_s):
        return ctx["t"] + duree_s <= limite

    # Priorité 1 : EC trop basse -> engrais A puis B, même durée
    if ctx["ec"] < d["ec_dose_si_inferieure_a"]:
        if ctx["nb_engrais_jour"] >= d["max_corrections_engrais_jour"]:
            res["plafond"] = "engrais"
        else:
            duree = 2 * d["dose_engrais_ms"] / 1000.0 + d["pause_entre_pompes_s"]
            if not tient_avant_redemarrage(duree):
                return refus("trop près du prochain démarrage")
            res["actions"] = [(POMPE_ENGRAIS_A, d["dose_engrais_ms"]),
                              (POMPE_ENGRAIS_B, d["dose_engrais_ms"])]
            res["type"] = "engrais"
            res["raison"] = "EC %.3f < %.3f mS/cm" % (ctx["ec"], d["ec_dose_si_inferieure_a"])
            return res

    # Priorité 2 : pH trop haut -> pH-
    if ctx["ph"] > d["ph_dose_si_superieur_a"]:
        if ctx["nb_ph_jour"] >= d["max_corrections_ph_jour"]:
            res["plafond"] = res["plafond"] or "ph"
            return refus("plafond journalier atteint")
        if not tient_avant_redemarrage(d["dose_ph_ms"] / 1000.0):
            return refus("trop près du prochain démarrage")
        res["actions"] = [(POMPE_PH_MOINS, d["dose_ph_ms"])]
        res["type"] = "ph"
        res["raison"] = "pH %.2f > %.2f" % (ctx["ph"], d["ph_dose_si_superieur_a"])
        return res

    if res["plafond"]:
        return refus("plafond journalier atteint")
    return refus("eau dans la plage")


# =============================================================================
# 7. Liaison série
# =============================================================================

class LiaisonPerdue(Exception):
    pass


class LiaisonSerie:
    """Dialogue commande / réponse avec l'Arduino, messages spontanés (# et !) transmis au rappel."""

    def __init__(self, cfg_serie, sur_spontane=None):
        self.cfg = cfg_serie
        self.sur_spontane = sur_spontane or (lambda ligne: None)
        self.ser = None
        self.port = None
        self.tampon = b""
        self.echecs = 0
        self.verrou = threading.RLock()

    def ports_candidats(self):
        if self.cfg["port"] != "auto":
            return [self.cfg["port"]]
        return sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*"))

    def est_ouverte(self):
        return self.ser is not None

    def ouvrir(self):
        """Essaie chaque port candidat ; garde le premier qui répond 'OK P'."""
        if serial is None:
            raise RuntimeError("pyserial absent : sudo apt install python3-serial")
        for port in self.ports_candidats():
            try:
                ser = serial.Serial(port, self.cfg["vitesse"], timeout=0.02, exclusive=True)
            except (serial.SerialException, OSError, ValueError) as e:
                LOG.warning("port %s inutilisable : %s", port, e)
                continue
            self.ser, self.port, self.tampon, self.echecs = ser, port, b"", 0
            try:
                self.attendre_pret()
                for _ in range(3):
                    if self.commande("P", ("OK P",)) is not None:
                        return True
            except LiaisonPerdue:
                pass
            self.fermer()
        return False

    def attendre_pret(self):
        """L'ouverture du port redémarre l'Uno : on attend '# pret' (délai max), puis on continue."""
        limite = time.monotonic() + self.cfg["attente_pret_s"]
        with self.verrou:
            while True:
                reste = limite - time.monotonic()
                if reste <= 0:
                    LOG.warning("'# pret' non reçu sur %s, on continue avec P", self.port)
                    return False
                ligne = self._lire_ligne(reste)
                if ligne is None:
                    continue
                if ligne and self._traiter_spontane(ligne):
                    if ligne.replace(" ", "").lower() == "#pret":
                        return True

    def fermer(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def _lire_ligne(self, delai_s):
        """Renvoie une ligne complète (sans fin de ligne) ou None après delai_s secondes."""
        limite = time.monotonic() + delai_s
        while True:
            if b"\n" in self.tampon:
                ligne, _, self.tampon = self.tampon.partition(b"\n")
                return ligne.decode("ascii", "replace").strip()
            try:
                n = self.ser.in_waiting
                morceau = self.ser.read(n if n else 1)
            except (serial.SerialException, OSError, TypeError) as e:
                raise LiaisonPerdue(str(e))
            if morceau:
                self.tampon += morceau
                continue
            if time.monotonic() >= limite:
                return None

    def _traiter_spontane(self, ligne):
        if ligne.startswith("#") or ligne.startswith("!"):
            self.sur_spontane(ligne)
            return True
        return False

    def lire_spontanes(self):
        """Lit sans attendre les messages spontanés déjà arrivés."""
        with self.verrou:
            if self.ser is None:
                raise LiaisonPerdue("port fermé")
            while True:
                ligne = self._lire_ligne(0.0)
                if ligne is None:
                    return
                if ligne and not self._traiter_spontane(ligne):
                    LOG.debug("ligne ignorée : %s", ligne)

    def commande(self, cmd, prefixes, delai_s=None):
        """Envoie cmd, attend une ligne commençant par un des préfixes (ou 'ERR').

        Renvoie la ligne, ou None si pas de réponse. Lève LiaisonPerdue si le port
        est perdu ou après trop d'absences de réponse consécutives.
        """
        delai_s = self.cfg["timeout_reponse_s"] if delai_s is None else delai_s
        with self.verrou:
            if self.ser is None:
                raise LiaisonPerdue("port fermé")
            try:
                self.ser.write((cmd + "\n").encode("ascii"))
                self.ser.flush()
            except (serial.SerialException, OSError) as e:
                raise LiaisonPerdue(str(e))
            limite = time.monotonic() + delai_s
            while True:
                reste = limite - time.monotonic()
                ligne = self._lire_ligne(max(0.0, reste))
                if ligne is None:
                    self.echecs += 1
                    LOG.warning("pas de réponse à '%s' (%d)", cmd, self.echecs)
                    if self.echecs >= self.cfg["echecs_avant_reconnexion"]:
                        raise LiaisonPerdue("trop de commandes sans réponse")
                    return None
                if not ligne or self._traiter_spontane(ligne):
                    continue
                if ligne.startswith("ERR") or any(ligne.startswith(p) for p in prefixes):
                    self.echecs = 0
                    return ligne
                LOG.debug("réponse inattendue à '%s' : %s", cmd, ligne)


# =============================================================================
# 8. Journal CSV et envoi au serveur
# =============================================================================

class Journal:
    """journal.csv : horodatage ; type (ACTION, ALARME, FIN_ALARME, INFO, ERREUR) ; message."""

    def __init__(self, chemin, horloge):
        self.chemin = chemin
        self.horloge = horloge
        self.verrou = threading.Lock()
        self.a_pousser = deque()   # entrées à envoyer à /api/journal
        self.vus = {}              # message -> dernier instant écrit (dédoublonnage)

    def ecrire_une_fois(self, type_, message, periode_s):
        """N'écrit pas un message identique déjà écrit depuis moins de periode_s (messages # répétés)."""
        t = self.horloge.t()
        if message in self.vus and t - self.vus[message] < periode_s:
            return
        self.vus[message] = t
        self.ecrire(type_, message)

    def ecrire(self, type_, message):
        horodatage = self.horloge.maintenant().isoformat(timespec="seconds")
        LOG.info("[%s] %s", type_, message)
        self.a_pousser.append({"t": self.horloge.utc_z(), "type": type_, "message": message})
        with self.verrou:
            neuf = not os.path.exists(self.chemin)
            with open(self.chemin, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                if neuf:
                    w.writerow(["horodatage", "type", "message"])
                w.writerow([horodatage, type_, message])


class EnvoiServeur:
    """POST JSON vers /api/data ; file d'attente locale (JSON Lines) si le serveur ne répond pas."""

    def __init__(self, cfg_serveur, chemin_file, chemin_rejets, journal, url=None):
        self.cfg = cfg_serveur
        self.url = url or cfg_serveur["url"]
        self.chemin_file = chemin_file
        self.chemin_rejets = chemin_rejets
        self.journal = journal
        self.file = deque()
        self.en_panne = False
        # le serveur est local : on ignore tout proxy éventuel
        self.ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        utilisateur = os.environ.get("HYDRO_USER", "")
        mot_de_passe = os.environ.get("HYDRO_PASS", "")
        self.entete_auth = None
        if utilisateur:
            jeton = base64.b64encode(("%s:%s" % (utilisateur, mot_de_passe)).encode("utf-8")).decode("ascii")
            self.entete_auth = "Basic " + jeton
        else:
            LOG.warning("HYDRO_USER absent : envoi sans authentification")
        if os.path.exists(chemin_file):
            with open(chemin_file, "r", encoding="utf-8") as f:
                for ligne in f:
                    ligne = ligne.strip()
                    if ligne:
                        try:
                            self.file.append(json.loads(ligne))
                        except ValueError:
                            pass

    def _poster(self, donnees):
        """Code HTTP renvoyé, ou None si le serveur est injoignable."""
        corps = json.dumps(donnees).encode("utf-8")
        req = urllib.request.Request(self.url, data=corps, method="POST",
                                     headers={"Content-Type": "application/json"})
        if self.entete_auth:
            req.add_header("Authorization", self.entete_auth)
        try:
            with self.ouvreur.open(req, timeout=self.cfg["timeout_s"]) as rep:
                return rep.status
        except urllib.error.HTTPError as e:
            return e.code
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def _reecrire_file(self):
        tmp = self.chemin_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for d in self.file:
                f.write(json.dumps(d) + "\n")
        os.replace(tmp, self.chemin_file)

    def _ajouter_file(self, donnees):
        self.file.append(donnees)
        if len(self.file) > self.cfg["max_file"]:
            perdu = self.file.popleft()
            self._rejeter(perdu, "file pleine")
            self._reecrire_file()
        else:
            with open(self.chemin_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(donnees) + "\n")

    def _rejeter(self, donnees, raison):
        with open(self.chemin_rejets, "a", encoding="utf-8") as f:
            f.write(json.dumps({"raison": raison, "donnees": donnees}) + "\n")

    def _ok(self, code):
        return code is not None and 200 <= code < 300

    def _definitif(self, code):
        """Refus définitif : données mal formées (pas un problème de serveur ou d'identifiants)."""
        return code is not None and 400 <= code < 500 and code not in (401, 403, 404, 408, 429)

    def publier(self, donnees):
        if not self.file:
            code = self._poster(donnees)
            if self._ok(code):
                self._signaler(True, code)
                return True
            if self._definitif(code):
                self._rejeter(donnees, "HTTP %s" % code)
                if self.journal is not None:
                    self.journal.ecrire(
                        "ERREUR", "serveur : données refusées (HTTP %s), mises dans rejets.jsonl" % code)
                return False
            self._signaler(False, code)
        self._ajouter_file(donnees)
        self.vider()
        return False

    def vider(self):
        """Renvoie les données en attente, les plus anciennes d'abord."""
        if not self.file:
            return
        modif = False
        for _ in range(self.cfg["max_par_vidage"]):
            if not self.file:
                break
            code = self._poster(self.file[0])
            if self._ok(code):
                self.file.popleft()
                modif = True
                self._signaler(True, code)
            elif self._definitif(code):
                self._rejeter(self.file.popleft(), "HTTP %s" % code)
                modif = True
            else:
                self._signaler(False, code)
                break
        if modif:
            self._reecrire_file()

    def _signaler(self, ok, code):
        if self.journal is None:   # file du journal : pas d'alarme en double
            self.en_panne = not ok
            return
        if ok and self.en_panne:
            self.en_panne = False
            self.journal.ecrire("FIN_ALARME", "serveur de nouveau joignable (%d en attente)" % len(self.file))
        elif not ok and not self.en_panne:
            self.en_panne = True
            self.journal.ecrire("ALARME", "serveur injoignable (code %s) : données mises en file d'attente" % code)


# =============================================================================
# 9. Cerveau
# =============================================================================

class Cerveau:
    def __init__(self, config=None, dossier=".", horloge=None):
        self.cfg = fusion(CONFIG_DEFAUT, config or {})
        self.dossier = dossier
        f = self.cfg["fichiers"]
        self.chemins = {cle: os.path.join(dossier, nom) for cle, nom in f.items()}
        self.horloge = horloge or Horloge(self.cfg["fuseau"])
        self.journal = Journal(self.chemins["journal"], self.horloge)
        self.cal = charger_json(self.chemins["calibration"], CALIBRATION_DEFAUT)
        self.creneaux = creneaux_du_jour(self.cfg["planning"])
        self.liaison = LiaisonSerie(self.cfg["serie"], self._sur_spontane)
        self.envoi = EnvoiServeur(self.cfg["serveur"], self.chemins["file_attente"],
                                  self.chemins["rejets"], self.journal)
        self.envoi_journal = EnvoiServeur(self.cfg["serveur"], self.chemins["file_journal"],
                                          self.chemins["rejets"], None,
                                          url=self.cfg["serveur"]["url_journal"])

        t = self.horloge.t()
        n = self.cfg["mesure"]["taille_mediane"]
        self.filtres = {"ph": FiltreMedian(n), "ec": FiltreMedian(n),
                        "te": FiltreMedian(n), "niv": FiltreMedian(n)}
        self.air = {"ta": None, "hu": None, "lux": None}
        self.inclinaison = None
        self.niveau_cm = None
        self.invalides = {"ph": 0, "ec": 0, "te": 0, "niv": 0}
        self.alarmes = {}           # nom -> message (alarmes et alertes actives)
        self.circ_cmd = False       # circulation commandée par le Pi
        self.circ_reelle = False    # circulation vue en marche (commande ou état Arduino)
        self.t_dernier_bail = None
        self.t_derniere_circulation = t   # prudence au démarrage : on attend la stabilisation
        self.t_fin_dose = None
        self.fin_pompe = [0.0, 0.0, 0.0, 0.0]
        self.bits_arduino = [False, False, False, False]
        self.file_doses = deque()   # (instant prévu, pompe, ms)
        self.prochaine_lecture = t
        self.prochain_envoi = t + 5
        self.prochaine_connexion = 0.0
        self.arret = threading.Event()
        self._charger_etat()

    # ---- état persistant (compteurs journaliers) ----
    def _charger_etat(self):
        e = charger_json(self.chemins["etat"], {"date": None, "nb_engrais": 0, "nb_ph": 0,
                                                "derniere_correction": None})
        self.etat = e

    def _sauver_etat(self):
        ecrire_json_atomique(self.chemins["etat"], self.etat)

    def _compteurs_du_jour(self, dt_local):
        jour = dt_local.date().isoformat()
        if self.etat["date"] != jour:
            self.etat.update({"date": jour, "nb_engrais": 0, "nb_ph": 0})
            self._sauver_etat()
            for nom in ("plafond_engrais", "plafond_ph"):
                self._alarme(nom, False)

    # ---- alarmes ----
    def _alarme(self, nom, active, message=""):
        if active and nom not in self.alarmes:
            self.alarmes[nom] = message or nom
            self.journal.ecrire("ALARME", "%s : %s" % (nom, message or nom))
        elif active:
            self.alarmes[nom] = message or nom
        elif not active and nom in self.alarmes:
            del self.alarmes[nom]
            self.journal.ecrire("FIN_ALARME", nom)

    # ---- messages spontanés de l'Arduino ----
    def _sur_spontane(self, ligne):
        if ligne.startswith("#"):
            # info pour l'humain, jamais bloquante ; les messages répétés (carte pompes
            # absente toutes les 10 s) ne sont écrits qu'une fois par heure
            self.journal.ecrire_une_fois("INFO", "Arduino : " + ligne[1:].strip(),
                                         self.cfg["repetition_messages_info_s"])
            return
        msg = ligne[1:].strip()
        if msg == "CHUTE":
            self._alarme("chute", True, "chute de la tour détectée par l'Arduino, tout est arrêté ; "
                                        "redresser puis réarmer (calibrer.py, commande R)")
            self._pompes_arretees_par_arduino()
        elif msg == "NIVEAU_BAS":
            self._alarme("niveau_bas", True, "niveau bas : circulation coupée par l'Arduino, ajouter de l'eau")
            self.circ_cmd = False
            self.bits_arduino[0] = False
        elif msg == "NIVEAU_OK":
            self._alarme("niveau_bas", False)
        elif msg == "SECOURS 1":
            self._alarme("secours", True, "Arduino en mode secours (Pi silencieux)")
        elif msg == "SECOURS 0":
            self._alarme("secours", False)
        else:
            self.journal.ecrire("INFO", "Arduino : !" + msg)

    def _pompes_arretees_par_arduino(self):
        self.circ_cmd = False
        self.file_doses.clear()
        self.bits_arduino = [False, False, False, False]
        t = self.horloge.t()
        self.fin_pompe = [min(f, t) for f in self.fin_pompe]

    # ---- connexion ----
    def _gerer_connexion(self, t_reel):
        if self.liaison.est_ouverte() or t_reel < self.prochaine_connexion:
            return
        if self.liaison.ouvrir():
            self.journal.ecrire("INFO", "Arduino connecté sur %s" % self.liaison.port)
            self._alarme("liaison_arduino", False)
            self.circ_cmd = False      # état inconnu après redémarrage : on renvoie un bail
            self.file_doses.clear()
            self.prochaine_lecture = self.horloge.t()
        else:
            self._alarme("liaison_arduino", True, "Arduino introuvable ou muet")
            self.prochaine_connexion = t_reel + self.cfg["serie"]["pause_reconnexion_s"]

    def _perte_liaison(self, raison):
        self.liaison.fermer()
        self._alarme("liaison_arduino", True, "liaison perdue : %s" % raison)
        self.circ_cmd = False
        self.file_doses.clear()
        self.prochaine_connexion = time.monotonic() + self.cfg["serie"]["pause_reconnexion_s"]

    def _refus_arduino(self, rep, quoi):
        """Réponse ERR de l'Arduino : journal, et alarme si elle révèle une sécurité active."""
        raison = rep[3:].strip()
        if raison == "chute":
            self._alarme("chute", True, "chute de la tour (refus de l'Arduino)")
            self._pompes_arretees_par_arduino()
        elif raison == "niveau_bas":
            self._alarme("niveau_bas", True, "niveau bas (refus de l'Arduino)")
        self.journal.ecrire_une_fois("ERREUR", "%s refusée par l'Arduino : %s" % (quoi, rep),
                                     self.cfg["repetition_messages_info_s"])

    # ---- circulation ----
    def _maj_circulation_reelle(self, t):
        en_marche = self.circ_cmd or self.bits_arduino[0]
        if en_marche and not self.circ_reelle:
            # nouveau brassage : les mesures de l'arrêt précédent ne comptent plus
            for nom in ("ph", "ec", "te"):
                self.filtres[nom].vider()
        if en_marche:
            self.t_derniere_circulation = t
        self.circ_reelle = en_marche

    def gerer_circulation(self, t, dt):
        plan = etat_planning(dt, self.creneaux)
        autorise = plan["en_marche"] and "chute" not in self.alarmes and "niveau_bas" not in self.alarmes
        bail = 0
        if autorise:
            bail = duree_bail_ms(t, plan["fin_creneau"].timestamp(), self.cfg["circulation"]["bail_ms"])
            autorise = bail >= 1000
        if autorise:
            delai = (self.cfg["circulation"]["renouvellement_s"] if self.circ_cmd
                     else self.cfg["relance_circulation_refusee_s"])
            if self.t_dernier_bail is None or t - self.t_dernier_bail >= delai:
                rep = self.liaison.commande("D 0 %d" % bail, ("OK D",))
                self.t_dernier_bail = t
                if rep and rep.startswith("OK"):
                    if not self.circ_cmd:
                        self.journal.ecrire("ACTION", "démarrage circulation (jusqu'à %s)"
                                            % plan["fin_creneau"].strftime("%H:%M"))
                    self.circ_cmd = True
                    self.bits_arduino[0] = True
                    self.fin_pompe[0] = t + bail / 1000.0
                elif rep:
                    self._refus_arduino(rep, "circulation")
                    self.circ_cmd = False
        elif self.circ_cmd:
            rep = self.liaison.commande("D 0 0", ("OK D",))
            self.circ_cmd = False
            self.t_dernier_bail = None
            self.bits_arduino[0] = False
            self.fin_pompe[0] = t
            self.t_derniere_circulation = t
            if rep and rep.startswith("ERR"):
                self._refus_arduino(rep, "arrêt circulation")
            self.journal.ecrire("ACTION", "arrêt circulation" + ("" if rep and rep.startswith("OK")
                                                                 else " (réponse : %s)" % rep))
        self._maj_circulation_reelle(t)
        return plan

    # ---- mesures ----
    def lire_capteurs(self, t):
        rep = self.liaison.commande("L", ("M ",), self.cfg["serie"]["timeout_lecture_s"])
        m = parser_mesure(rep) if rep else None
        if m is None:
            return
        cm = self.cfg["mesure"]
        valide = mesure_eau_valide(t, self.t_derniere_circulation, self.t_fin_dose,
                                   self.circ_reelle, cm)
        seuil_inv = cm["lectures_invalides_avant_alarme"]

        def suivre_capteur(nom, ok, alarme, message):
            self.invalides[nom] = 0 if ok else self.invalides[nom] + 1
            if ok:
                self._alarme(alarme, False)
            elif self.invalides[nom] >= seuil_inv:
                self._alarme(alarme, True, message)

        # température de l'eau (nécessaire à la compensation de l'EC)
        te = m["te"]
        te_ok = valeur_plausible("te", te)
        suivre_capteur("te", te_ok, "capteur_temp_eau", "sonde DS18B20 absente ou hors plage")
        if te_ok and valide:
            self.filtres["te"].ajouter(te, t)
        t_comp = te if te_ok else self.filtres["te"].derniere

        ph = ph_depuis_mV(m["ph"], self.cal["ph"])
        ph_ok = valeur_plausible("ph", ph)
        suivre_capteur("ph", ph_ok, "capteur_ph", "sonde pH absente ou hors plage")
        if ph_ok and valide:
            self.filtres["ph"].ajouter(ph, t)

        ec = ec25_depuis_mV(m["ec"], t_comp, self.cal["ec"]) if t_comp is not None else None
        ec_ok = valeur_plausible("ec", ec)
        suivre_capteur("ec", ec_ok, "capteur_ec", "sonde EC absente ou hors plage")
        if ec_ok and valide:
            self.filtres["ec"].ajouter(ec, t)

        h = niveau_cm_depuis_mV(m["niv"], self.cal["etape"])
        suivre_capteur("niv", h is not None, "capteur_niveau", "eTape absente ou hors plage")
        if h is not None:
            self.niveau_cm = self.filtres["niv"].ajouter(h, t)
        pct = self.niveau_pct()
        if pct is not None:
            self._alarme("niveau_faible", pct < self.cfg["dosage"]["niveau_min_pct"],
                         "niveau %.0f %% < %d %% : dosage suspendu"
                         % (pct, self.cfg["dosage"]["niveau_min_pct"]))

        self.air = {"ta": m["ta"], "hu": m["hu"], "lux": m["lux"]}
        if m["inc"] is not None:
            self.inclinaison = m["inc"]

        alertes = evaluer_alertes(self.filtres["ph"].derniere, self.filtres["ec"].derniere,
                                  self.filtres["te"].derniere, self.cfg["plages"])
        for nom in ("ph_bas", "ph_haut", "ec_haute", "ec_basse", "temp_eau_haute"):
            self._alarme(nom, nom in alertes, alertes.get(nom, ""))

    def niveau_pct(self):
        return niveau_pct(self.niveau_cm, self.cal["etape"])

    def lire_etat(self, t):
        rep = self.liaison.commande("E", ("E ",))
        e = parser_etat(rep) if rep else None
        if e is None:
            return
        self.bits_arduino = e["pompes"]
        self._alarme("chute", e["chute"], "chute de la tour (état Arduino)")
        self._alarme("niveau_bas", e["niv_bas"], "niveau bas (état Arduino)")
        self._alarme("secours", e["secours"], "Arduino en mode secours")
        if e["chute"]:
            self._pompes_arretees_par_arduino()
        if e["inc"] is not None:
            self.inclinaison = e["inc"]
        self._maj_circulation_reelle(t)

    # ---- dosage ----
    def evaluer_dosage(self, t, dt, plan):
        if self.file_doses:
            return
        self._compteurs_du_jour(dt)
        debut_arret = None
        if not plan["en_marche"] and not self.circ_reelle:
            debut_arret = max(plan["debut_arret"].timestamp(), self.t_derniere_circulation)
        fraiches = all(self.filtres[n].plein() and debut_arret is not None
                       and self.filtres[n].t_dernier is not None
                       and self.filtres[n].t_dernier >= debut_arret
                       for n in ("ph", "ec"))
        ctx = {"t": t, "debut_arret": debut_arret,
               "prochain_demarrage": plan["prochain_demarrage"].timestamp(),
               "circulation_en_marche": self.circ_reelle,
               "derniere_correction": self.etat["derniere_correction"],
               "nb_engrais_jour": self.etat["nb_engrais"], "nb_ph_jour": self.etat["nb_ph"],
               "alarmes": set(self.alarmes), "ph": self.filtres["ph"].derniere,
               "ec": self.filtres["ec"].derniere, "mesures_fraiches": fraiches}
        dec = decider_dosage(ctx, self.cfg)
        if dec["plafond"]:
            self._alarme("plafond_" + dec["plafond"], True,
                         "plafond journalier de corrections %s atteint" % dec["plafond"])
        if not dec["actions"]:
            return
        pause = self.cfg["dosage"]["pause_entre_pompes_s"]
        instant = t
        for pompe, ms in dec["actions"]:
            self.file_doses.append((instant, pompe, ms))
            instant += ms / 1000.0 + pause
        self.etat["derniere_correction"] = t
        cle = "nb_engrais" if dec["type"] == "engrais" else "nb_ph"
        self.etat[cle] += 1
        self._sauver_etat()
        self.journal.ecrire("ACTION", "correction %s n°%d du jour : %s"
                            % (dec["type"], self.etat[cle], dec["raison"]))

    def executer_doses(self, t):
        if not self.file_doses or self.file_doses[0][0] > t:
            return
        instant, pompe, ms = self.file_doses.popleft()
        bloquantes = set(self.alarmes) & {"chute", "niveau_bas", "secours", "liaison_arduino"}
        if bloquantes or self.circ_reelle:
            self.journal.ecrire("ERREUR", "dose %s annulée (%s)" % (
                NOMS_POMPES[pompe], ", ".join(sorted(bloquantes)) or "circulation en marche"))
            self.file_doses.clear()
            return
        rep = self.liaison.commande("D %d %d" % (pompe, ms), ("OK D",))
        if rep and rep.startswith("OK"):
            fin = t + ms / 1000.0
            self.fin_pompe[pompe] = fin
            self.t_fin_dose = fin if self.t_fin_dose is None else max(self.t_fin_dose, fin)
            ml = ms / 60000.0 * self.cfg["dosage"]["debit_doseuse_ml_min"]
            self.journal.ecrire("ACTION", "dose %s : %d ms (environ %.1f mL)" % (NOMS_POMPES[pompe], ms, ml))
        else:
            if rep:
                self._refus_arduino(rep, "dose %s" % NOMS_POMPES[pompe])
            self.journal.ecrire("ERREUR", "dose %s non exécutée (réponse : %s), suite annulée"
                                % (NOMS_POMPES[pompe], rep))
            self.file_doses.clear()

    # ---- envoi ----
    def donnees_envoi(self, t):
        def arrondi(v, n):
            return None if v is None else round(v, n)
        pompes = {"circulation": bool(self.circ_cmd or self.bits_arduino[0]),
                  "engrais_a": bool(t < self.fin_pompe[1] or self.bits_arduino[1]),
                  "engrais_b": bool(t < self.fin_pompe[2] or self.bits_arduino[2]),
                  "ph_moins": bool(t < self.fin_pompe[3] or self.bits_arduino[3])}
        d = {"ph": arrondi(self.filtres["ph"].derniere, 2),
             "ec": arrondi(self.filtres["ec"].derniere, 3),
             "temp_eau": arrondi(self.filtres["te"].derniere, 2),
             "temp_air": self.air["ta"], "humidite": self.air["hu"], "lux": self.air["lux"],
             "niveau": arrondi(self.niveau_pct(), 1),
             "niveau_cm": arrondi(self.niveau_cm, 1),
             "pompes": pompes,
             "inclinaison": arrondi(self.inclinaison, 1),
             "alarmes": alarmes_pour_serveur(self.alarmes)}
        if self.cfg["serveur"]["envoyer_horodatage"]:
            # heure réelle de la mesure, en UTC suffixé Z : conservée telle quelle dans la
            # file d'attente, donc une mesure renvoyée après une coupure garde son heure
            d["t"] = self.horloge.utc_z()
        return d

    # ---- boucle ----
    def pas(self):
        """Un tour de boucle (environ une seconde)."""
        t = self.horloge.t()
        dt = self.horloge.maintenant()
        self._gerer_connexion(time.monotonic())
        if self.liaison.est_ouverte():
            try:
                self.liaison.lire_spontanes()
                plan = self.gerer_circulation(t, dt)
                self.executer_doses(t)
                if t >= self.prochaine_lecture:
                    self.prochaine_lecture = t + self.cfg["mesure"]["periode_lecture_s"]
                    self.lire_capteurs(t)
                    self.lire_etat(t)
                self.evaluer_dosage(t, dt, plan)
            except LiaisonPerdue as e:
                self._perte_liaison(str(e))
        if t >= self.prochain_envoi:
            self.prochain_envoi = t + self.cfg["serveur"]["periode_envoi_s"]
            self.envoi.publier(self.donnees_envoi(t))
            if self.envoi.file:
                self.envoi_journal.en_panne = True   # serveur absent : on n'insiste pas
        elif self.envoi.file and not self.envoi.en_panne:
            self.envoi.vider()
        self.pousser_journal()

    def pousser_journal(self):
        """Envoie le journal à /api/journal (une entrée par POST), avec file d'attente."""
        while self.journal.a_pousser:
            entree = self.journal.a_pousser.popleft()
            if self.cfg["serveur"]["envoyer_journal"]:
                self.envoi_journal._ajouter_file(entree)
        if self.envoi_journal.file and not self.envoi.en_panne:
            self.envoi_journal.vider()

    def executer(self, fin_t=None):
        self.journal.ecrire("INFO", "démarrage du cerveau")
        try:
            while not self.arret.is_set():
                if fin_t is not None and self.horloge.t() >= fin_t:
                    break
                self.pas()
                self.horloge.dormir(self.cfg["tick_s"])
        finally:
            self.terminer()

    def terminer(self):
        if self.liaison.est_ouverte():
            try:
                self.liaison.commande("S", ("OK S",))
            except LiaisonPerdue:
                pass
            self.liaison.fermer()
        self.journal.ecrire("INFO", "arrêt du cerveau (pompes arrêtées ; l'Arduino passera en secours après 5 min)")


# =============================================================================
# 10. Programme principal
# =============================================================================

def main(argv=None):
    ici = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Cerveau de la tour HydroTour")
    ap.add_argument("--config", default=os.path.join(ici, "config.json"))
    ap.add_argument("--port", help="port série (remplace config.json)")
    ap.add_argument("--acceleration", type=float, default=1.0,
                    help="démonstration avec faux_arduino : facteur d'accélération du temps")
    ap.add_argument("--verbeux", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbeux else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    config = charger_json(args.config, {})
    if args.port:
        config.setdefault("serie", {})["port"] = args.port
    dossier = os.path.dirname(os.path.abspath(args.config))
    fuseau = config.get("fuseau", CONFIG_DEFAUT["fuseau"])
    horloge = HorlogeAcceleree(time.time(), args.acceleration, fuseau) if args.acceleration != 1.0 else Horloge(fuseau)
    cerveau = Cerveau(config, dossier, horloge)

    def arreter(signum, frame):
        cerveau.arret.set()
    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGINT, arreter)
    cerveau.executer()


if __name__ == "__main__":
    main()
