/*
  HydroTour_Actionneur.ino
  ------------------------------------------------------------------
  Projet tutoré L3 SPI, UPF 2026-2027 : tour hydroponique HydroTour.
  Carte : Arduino Uno R3 + base Grove (Arduino Sensor Kit).

  Rôle de l'Arduino : ACTIONNEUR seulement.
    - lit les capteurs en brut (mV, °C, %, degrés) et les envoie au Raspberry Pi ;
    - exécute les commandes de pompes envoyées par le Pi ;
    - assure les sécurités matérielles non contournables :
        chien de garde 8 s, durée max par commande, arrêt de la circulation
        si niveau bas, arrêt de tout si chute de la tour, mode secours si
        le Pi se tait plus de 5 min.
  Toute la logique (planning, dosage, conversions pH/EC) est sur le Pi.

  Protocole série (CONTRAT, section 4 du cahier commun), 115200 bauds,
  lignes ASCII terminées par "\n" :
    P                 -> OK P
    L                 -> M ph=<mV>,ec=<mV>,niv=<mV>,te=<°C>,ta=<°C>,hu=<%>,lux=<0-1023>,inc=<deg>
    D <c> <ms>        -> OK D <c> <ms>  ou  ERR <raison>
    S                 -> OK S
    E                 -> E pompes=<c0c1c2c3>,secours=<0/1>,chute=<0/1>,niv_bas=<0/1>,inc=<deg>
    N <seuil_mV> <sens> -> OK N
    Z                 -> OK Z
    R                 -> OK R  ou  ERR incline
  Messages spontanés : "# texte", "! CHUTE", "! NIVEAU_BAS", "! NIVEAU_OK",
                       "! SECOURS 1", "! SECOURS 0".
  ------------------------------------------------------------------
*/

#include <Wire.h>
#include <EEPROM.h>
#include <avr/wdt.h>
#include <math.h>
#include <stdlib.h>
#include <Adafruit_MCP23X17.h>
#include <Adafruit_ADS1X15.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <DHT.h>
#include <LIS3DHTR.h>

// =================================================================
// 1. BROCHAGE
// =================================================================
const uint8_t BROCHE_PH      = A1;  // sonde pH DFRobot (analogique)
const uint8_t BROCHE_LUMIERE = A3;  // capteur de lumière Grove (analogique)
const uint8_t BROCHE_DHT     = 3;   // DHT11 (T et humidité de l'air)
const uint8_t BROCHE_EC_ALIM = 7;   // alimentation de la carte EC (HIGH = alimentée)
const uint8_t BROCHE_DS18B20 = 8;   // sonde de température de l'eau (1-Wire)
// I2C : SDA = A4, SCL = A5

// Adresses I2C
const uint8_t ADR_MCP23017 = 0x20;  // carte pompes Adafruit 6318
const uint8_t ADR_ADS1115  = 0x48;  // CAN 16 bits
const uint8_t ADR_LIS3DHTR = 0x19;  // accéléromètre (Sensor Kit)

// Voies de l'ADS1115
const uint8_t VOIE_ADS_EC    = 0;   // A0 de l'ADS : sonde EC
const uint8_t VOIE_ADS_ETAPE = 1;   // A1 de l'ADS : eTape (niveau)

// Canaux logiques des pompes (protocole) -> sorties de la carte 6318
//   0 = circulation  : sorties 0 ET 1 en parallèle (moins d'échauffement)
//   1 = engrais A    : sortie 2
//   2 = engrais B    : sortie 3
//   3 = pH-          : sortie 4
const uint8_t NB_POMPES = 4;
const uint8_t MASQUE_SORTIES[NB_POMPES] = {
  0b00000011,   // canal 0 : sorties 0 et 1
  0b00000100,   // canal 1 : sortie 2
  0b00001000,   // canal 2 : sortie 3
  0b00010000    // canal 3 : sortie 4
};
const uint8_t NB_SORTIES_CARTE = 8;  // la 6318 a 8 MOSFET (GPA0..GPA7)

