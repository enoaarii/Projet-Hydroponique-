"""Essai de tout le matériel HydroTour d'un coup, avant de lancer le serveur.

Le serveur doit être ARRÊTÉ (un seul programme à la fois peut parler à l'Arduino).
Voir le guide ESSAIS.md (dans ce dossier).

  python essai_materiel.py                  tout : modules, capteurs, sondes, écran, pompes, sécurité
  python essai_materiel.py --sans-pompes    sans faire tourner les pompes
  python essai_materiel.py --sans-securite  sans l'essai de la coupure de sécurité (40 s)
"""
import argparse
import time

import arduino as A
import pilote as pl

resultats = []  # (élément, "OK" / "ÉCHEC" / "?", détail)


def note(element, ok, detail="", conseil=""):
    etat = "OK" if ok is True else "ÉCHEC" if ok is False else "?"
    resultats.append((element, etat, detail if ok is not False or not conseil else f"{detail} -> {conseil}"))
    print(f"  [{etat:^5}] {element:<28} {detail}")
    if ok is False and conseil:
        print(f"          {'':<28} -> {conseil}")


def oui(question):
    return input(f"  {question} (o/n) ").strip().lower().startswith("o")


def modules(c):
    print("\n1. Modules du bus I2C")
    attendus = [
        (A.MCP_ADDR, 0x00, "Carte 8 MOSFET (0x20)", "souder aucun cavalier A0-A2, vérifier SDA/SCL et le 5 V (Vcc)"),
        (A.ADS_ADDR, 0x01, "ADS1115 (0x48)", "ADDR relié à GND, alimentation 5 V"),
        (A.INA_ADDR, 0xFE, "INA260 batterie (0x40)", "A0 et A1 non pontés, VCC 5 V"),
        (A.RTC_ADDR, 0x00, "Horloge (0x68)", "pile en place, SDA/SCL"),
        (A.DHT_ADDR, None, "DHT20 air (0x38)", "brancher sur un port I2C du Sensor Kit"),
        (A.BMP_ADDR, 0xD0, "BMP280 pression (0x77)", "brancher sur un port I2C du Sensor Kit"),
        (A.OLED_ADDR, None, "Écran OLED (0x3C)", "brancher sur un port I2C du Sensor Kit"),
    ]
    for addr, reg, nom, conseil in attendus:
        r = c._lire_i2c(addr, reg, 2)
        detail = "répond" if r else "ne répond pas"
        if r and addr == A.INA_ADDR:
            detail += " (fabricant TI)" if r == [0x54, 0x49] else f" mais identifiant {r[0]:02X}{r[1]:02X} (autre module en 0x40 ?)"
        if r and addr == A.BMP_ADDR:
            detail += {0x58: " (BMP280)", 0x60: " (BME280)"}.get(r[0], f" mais identifiant {r[0]:02X}")
        note(nom, r is not None, detail, conseil)


def capteurs(c, r):
    print("\n2. Capteurs (valeurs à comparer avec la réalité)")
    t = c.lire_temp_eau()
    note("Température eau (DS18B20)", t is not None and -5 < t < 50, "—" if t is None else f"{t:.1f} °C",
         "sonde sur D2, résistance 4,7 k entre D2 et 5 V, programme HydroTour_Firmata téléversé")
    an = c.lire_analogiques(avec_ec=True)
    ph, s1, s2, ohm = an["ph_mv"], an["ec_s1"], an["ec_s2"], an["etape_ohm"]
    note("Sonde pH (ADS A0)", ph is not None and 200 < ph < 3000,
         "—" if ph is None else f"{ph:.0f} mV soit pH {pl.ph_depuis_mv(ph, r):.2f} (non étalonné)",
         "signal de la carte pH sur A0 de l'ADS1115, masse de la carte sur la sortie 4")
    x = None if s1 is None else pl.rapport_ec(s1, s2)
    ec = None if x is None else pl.ec_depuis_sommes(s1, s2, t, r)
    note("Sonde EC (graphite, A0 de l'Arduino)", x is not None,
         "—" if s1 is None else f"S1 = {s1}, S2 = {s2}" + ("" if x is None else f", x = {x:.3f}, soit {ec:.0f} µS/cm (non étalonné)"),
         "D5 -> R1 340 ohms -> point J (A0) -> sonde -> D6, programme HydroTour_Firmata avec la commande EC téléversé ; "
         "dans l'air : S1 proche de 1023 x 64, pas de valeur utilisable, c'est normal")
    note("Ruban eTape (ADS A2)", ohm is not None and 100 < ohm < 4000,
         "—" if ohm is None else f"{ohm:.0f} ohms soit {pl.niveau_depuis_ohm(ohm, r):.0f} % (non étalonné)",
         "5 V -> 560 ohms -> A2 -> ruban -> GND")
    air = c.lire_air()
    note("Air (DHT20)", air is not None, "—" if air is None else f"{air[0]:.1f} °C, {air[1]:.0f} %")
    p = c.lire_pression()
    note("Pression (BMP280)", p is not None and 900 < p < 1100, "—" if p is None else f"{p:.1f} hPa")
    time.sleep(1)
    lum = c.lire_lumiere()
    note("Lumière (A3)", lum is not None, "—" if lum is None else f"{lum:.0f} % (cacher le capteur : ça doit baisser)")
    b = c.lire_batterie()
    note("Batterie (INA260)", b is not None and 9 < b[0] < 16,
         "—" if b is None else f"{b[0]:.2f} V, {b[1]:+.2f} A ({'charge' if b[1] > 0 else 'décharge'})",
         "VIN+ côté contrôleur, VIN- côté batterie ; si la charge est négative au soleil, mettre INA_SENS = -1")
    h = c.lire_horloge()
    note("Horloge", h is not None, "—" if h is None else f"{h:%d/%m/%Y %H:%M:%S} UTC",
         "réglée toute seule par le serveur quand le Raspberry a Internet")


