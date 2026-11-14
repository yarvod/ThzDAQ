"""The domain's devices, quantities and procedures as the contract describes them."""

import math
from dataclasses import fields
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple, Type

from thzdaq_api import devices as api
from thzdaq_api import measurements, station as station_api
from thzdaq_api.measurement_file import Column, Table
from thzdaq_instruments.actions import Action, Argument
from thzdaq_instruments.errors import ConfigurationError
from thzdaq_instruments.quantities import Quantity
from thzdaq_instruments.readings import ComplexTrace, Trace
from thzdaq_instruments.registry import DriverInfo as Driver
from thzdaq_instruments.transport.base import (
    KIND_FIELDS,
    KIND_TITLES,
    KINDS,
    ConnectionSpec,
)
from thzdaq_instruments.units import prefixes_for

from thzdaq_core.domain.measurements.procedure import Procedure
from thzdaq_core.domain.parameters import Parameter
from thzdaq_core.domain.station.kinds import instrument_type, kinds_for
from thzdaq_core.domain.station.profile import connection_to_dict
from thzdaq_core.domain.station.safety import Guard, SafetyLimit
from thzdaq_core.domain.station.station import ConnectionInfo, DeviceInfo, Station


def device_info(info: DeviceInfo, station: Station) -> api.DeviceInfo:
    configured = info.kind not in (api.INSTRUMENT, api.CHANNEL)
    driver = station.config.instruments[info.instrument].driver
    return api.DeviceInfo(
        ref=info.ref,
        title=info.title,
        instrument=info.instrument,
        driver=driver,
        kind=info.kind,
        type=info.kind if configured else instrument_type(driver, station.registry),
        capabilities=tuple(c.__name__ for c in info.capabilities),
        channel=None if info.channel is None else str(info.channel),
        configured=info.configured,
        raw=station.takes_raw(info.instrument),
    )


def prefixes(unit: str) -> Tuple[api.Prefix, ...]:
    """The SI prefixes a value of this unit is shown in."""
    return tuple(api.Prefix(*prefix) for prefix in prefixes_for(unit))


def quantity_info(quantity: Quantity, guard: Guard) -> api.QuantityInfo:
    """A quantity as a device takes it: with its limits and how it changes."""
    taken = guard.range(quantity)
    bench = guard.bench.get(quantity.key, SafetyLimit())
    return api.QuantityInfo(
        key=quantity.key,
        title=quantity.title,
        unit=quantity.unit,
        kind=quantity.kind,
        readable=quantity.readable,
        settable=quantity.settable,
        persistent=quantity.persistent,
        minimum=taken.minimum,
        maximum=taken.maximum,
        choices=tuple(str(c) for c in quantity.choices),
        warn_minimum=bench.warn_minimum,
        warn_maximum=bench.warn_maximum,
        step=bench.step,
        rate=bench.rate,
        danger=quantity.danger,
        prefixes=prefixes(quantity.unit),
    )


def setting_info(setting: Parameter) -> api.QuantityInfo:
    """A setting a configured device keeps in the profile, described as a
    value of the device: neither read from it nor set on it."""
    described = parameter_info(setting)
    return api.QuantityInfo(
        key=described.name,
        title=described.label,
        unit=described.unit,
        kind=described.kind,
        readable=False,
        persistent=True,
        minimum=described.minimum,
        maximum=described.maximum,
        prefixes=prefixes(described.unit),
    )


def argument_info(argument: Argument) -> api.ArgumentInfo:
    return api.ArgumentInfo(
        key=argument.key,
        title=argument.title,
        unit=argument.unit,
        kind=argument.kind,
        default=argument.default,
        minimum=argument.minimum,
        maximum=argument.maximum,
        choices=tuple(str(c) for c in argument.choices),
        prefixes=prefixes(argument.unit),
    )


def action_info(action: Action) -> api.ActionInfo:
    return api.ActionInfo(
        key=action.key,
        title=action.title,
        arguments=tuple(argument_info(a) for a in action.arguments),
        danger=action.danger,
        changes=action.changes,
        help=action.help,
    )


def action_result(result: Any) -> Any:
    """What an action returned, as the contract carries it: a trace as Trace,
    a value as it is."""
    if isinstance(result, ComplexTrace):
        return api.Trace(
            frequency=tuple(result.frequency),
            values=tuple(v.real for v in result.values),
            imaginary=tuple(v.imag for v in result.values),
            parameter=result.parameter,
        )
    if isinstance(result, Trace):
        return api.Trace(tuple(result.frequency), tuple(result.values))
    return result