// =================================================================
// 2. CONSTANTES
// =================================================================
const unsigned long VITESSE_SERIE = 115200UL;

// Durées maximales d'une commande D (ms)
const unsigned long DUREE_MAX_CIRCULATION = 1000000UL;
const unsigned long DUREE_MAX_DOSEUSE     = 30000UL;

// Mesures
const uint8_t       NB_LECTURES_PH    = 20;      // moyenne de 20 lectures
const unsigned long PAUSE_LECTURE_PH  = 5;       // ms entre deux lectures
const float         VREF_UNO_MV       = 5000.0;  // référence du CAN de l'Uno (mV)
const unsigned long STABILISATION_EC  = 1000;    // ms d'attente après mise sous tension de l'EC
const unsigned long CONVERSION_DS18B20 = 750;    // ms pour une conversion 12 bits

// Niveau bas
const unsigned long PERIODE_NIVEAU = 5000;       // lecture de l'eTape toutes les 5 s
const float         HYSTERESIS_NIVEAU_MV = 50.0; // hystérésis (mV)

// Chute
const float         SEUIL_CHUTE_DEG   = 35.0;    // inclinaison limite (degrés)
const unsigned long DUREE_CHUTE       = 1000;    // ms au-delà du seuil avant alarme
const unsigned long PERIODE_ACCEL     = 50;      // échantillonnage accéléromètre (ms)
const float         FILTRE_ACCEL      = 0.2;     // coefficient du filtre passe-bas (0..1)
const float         NORME_MIN_G       = 0.3;     // en dessous : lecture jugée invalide

// Mode secours
const unsigned long SILENCE_MAX       = 300000UL; // 5 min sans commande
const unsigned long DEMI_CYCLE_SECOURS = 900000UL; // 15 min marche / 15 min arrêt

// Surveillance des modules I2C absents
const unsigned long PERIODE_VERIF_I2C = 10000;

// Tampon de réception série
const uint8_t TAILLE_TAMPON = 40;

// EEPROM : emplacement des réglages
const uint8_t  EE_MAGIC        = 0xA5;  // signature "réglage valide"
const int      EE_N_MAGIC      = 0;     // 1 octet
const int      EE_N_SEUIL      = 1;     // float (4 octets)
const int      EE_N_SENS       = 5;     // int8 (1 octet)
const int      EE_Z_MAGIC      = 8;     // 1 octet
const int      EE_Z_REF        = 9;     // 3 float (12 octets)

// =================================================================
// 3. OBJETS DES BIBLIOTHÈQUES
// =================================================================
Adafruit_MCP23X17   mcp;
Adafruit_ADS1115    ads;
OneWire             busOneWire(BROCHE_DS18B20);
DallasTemperature   ds18b20(&busOneWire);
DHT                 dht(BROCHE_DHT, DHT11);
LIS3DHTR<TwoWire>   lis;

// =================================================================
// 4. ÉTAT DU PROGRAMME
// =================================================================
// Modules présents
bool mcpPresent = false;   // carte pompes joignable
bool mcpInit    = false;   // begin_I2C déjà fait (on ne le refait jamais : évite les fuites mémoire)
bool adsPresent = false;
bool adsInit    = false;
bool lisPresent = false;

// Pompes : une minuterie non bloquante par canal logique
bool          pompeActive[NB_POMPES]  = {false, false, false, false};
unsigned long pompeDebut[NB_POMPES]   = {0, 0, 0, 0};
unsigned long pompeDuree[NB_POMPES]   = {0, 0, 0, 0};
uint8_t       sortiesEcrites = 0xFF;  // dernière valeur envoyée à la carte (0xFF = à écrire)

// Niveau bas
bool  niveauRegle = false;  // N déjà fait au moins une fois ?
float seuilNiveau = 0.0;    // mV
int8_t sensNiveau = 1;      // 1 : bas si mV > seuil ; -1 : bas si mV < seuil
bool  niveauBas   = false;
unsigned long derniereLectureNiveau = 0;

