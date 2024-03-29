import logging
import sys
from typing import Tuple

from serial.tools.list_ports import main as list_ports

from api.adapters.http_adapter import HttpAdapter
from settings import ADAPTERS, HTTP, SERIAL
from store.state import state
from utils.functions import import_class

logger = logging.getLogger(__name__)


class GridManager:
    MAX_STEPS = 4000

    def __init__(
        self,
        host: str = state.GRID_ADDRESS,
        adapter: str = HTTP,
        *args,
        **kwargs,
    ):
        self.host = host
        self.adapter_name = adapter
        self.adapter = HttpAdapter(host=host)
        if self.adapter is None:
            self._set_adapter(adapter, *args, **kwargs)
        self.finish = False

    def _set_adapter(self, adapter: str, *args, **kwargs) -> None:
        adapter_path = ADAPTERS.get(adapter)
        try:
            adapter_class = import_class(adapter_path)
            self.adapter = adapter_class(host=self.host, *args, **kwargs)
        except (ImportError, ImportWarning) as e:
            logger.error(f"[{self.__class__.__name__}._set_adapter] {e}")

    def rotate(self, angle: float = 90, finish: bool = False) -> None:
        """Rotate method
        Params:
            angle: float - Angle in degrees
        """
        if self.finish:
            return

        angle_to_rotate = angle - float(state.GRID_ANGLE.val)
        if self.adapter_name == SERIAL:
            self.adapter.write(f"{angle}\n".encode())
        elif self.adapter_name == HTTP:
            self.adapter.post(url="/rotate", data={"angle": angle_to_rotate})
        state.GRID_ANGLE.val = str(angle)

        self.finish = finish

    def test(self) -> Tuple[bool, str]:
        """Simple test func"""
        if self.adapter_name == SERIAL:
            try:
                self.adapter.write(f"test\n".encode())
                response = self.adapter.readline().decode(encoding="utf-8").rstrip()
                return response == "OK", response
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}.test] {e}")
                return False, f"{e}"
        if self.adapter_name == HTTP:
            try:
                status, response = self.adapter.post(url="/test", data={})
                return status == 200, "Ok"
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}.test] {e.__str__()}")
                return False, f"Connection Error!"

    @staticmethod
    def scan_ports():
        list_ports()

    def __del__(self) -> None:
        self.adapter.close()


if __name__ == "__main__":
    angle = float(sys.argv[1])
    ard = GridManager()
    ard.rotate(angle)
