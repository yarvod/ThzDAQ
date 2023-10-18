from api.adapters.socket_adapter import SocketAdapter


class Sensor:
    def __init__(
        self,
        host: str = "169.254.0.53",
        port: int = 80,
    ):
        self.adapter = SocketAdapter(host=host, port=port, delay=0)

    def connect(self):
        self.adapter.connect()

    def read(self):
        return self.adapter.read()


if __name__ == "__main__":
    s = Sensor()
    s.connect()
    while 1:
        print(s.read())
