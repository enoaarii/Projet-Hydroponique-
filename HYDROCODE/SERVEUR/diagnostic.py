"""Diagnostic : qu'est-ce qui est vraiment branché sur l'Arduino ?

Arrête d'abord le serveur (il occupe le port USB), puis :
    sudo systemctl stop hydrotour
    venv/bin/python diagnostic.py
    sudo systemctl start hydrotour
"""
import time

import arduino as ar

NOMS = {0x20: "carte 8 MOSFET", 0x38: "DHT20 (air : température, humidité)", 0x3C: "écran OLED",
        0x3D: "écran OLED (autre adresse)", 0x40: "INA260 (batterie)", 0x48: "ADS1115 (pH, EC, niveau)",
        0x57: "mémoire du module horloge", 0x68: "horloge DS3231/DS1307",
        0x76: "BMP280/BME280 (adresse 0x76)", 0x77: "BMP280/BME280 (adresse 0x77)"}

c = ar.Arduino()
time.sleep(6)  # le temps que l'Arduino réponde au « qui es-tu ? » envoyé toutes les 5 s
print("Programme de l'Arduino :", getattr(c.board, "firmware", None), getattr(c.board, "firmware_version", None))
print("\n=== Modules I2C ===")
for addr, nom in NOMS.items():
    ok = c._lire_i2c(addr, None, 1) is not None
    print(f"  0x{addr:02X}  {'PRÉSENT' if ok else '  -    '}  {nom}")

print("\n=== Entrées analogiques (mV, 5 V = 5000) ===")
valeurs = {}
for pin in range(3):  # A3 est déjà suivi par arduino.py (lumière)
    c.board.analog[pin].register_callback(lambda v, p=pin: valeurs.__setitem__(p, v))
    c.board.analog[pin].enable_reporting()
time.sleep(2)
if c._lumiere:
    valeurs[3] = c._lumiere[-1]
for pin in range(4):
    v = valeurs.get(pin)
    print(f"  A{pin} : {'rien' if v is None else f'{v * 5000:.0f} mV'}")

print("\n=== Capteurs ===")
print("  Sonde de l'eau DS18B20 (D2) :", c.lire_temp_eau())
print("  DHT20 (température, humidité) :", c.lire_air())
print("  Pression BMP280 (hPa) :", c.lire_pression())
for addr in (0x76, 0x77):
    ident = c._lire_i2c(addr, 0xD0, 1)
    if ident:
        print(f"  Puce en 0x{addr:02X} : identifiant 0x{ident[0]:02X} "
              "(0x58 = BMP280, 0x60 = BME280 avec humidité)")
print("  Horloge :", c.lire_horloge())

print("\n=== Écran ===")
c.afficher(["DIAGNOSTIC", "HydroTour", time.strftime("%H:%M:%S")])
print("  Texte « DIAGNOSTIC » envoyé : regarde l'écran.")
time.sleep(2)  # laisse le temps au texte de partir avant de fermer le port USB
c.fermer()
