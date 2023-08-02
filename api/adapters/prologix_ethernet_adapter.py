import logging
import socket
from typing import Union

from utils.classes import InstrumentAdapterInterface, Singleton


logger = logging.getLogger(__name__)


class PrologixEthernetAdapter(InstrumentAdapterInterface, metaclass=Singleton):
    PORT = 1234
    socket = None
    host = None

    def __init__(self, host: str, timeout: float = 2, *args, **kwargs):
        self.host = host
        self.timeout = 0
        self.init(timeout)

    def init(self, timeout: float = 2):
        if self.socket is None:
            logger.info(f"[{self.__class__.__name__}.init]Socket is None, creating ...")
            self.socket = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP
            )
        else:
            logger.info(
                f"[{self.__class__.__name__}.init]Socket is already existed, connecting ..."
            )
        self.connect(timeout)
        self._setup()

    def connect(self, timeout: float = 2):
        self.set_timeout(timeout)
        try:
            self.socket.connect((self.host, self.PORT))
            logger.info(
                f"[{self.__class__.__name__}.connect]Socket has been connected {self.socket}."
            )
        except OSError as e:
            logger.error(f"[{self.__class__.__name__}.connect] {e}")

    def is_socket_closed(self) -> Union[bool, None]:
        try:
            # this will try to read bytes without blocking and also without removing them from buffer (peek only)
            data = self.socket.recv(16)
            if len(data) == 0:
                logger.info(
                    f"[{self.__class__.__name__}.is_socket_closed] Socket is closed"
                )
                return True
        except BlockingIOError:
            logger.info(
                f"[{self.__class__.__name__}.is_socket_closed] BlockingIOError, socket is opened"
            )
            return False  # socket is open and reading from it would block
        except ConnectionResetError:
            logger.info(
                f"[{self.__class__.__name__}.is_socket_closed] ConnectionResetError, socket is closed"
            )
            return True  # socket was closed for some other reason
        except Exception as e:
            logger.error(
                f"[{self.__class__.__name__}.is_socket_closed] Unexpected exception '{e}', socket status is undefined"
            )
            return None
        logger.info(f"[{self.__class__.__name__}.is_socket_closed] Socket is opened")
        return False

    def close(self):
        if self.socket is None:
            logger.warning(f"[{self.__class__.__name__}.close] Socket is None")
            return
        self.socket.close()
        del self.socket
        logger.info(f"[{self.__class__.__name__}.close] Socket has been closed.")

    def select(self, eq_addr):
        self._send("++addr %i" % int(eq_addr))

    def write(self, cmd, eq_addr: int = None):
        if eq_addr:
            self.select(eq_addr)
        self._send(cmd)

    def read(self, eq_addr: int = None, num_bytes=1024):
        if eq_addr:
            self.select(eq_addr)
        self._send("++read eoi")
        return self._recv(num_bytes)

    def query(self, cmd, eq_addr: int = None, buffer_size=1024 * 1024):
        if eq_addr:
            self.select(eq_addr)
        self.write(cmd)
        return self.read(num_bytes=buffer_size)

    def set_timeout(self, timeout):
        # see user manual for details on accepted timeout values
        # https://prologix.biz/downloads/PrologixGpibEthernetManual.pdf#page=13
        if timeout < 1e-3 or timeout > 3:
            raise ValueError("Timeout must be >= 1e-3 (1ms) and <= 3 (3s)")

        self.timeout = timeout
        self.socket.settimeout(self.timeout)

    def _send(self, value):
        encoded_value = ("%s\n" % value).encode("ascii")
        self.socket.send(encoded_value)

    def _recv(self, byte_num):
        value = self.socket.recv(byte_num)
        return value.decode("ascii")

    def _setup(self):
        # set device to CONTROLLER mode
        self._send("++mode 1")

        # disable read after write
        self._send("++auto 0")

        # set GPIB timeout
        self._send("++read_tmo_ms %i" % int(self.timeout * 1e3))

        # do not require CR or LF appended to GPIB data
        self._send("++eos 3")

    def __del__(self):
        self.close()


if __name__ == "__main__":
    print("IP address:")
    host = input()
    dev = PrologixEthernetAdapter(host=host)
    dev.connect()
    print("GPIB address:")
    gpib = int(input())
    dev.select(gpib)
    print(dev.query("*IDN?"))
