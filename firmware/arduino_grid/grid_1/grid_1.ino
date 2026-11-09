// Wire grid rotator 1: a step/dir stepper driver (A4988 pinout) on an Iskra
// Neo (ATmega32U4, Arduino Leonardo compatible) with a W5500 on SPI, driven by
// thzdaq_instruments' arduino.grid.
//
//   POST /rotate {"angle": <relative degrees>}  moves, then {"status":"OK"}
//   POST /test                                   +45 deg and back
//   GET  /status  {"uptime_s", "eth_restores", "link"}: after a glitch, a small
//                 uptime means the board rebooted, a grown eth_restores that
//                 the W5500 lost its settings and they were written again
//
// Libraries: only those of the Arduino IDE (Ethernet 2.x drives the W5500).
// Serial is the USB port here (log at any baud rate), so pin 1 is free for DIR.
// The driver's ENABLE is not wired: its coils carry the holding current all
// the time, the motor must not be plugged in or out while the board is on.

#include <SPI.h>
#include <Ethernet.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// The W5500 is on the ICSP SPI of the 32U4; 10 selects it
const uint8_t DIR_PIN = 1;
const uint8_t STEP_PIN = 2;
const uint8_t RESET_PIN = 3;
const uint8_t SLEEP_PIN = 4;
const uint8_t MS1_PIN = 5;
const uint8_t MS2_PIN = 6;
const uint8_t MS3_PIN = 7;
const uint8_t ETHERNET_CS_PIN = 10;

const long STEPS_PER_TURN = 16000;  // microsteps (MS1-3 high: 1/16) per grid turn
const unsigned int STEP_HALF_PERIOD_US = 350;
const float MAX_ANGLE = 3600;  // of one move, deg: bounds the step count

byte MAC[] = {0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED};
const IPAddress IP(169, 254, 0, 52);
const IPAddress SUBNET(255, 255, 0, 0);  // all of link-local 169.254.0.0/16
const IPAddress NO_ADDRESS(0, 0, 0, 0);  // no DNS, no gateway on a direct link

const unsigned long REQUEST_TIMEOUT_MS = 2000;
const unsigned long ETHERNET_CHECK_MS = 1000;
// The library waits for a send to finish without a timeout: a peer that
// vanished frees the socket after 200 ms doubling 4 times (~6 s), not the
// W5500's default ~30 s
const uint8_t RETRANSMISSIONS = 4;

EthernetServer server(80);
unsigned long ethernetRestores = 0;
bool linkOn = false;

// Driver

void setOutput(uint8_t pin, uint8_t level) {
  digitalWrite(pin, level);  // before pinMode: the pin never drives the other level
  pinMode(pin, OUTPUT);
}

void rotate(float angle) {
  long steps = lround(fabs(angle) * STEPS_PER_TURN / 360.0);
  Serial.print(F("Rotate "));
  Serial.print(angle);
  Serial.print(F(" deg, "));
  Serial.print(steps);
  Serial.println(F(" steps"));
  digitalWrite(DIR_PIN, angle >= 0 ? HIGH : LOW);
  for (long i = 0; i < steps; i++) {
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(STEP_HALF_PERIOD_US);
    digitalWrite(STEP_PIN, LOW);
    delayMicroseconds(STEP_HALF_PERIOD_US);
  }
}

// Ethernet

// Writes our addresses into the W5500; true when it answers and holds them
bool configureEthernet() {
  Ethernet.begin(MAC, IP, NO_ADDRESS, NO_ADDRESS, SUBNET);
  if (Ethernet.hardwareStatus() == EthernetNoHardware) return false;
  Ethernet.setRetransmissionCount(RETRANSMISSIONS);
  return Ethernet.localIP() == IP;
}

// A dip of its supply resets the W5500 while the board runs on: its addresses
// read back wrong, write them again. The server listens again by itself on the
// next accept().
void checkEthernet() {
  static unsigned long checked = 0;
  if (millis() - checked < ETHERNET_CHECK_MS) return;
  checked = millis();
  bool link = Ethernet.linkStatus() == LinkON;
  if (link != linkOn) {
    linkOn = link;
    Serial.println(link ? F("Link up") : F("Link down"));
  }
  if (Ethernet.localIP() == IP) return;
  ethernetRestores++;
  Serial.println(F("W5500 lost its settings, writing them again"));
  if (!configureEthernet()) Serial.println(F("W5500 does not answer"));
}

// HTTP

// The next byte of the request, or -1 when the client left or is too slow
int nextByte(EthernetClient &client, unsigned long started) {
  while (millis() - started < REQUEST_TIMEOUT_MS) {
    int c = client.read();
    if (c >= 0) return c;
    if (!client.connected()) return -1;
  }
  return -1;
}

// A line without CR LF, cut to the size of line; false as nextByte
bool readLine(EthernetClient &client, char *line, size_t size, unsigned long started) {
  size_t length = 0;
  for (;;) {
    int c = nextByte(client, started);
    if (c < 0) return false;
    if (c == '\n') break;
    if (c != '\r' && length < size - 1) line[length++] = c;
  }
  line[length] = '\0';
  return true;
}

