from typing import Literal, Tuple

from thzdaq_instruments.instrument import ScpiInstrument
from thzdaq_instruments.readings import Trace, linspace
from thzdaq_instruments.transport.base import PROLOGIX, ConnectionSpec

# Bandwidths the FSEK accepts, Hz
BANDWIDTHS = tuple(
    v * 1e3
    for v in (
        1e-3, 2e-3, 3e-3, 5e-3, 1e-2, 2e-2, 3e-2, 5e-2, 1e-1, 2e-1, 3e-1, 5e-1,
        1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1e3, 2e3, 5e3, 10e3,
    )
)  # fmt: skip

AverageMode = Literal["LIN", "LOG", "POW"]


def nearest_bandwidth(bandwidth: float) -> float:
    return min(BANDWIDTHS, key=lambda value: abs(value - bandwidth))


class RohdeSchwarzFSEK30(ScpiInstrument):
    """R&S FSEK30 spectrum analyzer, usually GPIB behind Prologix: SpectrumAnalyzer."""

    @staticmethod
    def connection(host: str = "169.254.156.103", gpib: int = 20) -> ConnectionSpec:
        return ConnectionSpec(PROLOGIX, host=host, gpib=gpib, read_delay=0.01)

    def test(self) -> bool:
        return "Rohde" in self.identify()

    def reset(self) -> None:
        self.write("*RST")

    # Frequency axis
    def set_center_frequency(self, frequency: float) -> None:
        self.write(f":FREQ:CENT {frequency}Hz")

    def get_center_frequency(self) -> float:
        return self.query_float(":FREQ:CENT?")

    def set_span(self, span: float) -> None:
        self.write(f":FREQ:SPAN {span}Hz")

    def get_span(self) -> float:
        return self.query_float(":FREQ:SPAN?")

    def set_frequency_range(self, start: float, stop: float) -> None:
        self.write(f":FREQ:STAR {start}Hz")
        self.write(f":FREQ:STOP {stop}Hz")

    def get_frequency_range(self) -> Tuple[float, float]:
        return self.query_float(":FREQ:STAR?"), self.query_float(":FREQ:STOP?")

    # Bandwidths
    def set_resolution_bandwidth(self, bandwidth: float) -> None:
        self.write(f":BAND:RES {nearest_bandwidth(bandwidth)}Hz")

    def set_video_bandwidth(self, bandwidth: float) -> None:
        self.write(f":BAND:VID {nearest_bandwidth(bandwidth)}Hz")

    def set_video_bandwidth_auto(self, value: bool) -> None:
        # The legacy driver queried this setting command and waited for a reply
        self.write(f":BAND:VID:AUTO {'ON' if value else 'OFF'}")

    def set_average_mode(self, mode: AverageMode) -> None:
        self.write(f"AVER:TYPE {mode}")

    # Sweep
    def set_continuous_sweep(self, value: bool) -> None:
        self.write(f":INIT:CONT {'ON' if value else 'OFF'}")

    def get_continuous_sweep(self) -> bool:
        return self.query_bool(":INIT:CONT?")

    def trigger(self) -> None:
        self.write(":INIT")

    # Readout
    def peak_search(self) -> None:
        self.write("CALC:MARK:MAX")

    def read_marker(self) -> Tuple[float, float]:
        """(frequency Hz, level dBm) of marker 1"""
        with self.transport.transaction():
            return self.query_float("CALC:MARK:X?"), self.query_float("CALC:MARK:Y?")

    def read_peak(self) -> Tuple[float, float]:
        with self.transport.transaction():
            self.peak_search()
            return self.read_marker()

    def read_trace(self, trace: str = "TRACE1") -> Trace:
        start, stop = self.get_frequency_range()
        raw = self.query(f":TRAC:DATA? {trace}").split(",")
        frequency = linspace(start, stop, len(raw))
        points = []
        for f, value in zip(frequency, raw):
            try:
                points.append((f, float(value)))
            except ValueError:
                continue
        return Trace(
            frequency=tuple(f for f, _ in points), values=tuple(v for _, v in points)
        )