def parameter_info(
    parameter: Parameter, procedure: Optional[Type[Procedure]] = None
) -> measurements.ParameterInfo:
    """As the contract describes it; of a procedure, with what it is shown under."""
    conditions = procedure.conditions().get(parameter.name, ()) if procedure else ()
    parameters = procedure.parameters() if procedure else {}
    return measurements.ParameterInfo(
        **parameter.describe(),
        shown_if=tuple(
            measurements.Condition(
                condition.parameter,
                tuple(
                    parameters[condition.parameter].to_json(value)
                    for value in condition.values
                ),
            )
            for condition in conditions
        ),
    )


def procedure_summary(cls: Type[Procedure]) -> measurements.ProcedureSummary:
    return measurements.ProcedureSummary(
        cls.name, cls.title, cls.description, tuple(cls.plots)
    )


def procedure_info(
    procedure: Procedure,
    quantities: Optional[Callable[[str], Iterable[Quantity]]] = None,
) -> measurements.ProcedureInfo:
    """As a run with its parameters goes; quantities(slot) lists what the
    device in a slot reads (a monitor's plots follow them), None: every plot."""
    slots = tuple(
        measurements.SlotInfo(
            name=slot,
            title=procedure.slot_title(slot),
            capabilities=tuple(
                c.__name__
                for c in (needs if isinstance(needs, tuple) else (needs,))
                if c is not object  # any device: what a monitor watches
            ),
            kind=procedure.slot_kinds.get(slot),
        )
        for slot, needs in procedure.slots().items()
    )
    return measurements.ProcedureInfo(
        name=procedure.name,
        title=procedure.title,
        description=procedure.description,
        parameters=tuple(
            parameter_info(p, type(procedure)) for p in procedure.parameters().values()
        ),
        slots=slots,
        plots=tuple(procedure.active_plots(quantities)),
        steps=procedure.estimate_steps(),
        plot_window=procedure.plot_window(),
        guide=procedure.guide,
    )


def column_summary(column: Column, values: Sequence[Any]) -> measurements.ColumnSummary:
    numbers = [
        value
        for value in values
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ]
    return measurements.ColumnSummary(
        key=column.key,
        title=column.title,
        unit=column.unit,
        minimum=min(numbers, default=None),
        maximum=max(numbers, default=None),
        prefixes=prefixes(column.unit),
    )


def table_summary(table: Table, records: int) -> measurements.TableSummary:
    """Its first records (those published), each column by its range."""
    return measurements.TableSummary(
        name=table.name,
        title=table.title,
        records=records,
        columns=tuple(
            column_summary(column, table.data.get(column.key, [])[:records])
            for column in list(table.columns)  # a run may add one meanwhile
        ),
    )


def measurement_summary(
    run: measurements.RunInfo,
    tables: Tuple[measurements.TableSummary, ...],
    results: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> measurements.MeasurementSummary:
    """Results as single values; a list (a fitted curve) only by its length."""
    given = dict(results)  # the run's thread may add one meanwhile
    single = (bool, int, float, str)
    return measurements.MeasurementSummary(
        run=run,
        tables=tables,
        parameters=dict(parameters),
        results={k: v for k, v in given.items() if isinstance(v, single)},
        series={
            k: len(v)
            for k, v in given.items()
            if isinstance(v, (list, tuple)) and not isinstance(v, single)
        },
    )


def driver_info(driver: Driver) -> station_api.DriverInfo:
    cls = driver.cls
    recommended = getattr(cls, "connection", None)
    try:  # drivers that open a connection recommend one; others have none
        connection = connection_to_dict(recommended()) if recommended else None
    except (TypeError, ConfigurationError):  # it needs a port or an address
        connection = None
    return station_api.DriverInfo(
        key=driver.key,
        title=driver.title,
        type=driver.device_type,
        capabilities=tuple(c.__name__ for c in driver.capabilities),
        simulated=driver.simulated,
        kinds=tuple(
            station_api.DeviceKindInfo(
                key=kind.key,
                title=kind.title,
                settings=tuple(parameter_info(p) for p in kind.settings),
                needs_channel=kind.needs_channel,
                channels=tuple(str(k) for k in kind.keys),
            )
            for kind in kinds_for(cls).values()
        ),
        channels=tuple(str(k) for k in cls.fixed_channels()),
        connection=connection,
    )


def connection_kinds() -> Tuple[station_api.ConnectionKindInfo, ...]:
    defaults = {f.name: f.default for f in fields(ConnectionSpec)}
    return tuple(
        station_api.ConnectionKindInfo(
            key=kind,
            title=KIND_TITLES[kind],
            fields=KIND_FIELDS[kind],
            defaults={name: defaults[name] for name in KIND_FIELDS[kind]},
        )
        for kind in KINDS
    )


def connection_info(connection: ConnectionInfo) -> station_api.ConnectionInfo:
    return station_api.ConnectionInfo(
        key=tuple(connection.key),
        label=connection.label,
        instruments=connection.instruments,
        open=connection.open,
        broken=connection.broken,
    )
