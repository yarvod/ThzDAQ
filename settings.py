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
