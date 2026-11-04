"""The windows a client opens apart from itself, each a program of its own:
the main window in a workspace (thzdaq gui, m.show("gui")), and the plots
window of one measurement (thzdaq plot, lab.plot, run.show, m.show), which
draws only its plots: a measurement of the daemon, followed by its events
while it runs, or a measurement file.

Their options are named here, for the commands that start them and for the
window program that reads them (thzdaq_gui.app).
"""

import argparse
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import msgspec

from thzdaq_api import host
from thzdaq_api.daemon import GetDaemonStatus
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.measurement_file import (
    Column,
    Measurement,
    column_for,
    read_measurement,
)
from thzdaq_api.measurements import (
    ListProcedures,
    PlotInfo,
    ProcedureSummary,
    WaitMeasurement,
    saved_plots,
)
from thzdaq_api.origins import GUI

WORKSPACE = "--workspace"  # the folder of the main window
PLOT = "--plot"  # only the plots of a measurement: its number, or its file
TABLE, X, Y, GROUP = "--table", "--x", "--y", "--group"  # a plot of one's own
WHICH = "ID|FILE"
WHICH_HELP = "a measurement: its number in the daemon, or its file"
OWN = "own"  # the key of a plot of one's own

# A measurement as people name it: its number in the daemon, or its file
Which = Union[int, str]
Call = Callable[..., object]  # a lab's (or a command line's) call of an operation


def which(text: str) -> Which:
    """A number names a measurement of the daemon, anything else a file."""
    return int(text) if text.isdigit() else text


class OwnPlot(msgspec.Struct, frozen=True):
    """A plot one asks for by a table and its columns: the plots window draws
    it instead of the measurement's own."""

    table: str
    x: str
    y: str
    group_by: Tuple[str, ...] = ()  # a curve for each of their values

    @classmethod
    def asked(
        cls,
        table: Optional[str] = None,
        x: Optional[str] = None,
        y: Optional[str] = None,
        group_by: Sequence[str] = (),
    ) -> Optional["OwnPlot"]:
        """The plot asked for, None when none is; LabError for a part of one."""
        if table is None and x is None and y is None and not group_by:
            return None
        if not (table and x and y):
            raise LabError(
                ErrorCode.INVALID_ARGUMENTS,
                "A plot of one's own names its table, x and y",
                f"{TABLE} pv {X} voltage {Y} power [{GROUP} angle]",
            )
        return cls(table, x, y, tuple(group_by))

    @classmethod
    def of(cls, arguments: argparse.Namespace) -> Optional["OwnPlot"]:
        """The plot the options of add_options name."""
        return cls.asked(arguments.table, arguments.x, arguments.y, arguments.group)

    def arguments(self) -> List[str]:
        """As the window program's options name it."""
        told = [TABLE, self.table, X, self.x, Y, self.y]
        for key in self.group_by:
            told += [GROUP, key]
        return told

    def plot(self, columns: Mapping[str, Column]) -> PlotInfo:
        """As drawn: axes labelled by the measurement's columns (by their keys
        while it has none of them yet)."""
        x, y = (column_for(key, columns) for key in (self.x, self.y))
        return PlotInfo(
            key=OWN, title=f"{y.title} – {x.title}", table=self.table, x=self.x,
            y=self.y, x_label=x.label, y_label=y.label, group_by=self.group_by,
        )  # fmt: skip


def add_options(parser: argparse.ArgumentParser) -> None:
    """The options of a plot of one's own, for a command that opens the plots
    window and for the window program."""
    parser.add_argument(TABLE, help="a plot of one's own: its table (with --x, --y)")
    parser.add_argument(X, help="the column along x")
    parser.add_argument(Y, help="the column along y")
    parser.add_argument(
        GROUP, action="append", default=[], metavar="COLUMN",
        help="a curve for each value of this column (repeat for several)",
    )  # fmt: skip


def read_file(path: Union[str, Path]) -> Measurement:
    """A measurement file; LabError NOT_FOUND when there is none there."""
    try:
        return read_measurement(path)
    except ValueError as e:
        raise LabError(ErrorCode.NOT_FOUND, str(e)) from None


def file_plots(
    measurement: Measurement,
    procedures: Iterable[ProcedureSummary],
    own: Optional[OwnPlot] = None,
) -> Tuple[PlotInfo, ...]:
    """The plots a measurement file is drawn with: one's own, else those it
    was made with; LabError NOT_FOUND when there is none to draw."""
    if own is None:
        plots = saved_plots(measurement, procedures)
        if not plots:
            raise LabError(
                ErrorCode.NOT_FOUND,
                f"#{measurement.id} has no plots to draw",
                f"name one: {TABLE}, {X} and {Y}",
            )
        return plots
    table = measurement.tables.get(own.table)
    if table is None:
        raise LabError(
            ErrorCode.NOT_FOUND,
            f"#{measurement.id} has no table {own.table!r}",
            f"it has: {', '.join(measurement.tables) or 'none'}",
        )
    return (own.plot({column.key: column for column in table.columns}),)


def plot_command(
    measurement: Which, simulate: bool = False, own: Optional[OwnPlot] = None
) -> List[str]:
    """How the plots window of a measurement starts."""
    named = measurement if isinstance(measurement, int) else Path(measurement).resolve()
    command = host.window_command() + [PLOT, str(named)]
    if own is not None:
        command += own.arguments()
    if simulate:
        command.append(host.SIMULATE)
    return command


def open_plots(
    call: Call,
    measurement: Which,
    simulate: bool = False,
    own: Optional[OwnPlot] = None,
) -> List[str]:
    """Open the plots window of a measurement apart from this process, once the
    daemon knows it (a number) or its file is read and has a plot to draw;
    LabError NOT_FOUND otherwise. Returns how the window started."""
    command = plot_command(measurement, simulate, own)
    if isinstance(measurement, int):
        call(WaitMeasurement(id=measurement, timeout=0))
    else:
        file_plots(read_file(measurement), call(ListProcedures()), own)
    host.start_apart(command)
    return command


def gui_command(workspace: Optional[Path] = None, simulate: bool = False) -> List[str]:
    """How the main window starts in a workspace (None: its default one)."""
    command = host.window_command()
    if workspace is not None:
        command += [WORKSPACE, str(workspace)]
    if simulate:
        command.append(host.SIMULATE)
    return command


def window_open(call: Call) -> bool:
    """A main window listens to the daemon: the measurements running come on
    screen there by themselves."""
    return any(client.kind == GUI for client in call(GetDaemonStatus()).clients)