// Chute
bool  refRegle = false;     // Z déjà fait au moins une fois ?
float refX = 0, refY = 0, refZ = 1;   // vecteur "tour droite" (normé)
float filtX = 0, filtY = 0, filtZ = 0; // vecteur mesuré filtré
bool  filtreAmorce = false;
float inclinaison = NAN;    // degrés par rapport à la référence
bool  chute = false;        // alarme verrouillée jusqu'à R
bool  depassementEnCours = false;
unsigned long debutDepassement = 0;
unsigned long derniereLectureAccel = 0;

// Mode secours
bool secours = false;
unsigned long derniereCommande = 0;
unsigned long debutSecours = 0;

// Divers
unsigned long derniereVerifI2C = 0;
char    tampon[TAILLE_TAMPON];
uint8_t longueurTampon = 0;
bool    tamponDeborde = false;

// =================================================================
// 5. OUTILS
// =================================================================

// Teste si un module répond à une adresse I2C
bool presentI2C(uint8_t adresse) {
  Wire.beginTransmission(adresse);
  return (Wire.endTransmission() == 0);
}

// Durée maximale autorisée pour un canal
unsigned long dureeMax(uint8_t canal) {
  return (canal == 0) ? DUREE_MAX_CIRCULATION : DUREE_MAX_DOSEUSE;
}

// Fonctions déclarées plus bas mais utilisées avant
void taches();
void surveillerChute();

// Attente "active" : pendant qu'on attend (stabilisation EC, DS18B20),
// on continue à gérer les minuteries des pompes, la chute et le watchdog.
void attendre(unsigned long ms) {
  unsigned long debut = millis();
  while (millis() - debut < ms) {
    taches();
  }
}

// =================================================================
// 6. POMPES
// =================================================================

// Envoie l'état des pompes à la carte 6318 (seulement si changement,
// ou si force = true pour rafraîchir)
void appliquerSorties(bool force) {
  uint8_t valeur = 0;
  for (uint8_t c = 0; c < NB_POMPES; c++) {
    if (pompeActive[c]) valeur |= MASQUE_SORTIES[c];
  }
  if (!mcpPresent) return;
  if (force || valeur != sortiesEcrites) {
    mcp.writeGPIOA(valeur);
    sortiesEcrites = valeur;
  }
}

void demarrerPompe(uint8_t canal, unsigned long duree) {
  pompeActive[canal] = true;
  pompeDebut[canal]  = millis();
  pompeDuree[canal]  = duree;
  appliquerSorties(false);
}

void arreterPompe(uint8_t canal) {
  pompeActive[canal] = false;
  appliquerSorties(false);
}

void arreterToutes() {
  for (uint8_t c = 0; c < NB_POMPES; c++) pompeActive[c] = false;
  appliquerSorties(false);
}

// Arrêt automatique en fin de durée (et ceinture de sécurité sur la durée max)
void gererPompes() {
  unsigned long maintenant = millis();
  bool change = false;
  for (uint8_t c = 0; c < NB_POMPES; c++) {
    if (!pompeActive[c]) continue;
    unsigned long ecoule = maintenant - pompeDebut[c];
    if (ecoule >= pompeDuree[c] || ecoule >= dureeMax(c)) {
      pompeActive[c] = false;
      change = true;
    }
  }
  if (change) appliquerSorties(false);
}

// Configure les 8 sorties de la carte (toutes à l'arrêt)
void configurerCartePompes() {
  for (uint8_t i = 0; i < NB_SORTIES_CARTE; i++) {
    mcp.pinMode(i, OUTPUT);
  }
  mcp.writeGPIOA(0);
  sortiesEcrites = 0;
  appliquerSorties(true);
}

// =================================================================
// 7. CAPTEURS
// =================================================================

// Lecture d'une voie de l'ADS1115 en mV (NAN si absent)
float lireADSmV(uint8_t voie) {
  if (!adsPresent) return NAN;
  int16_t brut = ads.readADC_SingleEnded(voie);
  return ads.computeVolts(brut) * 1000.0;
}

