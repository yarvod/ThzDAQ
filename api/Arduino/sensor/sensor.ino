#include <SPI.h>
#include <Ethernet.h>

const int pin4 = 4;
const int pin3 = 3;

byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
IPAddress ip(169, 254, 10, 177);
IPAddress myDns(169, 254, 10, 1);
IPAddress gateway(169, 254, 10, 1);
IPAddress subnet(255, 255, 0, 0);
EthernetServer server(23);

void setup() {
  Serial.begin(9600);
  Serial.print("Serial init OK\r\n");
  pinMode(pin4, INPUT);
  pinMode(pin3, INPUT);
  Ethernet.begin(mac, ip);
  server.begin();
  Serial.print("Server is at ");
  Serial.println(Ethernet.localIP());
}

void loop() {
  EthernetClient client = server.available();

  if (client) {
    while (client.connected()) {
      int pin3Value = digitalRead(pin3);
      int pin4Value = digitalRead(pin4);
      Serial.println(String(pin3Value) + " " + String(pin4Value));
      client.println(String(pin3Value) + " " + String(pin4Value));
      delay(10);

      if (!client.connected()) {
        client.stop();
      }
    }
  }
}
