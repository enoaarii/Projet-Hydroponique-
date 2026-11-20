"""Liaison Raspberry Pi <-> Arduino par le câble USB, avec le protocole Firmata.

L'Arduino reçoit une seule fois le programme ARDUINO/HydroTour_Firmata : c'est
ConfigurableFirmata, plus une sécurité qui coupe toutes les pompes si le Raspberry
se tait pendant 30 s. L'Arduino reste une simple carte d'entrées/sorties : il lit
les capteurs et actionne les pompes, mais c'est le Raspberry qui décide (pilote.py).
Ce fichier ne renvoie que des valeurs brutes (mV, ohms...) : les conversions et
l'étalonnage sont dans pilote.py.

Port série : détecté tout seul. Sinon, ARDUINO_PORT=/dev/ttyACM0 (Uno)
ou /dev/ttyUSB0 (Nano clone) avant de lancer le serveur.

Câblage (Arduino Uno + Sensor Kit) :
  Bus I2C : SDA = A4, SCL = A5 (ou les ports I2C du Sensor Kit), modules en 5 V, GND commun.
    0x20  carte 8 MOSFET Adafruit 6318 (MCP23017). V+ = 12 V de la batterie (après le fusible).
          Sortie 0 = pompe principale, 1 = engrais A, 2 = engrais B, 3 = pH-,
          4 = masse (GND) de la carte de la sonde pH (la sortie 5 n'est plus utilisée).
          Le + de la carte de la sonde pH va au 5 V de l'Arduino, JAMAIS au + (12 V) de la carte MOSFET.
    0x48  convertisseur ADS1115, alimenté en 5 V : A0 = sonde pH, A2 = ruban eTape (la voie A1 est libre).
          Sans ADS1115, la carte de la sonde pH peut aller directement sur A1 de l'Arduino.
          eTape : 5 V -> résistance 560 ohms (fournie) -> A2 -> eTape -> GND.
    0x40  INA260 de la batterie. VIN+ côté contrôleur de charge, VIN- côté batterie
          (courant positif en charge, négatif en décharge).
    0x68  horloge DS3231 ou DS1307, réglée en UTC, sa pile garde l'heure.
    0x38  DHT20 (température et humidité de l'air, Sensor Kit)
    0x77  BMP280 (pression de l'air, Sensor Kit)
    0x3C  écran OLED 128 x 64 du Sensor Kit
  D2 : sonde DS18B20 de l'eau, résistance 4,7 kohms (fournie) entre D2 et 5 V.
  A3 : capteur de lumière du Sensor Kit.
  Sonde EC en graphite (rapport, partie 7.6) : D5 -> R1 (340 ohms) -> point J -> sonde -> D6,
  le point J est lu sur A0 de l'Arduino (pas sur l'ADS1115). La mesure se fait dans l'Arduino
  (commande SysEx 0x0E du programme HydroTour_Firmata) : il renvoie deux sommes S1 et S2.
  Les sondes pH et EC dans la même eau se perturbent : pendant la mesure de l'EC, la carte de
  la sonde pH est coupée (sortie 4) et le pH n'est pas lu dans les ATTENTE_PH s qui suivent.
"""
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

import pyfirmata2

PORT = os.environ.get("ARDUINO_PORT", pyfirmata2.Arduino.AUTODETECT)
VITESSE = 115200  # la même que dans HydroTour_Firmata.ino
PIN_LUMIERE = 3   # capteur de lumière du Sensor Kit sur A3
PIN_DS18B20 = 2   # sonde de température de l'eau sur D2
PIN_PH_DIRECT = 1  # sans ADS1115 : carte de la sonde pH branchée directement sur A1

POMPES = ["principale", "engrais_a", "engrais_b", "ph"]  # sorties 0, 1, 2, 3 de la carte 8 MOSFET
SONDE_PH = 4     # sortie de la carte 8 MOSFET qui alimente la sonde pH
ATTENTE_PH = 5   # s entre la fin de la mesure de l'EC et la lecture du pH
SONDE_EC = 5     # ancienne sortie de la carte DFR0300 (plus utilisée, gardée pour essai_materiel.py)