def interference(c, r):
    print("\n3. Alternance des sondes pH / EC (sondes dans l'eau du réservoir)")
    seul, _ = c.lire_ph_ec(avec_ec=False)
    c.mesurer_ec()  # exprès : mesure de l'EC avec la carte pH restée allumée
    ensemble = c._ads_mv(A.ADS_PH)
    c._ec_eteinte = time.monotonic()
    if seul is None or ensemble is None:
        note("Alternance pH / EC", None, "pas de lecture du pH")
        return
    ecart = abs(pl.ph_depuis_mv(ensemble, r) - pl.ph_depuis_mv(seul, r))
    note("Alternance pH / EC", True, f"pH {pl.ph_depuis_mv(seul, r):.2f} sans mesure EC, "
         f"{pl.ph_depuis_mv(ensemble, r):.2f} juste après une mesure EC (écart {ecart:.2f})"
         + (" : l'alternance est bien utile" if ecart > 0.1 else ""))
    seul2, _ = c.lire_ph_ec(avec_ec=False)
    if seul2 is not None:
        note("pH revenu après 5 s", abs(seul2 - seul) < 15, f"{pl.ph_depuis_mv(seul2, r):.2f}",
             "le pH met plus de 5 s à revenir : augmenter ATTENTE_PH dans arduino.py")


def ecran(c):
    print("\n4. Écran OLED")
    try:
        import PIL  # noqa: F401
    except ImportError:
        note("Écran OLED", False, "Pillow manquant", "pip install pillow")
        return
    c.afficher(["ESSAI HYDROTOUR", "", "Si tu lis ceci,", "l'ecran marche."])
    note("Écran OLED", oui("L'écran affiche-t-il « ESSAI HYDROTOUR » ?"))


def pompes(c):
    print("\n5. Pompes (chacune tourne quelques secondes)")
    print("  Mets les tuyaux des doseuses dans un verre d'eau : chaque essai pompe environ 3 mL.")
    if not oui("Prêt ?"):
        note("Pompes", None, "essai sauté")
        return
    for nom, s, texte in [("principale", 5, "Pompe principale"), ("engrais_a", 2, "Doseuse engrais A (sortie 1)"),
                          ("engrais_b", 2, "Doseuse engrais B (sortie 2)"), ("ph", 2, "Doseuse pH- (sortie 3)")]:
        print(f"  {texte} : marche {s} s...")
        try:
            c.set_pompe(nom, True)
            time.sleep(s)
        finally:
            c.set_pompe(nom, False)
        note(texte, oui("A-t-elle tourné, puis s'est-elle arrêtée ?"), "",
             "LED rouge de la sortie allumée ? sinon I2C ; allumée mais pompe immobile : V+ 12 V, fil - de la pompe sur la sortie")


def securite(c):
    print("\n6. Sécurité de l'Arduino (le Raspberry se tait 40 s)")
    if not oui("La pompe principale va tourner puis doit s'arrêter seule après 30 s. On essaie ?"):
        note("Sécurité 30 s", None, "essai sauté")
        return
    c.set_pompe("principale", True)
    c._vivant = False  # plus de message de présence
    print("  Pompe en marche, le Raspberry se tait...")
    for s in range(40, 0, -5):
        print(f"  {s} s")
        time.sleep(5)
    note("Sécurité 30 s", oui("La pompe s'est-elle arrêtée toute seule ?"), "",
         "vérifier que c'est bien HydroTour_Firmata qui est téléversé (et pas StandardFirmata)")
    c.set_pompe("principale", False)


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--sans-pompes", action="store_true")
    a.add_argument("--sans-securite", action="store_true")
    o = a.parse_args()
    print("Connexion à l'Arduino...")
    try:
        c = A.Arduino()
    except Exception as e:
        print("  Arduino introuvable :", e)
        print("  -> câble USB, `ls /dev/ttyACM* /dev/ttyUSB*`, utilisateur dans le groupe dialout")
        return
    time.sleep(2)
    nom = getattr(c.board, "firmware", None)
    note("Arduino", True, f"programme : {nom or 'inconnu'}",)
    if nom and "HydroTour" not in str(nom):
        note("Programme de l'Arduino", False, str(nom), "téléverser ARDUINO/HydroTour_Firmata")
    r = dict(pl.REGLAGES)
    try:
        modules(c)
        capteurs(c, r)
        interference(c, r)
        ecran(c)
        if not o.sans_pompes:
            pompes(c)
            if not o.sans_securite:
                securite(c)
    finally:
        c.eteindre_pompes()
        c.fermer()
    print("\nRésumé")
    for element, etat, detail in resultats:
        print(f"  {etat:<6} {element:<28} {detail}")
    n = sum(e == "ÉCHEC" for _, e, _ in resultats)
    print(f"\n{n} échec(s)." if n else "\nTout répond. Étape suivante : python server.py et l'étalonnage (voir le guide).")


if __name__ == "__main__":
    main()