// pH : moyenne de plusieurs lectures de A1, convertie en mV.
// La carte EC doit être éteinte (les deux sondes se perturbent).
float lirePhmV() {
  digitalWrite(BROCHE_EC_ALIM, LOW);
  unsigned long somme = 0;
  for (uint8_t i = 0; i < NB_LECTURES_PH; i++) {
    somme += analogRead(BROCHE_PH);
    attendre(PAUSE_LECTURE_PH);
  }
  float moyenne = (float)somme / NB_LECTURES_PH;
  return moyenne * VREF_UNO_MV / 1024.0;
}

// EC : on alimente la carte, on attend la stabilisation, on lit, on éteint.
float lireECmV() {
  if (!adsPresent) return NAN;
  digitalWrite(BROCHE_EC_ALIM, HIGH);
  attendre(STABILISATION_EC);
  float mv = lireADSmV(VOIE_ADS_EC);
  digitalWrite(BROCHE_EC_ALIM, LOW);
  return mv;
}

// Température de l'eau (°C), NAN si sonde absente ou valeur aberrante
float lireTempEau() {
  float t = ds18b20.getTempCByIndex(0);
  if (t == DEVICE_DISCONNECTED_C || t == 85.0) return NAN;  // 85 °C = valeur de mise sous tension
  return t;
}

// Inclinaison (degrés) entre le vecteur filtré et la référence ; NAN si impossible
float calculerInclinaison() {
  if (!lisPresent || !refRegle || !filtreAmorce) return NAN;
  float norme = sqrt(filtX * filtX + filtY * filtY + filtZ * filtZ);
  if (norme < NORME_MIN_G) return NAN;
  float cosA = (filtX * refX + filtY * refY + filtZ * refZ) / norme;
  if (cosA > 1.0) cosA = 1.0;
  if (cosA < -1.0) cosA = -1.0;
  return acos(cosA) * 180.0 / PI;
}

// Commande L : lecture complète
void commandeLecture() {
  // 1. Lancer la conversion DS18B20 (non bloquante), elle se fait pendant le reste
  unsigned long debutDS = millis();
  ds18b20.requestTemperatures();

  // 2. pH (EC éteinte)
  float ph = lirePhmV();

  // 3. EC (allumée seulement pendant sa lecture)
  float ec = lireECmV();

  // 4. Niveau eTape
  float niv = lireADSmV(VOIE_ADS_ETAPE);

  // 5. Température de l'eau : attendre la fin de conversion si besoin
  unsigned long ecoule = millis() - debutDS;
  if (ecoule < CONVERSION_DS18B20) attendre(CONVERSION_DS18B20 - ecoule);
  float te = lireTempEau();

  // 6. Air (DHT11 renvoie NAN en cas d'échec)
  float ta = dht.readTemperature();
  float hu = dht.readHumidity();

  // 7. Lumière brute et inclinaison
  int lux = analogRead(BROCHE_LUMIERE);
  float inc = calculerInclinaison();

  // Réponse (Serial.print d'un NAN écrit "nan")
  Serial.print(F("M ph="));  Serial.print(ph, 1);
  Serial.print(F(",ec="));   Serial.print(ec, 1);
  Serial.print(F(",niv="));  Serial.print(niv, 1);
  Serial.print(F(",te="));   Serial.print(te, 2);
  Serial.print(F(",ta="));   Serial.print(ta, 1);
  Serial.print(F(",hu="));   Serial.print(hu, 1);
  Serial.print(F(",lux="));  Serial.print(lux);
  Serial.print(F(",inc="));  Serial.println(inc, 1);
}

// =================================================================
// 8. SÉCURITÉS
// =================================================================

