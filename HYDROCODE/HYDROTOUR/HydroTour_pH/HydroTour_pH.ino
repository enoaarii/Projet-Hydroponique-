// HydroTour : lit la sonde pH (A1) et l'envoie au serveur du PC
// via le module Grove UART WiFi V2 (commandes AT).
//
// Prérequis : le module a déjà rejoint le Wi-Fi (AT+CWJAP fait une fois, il s'en souvient).
// Moniteur série : 9600 baud. Il affiche le pH lu et les réponses du module.

#include <SoftwareSerial.h>

const char SERVEUR[] = "192.168.137.1";  // adresse du PC (point d'accès Windows)
const int  PORT = 5000;
const long WIFI_BAUD = 9600;            // débit actuel du module (mets 9600 si tu l'as changé)
const unsigned long PERIODE = 10000;     // un envoi toutes les 10 secondes

// Étalonnage : tension (mV) lue dans les solutions tampon pH 7.00 et pH 4.00.
// Valeurs de départ de DFRobot : à remplacer par tes propres mesures (voir le moniteur série).
float V_PH7 = 1500.0;
float V_PH4 = 2032.0;

SoftwareSerial wifi(2, 3);  // RX = D2, TX = D3

float derniereTension = 0;

float lirePH() {
  long somme = 0;
  for (int i = 0; i < 20; i++) {
    somme += analogRead(A1);
    delay(10);
  }
  derniereTension = (somme / 20.0) * 5000.0 / 1023.0;  // en mV
  return 7.0 + (derniereTension - V_PH7) * (4.0 - 7.0) / (V_PH4 - V_PH7);
}

// Attend ms millisecondes en affichant ce que répond le module.
void ecouter(unsigned long ms) {
  unsigned long t = millis();
  while (millis() - t < ms) {
    while (wifi.available()) Serial.write(wifi.read());
  }
}

void envoyer(float ph) {
  char phs[10];
  dtostrf(ph, 1, 2, phs);

  char req[120];
  snprintf(req, sizeof(req),
           "GET /api/data?ph=%s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n",
           phs, SERVEUR);

  wifi.print(F("AT+CIPSTART=\"TCP\",\""));
  wifi.print(SERVEUR);
  wifi.print(F("\","));
  wifi.println(PORT);
  ecouter(1500);

  wifi.print(F("AT+CIPSEND="));
  wifi.println(strlen(req));
  ecouter(500);

  wifi.print(req);
  ecouter(1500);

  wifi.println(F("AT+CIPCLOSE"));
  ecouter(300);
}

void setup() {
  Serial.begin(9600);
  wifi.begin(WIFI_BAUD);
  delay(1000);
  wifi.println(F("AT+CIPMUX=0"));  // une seule connexion à la fois
  ecouter(500);
}

void loop() {
  static unsigned long dernier = 0;
  if (millis() - dernier >= PERIODE) {
    dernier = millis();
    float ph = lirePH();
    Serial.print(F("\n[pH] tension = "));
    Serial.print(derniereTension, 0);
    Serial.print(F(" mV, pH = "));
    Serial.println(ph, 2);
    envoyer(ph);
  }
}
