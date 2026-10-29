"""Graphs of observed runs, independent of any procedure configuration form."""

from PySide6.QtCore import QObject


class RunGraphs(QObject):
    def __init__(self, session, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        session.run_events.observed.connect(self.follow)
        for model in session.run_events.external:
            self.follow(model)

    def follow(self, model) -> None:
        model.started.connect(lambda _: self.started(model))
        model.record.connect(
            lambda table, record: self.hub.feed(
                model.measurement, model.plots, table, record
            )
        )
        model.resetting.connect(self.hub.clear_measurement)
        if model.measurement is not None:
            self.started(model)
            self.hub.show_measurement(model.measurement, model.plots)

    def started(self, model) -> None:
        self.hub.register_plots(model.plots)
        self.hub.show_run([plot.title for plot in model.plots])