MCP_ADDR = 0x20  # carte 8 MOSFET
ADS_ADDR = 0x48  # ADS1115
INA_ADDR = 0x40  # INA260 (adresse par défaut, A0 et A1 non pontés)
INA_SENS = 1     # mettre -1 si VIN+ et VIN- sont inversés (charge affichée en négatif)
RTC_ADDR = 0x68  # adresse I2C commune au DS3231 et au DS1307
DHT_ADDR = 0x38
BMP_ADDR = 0x77
OLED_ADDR = 0x3C
ADS_PH, ADS_ETAPE = 0, 2
R_ETAPE = 560.0  # résistance fournie avec l'eTape, en série côté 5 V
VCC_MV = 5000.0

# Messages du protocole Firmata (gérés par ConfigurableFirmata).
I2C_REQUEST, I2C_REPLY, I2C_CONFIG = 0x76, 0x77, 0x78
I2C_WRITE, I2C_READ_ONCE = 0x00, 0x08
SANS_REGISTRE = 0  # registre renvoyé par ConfigurableFirmata 3.x pour une lecture I2C sans registre
ONEWIRE_DATA, OW_CONFIG, OW_READ_REPLY = 0x73, 0x41, 0x43
EC_COMMANDE = 0x0E  # « mesure EC » : commande ajoutée dans HydroTour_Firmata.ino (même numéro des deux côtés)
OW_RESET, OW_SKIP, OW_READ, OW_WRITE = 0x01, 0x02, 0x08, 0x20
REPORT_FIRMWARE = 0x79
STRING_DATA = 0x71  # message texte envoyé par l'Arduino (deux octets de 7 bits par caractère)


def _7bits(valeurs):
    """Firmata n'envoie que des octets de 7 bits : chaque valeur part en deux morceaux."""
    out = []
    for v in valeurs:
        out += [v & 0x7F, (v >> 7) & 0x7F]
    return out


def _encode7(octets):
    """Encodage « Encoder7Bit » du OneWire : un flot d'octets découpé en paquets de 7 bits."""
    out, decal, reste = [], 0, 0
    for b in octets:
        out.append(((b << decal) & 0x7F) | reste)
        reste = b >> (7 - decal)
        decal += 1
        if decal == 7:
            out.append(reste)
            decal, reste = 0, 0
    if decal:
        out.append(reste)
    return out


