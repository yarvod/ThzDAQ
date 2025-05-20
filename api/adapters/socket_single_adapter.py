from api.adapters.socket_adapter import SocketAdapter
from utils.classes import SocketMeta


class SocketSingleAdapter(SocketAdapter, metaclass=SocketMeta):
    __metaclass__ = SocketMeta
