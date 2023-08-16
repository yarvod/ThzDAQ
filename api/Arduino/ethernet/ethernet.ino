#include <SPI.h>
#include <Ethernet2.h>
#include <ArduinoJson.h>

const int dirPin = 4;
const int stepPin = 3;
const int stepsPerRevolution = 1000;
const int stepDelay = 700;

byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
IPAddress ip(169, 254, 0, 52);
EthernetServer server(80);

void setup()
{
  Serial.begin(9600);
  while (!Serial) {
  }
  Serial.print("Serial init OK\r\n");
  if (Ethernet.begin(mac) == 0) {
    Serial.println("Failed to configure Ethernet using DHCP");
    Ethernet.begin(mac, ip);
  }
  server.begin();
  Serial.print("Server is at ");
  Serial.println(Ethernet.localIP());
}


void loop()
{
  EthernetClient client = server.available();
  if (client) {
    Serial.println("New client");
    boolean currentLineIsBlank = true;
    String request = "";
    while (client.connected()) {
      if (client.available()) {
        char c = client.read();
        request += c;
        Serial.write(c);
        if (c == '\n') {
          break;
        }
        urlHandler(request);
      }
    delay(1);
    client.stop();
    Serial.println("Client disconnected");
  }
}

void urlHandler(String request) {
  if (request.indexOf("POST /rotate") != -1) {
    stepperRotateView(request);
  }
}

int getContentLength(String request) {
  int contentLength = 0;
  int contentLengthIndex = request.indexOf("Content-Length:");
  if (contentLengthIndex != -1) {
    contentLengthIndex += 16;
    String contentLengthStr = request.substring(contentLengthIndex);
    contentLength = contentLengthStr.toInt();
  }
  return contentLength;
}

String getRequestBody(String request) {
  int contentLength = getContentLength(request);
  String body = "";
  for (int i = 0; i < contentLength; i++) {
    body += (char)client.read();
  }
  return body
}

void stepperRotateView(String request) {
  String body = getRequestBody(request);
  DynamicJsonDocument doc(1024);
  deserializeJson(doc, body);
  int angle = doc["angle"];
}

void stepperRotate(int angle) {
  int stepsRev = abs((float)stepsPerRevolution * angle / 360);
  if (angle >= 0) {
    digitalWrite(dirPin, HIGH);
  } else {
    digitalWrite(dirPin, LOW);
  }

  for (int i = 0; i < stepsRev; i++) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(stepDelay);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelay);
  }
}
