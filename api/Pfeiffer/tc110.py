# %%
import logging
import serial
from time import sleep

from settings import PFEIFFER_PARAMETERS
from api.Pfeiffer.data_types import PFEIFFER_DATA_TYPES

logger = logging.getLogger(__name__)


class TC110:
    def __init__(self, device_id=1, port=None, autoconnect=True):
        self.device_id = self._format_id(device_id)
        self.communication = {
            "BAUDRATE": 9600,
            "DATA_BITS": serial.EIGHTBITS,
            "PARITY": serial.PARITY_NONE,
            "STOP_BITS": serial.STOPBITS_ONE,
        }
        self.port = port
        self.data_types = PFEIFFER_DATA_TYPES
        self.commands = PFEIFFER_PARAMETERS
        if autoconnect:
            self.connect(self.device_id, self.port)

    def connect(self, device_id=1, port=None):
        if port is not None:
            self.port = port
        self.device_id = self._format_id(device_id)
        self.inst = serial.Serial(
            port=self.port,
            baudrate=self.communication["BAUDRATE"],
            parity=self.communication["PARITY"],
            stopbits=self.communication["STOP_BITS"],
        )

    @classmethod
    def _pad_payload(cls, payload, length):
        payload = str(payload)
        if len(payload) >= length:
            return payload
        else:
            return cls._pad_payload("0" + payload, length)

    @classmethod
    def _format_id(cls, id):
        if type(id) not in [str, int]:
            raise TypeError(
                f"ID should be an integer between 1 and 255. {type(id)} was given."
            )
        if int(id) > 255 or int(id) < 1:
            raise ValueError(
                f"ID should be an integer between 1 and 255. {id} was given."
            )
        formatted_id = cls._pad_payload(str(int(id)), 3)
        return formatted_id

    @classmethod
    def _calculate_checksum(cls, message_string):
        # Could also just attempt conversion with message_string = str(message_string)
        if type(message_string) == str:
            checksum = cls._pad_payload(
                str(sum(message_string.encode("ascii")) % 256), 3
            )
            return checksum
        else:
            raise TypeError(
                f"Expected input of type string but received {type(message_string)}."
            )

    @classmethod
    def _received_ok(cls, received_string):
        if type(received_string) == str:
            bool_result = (
                cls._calculate_checksum(received_string[:-3]) == received_string[-3:]
            )
        else:
            raise TypeError(
                f"Expected input of type string but received {type(received_string)}."
            )
        return bool_result

    # def receive_message_backup(self):
    #     response_header = self.inst.read_bytes(10)
    #     payload_length = int(response_header[-2:])
    #     payload, checksum = self.inst.read_bytes(
    #         payload_length), self.inst.read_bytes(3)
    #     if not self.received_ok(response_header+payload+checksum):
    #         warnings.warn('Checksum error.')
    #         return None
    #     else:
    #         return payload

    def receive_message(self):
        full_response = self.inst.read(1024)
        full_response = full_response.decode("ascii")
        logger.debug(f"Received: {full_response}")
        if not self._received_ok(full_response):
            logger.warning("Checksum error.")
            return None
        else:
            device_id = full_response[:3]
            action = full_response[4]
            param_number = full_response[5:8]
            payload_length = int(full_response[8:10])
            payload = full_response[10:-3]
            if payload_length != len(payload):
                logger.warning("Payload length error.")
                return None
            else:
                message = {
                    "device_id": device_id,
                    "action": action,
                    "param_number": param_number,
                    "payload_length": payload_length,
                    "payload": payload,
                }
                return message

    def send_message(self, command, device_id=None, query_only=True, payload="=?"):
        if device_id is None:
            device_id = self.device_id
        else:
            device_id = self._format_id(device_id)
        param_number = str(command["number"])
        action = "00" if query_only else "10"
        payload_length = (
            "02" if query_only else self.data_types[command["data type"]]["length"]
        )
        message_string = device_id + action + param_number + payload_length + payload
        checksum = self._calculate_checksum(message_string)
        full_message = message_string + checksum
        logger.debug(f"Sending: {full_message}")
        self.inst.write(full_message.encode("ascii"))
        return full_message

    @staticmethod
    def cast(payload, command):
        data_type = command["data type"]
        if data_type == 0:
            out = bool(int(payload))
        elif data_type == 1:
            out = int(payload)
        elif data_type == 2:
            out = float(payload)
        elif data_type == 4:
            out = str(payload)
        elif data_type == 7:
            out = int(payload)
        elif data_type == 11:
            out = str(payload)
        else:
            raise Exception("Unknwon data type.")
        return out

    def get_fromkey(self, command_key, device_id=None):
        self.send_message(command=self.commands[command_key], device_id=device_id)
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands[command_key])
        else:
            logger.warning(f"{command_key} not received sucessfully.")
            return None

    def get_pressure(self, device_id=None):
        self.send_message(command=self.commands["Pressure"], device_id=device_id)
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands["Pressure"])
        else:
            logger.warning("Pressure not received sucessfully.")
            return None

    def get_speed(self, device_id=None):
        self.send_message(command=self.commands["ActualSpd"], device_id=device_id)
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands["ActualSpd"])
        else:
            logger.warning("Speed not received sucessfully.")
            return None

    def get_power(self, device_id=None):
        self.send_message(command=self.commands["DrvPower"], device_id=device_id)
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands["DrvPower"])
        else:
            logger.warning("Power not received sucessfully.")
            return None

    def get_current(self, device_id=None):
        self.send_message(command=self.commands["DrvCurrent"], device_id=device_id)
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands["DrvCurrent"])
        else:
            logger.warning("Current not received sucessfully.")
            return None

    def start(self, device_id=None):
        self.send_message(
            command=self.commands["PumpgStatn"],
            device_id=device_id,
            query_only=False,
            payload="111111",
        )
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands["PumpgStatn"])
        else:
            logger.warning("Reply not received sucessfully.")
            return None

    def stop(self, device_id=None):
        self.send_message(
            command=self.commands["PumpgStatn"],
            device_id=device_id,
            query_only=False,
            payload="000000",
        )
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands["PumpgStatn"])
        else:
            logger.warning("Reply not received sucessfully.")
            return None

    def toggle(self, device_id=None):
        self.send_message(
            command=self.commands["PumpgStatn"],
            device_id=device_id,
            query_only=True,
            payload="=?",
        )
        message = self.receive_message()
        if message["payload"] in ["000000", "111111"]:
            new_payload = self._pad_payload(
                str(int(message["payload"]) ^ 111111), 6
            )  # flip 111111 to 000000 and the other way round.
            self.send_message(
                command=self.commands["PumpgStatn"],
                device_id=device_id,
                query_only=False,
                payload=new_payload,
            )
            message = self.receive_message()
            if message:
                # FIXME check for error messages from pump
                return self.cast(message["payload"], self.commands["PumpgStatn"])
            else:
                logger.warning("Reply not received sucessfully.")
                return None
        else:
            logger.warning(f'Invalid pump status received: {message["payload"]}.')
            return None

    def get_running(self, device_id=None):
        self.send_message(command=self.commands["PumpgStatn"], device_id=device_id)
        message = self.receive_message()
        if message:
            # FIXME check for error messages from pump
            return self.cast(message["payload"], self.commands["PumpgStatn"])
        else:
            logger.warning("On/off status not received sucessfully.")
            return None

    def get_status(self, device_id=None):
        running = self.get_running(device_id=device_id)
        speed = self.get_speed(device_id=device_id)
        pressure = self.get_pressure(device_id=device_id)
        status = {"Running": running, "Speed": speed, "Pressure": pressure}
        return status

    def run_timed(self, seconds):
        try:
            self.timer = BoolTimer(seconds)
            self.timer.start()
            self.start()
            while self.timer.state:
                sleep(0.3)
                status = self.get_status()
                print(f'Frequency: {status["Speed"]} Hz')
                if not self.timer.state:
                    break
                sleep(0.05)
        finally:
            self.stop()

    def close(self):
        self.inst.close()


# %%

from threading import Thread, Event


class BoolTimer(Thread):
    """A boolean value that toggles after a specified number of seconds:

    bt = BoolTimer(30.0, False)
    bt.start()
    bt.cancel() # prevent the booltimer from toggling if it is still waiting
    """

    def __init__(self, interval, initial_state=True):
        Thread.__init__(self)
        self.interval = interval
        self.state = initial_state
        self.finished = Event()

    def __nonzero__(self):
        return bool(self.state)

    def cancel(self):
        """Stop BoolTimer if it hasn't toggled yet"""
        self.finished.set()

    def run(self):
        self.finished.wait(self.interval)
        if not self.finished.is_set():
            self.state = not self.state
        self.finished.set()


if __name__ == "__main__":
    pump = TC110(port="COM20")
    pump.get_status(1)
    # bytearray(b'6000000014\r')