def _decode7(data):
    out = []
    for i in range(len(data) * 7 // 8):
        j = i * 8
        pos, decal = j // 7, j % 7
        suivant = data[pos + 1] if pos + 1 < len(data) else 0
        out.append(((data[pos] >> decal) | (suivant << (7 - decal))) & 0xFF)
    return out


def _crc8(octets):
    """CRC Dallas/Maxim des sondes DS18B20."""
    crc = 0
    for b in octets:
        for _ in range(8):
            m = (crc ^ b) & 1
            crc >>= 1
            if m:
                crc ^= 0x8C
            b >>= 1
    return crc


def _bcd(b):
    return (b >> 4) * 10 + (b & 0x0F)


def _vers_bcd(n):
    return (n // 10) << 4 | n % 10


def _s16(hi, lo):
    v = hi << 8 | lo
    return v - 0x10000 if v & 0x8000 else v


class Arduino:
    def __init__(self, port=PORT):
        self.board = pyfirmata2.Arduino(port, baudrate=VITESSE)
        self._lock = threading.RLock()
        self._lumiere = deque(maxlen=20)  # 20 dernières lectures de A3, pour lisser
        self.board.samplingOn(100)
        self.board.analog[PIN_LUMIERE].register_callback(self._lumiere.append)
        self.board.analog[PIN_LUMIERE].enable_reporting()
        self._ph_a1 = deque(maxlen=20)    # 20 dernières lectures de A1 (pH sans ADS1115)
        self.board.analog[PIN_PH_DIRECT].register_callback(self._ph_a1.append)
        self.board.analog[PIN_PH_DIRECT].enable_reporting()
        self._i2c = {}       # (adresse, registre) -> octets reçus
        self._attente = {}   # (adresse, registre) -> Event de la lecture en cours
        self._absent = {}    # adresse -> heure du prochain essai (module qui ne répond pas)
        self._textes = {}    # messages texte de l'Arduino -> nombre de fois reçus
        self._ec = None      # dernière réponse de la commande « mesure EC » : (S1, S2)
        self._ec_attente = threading.Event()
        self._ow = {}        # numéro de requête OneWire -> octets reçus
        self._ow_attente = {}
        self._ow_n = 0
        self.board.add_cmd_handler(I2C_REPLY, self._reponse_i2c)
        self.board.add_cmd_handler(ONEWIRE_DATA, self._reponse_onewire)
        self.board.add_cmd_handler(EC_COMMANDE, self._reponse_ec)
        # Indispensable : sans gestionnaire, pyfirmata2 abandonne un message texte en plein milieu
        # sans aller jusqu'à sa fin, et lit la suite de ce message comme si c'étaient de nouvelles
        # commandes. Le flux se décale et les réponses qui suivent (I2C, OneWire, EC) sont perdues.
        self.board.add_cmd_handler(STRING_DATA, self._reponse_texte)
        self.board.send_sysex(I2C_CONFIG, [0, 0])  # active le bus I2C (A4/A5)
        self.board.send_sysex(ONEWIRE_DATA, [OW_CONFIG, PIN_DS18B20, 1])
        self._sorties = 1 << SONDE_PH  # bit n = sortie n de la carte 8 MOSFET ; seule la sonde pH allumée
        self._ec_eteinte = time.monotonic() - ATTENTE_PH
        self._ecrire_i2c(MCP_ADDR, [0x00, 0x00])  # IODIRA : les 8 broches du port A en sorties
        self.rafraichir_pompes()                  # tout arrêté au démarrage
        self._bmp = None
        self._oled_regle = None   # heure du dernier réglage de l'écran OLED (None : jamais)
        self._oled_signale = set()  # problèmes d'écran déjà écrits dans le journal
        self._vivant = True
        threading.Thread(target=self._presence, daemon=True).start()

    # ---------- Bas niveau ----------
    def _presence(self):
        """Un petit message toutes les 5 s : l'Arduino sait que le Raspberry est là (sécurité 30 s)."""
        while self._vivant:
            with self._lock:
                self.board.send_sysex(REPORT_FIRMWARE, [])
            time.sleep(5)

    def _ecrire_i2c(self, addr, octets):
        with self._lock:
            self.board.send_sysex(I2C_REQUEST, [addr, I2C_WRITE] + _7bits(octets))

    def _reponse_i2c(self, *data):
        v = [data[i] | data[i + 1] << 7 for i in range(0, len(data) - 1, 2)]
        if len(v) >= 2:  # adresse, registre, puis les octets lus
            self._i2c[(v[0], v[1])] = v[2:]
            ev = self._attente.get((v[0], v[1]))
            if ev:
                ev.set()

    def _lire_i2c(self, addr, reg, n):
        """Lit n octets d'un module I2C à partir du registre reg (None : sans registre).
        Renvoie None s'il ne répond pas ; on ne le réessaie alors qu'une minute plus tard."""
        if time.monotonic() < self._absent.get(addr, 0):
            return None
        cle = (addr, SANS_REGISTRE if reg is None else reg)
        with self._lock:
            ev = self._attente[cle] = threading.Event()
            args = [n] if reg is None else [reg, n]
            self.board.send_sysex(I2C_REQUEST, [addr, I2C_READ_ONCE] + _7bits(args))
            ok = ev.wait(1)
            self._attente.pop(cle, None)
            octets = self._i2c.pop(cle, None)
        if ok and octets and len(octets) >= n:
            self._absent.pop(addr, None)
            return octets[:n]
        self._absent[addr] = time.monotonic() + 60
        return None

    def _reponse_onewire(self, *data):
        if len(data) < 2 or data[0] != OW_READ_REPLY:
            return
        octets = _decode7(list(data[2:]))
        if len(octets) >= 2:
            n = octets[0] | octets[1] << 8
            self._ow[n] = octets[2:]
            ev = self._ow_attente.get(n)
            if ev:
                ev.set()

    # ---------- Pompes (carte 8 MOSFET) ----------
    def set_pompe(self, nom, on):
        self._sortie(POMPES.index(nom), on)

    def _sortie(self, n, on):
        bit = 1 << n
        with self._lock:
            self._sorties = self._sorties | bit if on else self._sorties & ~bit
            self._ecrire_i2c(MCP_ADDR, [0x12, self._sorties])  # GPIOA

    def rafraichir_pompes(self):
        """Renvoie l'état voulu : remet les pompes en route après une coupure de sécurité de l'Arduino."""
        with self._lock:
            self._ecrire_i2c(MCP_ADDR, [0x00, 0x00])
            self._ecrire_i2c(MCP_ADDR, [0x12, self._sorties])

    def pompes(self):
        return {nom: bool(self._sorties >> i & 1) for i, nom in enumerate(POMPES)}

    def carte_pompes_branchee(self):
        """Vrai si la carte 8 MOSFET répond (relit le registre GPIOA)."""
        return self._lire_i2c(MCP_ADDR, 0x12, 1) is not None

    def eteindre_pompes(self):
        """Arrête les pompes sans toucher aux sondes."""
        for nom in POMPES:
            self.set_pompe(nom, False)

    # ---------- Capteurs ----------
    def _ads_mv(self, canal, n=5):
        """Tension d'une entrée de l'ADS1115 en mV (médiane de n lectures), ou None."""
        config = 0x8000 | (0x4 + canal) << 12 | 0x0100 | 0x0080 | 0x0003  # coup unique, ±6,144 V, 128 mesures/s
        valeurs = []
        for _ in range(n):
            self._ecrire_i2c(ADS_ADDR, [0x01, config >> 8, config & 0xFF])
            time.sleep(0.01)
            r = self._lire_i2c(ADS_ADDR, 0x00, 2)
            if r is None:
                return None
            valeurs.append(_s16(r[0], r[1]) * 0.1875)
        return sorted(valeurs)[n // 2]

    def _reponse_texte(self, *data):
        """Message texte de l'Arduino (erreur I2C, avertissement...). Chaque caractère arrive en deux
        octets de 7 bits. On n'écrit que les trois premières fois, pour ne pas remplir le journal."""
        texte = "".join(chr(data[i] | data[i + 1] << 7) for i in range(0, len(data) - 1, 2)).strip("\x00")
        n = self._textes.get(texte, 0) + 1
        self._textes[texte] = n
        if n <= 3:
            print("Arduino :", texte, flush=True)

    def _reponse_ec(self, *data):
        """Réponse de l'Arduino à la commande « mesure EC » : S1 et S2, chacune en 3 octets de 7 bits
        (poids faible d'abord). Exemple : S = d0 | d1 << 7 | d2 << 14."""
        if len(data) >= 6:
            s1 = data[0] | data[1] << 7 | data[2] << 14
            s2 = data[3] | data[4] << 7 | data[5] << 14
            self._ec = (s1, s2)
            self._ec_attente.set()

    def mesurer_ec(self):
        """(S1, S2) : sommes des 64 lectures de A0 dans chaque sens du courant, ou None si l'Arduino
        ne répond pas. Chaque somme est un entier de 0 à 65 472. La mesure dure environ 17 ms."""
        with self._lock:
            self._ec = None
            self._ec_attente.clear()
            self.board.send_sysex(EC_COMMANDE, [])
        if not self._ec_attente.wait(1):  # un seul tour de câble : la réponse arrive en quelques ms
            return None
        return self._ec

    def mesurer_ec_sur(self, essais=2):
        """Comme mesurer_ec, mais réessaie : une réponse peut être perdue si le flux série s'est
        décalé juste avant (message texte de l'Arduino, par exemple)."""
        for _ in range(essais):
            r = self.mesurer_ec()
            if r is not None:
                return r
        return None

    def lire_ph_ec(self, avec_ec=True):
        """(pH en mV, (S1, S2) de l'EC) : la carte de la sonde pH est coupée pendant la mesure de l'EC,
        et le pH n'est pas lu dans les ATTENTE_PH s qui suivent. None si pas de lecture."""
        attente = ATTENTE_PH - (time.monotonic() - self._ec_eteinte)
        if attente > 0:
            time.sleep(attente)
        ph, ec = self._ads_mv(ADS_PH), None
        if ph is None and self._ph_a1:  # pas d'ADS1115 : sonde pH sur A1 (10 bits, référence 5 V)
            ph = sorted(self._ph_a1)[len(self._ph_a1) // 2] * VCC_MV
        if avec_ec:
            try:
                self._sortie(SONDE_PH, False)  # carte pH coupée pendant la mesure
                ec = self.mesurer_ec_sur()
            finally:
                self._sortie(SONDE_PH, True)
                self._ec_eteinte = time.monotonic()
        return ph, ec

    def lire_analogiques(self, avec_ec=True):
        """{"ph_mv", "ec_s1", "ec_s2", "etape_ohm"} ; une valeur est None si le capteur ne répond pas."""
        ph, ec = self.lire_ph_ec(avec_ec)
        et = self._ads_mv(ADS_ETAPE)
        ohm = None
        if et is not None and 1 < et < VCC_MV - 1:
            ohm = R_ETAPE * et / (VCC_MV - et)
        s1, s2 = ec if ec else (None, None)
        return {"ph_mv": ph, "ec_s1": s1, "ec_s2": s2, "etape_ohm": ohm}

    def lire_temp_eau(self):
        """Température de l'eau (°C) de la DS18B20, ou None."""
        with self._lock:
            self.board.send_sysex(ONEWIRE_DATA, [OW_RESET | OW_SKIP | OW_WRITE, PIN_DS18B20] + _encode7([0x44]))
        time.sleep(0.8)  # durée d'une conversion en 12 bits
        self._ow_n = n = (self._ow_n + 1) % 0x4000
        with self._lock:
            ev = self._ow_attente[n] = threading.Event()
            self.board.send_sysex(ONEWIRE_DATA, [OW_RESET | OW_SKIP | OW_READ | OW_WRITE, PIN_DS18B20]
                                  + _encode7([9, 0, n & 0xFF, n >> 8, 0xBE]))
            ok = ev.wait(1)
            self._ow_attente.pop(n, None)
            sp = self._ow.pop(n, None)
        # Sans sonde, la réponse n'est que des zéros, et son CRC (0) a l'air juste : on la refuse.
        if not ok or not sp or len(sp) < 9 or not any(sp[:8]) or _crc8(sp[:8]) != sp[8]:
            return None
        t = _s16(sp[1], sp[0]) / 16
        return None if t in (85.0, -127.0) else round(t, 2)  # 85 °C : valeur de mise sous tension

    def lire_air(self):
        """(température °C, humidité %) du DHT20, ou None."""
        if time.monotonic() < self._absent.get(DHT_ADDR, 0):
            return None
        self._ecrire_i2c(DHT_ADDR, [0xAC, 0x33, 0x00])  # lance une mesure
        time.sleep(0.1)
        r = self._lire_i2c(DHT_ADDR, None, 7)
        if r is None or r[0] & 0x80:  # pas de réponse, ou mesure pas finie
            return None
        hum = (r[1] << 12 | r[2] << 4 | r[3] >> 4) / 2 ** 20 * 100
        temp = ((r[3] & 0x0F) << 16 | r[4] << 8 | r[5]) / 2 ** 20 * 200 - 50
        return round(temp, 1), round(hum, 1)

    def lire_pression(self):
        """Pression de l'air en hPa (BMP280), ou None."""
        if self._bmp is None:
            c = self._lire_i2c(BMP_ADDR, 0x88, 24)  # coefficients d'étalonnage d'usine
            if c is None:
                return None
            u = lambda i: c[i] | c[i + 1] << 8
            s = lambda i: _s16(c[i + 1], c[i])
            self._bmp = [u(0), s(2), s(4), u(6)] + [s(i) for i in range(8, 24, 2)]
            self._ecrire_i2c(BMP_ADDR, [0xF5, 0xA0])  # une mesure par seconde
            self._ecrire_i2c(BMP_ADDR, [0xF4, 0x27])  # mode continu
            time.sleep(0.1)
        r = self._lire_i2c(BMP_ADDR, 0xF7, 6)
        if r is None:
            self._bmp = None
            return None
        T1, T2, T3, P1, P2, P3, P4, P5, P6, P7, P8, P9 = self._bmp
        adc_p = r[0] << 12 | r[1] << 4 | r[2] >> 4
        adc_t = r[3] << 12 | r[4] << 4 | r[5] >> 4
        v1 = (adc_t / 16384 - T1 / 1024) * T2
        v2 = (adc_t / 131072 - T1 / 8192) ** 2 * T3
        t_fine = v1 + v2
        v1 = t_fine / 2 - 64000
        v2 = v1 * v1 * P6 / 32768 + v1 * P5 * 2
        v2 = v2 / 4 + P4 * 65536
        v1 = (P3 * v1 * v1 / 524288 + P2 * v1) / 524288
        v1 = (1 + v1 / 32768) * P1
        if v1 == 0:
            return None
        p = 1048576 - adc_p
        p = (p - v2 / 4096) * 6250 / v1
        p += (P9 * p * p / 2147483648 + p * P8 / 32768 + P7) / 16
        return round(p / 100, 1)

    def lire_lumiere(self):
        """Lumière en % (capteur du Sensor Kit, non étalonné en lux), ou None."""
        if not self._lumiere:
            return None
        return round(sum(self._lumiere) / len(self._lumiere) * 100, 1)

    def lire_batterie(self):
        """(tension en V, courant en A, puissance en W) de la batterie, mesurés par l'INA260.
        Courant et puissance sont positifs en charge, négatifs en décharge. None si pas de capteur."""
        i = self._lire_i2c(INA_ADDR, 0x01, 2)  # registre courant : 1,25 mA par unité, signé
        u = self._lire_i2c(INA_ADDR, 0x02, 2)  # registre tension : 1,25 mV par unité
        if i is None or u is None:
            return None
        a = INA_SENS * _s16(i[0], i[1]) * 0.00125
        v = (u[0] << 8 | u[1]) * 0.00125
        return round(v, 3), round(a, 3), round(v * a, 2)  # puissance signée (le registre 0x03 ne l'est pas)

    def lire_horloge(self):
        """Heure du module horloge (UTC), ou None s'il ne répond pas ou n'a jamais été réglé."""
        regs = self._lire_i2c(RTC_ADDR, 0, 7)
        if regs is None:
            return None
        s, mi, h, _, j, mo, a = regs[:7]
        try:
            return datetime(2000 + _bcd(a), _bcd(mo & 0x1F), _bcd(j),
                            _bcd(h & 0x3F), _bcd(mi), _bcd(s & 0x7F), tzinfo=timezone.utc)
        except ValueError:  # module neuf ou pile vide : registres incohérents
            return None

    def regler_horloge(self, dt):
        dt = dt.astimezone(timezone.utc)
        regs = [_vers_bcd(dt.second), _vers_bcd(dt.minute), _vers_bcd(dt.hour),  # heure en mode 24 h
                dt.isoweekday(), _vers_bcd(dt.day), _vers_bcd(dt.month), _vers_bcd(dt.year - 2000)]
        self._ecrire_i2c(RTC_ADDR, [0] + regs)

    # ---------- Écran OLED ----------
    def afficher(self, lignes):
        """Écrit jusqu'à 6 lignes de texte sur l'écran OLED (il faut Pillow : pip install pillow)."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self._signaler_oled("pillow", "Écran OLED : Pillow manque dans le Python du serveur "
                                "(venv/bin/pip install pillow), rien n'est affiché.")
            return
        # Pas de test par lecture : certains écrans (SSD1315 du Sensor Kit) ne répondent pas
        # à une lecture alors qu'ils marchent. On envoie le réglage directement (sans danger
        # si l'écran est absent), et on le renvoie chaque minute : s'il a perdu l'alimentation
        # ou redémarré, il se rallume tout seul.
        if self._oled_regle is None or time.monotonic() - self._oled_regle > 60:
            init = [0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00,
                    0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF]
            self._ecrire_i2c(OLED_ADDR, [0x00] + init)
            if self._oled_regle is None:
                print("Écran OLED : réglage envoyé à l'adresse 0x3C.", flush=True)
            self._oled_regle = time.monotonic()
        img = Image.new("1", (128, 64))
        d, police = ImageDraw.Draw(img), ImageFont.load_default()
        for i, texte in enumerate(lignes[:6]):
            d.text((0, i * 10 + 2), texte, fill=1, font=police)
        px = img.load()
        octets = [sum((1 if px[x, page * 8 + b] else 0) << b for b in range(8))
                  for page in range(8) for x in range(128)]
        with self._lock:
            self._ecrire_i2c(OLED_ADDR, [0x00, 0x21, 0, 127, 0x22, 0, 7])  # tout l'écran
            for k in range(0, len(octets), 16):
                self._ecrire_i2c(OLED_ADDR, [0x40] + octets[k:k + 16])

    def _signaler_oled(self, cle, texte):
        """Écrit un problème d'écran dans le journal, une seule fois."""
        if cle not in self._oled_signale:
            self._oled_signale.add(cle)
            print(texte, flush=True)

    def fermer(self):
        self._vivant = False
        with self._lock:
            self._sorties = 0
            self._ecrire_i2c(MCP_ADDR, [0x12, 0])
        time.sleep(0.2)
        self.board.exit()
