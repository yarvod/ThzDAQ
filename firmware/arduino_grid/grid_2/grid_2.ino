#include <SPI.h>
#include <Ethernet2.h>
#include <ArduinoJson.h>

const int dirPin = 2;
const int stepPin = 3;
const int sleepPin = 4;
const int resetPin = 5;
const int ms3Pin = 6;
const int ms2Pin = 7;
const int ms1Pin = 8;
const int enablePin = 9;

const int stepsPerRevolution = 16000;
const int stepDelay = 350;

byte mac[] = { 0x00, 0xAA, 0xBB, 0xCC, 0xDE, 0x02 };
IPAddress ip(169, 254, 0, 53);
EthernetServer server(80);

// Helpers
void urlHandler(String request, EthernetClient client) {
  Serial.print("Recieved request: " + String(request));
  if (request.indexOf("POST /rotate") != -1) {
    Serial.println("Calling stepperRotateView");
    stepperRotateView(request, client);
  }
  if (request.indexOf("POST /test") != -1) {
    Serial.println("Calling testStepperRotateView");
    testStepperRotateView(request, client);
  }
}

int getContentLength(String bodyFull) {
  int contentLength = 0;
  int contentLengthIndex = bodyFull.indexOf("Content-Length:");
  if (contentLengthIndex != -1) {
    contentLengthIndex += 16;
    String contentLengthStr = bodyFull.substring(contentLengthIndex);
    contentLength = contentLengthStr.toInt();
  }
  Serial.println("Request Length: " + String(contentLength));
  return contentLength;
}

void sendResponse(EthernetClient client, String response) {
  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: application/json");
  client.println("Connection: close");
  client.print("Content-Length: ");
  client.println(response.length());
  client.println();
  client.println(response);
}

// Serialization
float serializeRequest(String request, EthernetClient client) {
  String bodyFull = client.readString();
  int contentLength = getContentLength(bodyFull);
  int bodyFullLength = bodyFull.length();
  String body = bodyFull.substring(bodyFullLength - contentLength, bodyFullLength);
  body.replace("\n", "");
  body.replace("\r", "");
  body.replace(" ", "");
  Serial.println("Body: " + body);
  int ind1 = body.indexOf(":") + 1;
  int ind2 = body.length() - 1;
  float angle = body.substring(ind1, ind2).toFloat();
  Serial.println("Angle: " + String(angle));
  client.flush();
  return angle;
}

String serializeResponse() {
  DynamicJsonDocument responseDoc(1024);
  responseDoc["status"] = "OK";
  String response;
  serializeJson(responseDoc, response);
  return response;
}

void processResponse(EthernetClient client) {
  String response = serializeResponse();
  sendResponse(client, response);
}

// Views
void stepperRotateView(String request, EthernetClient client) {
  float angle = serializeRequest(request, client);
  stepperRotate(angle);
  processResponse(client);
}

void testStepperRotateView(String request, EthernetClient client) {
  stepperRotate(45);
  stepperRotate(-45);
  processResponse(client);
}

// UseCases
void stepperRotate(float angle) {
  int stepsRev = abs(stepsPerRevolution * angle / 360);
  Serial.println("Steps: " + String(stepsRev));
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

// Set Up
void setup() {
  // Init serial
  Serial.begin(9600);
  Serial.print("Serial init OK\r\n");
  // Set pins outs
  pinMode(dirPin, OUTPUT);
  pinMode(stepPin, OUTPUT);
  pinMode(sleepPin, OUTPUT);
  pinMode(resetPin, OUTPUT);
  pinMode(ms1Pin, OUTPUT);
  pinMode(ms2Pin, OUTPUT);
  pinMode(ms3Pin, OUTPUT);
  pinMode(enablePin, OUTPUT);
  // pinMode(resetPin, OUTPUT);
  // pinMode(sleepPin, OUTPUT);
  // Init default pins values
  // Init ethernet
  Ethernet.begin(mac, ip);
  server.begin();
  Serial.print("Server is at ");
  Serial.println(Ethernet.localIP());
  // Enable driver motor
  digitalWrite(enablePin, LOW);
  digitalWrite(resetPin, HIGH);
  digitalWrite(sleepPin, HIGH);
  digitalWrite(ms1Pin, HIGH);
  digitalWrite(ms2Pin, HIGH);
  digitalWrite(ms3Pin, HIGH);
  Serial.println("Motor enabled");
}

// Main Loop
void loop() {
  EthernetClient client = server.available();
  if (client) {
    Serial.println("New client");
    String request = "";
    while (client.connected()) {
      if (client.available()) {
        char c = client.read();
        request += c;
        if (c == '\n') {
          break;
        }
      }
    }
    urlHandler(request, client);
    delay(0.1);
    client.stop();
    Serial.println("Client disconnected");
  }
}
