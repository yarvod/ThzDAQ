"""The system prompt of the assistant: its role and the rules (thzdaq_api.guides),
then the bench as it is now: the profile, the devices with their capabilities,
the connections, the procedures in short with their slots, and how a
measurement of the bench's own is written. It is made for each conversation
and again when the bench changes; details the model asks with its tools
(describe_device, describe_procedure)."""

from thzdaq_api import guides, present
from thzdaq_api.devices import ListDevices
from thzdaq_api.errors import LabError
from thzdaq_api.measurements import DescribeProcedure, ListProcedures, ProcedureSummary
from thzdaq_api.station import GetStation, ListConnections
from thzdaq_api.tools import Reach

BENCH = "## The bench now"
PROCEDURES = "## Procedures"
SIMULATED = "simulated: the instruments are simulators, nothing real changes"


def procedure_line(reach: Reach, summary: ProcedureSummary) -> str:
    """name: title. what it measures (slots: ...), as its defaults go."""
    line = f"{summary.name}: {summary.title}. {summary.description}"
    if summary.error:
        return f"{line} Cannot run: {present.last_line(summary.error)}"
    try:
        info = reach.call(DescribeProcedure(procedure=summary.name))
    except LabError as e:
        return f"{line} Not described: {e}"
    slots = ", ".join(slot.name for slot in info.slots)
    return f"{line} Slots: {slots or present.NOTHING}."


def system_prompt(reach: Reach) -> str:
    """LabError when the daemon cannot be asked."""
    station = reach.call(GetStation())
    where = station.path or "not saved"
    simulated = f"; {SIMULATED}" if station.simulate else ""
    bench = [
        BENCH,
        f"Profile {station.name} ({where}){simulated}.",
        "Devices (ref: title (type on instrument; capabilities)):",
        present.devices(reach.call(ListDevices())),
        "Connections:",
        present.connections(reach.call(ListConnections())),
    ]
    procedures = [PROCEDURES] + [
        procedure_line(reach, p) for p in reach.call(ListProcedures())
    ]
    return "\n\n".join(
        (
            guides.guide(guides.ASSISTANT).strip(),
            guides.section(guides.AGENTS, guides.RULES),
            "\n".join(bench),
            "\n".join(procedures),
            guides.section(guides.AGENTS, guides.OWN_MEASUREMENT),
        )
    )
