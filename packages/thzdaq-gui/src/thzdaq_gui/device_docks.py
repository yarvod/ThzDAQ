"""Device docks: one per instrument and configured device with controls.

They follow the bench: a dock comes and goes with its device, and is rebuilt
only when what it is built from changes (the device and its description), so
its reads and settings survive the rest.
"""

import logging
from typing import Dict, List

import PySide6QtAds as QtAds
from PySide6.QtWidgets import QLabel, QWidget
from thzdaq_api.devices import CHANNEL, DeviceInfo
from thzdaq_api.errors import LabError

from thzdaq_gui import theme
from thzdaq_gui.dock_names import DEVICE, dock_name, key_of
from thzdaq_gui.docking import DockSpace
from thzdaq_gui.docks.body import DockBody
from thzdaq_gui.docks.devices import DeviceWidget, has_content
from thzdaq_gui.graphs import GraphHub
from thzdaq_gui.device_types import type_title

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

    def refs(self) -> List[DeviceInfo]:
        # Fixed channels live inside their instrument's dock; an instrument with
        # nothing to show (a SIS block: its parts are devices) gets no dock
        return [
            info
            for info in self.session.devices()
            if info.kind != CHANNEL and has_content(self.session, info)
        ]

    def signature(self, info: DeviceInfo) -> tuple:
        """What a device dock is built from; it is rebuilt only when this changes.

        The values a dock keeps in the profile (a multiplier, offsets) are not
        in it: the dock writes them itself and survives saving them.
        """
        return info, self.session.description(info.ref)

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
            factory = lambda info=info: self.widget(info)  # noqa: E731
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

    def group(self, info: DeviceInfo):
        """Branch of the menu (the type: SIS bias, Power supply) and words to search."""
        return type_title(info.type), f"{info.ref} {info.instrument} {info.driver}"

    def widget(self, info: DeviceInfo) -> QWidget:
        try:
            return DeviceWidget(self.session, self.hub, info)
        except LabError as e:
            logger.error(f"Device dock {info.ref}: {e}")
            label = QLabel(f"{info.ref}: {e}")
            label.setWordWrap(True)
            return label

    def default_docks(self) -> List[str]:
        return [
            dock_name(DEVICE, info.ref)
            for info in self.refs()
            if info.kind in DEFAULT_KINDS
        ]
