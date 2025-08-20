import logging
import sys

from serial.tools.list_ports import main as list_ports

from api.adapters.http_adapter import HttpAdapter
from settings import ADAPTERS, HTTP, SERIAL
from store.state import state
from utils.exceptions import DeviceConnectionError
from utils.functions import import_class

logger = logging.getLogger(__name__)


class GridDevice:
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

    def rotate(
        self, angle: float = 90, current_angle: float = 0, finish: bool = False
    ) -> None | float:
        """Rotate method
        Params:
            angle: float - Angle in degrees
        """
        if self.finish:
            return

        angle_to_rotate = angle - current_angle
        if self.adapter_name == SERIAL:
            self.adapter.write(f"{angle}\n".encode())
            return angle
        elif self.adapter_name == HTTP:
            status, _ = self.adapter.post(
                url="/rotate", data={"angle": angle_to_rotate}
            )
            if status == 200:
                return angle
        self.finish = finish

    def test(self) -> bool:
        """Simple test func"""
        if self.adapter_name == SERIAL:
            try:
                self.adapter.write(f"test\n".encode())
                response = self.adapter.readline().decode(encoding="utf-8").rstrip()
                return response == "OK"
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}.test] {e}")
                raise DeviceConnectionError(str(e))
        if self.adapter_name == HTTP:
            try:
                status, response = self.adapter.post(url="/test", data={})
                return status == 200
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}.test] {e.__str__()}")
                raise DeviceConnectionError(str(e))

    @staticmethod
    def scan_ports():
        list_ports()

    def __del__(self) -> None:
        self.adapter.close()


if __name__ == "__main__":
    angle = float(sys.argv[1])
    ard = GridDevice()
    ard.rotate(10, angle)
