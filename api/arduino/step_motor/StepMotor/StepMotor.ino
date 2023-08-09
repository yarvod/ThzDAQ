const int dirPin = 4;
const int stepPin = 3;
const int stepsPerRevolution = 1000;
const int stepDelay = 700;


void setup() {
  Serial.begin(9600);
  pinMode(dirPin, OUTPUT);
  pinMode(stepPin, OUTPUT);
}

void loop() {
  while (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    Serial.println("Recieved data " + data);
    stepperRotate(data);
  }
}

void stepperRotate(String data) {
  Serial.println("Start rotation");
  int angle = data.toInt();
  Serial.println("Angle " + String(angle));
  int stepsRev = abs((float)stepsPerRevolution * angle / 360);
  Serial.println("Steps " + String(stepsRev));
  if (angle >= 0) {
    Serial.println("Set cw");
    digitalWrite(dirPin, HIGH);
  } else {
    Serial.println("Set ccw");
    digitalWrite(dirPin, LOW);
  }

  for (int i = 0; i < stepsRev; i++) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(stepDelay);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelay);
  }

  Serial.println("Finish rotation");
}