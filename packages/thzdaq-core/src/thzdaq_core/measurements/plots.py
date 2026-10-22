"""What a procedure wants to show, independent of any plotting library."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Tuple

PlotKind = Literal["line", "scatter", "map"]
GroupKey = Tuple[Any, ...]


@dataclass(frozen=True)
class PlotSpec:
    """A plot of records of one table.

    Values in records are SI; x_scale / y_scale convert them for display
    (value / scale), e.g. x_scale=1e9 shows Hz as GHz. Records with different
    values of `group_by` keys form separate curves. kind="map" draws z over x/y.
    """

    key: str
    title: str
    table: str
    x: str
    y: str
    x_label: str = ""
    y_label: str = ""
    x_scale: float = 1.0
    y_scale: float = 1.0
    group_by: Tuple[str, ...] = ()
    kind: PlotKind = "line"
    z: Optional[str] = None
    z_label: str = ""
    z_scale: float = 1.0
    # Optional analysis a viewer may offer on this plot, e.g. "iv" (Rn, Rj, gap)
    analysis: Optional[str] = None

    def group_key(self, record: Mapping[str, Any]) -> GroupKey:
        return tuple(record.get(key) for key in self.group_by)

    def label(self, group: GroupKey) -> str:
        return " ".join(f"{value}" for value in group if value is not None)

    def point(self, record: Mapping[str, Any]) -> Optional[Tuple[float, ...]]:
        """Display coordinates of a record, None when a value is missing."""
        keys = (self.x, self.y) + ((self.z,) if self.kind == "map" else ())
        scales = (self.x_scale, self.y_scale) + (
            (self.z_scale,) if self.kind == "map" else ()
        )
        values = []
        for key, scale in zip(keys, scales):
            value = record.get(key)
            if value is None:
                return None
            values.append(value / scale)
        return tuple(values)

    def curves(
        self, records: Iterable[Mapping[str, Any]]
    ) -> Dict[GroupKey, List[Tuple[float, ...]]]:
        """Points per group in record order."""
        result: Dict[GroupKey, List[Tuple[float, ...]]] = {}
        for record in records:
            point = self.point(record)
            if point is not None:
                result.setdefault(self.group_key(record), []).append(point)
        return result