// --- Niveau bas : eTape lue toutes les 5 s ---------------------
void surveillerNiveau() {
  if (millis() - derniereLectureNiveau < PERIODE_NIVEAU) return;
  derniereLectureNiveau = millis();
  if (!niveauRegle) return;          // sécurité désactivée tant que N n'a pas été fait
  float mv = lireADSmV(VOIE_ADS_ETAPE);
  if (isnan(mv)) return;             // pas de mesure : on garde l'état précédent

  if (!niveauBas) {
    bool bas = (sensNiveau > 0) ? (mv > seuilNiveau) : (mv < seuilNiveau);
    if (bas) {
      niveauBas = true;
      arreterPompe(0);               // coupe la circulation
      Serial.println(F("! NIVEAU_BAS"));
    }
  } else {
    // Retour à la normale seulement après l'hystérésis
    bool ok = (sensNiveau > 0) ? (mv < seuilNiveau - HYSTERESIS_NIVEAU_MV)
                               : (mv > seuilNiveau + HYSTERESIS_NIVEAU_MV);
    if (ok) {
      niveauBas = false;
      Serial.println(F("! NIVEAU_OK"));
    }
  }
}

// --- Chute : angle > 35° pendant 1 s -> tout couper, alarme verrouillée
void surveillerChute() {
  if (!lisPresent) return;
  if (millis() - derniereLectureAccel < PERIODE_ACCEL) return;
  derniereLectureAccel = millis();

  float x, y, z;
  lis.getAcceleration(&x, &y, &z);
  if (!filtreAmorce) {
    filtX = x; filtY = y; filtZ = z;
    filtreAmorce = true;
  } else {
    // filtre passe-bas : atténue les vibrations de la pompe
    filtX += FILTRE_ACCEL * (x - filtX);
    filtY += FILTRE_ACCEL * (y - filtY);
    filtZ += FILTRE_ACCEL * (z - filtZ);
  }
  inclinaison = calculerInclinaison();
  if (!refRegle) return;              // sécurité désactivée tant que Z n'a pas été fait

  if (!isnan(inclinaison) && inclinaison > SEUIL_CHUTE_DEG) {
    if (!depassementEnCours) {
      depassementEnCours = true;
      debutDepassement = millis();
    } else if (!chute && millis() - debutDepassement >= DUREE_CHUTE) {
      chute = true;
      arreterToutes();
      Serial.println(F("! CHUTE"));
    }
  } else {
    depassementEnCours = false;
  }
  if (chute) arreterToutes();         // rien ne doit tourner pendant une chute
}

// --- Mode secours : le Pi se tait depuis plus de 5 min --------
void gererSecours() {
  unsigned long maintenant = millis();
  if (!secours) {
    if (maintenant - derniereCommande >= SILENCE_MAX) {
      secours = true;
      debutSecours = maintenant;
      arreterToutes();                // aucun dosage en secours
      Serial.println(F("! SECOURS 1"));
    } else {
      return;
    }
  }
  // Cycle 15 min marche / 15 min arrêt depuis l'entrée en secours
  unsigned long dansCycle = (maintenant - debutSecours) % (2 * DEMI_CYCLE_SECOURS);
  bool marche = (dansCycle < DEMI_CYCLE_SECOURS);
  for (uint8_t c = 1; c < NB_POMPES; c++) {
    if (pompeActive[c]) arreterPompe(c);   // doseuses interdites
  }
  if (marche && !niveauBas && !chute) {
    if (!pompeActive[0]) demarrerPompe(0, DEMI_CYCLE_SECOURS - dansCycle);
  } else if (pompeActive[0]) {
    arreterPompe(0);
  }
}

// Sortie du mode secours (appelée à chaque commande reçue)
void sortirSecours() {
  derniereCommande = millis();
  if (secours) {
    secours = false;
    arreterPompe(0);                  // arrêt de la circulation de secours
    Serial.println(F("! SECOURS 0"));
  }
}

