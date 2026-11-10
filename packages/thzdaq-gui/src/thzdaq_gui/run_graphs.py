"""Graphs of observed runs, independent of any procedure configuration form.
A plot drawn into a graph of the window (into) goes there when it can; why
it cannot goes to the log."""

import logging
from typing import Tuple

from PySide6.QtCore import QObject
from thzdaq_api.measurements import PlotInfo

logger = logging.getLogger(__name__)


class RunGraphs(QObject):
    def __init__(self, hub, chosen: Tuple[PlotInfo, ...] = (), parent=None):
        """chosen: plots drawn instead of the runs' own (a plot of one's own in
        the plots window)."""
        super().__init__(parent)
        self.hub = hub
        self.chosen = chosen

    def follow_all(self, run_events) -> None:
        """Every run the window observes: those already followed, and those to come."""
        run_events.observed.connect(self.follow)
        for model in run_events.external:
            self.follow(model)

    def follow(self, model) -> None:
        model.started.connect(lambda _: self.started(model))
        model.plotted.connect(lambda plot: self.plotted(plot))
        model.record.connect(
            lambda table, record: self.hub.feed(
                model.measurement, self.plots(model), table, record
            )
        )
        model.resetting.connect(self.hub.clear_measurement)
        if model.measurement is not None:
            self.started(model)
            self.hub.show_measurement(model.measurement, self.plots(model))

    def plots(self, model) -> Tuple[PlotInfo, ...]:
        return self.chosen or self.hub.route(model.plots, logger.info)

    def started(self, model) -> None:
        plots = self.plots(model)
        self.hub.register_plots(plots)
        self.hub.show_run([plot.title for plot in plots])

    def plotted(self, plot) -> None:
        """A plot the run added while it runs (a script's): on screen too,
        unless other plots were chosen."""
        if not self.chosen:
            routed = self.hub.route([plot], logger.info)
            self.hub.register_plots(routed)
            self.hub.show_run([spec.title for spec in routed])
