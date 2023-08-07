from serial import Serial


ser = Serial("COM5", 9600)

ser.write(b"ping")

response = ser.readline().decode("ascii")
if response == "pong\r\n":
    print("Arduino Uno доступна")
else:
    print("Arduino Uno недоступна")

ser.close()