// Sends the whole response in one packet; json is a printf format in flash
void respond(EthernetClient &client, PGM_P status, PGM_P json, ...) {
  char body[96];
  va_list args;
  va_start(args, json);
  vsnprintf_P(body, sizeof body, json, args);
  va_end(args);
  char out[200];
  int length = snprintf_P(out, sizeof out,
                          PSTR("HTTP/1.1 %S\r\nContent-Type: application/json\r\n"
                               "Content-Length: %u\r\nConnection: close\r\n\r\n%s"),
                          status, strlen(body), body);
  if (length >= (int)sizeof out) length = sizeof out - 1;
  client.write((const uint8_t *)out, length);
}

// The angle of a body {"angle": <degrees>}; false when there is none in range
bool parseAngle(const char *body, float *angle) {
  const char *key = strstr_P(body, PSTR("\"angle\""));
  if (key == NULL) return false;
  const char *colon = strchr(key + 7, ':');
  if (colon == NULL) return false;
  char *end;
  double value = strtod(colon + 1, &end);
  if (end == colon + 1 || !(fabs(value) <= MAX_ANGLE)) return false;
  *angle = value;
  return true;
}

bool isRequest(const char *request, PGM_P start) {
  return strncmp_P(request, start, strlen_P(start)) == 0;
}

void route(EthernetClient &client, const char *request, const char *body) {
  if (isRequest(request, PSTR("POST /rotate "))) {
    float angle;
    if (!parseAngle(body, &angle)) {
      respond(client, PSTR("400 Bad Request"), PSTR("{\"error\":\"no angle within +-%d deg\"}"),
              (int)MAX_ANGLE);
      return;
    }
    rotate(angle);
    respond(client, PSTR("200 OK"), PSTR("{\"status\":\"OK\"}"));
  } else if (isRequest(request, PSTR("POST /test "))) {
    rotate(45);
    rotate(-45);
    respond(client, PSTR("200 OK"), PSTR("{\"status\":\"OK\"}"));
  } else if (isRequest(request, PSTR("GET /status "))) {
    respond(client, PSTR("200 OK"),
            PSTR("{\"status\":\"OK\",\"uptime_s\":%lu,\"eth_restores\":%lu,\"link\":%S}"),
            millis() / 1000, ethernetRestores,
            Ethernet.linkStatus() == LinkON ? PSTR("true") : PSTR("false"));
  } else {
    respond(client, PSTR("404 Not Found"),
            PSTR("{\"error\":\"POST /rotate, POST /test or GET /status\"}"));
  }
}

// Reads one request within REQUEST_TIMEOUT_MS and answers it
void serve(EthernetClient &client) {
  unsigned long started = millis();
  char request[32];  // "POST /rotate HTTP/1.1"
  char header[32];
  char body[48];
  long length = 0;
  if (!readLine(client, request, sizeof request, started)) return;
  Serial.println(request);
  for (;;) {
    if (!readLine(client, header, sizeof header, started)) return;
    if (header[0] == '\0') break;
    if (strncasecmp_P(header, PSTR("Content-Length:"), 15) == 0) length = atol(header + 15);
  }
  if (length < 0 || length >= (long)sizeof body) {
    respond(client, PSTR("400 Bad Request"), PSTR("{\"error\":\"body too long\"}"));
    return;
  }
  for (long i = 0; i < length; i++) {
    int c = nextByte(client, started);
    if (c < 0) return;
    body[i] = c;
  }
  body[length] = '\0';
  route(client, request, body);
}

void setup() {
  // Coils off (RESET low) while the W5500 starts, so their current does not
  // load the supply then; the lines float until here
  setOutput(RESET_PIN, LOW);
  setOutput(SLEEP_PIN, HIGH);
  setOutput(MS1_PIN, HIGH);
  setOutput(MS2_PIN, HIGH);
  setOutput(MS3_PIN, HIGH);
  setOutput(STEP_PIN, LOW);
  setOutput(DIR_PIN, LOW);

  Serial.begin(115200);
  Serial.println(F("Grid 1 boots"));

  Ethernet.init(ETHERNET_CS_PIN);
  // Each try waits out the W5500's reset (560 ms in the library) and looks for
  // the chip: a W5500 slower to power up than the board is found on a later try
  while (!configureEthernet()) Serial.println(F("W5500 does not answer"));
  server.begin();
  linkOn = Ethernet.linkStatus() == LinkON;
  Serial.print(F("Server at "));
  Serial.print(Ethernet.localIP());
  Serial.println(linkOn ? F(", link up") : F(", link down"));

  digitalWrite(RESET_PIN, HIGH);
}

void loop() {
  checkEthernet();
  // A new connection, once, even before it sends: serve() closes every one,
  // so a client that went silent cannot hold a socket
  EthernetClient client = server.accept();
  if (client) {
    serve(client);
    client.stop();
  }
}
