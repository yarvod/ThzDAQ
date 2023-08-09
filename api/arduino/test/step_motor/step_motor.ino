// Define pin connections & motor's steps per revolution
// const int enable = 4;
const int dirPin = 4;
const int stepPin = 3;
const int stepsPerRevolution = 1000;
const int stepDelay = 700;

void setup()
{
  // Declare pins as Outputs
  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);
}


void loop()
{
  digitalWrite(dirPin,HIGH); // Enables the motor to move in a particular direction
  // Makes 1000 pulses for making one full cycle rotation
  for(int x = 0; x < stepsPerRevolution; x++) {
    digitalWrite(stepPin,HIGH); 
    delayMicroseconds(stepDelay); 
    digitalWrite(stepPin,LOW); 
    delayMicroseconds(stepDelay); 
  }
  delay(1000); // One second delay
  
  digitalWrite(dirPin,LOW); //Changes the rotations direction
  // Makes 1000 pulses for making two full cycle rotation
  for(int x = 0; x < stepsPerRevolution; x++) {
    digitalWrite(stepPin,HIGH);
    delayMicroseconds(stepDelay);
    digitalWrite(stepPin,LOW);
    delayMicroseconds(stepDelay);
  }
  delay(1000);
}