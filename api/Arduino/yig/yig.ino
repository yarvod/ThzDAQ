#include <SPI.h>
#include <Ethernet.h>
#include <EEPROM.h>

// -------------------- Pin mapping (from your notebook photo) --------------------
// YIG D0..D11 are device bits; Arduino pins are:
static const uint8_t BIT_PINS[12] = {
  8,  // D0  -> Arduino D8
  7,  // D1  -> Arduino D7
  6,  // D2  -> Arduino D6
  5,  // D3  -> Arduino D5
  4,  // D4  -> Arduino D4
  3,  // D5  -> Arduino D3
  2,  // D6  -> Arduino D2
  A0, // D7  -> Arduino A0
  A1, // D8  -> Arduino A1
  A2, // D9  -> Arduino A2
  A3, // D10 -> Arduino A3
  A4  // D11 -> Arduino A4
};

static const uint8_t PIN_STB = A5;   // STB -> Arduino A5

// W5500 mapping (hardware SPI on Nano):
// MOSI D11, MISO D12, SCK D13, CS D10, RST D9 (if you wired it).
// Note: Ethernet library uses SS (D10) for W5500 CS by default if you pass it.
static const uint8_t PIN_W5500_CS = 10;

// -------------------- Timing --------------------
static const uint16_t STB_PULSE_US = 5;      // adjust if device needs longer
static const uint16_t SETTLE_US    = 2;      // small settle after data set

// -------------------- EEPROM MAC storage --------------------
static const int EEPROM_MAGIC_ADDR = 0;
static const int EEPROM_MAC_ADDR   = 1;
static const uint8_t EEPROM_MAGIC  = 0xA7;

byte mac[6];
EthernetServer server(80);

volatile uint16_t lastCode = 0;

// Fallback static if DHCP fails:
IPAddress fallbackIp(192, 168, 1, 77);
IPAddress fallbackDns(192, 168, 1, 1);
IPAddress fallbackGw(192, 168, 1, 1);
IPAddress fallbackMask(255, 255, 255, 0);

// -------------------- Helpers --------------------
static void printMac(const byte m[6]) {
  for (int i = 0; i < 6; i++) {
    if (m[i] < 16) Serial.print('0');
    Serial.print(m[i], HEX);
    if (i != 5) Serial.print(':');
  }
}

static void loadOrCreateMac() {
  if (EEPROM.read(EEPROM_MAGIC_ADDR) == EEPROM_MAGIC) {
    for (int i = 0; i < 6; i++) mac[i] = EEPROM.read(EEPROM_MAC_ADDR + i);
    return;
  }

  // Generate a locally-administered unicast MAC: 02:xx:xx:xx:xx:xx
  // Nano (ATmega328P) has no unique chip ID, so we use analog noise once and store in EEPROM.
  randomSeed(analogRead(A7) ^ micros());

  mac[0] = 0x02; // LAA + unicast
  for (int i = 1; i < 6; i++) mac[i] = (byte)random(0, 256);

  EEPROM.update(EEPROM_MAGIC_ADDR, EEPROM_MAGIC);
  for (int i = 0; i < 6; i++) EEPROM.update(EEPROM_MAC_ADDR + i, mac[i]);
}

static void pulseStb() {
  digitalWrite(PIN_STB, HIGH);
  delayMicroseconds(STB_PULSE_US);
  digitalWrite(PIN_STB, LOW);
}

static void applyCode(uint16_t code) {
  code &= 0x0FFF;

  // Set 12 bits: BIT_PINS[i] corresponds to device bit Di (i=0..11)
  for (uint8_t i = 0; i < 12; i++) {
    uint8_t level = (code >> i) & 0x01;
    digitalWrite(BIT_PINS[i], level ? HIGH : LOW);
  }

  delayMicroseconds(SETTLE_US);
  pulseStb();

  lastCode = code;
}

static void sendHttp(EthernetClient &c, int code, const __FlashStringHelper *ctype, const String &body) {
  c.print(F("HTTP/1.1 "));
  c.print(code);
  c.print(F(" OK\r\n"));
  c.print(F("Connection: close\r\n"));
  c.print(F("Content-Type: "));
  c.print(ctype);
  c.print(F("\r\n"));
  c.print(F("Access-Control-Allow-Origin: *\r\n"));
  c.print(F("\r\n"));
  c.print(body);
}

static String urlDecode(const String &s) {
  // Minimal decoder (handles %xx and +)
  String out;
  out.reserve(s.length());
  for (uint16_t i = 0; i < s.length(); i++) {
    char ch = s[i];
    if (ch == '+') out += ' ';
    else if (ch == '%' && i + 2 < s.length()) {
      char h1 = s[i + 1], h2 = s[i + 2];
      auto hexVal = [](char x)->int {
        if (x >= '0' && x <= '9') return x - '0';
        if (x >= 'a' && x <= 'f') return x - 'a' + 10;
        if (x >= 'A' && x <= 'F') return x - 'A' + 10;
        return -1;
      };
      int v1 = hexVal(h1), v2 = hexVal(h2);
      if (v1 >= 0 && v2 >= 0) {
        out += char((v1 << 4) | v2);
        i += 2;
      } else out += ch;
    } else out += ch;
  }
  return out;
}

