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

// Helpers
void urlHandler(String request, EthernetClient client) {
  Serial.print("Recieved request: " + String(request));
  if (request.indexOf("POST /rotate") != -1) {
    Serial.println("Calling stepperRotateView");
    stepperRotateView(request, client);
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

String serializeResponse(float angle) {
  DynamicJsonDocument responseDoc(1024);
  responseDoc["status"] = "OK";
  responseDoc["angle"] = angle;
  String response;
  serializeJson(responseDoc, response);
  return response;
}

void processResponse(EthernetClient client, float angle) {
  String response = serializeResponse(angle);
  sendResponse(client, response);
}

// Views
void stepperRotateView(String request, EthernetClient client) {
  float angle = serializeRequest(request, client);
  stepperRotate(angle);
  processResponse(client, angle);
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
  Serial.begin(9600);
  pinMode(dirPin, OUTPUT);
  pinMode(stepPin, OUTPUT);
  Serial.print("Serial init OK\r\n");
  Ethernet.begin(mac, ip);
  server.begin();
  Serial.print("Server is at ");
  Serial.println(Ethernet.localIP());
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
