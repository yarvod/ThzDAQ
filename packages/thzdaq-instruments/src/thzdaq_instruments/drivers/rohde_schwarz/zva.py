import logging
import time
from typing import Dict, Literal, Tuple

from thzdaq_instruments.errors import InstrumentResponseError
from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.readings import ComplexTrace, linspace
from thzdaq_instruments.transport.base import SOCKET, ConnectionSpec

logger = logging.getLogger(__name__)

DataFormat = Literal["COMP", "MLOG", "MLIN", "PHAS", "REAL", "IMAG"]


class RohdeSchwarzZVA67(ScpiInstrument):
    """R&S ZVA67 vector network analyzer: NetworkAnalyzer, PowerLevel."""

    @staticmethod
    def connection(host: str = "169.254.106.189", port: int = 5025) -> ConnectionSpec:
        return ConnectionSpec(SOCKET, host=host, port=port)

    def test(self) -> bool:
        return "Rohde&Schwarz,ZVA67" in self.identify()

    def set_points(self, points: int) -> None:
        self.write(f"SWE:POIN {int(points)}")

    def get_points(self) -> int:
        return self.query_int("SWE:POIN?")

    def set_frequency_range(self, start: float, stop: float) -> None:
        self.write(f"SENS:FREQ:STAR {start}")
        self.write(f"SENS:FREQ:STOP {stop}")

    def get_frequency_range(self) -> Tuple[float, float]:
        return self.query_float("SENS:FREQ:STAR?"), self.query_float("SENS:FREQ:STOP?")

    def set_power(self, power: float) -> None:
        self.write(f"SOUR:POW {power}")

    def get_power(self) -> float:
        return self.query_float("SOUR:POW?")

    def set_averaging(self, count: int, channel: int = 1) -> None:
        """Sweep averaging, count <= 1 switches it off."""
        if count > 1:
            self.write(f"SENS{channel}:AVER:COUN {int(count)}")
            self.write(f"SENS{channel}:AVER ON")
        else:
            self.write(f"SENS{channel}:AVER OFF")

    def set_format(self, data_format: DataFormat = "COMP") -> None:
        self.write(f"CALC:FORM {data_format}")

    def get_format(self) -> str:
        return self.query("CALC:FORM?")

    def define_parameter(
        self, parameter: str = "S11", trace: str = "Trc1", channel: int = 1
    ) -> None:
        self.write(f"CALC{channel}:PAR:DEF {trace},{parameter}")

    def select_parameter(self, parameter: str, channel: int = 1) -> None:
        """Measure `parameter` on trace Trc1 as complex data."""
        with self.transport.transaction():
            self.define_parameter(parameter, "Trc1", channel)
            self.set_format("COMP")

    def parameter_catalog(self, channel: int = 1) -> Dict[str, str]:
        """{"Trc1": "S11", ...}"""
        items = self.query(f"CALC{channel}:PAR:CAT?").replace("'", "").split(",")
        return dict(zip(items[::2], items[1::2]))

    def read_trace(
        self, channel: int = 1, attempts: int = 5, retry_delay: float = 0.05
    ) -> ComplexTrace:
        """Formatted trace in COMP format: real/imaginary pairs."""
        points = self.get_points()
        start, stop = self.get_frequency_range()
        catalog = self.parameter_catalog(channel)
        parameter = next(iter(catalog.values()), "")
        for attempt in range(1, attempts + 1):
            response = self.query(f"CALC{channel}:DATA? FDAT")
            try:
                values = [float(v) for v in response.split(",")]
            except ValueError:
                logger.warning(f"[{self.name}] unparsable trace, attempt {attempt}")
                time.sleep(retry_delay)
                continue
            # The analyzer answers zeros before the first sweep completes
            if len(values) == 2 * points and any(values):
                return ComplexTrace(
                    frequency=tuple(linspace(start, stop, points)),
                    values=tuple(
                        complex(r, i) for r, i in zip(values[::2], values[1::2])
                    ),
                    parameter=parameter,
                )
            time.sleep(retry_delay)
        raise InstrumentResponseError(
            f"{self.name}: no valid trace in {attempts} attempts"
        )
