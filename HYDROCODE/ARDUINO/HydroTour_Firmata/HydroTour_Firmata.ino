/*
  HydroTour : l'Arduino devient une simple carte d'entrées/sorties du Raspberry Pi.

  C'est ConfigurableFirmata (bus I2C, sonde OneWire DS18B20, entrées analogiques),
  avec une sécurité en plus : si le Raspberry ne dit plus rien pendant 30 s
  (programme planté, câble USB débranché, Raspberry éteint), l'Arduino coupe
  lui-même toutes les pompes de la carte 8 MOSFET. Le Raspberry les rallume
  dès qu'il reparle (il renvoie l'état des pompes toutes les 10 s).

  À installer une seule fois :
    Arduino IDE > Outils > Gérer les bibliothèques > « ConfigurableFirmata » (version 3.x)
    puis téléverser ce programme. Le Raspberry s'y connecte à 115200 bauds (arduino.py).

  Mesure de la sonde EC en graphite (ajout) : le Raspberry ne peut pas faire cette mesure
  lui-même, car un aller-retour par le câble USB dure plusieurs millisecondes alors qu'une
  phase de mesure dure environ 130 µs. L'Arduino fait donc toute la mesure en une seule
  commande SysEx et renvoie deux sommes entières S1 et S2 ; le Raspberry calcule le reste
  (arduino.py puis pilote.py). Rapport, parties 7.6 et 7.7.

  Câblage : voir l'en-tête de HYDROCODE/SERVEUR/arduino.py.
  Sonde EC : D5 -> R1 (340 ohms) -> point J (lu sur A0) -> sonde graphite -> D6.
*/
#include <ConfigurableFirmata.h>
#include <Wire.h>

#include <AnalogInputFirmata.h>
AnalogInputFirmata analogInput;   // capteur de lumière du Sensor Kit (A3)

#include <I2CFirmata.h>
I2CFirmata i2c;                   // pompes, ADS1115, INA260, horloge, DHT20, BMP280, écran

#include <OneWireFirmata.h>
OneWireFirmata oneWire;           // sonde de température de l'eau DS18B20 (D2)

#include <FirmataExt.h>
FirmataExt firmataExt;

#include <FirmataReporting.h>
FirmataReporting reporting;

// ============================================================================
//  Mesure de la sonde EC en graphite
// ============================================================================
//  Principe (rapport, partie 7.6) : on fait passer un courant dans l'eau, d'abord dans un
//  sens (phase 1 : D5 haut, D6 bas), puis dans l'autre (phase 2 : D5 bas, D6 haut). Le
//  courant moyen dans la sonde est nul, ce qui évite de polariser (d'user) le graphite.
//  Dans chaque phase on lit la tension du point J sur A0 :
//     phase 1 : J est entre R1 et la sonde  -> tension U1
//     phase 2 : J est entre la sonde et R1  -> tension U2
//  Le Raspberry calcule x = S1 / S2 = U1 / U2, d'où la résistance de l'eau.
//  Ici on ne fait que les deux sommes : S1 (somme des lectures de la phase 1) et S2 (phase 2).
//
//  Commande SysEx : le Raspberry envoie  F0 0E F7        (« mesure EC »)
//  Réponse         : l'Arduino renvoie    F0 0E s1 s1 s1 s2 s2 s2 F7
//  avec chaque somme (0 à 65 472) découpée en 3 paquets de 7 bits (poids faible d'abord),
//  car Firmata n'envoie que des octets de 7 bits.
const byte EC_COMMANDE = 0x0E;         // numéro SysEx (0x00 à 0x0F : libres pour l'utilisateur)
const byte EC_BROCHE_A = 5;            // D5 : côté R1
const byte EC_BROCHE_B = 6;            // D6 : côté sonde
const byte EC_ENTREE = A0;             // A0 : point J
const byte EC_REPETITIONS = 64;        // 64 allers-retours : 64 x 1023 = 65 472 < 65 535, tient sur 16 bits
const unsigned int EC_ATTENTE_US = 20; // attente après le changement de sens, que la tension se stabilise

class MesureECFirmata : public FirmataFeature {
  public:
    // Cette fonctionnalité n'utilise pas les modes de broches de Firmata.
    boolean handlePinMode(byte pin, int mode) { return false; }
    void handleCapability(byte pin) {}
    void reset() { deconnecterSonde(); }