// --- Modules I2C : présence de la carte pompes et de l'ADS ---
void verifierModules() {
  if (millis() - derniereVerifI2C < PERIODE_VERIF_I2C) return;
  derniereVerifI2C = millis();

  bool mcpLa = presentI2C(ADR_MCP23017);
  if (mcpLa && !mcpPresent) {
    if (!mcpInit) mcpInit = mcp.begin_I2C(ADR_MCP23017);
    if (mcpInit) {
      mcpPresent = true;
      configurerCartePompes();
      Serial.println(F("# carte pompes MCP23017 detectee"));
    }
  } else if (!mcpLa && mcpPresent) {
    mcpPresent = false;
    sortiesEcrites = 0xFF;
    arreterToutes();
    Serial.println(F("# ERREUR carte pompes MCP23017 (0x20) perdue"));
  } else if (!mcpLa) {
    Serial.println(F("# ERREUR carte pompes MCP23017 (0x20) absente, pompes inutilisables"));
  } else {
    appliquerSorties(true);           // rafraîchissement périodique
  }

  bool adsLa = presentI2C(ADR_ADS1115);
  if (adsPresent && !adsLa) {
    adsPresent = false;
    Serial.println(F("# ADS1115 (0x48) perdu : ec et niv = nan"));
  }
  if (!adsPresent && adsLa) {
    if (!adsInit) adsInit = ads.begin(ADR_ADS1115);
    if (adsInit) {
      ads.setGain(GAIN_TWOTHIRDS);
      adsPresent = true;
      Serial.println(F("# ADS1115 detecte"));
    }
  }
}

// Tâches de fond (appelées dans loop() et pendant les attentes)
void taches() {
  wdt_reset();
  gererPompes();
  surveillerChute();
}

// =================================================================
// 9. EEPROM
// =================================================================
void chargerReglages() {
  if (EEPROM.read(EE_N_MAGIC) == EE_MAGIC) {
    EEPROM.get(EE_N_SEUIL, seuilNiveau);
    int8_t s;
    EEPROM.get(EE_N_SENS, s);
    sensNiveau = (s < 0) ? -1 : 1;
    niveauRegle = !isnan(seuilNiveau);
  }
  if (EEPROM.read(EE_Z_MAGIC) == EE_MAGIC) {
    EEPROM.get(EE_Z_REF, refX);
    EEPROM.get(EE_Z_REF + 4, refY);
    EEPROM.get(EE_Z_REF + 8, refZ);
    refRegle = !(isnan(refX) || isnan(refY) || isnan(refZ));
  }
}

// =================================================================
// 10. TRAITEMENT DES COMMANDES
// =================================================================

// Lit un entier non signé en décimal ; renvoie false si le texte n'est pas un nombre
bool lireEntier(char *texte, unsigned long *valeur) {
  if (texte == NULL || *texte == '\0') return false;
  for (char *p = texte; *p; p++) {
    if (*p < '0' || *p > '9') return false;
  }
  if (strlen(texte) > 10) return false;
  *valeur = strtoul(texte, NULL, 10);
  return true;
}

void commandeD(char *arguments) {
  // Pendant une chute, toute commande D est refusée (même un arrêt : tout est déjà coupé)
  if (chute) { Serial.println(F("ERR chute")); return; }
  char *tCanal = strtok(arguments, " ");
  char *tDuree = strtok(NULL, " ");
  char *tReste = strtok(NULL, " ");
  unsigned long canal, duree;
  if (!lireEntier(tCanal, &canal) || !lireEntier(tDuree, &duree) || tReste != NULL) {
    Serial.println(F("ERR syntaxe"));
    return;
  }
  if (canal >= NB_POMPES)          { Serial.println(F("ERR canal"));  return; }
  if (duree > dureeMax(canal))     { Serial.println(F("ERR duree"));  return; }

  if (duree == 0) {
    arreterPompe(canal);
  } else {
    if (!mcpPresent)               { Serial.println(F("ERR pompes")); return; }
    if (canal == 0 && niveauBas)   { Serial.println(F("ERR niveau_bas")); return; }
    demarrerPompe(canal, duree);
  }
  Serial.print(F("OK D "));
  Serial.print(canal);
  Serial.print(' ');
  Serial.println(duree);
}

void commandeE() {
  Serial.print(F("E pompes="));
  for (uint8_t c = 0; c < NB_POMPES; c++) Serial.print(pompeActive[c] ? '1' : '0');
  Serial.print(F(",secours="));  Serial.print(secours ? 1 : 0);
  Serial.print(F(",chute="));    Serial.print(chute ? 1 : 0);
  Serial.print(F(",niv_bas="));  Serial.print(niveauBas ? 1 : 0);
  Serial.print(F(",inc="));      Serial.println(inclinaison, 1);
}

