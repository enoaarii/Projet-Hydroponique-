#include <SoftwareSerial.h>
SoftwareSerial wifi(2, 3);   // RX = D2, TX = D3

void setup() {
  Serial.begin(9600);
  wifi.begin(9600);        // débit du module : voir note ci-dessous
}
void loop() {
  if (wifi.available())   Serial.write(wifi.read());
  if (Serial.available()) wifi.write(Serial.read());
}