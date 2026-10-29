"""The domain's devices and quantities as the contract describes them."""

from thzdaq_api import devices as api
from thzdaq_instruments.quantities import Quantity

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