void commandeN(char *arguments) {
  char *tSeuil = strtok(arguments, " ");
  char *tSens  = strtok(NULL, " ");
  char *tReste = strtok(NULL, " ");
  if (tSeuil == NULL || tSens == NULL || tReste != NULL) {
    Serial.println(F("ERR syntaxe"));
    return;
  }
  char *fin;
  double seuil = strtod(tSeuil, &fin);
  if (fin == tSeuil || *fin != '\0') { Serial.println(F("ERR syntaxe")); return; }
  long sens = strtol(tSens, &fin, 10);
  if (*fin != '\0' || (sens != 1 && sens != -1)) { Serial.println(F("ERR syntaxe")); return; }

  seuilNiveau = (float)seuil;
  sensNiveau  = (int8_t)sens;
  niveauRegle = true;
  EEPROM.put(EE_N_SEUIL, seuilNiveau);
  EEPROM.put(EE_N_SENS, sensNiveau);
  EEPROM.update(EE_N_MAGIC, EE_MAGIC);
  derniereLectureNiveau = millis() - PERIODE_NIVEAU;  // réévaluation immédiate
  Serial.println(F("OK N"));
}

void commandeZ() {
  if (!lisPresent || !filtreAmorce) { Serial.println(F("ERR accel")); return; }
  float norme = sqrt(filtX * filtX + filtY * filtY + filtZ * filtZ);
  if (norme < NORME_MIN_G)          { Serial.println(F("ERR accel")); return; }
  refX = filtX / norme;
  refY = filtY / norme;
  refZ = filtZ / norme;
  refRegle = true;
  EEPROM.put(EE_Z_REF, refX);
  EEPROM.put(EE_Z_REF + 4, refY);
  EEPROM.put(EE_Z_REF + 8, refZ);
  EEPROM.update(EE_Z_MAGIC, EE_MAGIC);
  depassementEnCours = false;
  inclinaison = calculerInclinaison();
  Serial.println(F("OK Z"));
}

void commandeR() {
  if (chute) {
    float inc = calculerInclinaison();
    // On refuse si la tour est encore penchée ou si on ne peut pas le vérifier
    if (isnan(inc) || inc > SEUIL_CHUTE_DEG) {
      Serial.println(F("ERR incline"));
      return;
    }
    chute = false;
    depassementEnCours = false;
  }
  Serial.println(F("OK R"));
}

// Analyse une ligne complète reçue du Pi
void traiterLigne(char *ligne) {
  // Retire les espaces en début de ligne
  while (*ligne == ' ') ligne++;
  if (*ligne == '\0') return;          // ligne vide : ignorée

  sortirSecours();                     // toute commande remet le silence à zéro

  char cmd = ligne[0];
  char *arguments = ligne + 1;
  // La lettre de commande doit être suivie d'un espace ou de la fin de ligne
  if (*arguments != '\0' && *arguments != ' ') {
    Serial.println(F("ERR commande"));
    return;
  }
  while (*arguments == ' ') arguments++;
  bool sansArgument = (*arguments == '\0');

  switch (cmd) {
    case 'P':
      if (sansArgument) Serial.println(F("OK P")); else Serial.println(F("ERR syntaxe"));
      break;
    case 'L':
      if (sansArgument) commandeLecture(); else Serial.println(F("ERR syntaxe"));
      break;
    case 'D':
      commandeD(arguments);
      break;
    case 'S':
      if (sansArgument) { arreterToutes(); Serial.println(F("OK S")); }
      else Serial.println(F("ERR syntaxe"));
      break;
    case 'E':
      if (sansArgument) commandeE(); else Serial.println(F("ERR syntaxe"));
      break;
    case 'N':
      commandeN(arguments);
      break;
    case 'Z':
      if (sansArgument) commandeZ(); else Serial.println(F("ERR syntaxe"));
      break;
    case 'R':
      if (sansArgument) commandeR(); else Serial.println(F("ERR syntaxe"));
      break;
    default:
      Serial.println(F("ERR commande"));
      break;
  }
}

