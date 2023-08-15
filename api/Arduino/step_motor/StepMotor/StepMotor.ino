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
    if (data == "test") {
      Serial.println("OK");
    } else {
      stepperRotate(data);
    }
  }
}

void stepperRotate(String data) {
  int angle = data.toInt();
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
