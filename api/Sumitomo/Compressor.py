import serial

from utils.classes import Singleton

host = "169.254.54.24"
port = 23


class Compressor(metaclass=Singleton):
    def __init__(self):
        """ "Initialize."""
        self.ser = serial.Serial(
            "/dev/cu.usbserial-1440",
            baudrate=9600,
            timeout=1,
            stopbits=serial.STOPBITS_ONE,
            parity=serial.PARITY_NONE,
            bytesize=8,
            rtscts=False,
            dsrdtr=False,
            write_timeout=None,
        )

    def read_all_temperatures(self):
        self.ser.write(str("$TEAA4B9\x0D").encode("ascii"))
        serial_response = self.ser.readline()
        res = serial_response.decode("utf-8").rstrip().split(",")
        print(res)
        try:
            print(
                str("\x24Temperature 1: " + res[1] + " degrees Celsius\n"),
                str("\x24Temperature 2: " + res[2] + " degrees Celsius\n"),
                str("\x24Temperature 3: " + res[3] + " degrees Celsius\n"),
                str("\x24Temperature 4: " + res[4] + " degrees Celsius\n"),
            )
        except IndexError:
            ...

    def read_all_pressures(self):
        self.ser.write(str("$PRA95F7\x0D").encode("ascii"))
        serial_response = self.ser.readline()
        res = serial_response.decode("utf-8").split(",")
        print(
            str(
                "\x24Pressure 1: "
                + res[1]
                + " psig\n"
                + "\x24Pressure 2: "
                + res[2]
                + " psig\n"
            ),
        )

    def read_status_bits(self):
        self.ser.write(str("$PRA95F7\x0d").encode("ascii"))
        res = self.ser.readline()
        # print(res)
        hex_status = str(int(res[1]))
        # print(hex)
        status = int(hex_status, 16)
        # print(status)
        status = bin(status)
        status_bits = status[2:].zfill(16)
        print(status_bits)
        if status_bits[0] is False:
            print("\tConfiguration 1")
        else:
            print("\tConfiguration 2")
        state_number = int(status_bits[4:7], 2)
        if int(state_number) == 0:
            print("\tLocal off")
        elif int(state_number) == 1:
            print("\tLocal on")
        elif int(state_number) == 2:
            print("\tRemote off")
        elif int(state_number) == 3:
            print("\tRemote on")
        elif int(state_number) == 4:
            print("\tCold head run")
        elif int(state_number) == 5:
            print("\tCold head pause")
        elif int(state_number) == 6:
            print("\tFault off")
        elif int(state_number) == 7:
            print("\tOil fault on")
        if status[7] is True:
            print("\tSolenoid on")
        else:
            print("\tSolenoid off")
        if status_bits[8] is True:
            print("\tPressure alarm")
        else:
            pass
            # print("\tNo pressure alarm")
        if status_bits[9] is True:
            print("\tOil level alarm")
        else:
            pass
        #         print("\tNo oil level alarm")
        if status_bits[10] is True:
            print("\tWater flow alarm")
        else:
            pass
        #         print("\tNo water flow alarm")
        if status_bits[11] is True:
            print("\tWater Temperature alarm")
        else:
            pass
        #         print("\tNo water temperature alarm")
        if status_bits[12] is True:
            print("\tHelium temperature alarm")
        else:
            pass
        #         print("\tNo helium temperature alarm")
        if status_bits[13] is True:
            print("\tPhase sequence/fuse alarm")
        else:
            pass
        #         print("\tNo phase sequence/fuse alarm")
        if status_bits[14] is True:
            print("\tMotor temperature alarm")
        else:
            pass
        #         print("\tNo motor temperature alarm")
        if status_bits[15] is True:
            print("\tSystem ON")
        else:
            pass

    #         print("\tSystem OFF")

    def turn_on(self):
        self.ser.write(str("$ON177CF\x00").encode("ascii"))

    def turn_off(self):
        self.ser.write(str("$OFF9188\x00").encode("ascii"))

    def reset(self):
        self.ser.write(str("$RS12156\x00").encode("ascii"))

    def cold_head_run(self):
        self.ser.write(str("$CHRFD4C\x00").encode("ascii"))

    def cold_head_pause(self):
        self.ser.write(str("$CHP3CCD\x00").encode("ascii"))

    def cold_head_pause_off(self):
        self.ser.write(str("$CHRFD4C\x00").encode("ascii"))


if __name__ == "__main__":
    # compressor = Compressor()
    # ser = compressor.ser
    # while 1:
    #     if ser.is_open:
    #         print("Connected to serial device")
    #         print("--------------------------------")
    #
    #         comm = input("Please enter your command:\n>>")
    #
    #         if comm == "help":
    #             print(
    #                 str("--------------------------------\n"),
    #                 str("\x24Commands for F70H:\x24"),
    #                 str("\n\t$TEA: Read all  temperatures"),
    #                 str("\n\t$PRA: Read all  pressures"),
    #                 str("\n\t$STA: Read status bits"),
    #                 str("\n\t$ON1: On"),
    #                 str("\n\t$RS1: Reset"),
    #                 str("\n\t$CHP: Cold head pause"),
    #                 str("\n\t$CHR: Cold  head run"),
    #                 str("\n\t$POF: COld head pause off"),
    #             )
    #             print("--------------------------------")
    #         elif comm == "TEA":
    #             compressor.read_all_temperatures()
    #         elif comm == "PRA":
    #             compressor.read_all_pressures()
    #         elif comm == "STA":
    #             compressor.read_status_bits()
    #         elif comm == "ON1":
    #             compressor.turn_on()
    #         elif comm == "OFF":
    #             compressor.turn_off()
    #         elif comm == "RS1":
    #             compressor.reset()
    #         elif comm == "CHP":
    #             compressor.cold_head_pause()
    #         elif comm == "CHR":
    #             compressor.cold_head_run()
    #         elif comm == "POF":
    #             compressor.cold_head_pause_off()
    #         else:
    #             print("INVALID COMMAND")
    #
    #     else:
    #         print("Could not  connect to serial device")
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("169.254.54.24", 23))
        s.settimeout(5)
        # s.send(str("$TEAA4B9\x0D").encode("ascii"))
        s.send("++++".encode("ascii"))
        d = s.recv(1024)
        print(d)
