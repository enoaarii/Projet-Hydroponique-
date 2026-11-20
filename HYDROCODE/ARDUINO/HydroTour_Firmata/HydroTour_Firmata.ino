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

  Câblage : voir l'en-tête de HYDROCODE/SERVEUR/arduino.py.
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