// Lecture série non bloquante : on accumule les caractères dans un tampon
// fixe jusqu'au "\n", puis on traite la ligne.
void lireSerie() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;           // tolère les fins de ligne Windows
    if (c == '\n') {
      tampon[longueurTampon] = '\0';
      if (tamponDeborde) {
        sortirSecours();
        Serial.println(F("ERR trop_long"));
      } else {
        traiterLigne(tampon);
      }
      longueurTampon = 0;
      tamponDeborde = false;
      return;                          // une commande par tour de loop()
    }
    if (longueurTampon < TAILLE_TAMPON - 1) {
      tampon[longueurTampon++] = c;
    } else {
      tamponDeborde = true;            // ligne trop longue : elle sera rejetée
    }
  }
}

// =================================================================
// 11. SETUP ET LOOP
// =================================================================
void setup() {
  // Le watchdog peut rester armé après un redémarrage qu'il a provoqué : on le coupe d'abord
  MCUSR = 0;
  wdt_disable();

  // EC éteinte dès le départ
  pinMode(BROCHE_EC_ALIM, OUTPUT);
  digitalWrite(BROCHE_EC_ALIM, LOW);

  Serial.begin(VITESSE_SERIE);
  Wire.begin();
  Wire.setWireTimeout(25000, true);    // évite un blocage si le bus I2C se coince

  Serial.println(F("# HydroTour actionneur, demarrage"));

  // Carte pompes (indispensable)
  if (presentI2C(ADR_MCP23017)) {
    mcpInit = mcp.begin_I2C(ADR_MCP23017);
  }
  if (mcpInit) {
    mcpPresent = true;
    configurerCartePompes();
    Serial.println(F("# carte pompes MCP23017 OK"));
  } else {
    Serial.println(F("# ERREUR carte pompes MCP23017 (0x20) absente, pompes inutilisables"));
  }

  // CAN ADS1115 (EC et niveau)
  if (presentI2C(ADR_ADS1115)) adsInit = ads.begin(ADR_ADS1115);
  if (adsInit) {
    ads.setGain(GAIN_TWOTHIRDS);       // pleine échelle +/- 6,144 V (0,1875 mV par pas)
    adsPresent = true;
    Serial.println(F("# ADS1115 OK"));
  } else {
    Serial.println(F("# ADS1115 (0x48) absent : ec et niv = nan"));
  }

  // Accéléromètre
  if (presentI2C(ADR_LIS3DHTR)) {
    lis.begin(Wire, ADR_LIS3DHTR);
    lisPresent = lis.isConnection();
  }
  if (lisPresent) {
    lis.setFullScaleRange(LIS3DHTR_RANGE_2G);
    lis.setOutputDataRate(LIS3DHTR_DATARATE_50HZ);
    Serial.println(F("# LIS3DHTR OK"));
  } else {
    Serial.println(F("# LIS3DHTR (0x19) absent : detection de chute inactive, inc = nan"));
  }

  // Capteurs non I2C
  ds18b20.begin();
  ds18b20.setWaitForConversion(false); // conversion non bloquante
  dht.begin();

  // Réglages mémorisés
  chargerReglages();
  if (!niveauRegle) Serial.println(F("# seuil niveau non regle (commande N) : securite niveau inactive"));
  if (!refRegle)    Serial.println(F("# orientation non memorisee (commande Z) : securite chute inactive"));

  derniereCommande = millis();
  derniereVerifI2C = millis();
  derniereLectureNiveau = millis();

  wdt_enable(WDTO_8S);                 // chien de garde : redémarrage si blocage > 8 s
  Serial.println(F("# pret"));
}

void loop() {
  taches();            // watchdog, minuteries des pompes, chute
  lireSerie();         // commandes du Pi
  surveillerNiveau();  // niveau bas toutes les 5 s
  gererSecours();      // mode secours si le Pi se tait
  verifierModules();   // carte pompes / ADS absentes ou perdues
}
