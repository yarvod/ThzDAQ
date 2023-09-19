SOCKET = "SOCKET"
PROLOGIX_ETHERNET = "PROLOGIX_ETHERNET"
HTTP = "HTTP"
SERIAL = "SERIAL"

ADAPTERS = {
    SOCKET: "api.adapters.socket_adapter.SocketAdapter",
    PROLOGIX_ETHERNET: "api.adapters.prologix_ethernet_adapter.PrologixEthernetAdapter",
    HTTP: "api.adapters.http_adapter.HttpAdapter",
    SERIAL: "serial.Serial",
}


WAVESHARE_ETHERNET = "WaveShare Ethernet"
SERIAL_USB = "Serial Usb"


class GridPlotTypes:
    IV_CURVE = 0
    PV_CURVE = 1

    CHOICES = [
        "I-V curve",
        "P-V curve",
    ]


NOT_INITIALIZED = "Doesn't initialized yet!"