    boolean handleSysex(byte command, byte argc, byte *argv) {
      if (command != EC_COMMANDE) return false;  // ce n'est pas pour nous
      unsigned int s1 = 0, s2 = 0;
      mesurer(s1, s2);
      Firmata.write(START_SYSEX);
      Firmata.write(EC_COMMANDE);
      ecrire16(s1);
      ecrire16(s2);
      Firmata.write(END_SYSEX);
      return true;
    }

  private:
    // Sonde déconnectée : les deux broches en entrée (haute impédance), aucun courant dans l'eau.
    void deconnecterSonde() {
      pinMode(EC_BROCHE_A, INPUT);
      pinMode(EC_BROCHE_B, INPUT);
    }

    // Un nombre de 16 bits envoyé en 3 octets de 7 bits.
    void ecrire16(unsigned int v) {
      Firmata.write(v & 0x7F);
      Firmata.write((v >> 7) & 0x7F);
      Firmata.write((v >> 14) & 0x7F);
    }

    void mesurer(unsigned int &s1, unsigned int &s2) {
      pinMode(EC_BROCHE_A, OUTPUT);
      pinMode(EC_BROCHE_B, OUTPUT);
      digitalWrite(EC_BROCHE_A, LOW);
      digitalWrite(EC_BROCHE_B, LOW);
      analogRead(EC_ENTREE);  // lecture à blanc : la première lecture après un temps d'arrêt est moins fiable
      for (byte i = 0; i < EC_REPETITIONS; i++) {
        // Phase 1 : D5 haut, D6 bas. On coupe d'abord D6 avant d'allumer D5 : jamais les deux en même temps.
        digitalWrite(EC_BROCHE_B, LOW);
        digitalWrite(EC_BROCHE_A, HIGH);
        delayMicroseconds(EC_ATTENTE_US);
        s1 += analogRead(EC_ENTREE);
        // Phase 2 : D5 bas, D6 haut (courant en sens inverse, même durée que la phase 1).
        digitalWrite(EC_BROCHE_A, LOW);
        digitalWrite(EC_BROCHE_B, HIGH);
        delayMicroseconds(EC_ATTENTE_US);
        s2 += analogRead(EC_ENTREE);
      }
      deconnecterSonde();  // la sonde reste déconnectée tout le reste du temps
    }
};
MesureECFirmata mesureEC;

const long VITESSE = 115200;
const unsigned long SILENCE_MAX = 30000;  // ms sans message du Raspberry avant de tout couper
const byte CARTE_POMPES = 0x20;           // carte 8 MOSFET Adafruit 6318 (MCP23017)
const byte GPIOA = 0x12;                  // les 8 sorties sont sur le port A du MCP23017

unsigned long dernierMessage = 0;
unsigned long derniereCoupure = 0;

void couperPompes() {
  Wire.beginTransmission(CARTE_POMPES);
  Wire.write(GPIOA);
  Wire.write(0x00);  // les 8 sorties à 0 : MOSFET bloqués, pompes arrêtées
  Wire.endTransmission();
}

void systemResetCallback() {
  for (byte i = 0; i < TOTAL_PINS; i++) {
    if (FIRMATA_IS_PIN_ANALOG(i)) {
      Firmata.setPinMode(i, PIN_MODE_ANALOG);
    }
  }
  firmataExt.reset();
}

void setup() {
  Firmata.setFirmwareNameAndVersion("HydroTour", FIRMATA_FIRMWARE_MAJOR_VERSION, FIRMATA_FIRMWARE_MINOR_VERSION);
  Serial.begin(VITESSE);
  Firmata.begin(Serial);
  firmataExt.addFeature(analogInput);
  firmataExt.addFeature(i2c);
  firmataExt.addFeature(oneWire);
  firmataExt.addFeature(mesureEC);  // commande « mesure EC » de la sonde en graphite
  firmataExt.addFeature(reporting);
  Firmata.attach(SYSTEM_RESET, systemResetCallback);
  Firmata.parse(SYSTEM_RESET);
  Wire.begin();  // pour la sécurité, même si le Raspberry n'a jamais activé l'I2C
}

void loop() {
  if (Firmata.available()) {
    dernierMessage = millis();
  }
  while (Firmata.available()) {
    Firmata.processInput();
    if (!Firmata.isParsingMessage()) {
      break;
    }
  }
  firmataExt.report(reporting.elapsed());

  // Raspberry muet : on coupe, et on recoupe toutes les 5 s tant qu'il se tait.
  unsigned long t = millis();
  if (t - dernierMessage > SILENCE_MAX && t - derniereCoupure > 5000) {
    couperPompes();
    derniereCoupure = t;
  }
}
