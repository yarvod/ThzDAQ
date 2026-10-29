"""The domain's devices, quantities and procedures as the contract describes them."""

from dataclasses import asdict
from typing import Type

from thzdaq_api import devices as api
from thzdaq_api import measurements
from thzdaq_instruments.quantities import Quantity

from thzdaq_core.domain.measurements.plots import PlotSpec
from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.parameters import Parameter
from thzdaq_core.domain.station.kinds import instrument_type
from thzdaq_core.domain.station.station import INSTRUMENT, CHANNEL, DeviceInfo, Station


def device_info(info: DeviceInfo, station: Station) -> api.DeviceInfo:
    configured = info.kind not in (INSTRUMENT, CHANNEL)
    driver = station.config.instruments[info.instrument].driver
    return api.DeviceInfo(
        ref=info.ref,
        title=info.title,
        instrument=info.instrument,
        kind=info.kind,
        type=info.kind if configured else instrument_type(driver, station.registry),
        capabilities=tuple(c.__name__ for c in info.capabilities),
        channel=None if info.channel is None else str(info.channel),
        configured=info.configured,
    )


def quantity_info(quantity: Quantity) -> api.QuantityInfo:
    return api.QuantityInfo(
        key=quantity.key,
        title=quantity.title,
        unit=quantity.unit,
        kind=quantity.kind,
        readable=quantity.readable,
        settable=quantity.settable,
        persistent=quantity.persistent,
        minimum=quantity.minimum,
        maximum=quantity.maximum,
        choices=tuple(str(c) for c in quantity.choices),
    )


def parameter_info(parameter: Parameter) -> measurements.ParameterInfo:
    return measurements.ParameterInfo(**parameter.describe())


def plot_info(spec: PlotSpec) -> measurements.PlotInfo:
    return measurements.PlotInfo(**asdict(spec))


def procedure_summary(cls: Type[Procedure]) -> measurements.ProcedureSummary:
    return measurements.ProcedureSummary(cls.name, cls.title, cls.description)


def procedure_info(procedure: Procedure) -> measurements.ProcedureInfo:
    """With the slots and plots its parameters give."""
    slots = tuple(
        measurements.SlotInfo(
            name=slot,
            title=procedure.slot_title(slot),
            capabilities=tuple(
                c.__name__ for c in (needs if isinstance(needs, tuple) else (needs,))
            ),
            kind=procedure.slot_kinds.get(slot),
        )
        for slot, needs in procedure.slots().items()
    )
    return measurements.ProcedureInfo(
        name=procedure.name,
        title=procedure.title,
        description=procedure.description,
        parameters=tuple(parameter_info(p) for p in procedure.parameters().values()),
        slots=slots,
        plots=tuple(plot_info(spec) for spec in procedure.plots),
    )
