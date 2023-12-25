from .prologix import Prologix
from .socket_adapter import SocketAdapter
from store.adapterConfig import AdapterManager


class PrologixManager(AdapterManager):
    name = "Prologix ethernet"
