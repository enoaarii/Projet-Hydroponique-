/*
  Pompe DC via MOSFET : tu tapes ON ou OFF dans le moniteur serie.

  Cablage : D9 --[220 ohm]--> Gate IRLZ44N ; Gate --[10 k]--> GND
            Drain --> pompe(-) ; pompe(+) --> +12 V ; Source --> GND commun
            Diode 1N5822 en parallele de la pompe (cathode cote +12 V)

  Moniteur serie : 115200 bauds, "Nouvelle ligne" (menu deroulant en bas)
  Tape  ON   puis Entree -> le MOSFET est passant, la pompe tourne
  Tape  OFF  puis Entree -> le MOSFET est bloque, la pompe s'arrete
*/

const uint8_t PIN_MOSFET = 3;

void setup() {
  pinMode(PIN_MOSFET, OUTPUT);
  digitalWrite(PIN_MOSFET, LOW);      // pompe arretee au demarrage
  Serial.begin(9600);
  Serial.println(F("Tape ON ou OFF"));
}

void loop() {
  if (Serial.available()) {
    String texte = Serial.readStringUntil('\n');
    texte.trim();
    texte.toUpperCase();

    if (texte == "ON") {
      digitalWrite(PIN_MOSFET, HIGH);
      Serial.println(F("Pompe ON"));
    } else if (texte == "OFF") {
      digitalWrite(PIN_MOSFET, LOW);
      Serial.println(F("Pompe OFF"));
    } else if (texte.length() > 0) {
      Serial.println(F("Commande inconnue : tape ON ou OFF"));
    }
  }
}
