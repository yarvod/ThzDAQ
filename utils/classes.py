import threading


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


lock = threading.Lock()


class SingletonSafe(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super(SingletonSafe, cls).__call__(
                        *args, **kwargs
                    )
        return cls._instances[cls]


class BaseInstrumentInterface:
    """Base Instrument Api interface"""

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def __del__(self):
        raise NotImplementedError