static bool parseCodeFromPath(const String &path, uint16_t &codeOut) {
  // Accept:
  //  /set?code=1234
  //  /set/1234
  //  /set?value=...
  int q = path.indexOf('?');
  String p = (q >= 0) ? path.substring(0, q) : path;
  String query = (q >= 0) ? path.substring(q + 1) : "";

  // /set/1234
  if (p.startsWith("/set/")) {
    String tail = p.substring(5);
    tail.trim();
    long v = tail.toInt();
    if (v >= 0 && v <= 4095) { codeOut = (uint16_t)v; return true; }
    return false;
  }

  // /set?code=1234 or /set?value=1234
  if (p == "/set") {
    query = urlDecode(query);
    // very small parser: split by &
    int start = 0;
    while (start < (int)query.length()) {
      int amp = query.indexOf('&', start);
      if (amp < 0) amp = query.length();
      String pair = query.substring(start, amp);
      int eq = pair.indexOf('=');
      if (eq > 0) {
        String k = pair.substring(0, eq);
        String v = pair.substring(eq + 1);
        k.trim(); v.trim();
        if (k == "code" || k == "value" || k == "v") {
          long n = v.toInt();
          if (n >= 0 && n <= 4095) { codeOut = (uint16_t)n; return true; }
          return false;
        }
      }
      start = amp + 1;
    }
  }

  return false;
}

static String statusJson() {
  IPAddress ip = Ethernet.localIP();
  String s;
  s.reserve(200);

  s += "{";
  s += "\"ip\":\"";
  s += ip[0]; s += "."; s += ip[1]; s += "."; s += ip[2]; s += "."; s += ip[3];
  s += "\",\"mac\":\"";
  for (int i = 0; i < 6; i++) {
    if (mac[i] < 16) s += "0";
    s += String(mac[i], HEX);
    if (i != 5) s += ":";
  }
  s += "\",\"lastCode\":";
  s += String(lastCode);
  s += "}";
  return s;
}

// -------------------- Setup / Loop --------------------
void setup() {
  Serial.begin(115200);

  // Pins init
  for (uint8_t i = 0; i < 12; i++) pinMode(BIT_PINS[i], OUTPUT);
  pinMode(PIN_STB, OUTPUT);
  digitalWrite(PIN_STB, LOW);

  // Start with 0
  applyCode(0);

  loadOrCreateMac();

  Serial.print(F("MAC (stored/created): "));
  printMac(mac);
  Serial.println();

  // Ethernet init
  Ethernet.init(PIN_W5500_CS);

  Serial.println(F("DHCP..."));
  int dhcpOk = Ethernet.begin(mac, 8000); // 8s timeout
  if (dhcpOk == 0) {
    Serial.println(F("DHCP failed. Using fallback static IP."));
    Ethernet.begin(mac, fallbackIp, fallbackDns, fallbackGw, fallbackMask);
  } else {
    Serial.println(F("DHCP OK."));
  }

  Serial.print(F("IP: "));
  Serial.println(Ethernet.localIP());

  server.begin();
  Serial.println(F("HTTP server started on port 80"));
  Serial.println(F("Endpoints: /  /set?code=1234  /set/1234  /mac  /pulse"));
}

void loop() {
  EthernetClient client = server.available();
  if (!client) return;

  // Read first request line
  String line;
  line.reserve(120);
  unsigned long t0 = millis();
  while (client.connected() && (millis() - t0 < 1000)) {
    if (client.available()) {
      char ch = client.read();
      if (ch == '\n') break;
      if (ch != '\r') line += ch;
    }
  }

  // Drain headers quickly
  t0 = millis();
  while (client.connected() && (millis() - t0 < 200)) {
    if (!client.available()) break;
    String h = client.readStringUntil('\n');
    if (h == "\r" || h.length() == 0) break;
  }

  // Parse: "GET /path HTTP/1.1"
  String path = "/";
  if (line.startsWith("GET ")) {
    int sp1 = line.indexOf(' ');
    int sp2 = line.indexOf(' ', sp1 + 1);
    if (sp1 >= 0 && sp2 > sp1) path = line.substring(sp1 + 1, sp2);
  }

  // Routing
  if (path == "/" || path.startsWith("/status")) {
    sendHttp(client, 200, F("application/json"), statusJson());
  }
  else if (path.startsWith("/mac")) {
    String body;
    body.reserve(64);
    body += "{\"mac\":\"";
    for (int i = 0; i < 6; i++) {
      if (mac[i] < 16) body += "0";
      body += String(mac[i], HEX);
      if (i != 5) body += ":";
    }
    body += "\"}";
    sendHttp(client, 200, F("application/json"), body);
  }
  else if (path.startsWith("/pulse")) {
    pulseStb();
    sendHttp(client, 200, F("application/json"), "{\"ok\":true,\"action\":\"pulse\"}");
  }
  else {
    uint16_t code;
    if (parseCodeFromPath(path, code)) {
      applyCode(code);

      Serial.print(F("SET code="));
      Serial.println(code);

      String body = "{\"ok\":true,\"code\":";
      body += String(code);
      body += "}";
      sendHttp(client, 200, F("application/json"), body);
    } else {
      sendHttp(client, 404, F("text/plain"),
               "Not found.\nUse:\n  / (status)\n  /set?code=0..4095\n  /set/<0..4095>\n  /mac\n  /pulse\n");
    }
  }

  delay(1);
  client.stop();
}