"""Device docks: one per instrument and configured device with controls.

They follow the station: a dock comes and goes with its device, and is
rebuilt only when what it is built from changes (an edited profile), so its
reads and settings survive the rest.
"""

import logging
from typing import Dict, List

import PySide6QtAds as QtAds
from PySide6.QtWidgets import QLabel, QWidget
from thzdaq_instruments import InstrumentError

from thzdaq_gui import theme
from thzdaq_gui.dock_names import DEVICE, dock_name, key_of
from thzdaq_gui.docking import DockSpace
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.docks.devices import DeviceWidget, has_content
from thzdaq_gui.graphs import GraphHub
from thzdaq_gui.navigator import instrument_type, type_title

logger = logging.getLogger(__name__)

DEFAULT_KINDS = ("sis_bias", "sis_coil")  # below the graphs in a default layout


class DeviceDocks:
    def __init__(self, session, hub: GraphHub, docks: DockSpace):
        self.session = session
        self.hub = hub
        self.docks = docks
        self.signatures: Dict[str, tuple] = {}  # dock name -> what it is built from
        session.config_changed.connect(self.sync)
        session.station_changed.connect(self.rebuild)

    def refs(self):
        station = self.session.station
        if station is None:
            return []
        # Fixed channels live inside their instrument's dock; an instrument with
        # nothing to show (a SIS block: its parts are devices) gets no dock
        return [
            info
            for info in station.devices()
            if info.kind != "channel" and has_content(station, info)
        ]

    def signature(self, info) -> tuple:
        """What a device dock is built from; it is rebuilt only when this changes.

        Instrument settings (multiplier, OEM head) are left out: the dock writes
        them itself and must survive saving them.
        """
        station = self.session.station
        spec = station.config.instruments[info.instrument]
        found = station.config.find_device(info.ref)
        device = found[1] if found else None
        return (
            info,
            spec.driver,
            spec.title,
            spec.simulate or self.session.simulate,
            repr(device),
        )

    def rebuild(self, *_) -> None:
        """Another Station: every dock is rebuilt."""
        self.signatures.clear()
        self.sync()

    def sync(self, *_) -> None:
        wanted = {dock_name(DEVICE, info.ref): info for info in self.refs()}
        for name in [n for n in self.docks if key_of(n, DEVICE) and n not in wanted]:
            self.docks.remove(name)
            self.signatures.pop(name, None)
        for name, info in wanted.items():
            signature = self.signature(info)
            dock = self.docks.get(name)
            if dock is not None and self.signatures.get(name) == signature:
                continue
            factory = lambda ref=info.ref: self.widget(ref)  # noqa: E731
            self.signatures[name] = signature
            icon = theme.device_icon(info.kind, info.instrument)
            group, hint = self.group(info)
            if dock is None:
                dock = self.docks.add(
                    name,
                    info.title,
                    DockBody(factory),
                    "Devices",
                    icon,
                    QtAds.LeftDockWidgetArea,
                    group=group,
                    hint=hint,
                )
                dock.toggleView(False)
            else:
                dock.widget().replace(factory)
                self.docks.retitle(name, info.title)
                entry = self.docks.entries[name]
                entry.icon, entry.group, entry.hint = icon, group, hint

    def group(self, info):
        """Branch of the menu (the type: SIS bias, Power supply) and words to search."""
        spec = self.session.station.config.instruments[info.instrument]
        key = (
            info.kind if info.kind != "instrument" else instrument_type(info.instrument)
        )
        return type_title(key), f"{info.ref} {info.instrument} {spec.driver}"

    def widget(self, ref: str) -> QWidget:
        try:
            return DeviceWidget(self.session, self.hub, ref)
        except (InstrumentError, KeyError) as e:
            logger.error(f"Device dock {ref}: {e}")
            label = QLabel(f"{ref}: {e}")
            label.setWordWrap(True)
            return label

    def default_docks(self) -> List[str]:
        return [
            dock_name(DEVICE, info.ref)
            for info in self.refs()
            if info.kind in DEFAULT_KINDS
        ]
