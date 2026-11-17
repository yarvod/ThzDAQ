"""The system prompt of the assistant: its role and the rules (thzdaq_api.guides),
the person's instructions (they add to the rules, never replace them), then the
bench as it is now: the profile, the devices with their capabilities, the
connections, the procedures in short with their slots, and how a measurement
of the bench's own is written. It is made for each conversation and again when
the bench or the instructions change; details the model asks with its tools
(describe_device, describe_procedure)."""

from typing import Sequence

from thzdaq_api import guides, present
from thzdaq_api.devices import ListDevices
from thzdaq_api.errors import LabError
from thzdaq_api.measurements import DescribeProcedure, ListProcedures, ProcedureSummary
from thzdaq_api.station import GetStation, ListConnections
from thzdaq_api.tools import Reach

INSTRUCTIONS = "## The person's instructions"
INSTRUCTIONS_RANK = (
    "They add to the rules above; where they contradict them, the rules hold."
)
BENCH = "## The bench now"
PROCEDURES = "## Procedures"
SIMULATED = "simulated: the instruments are simulators, nothing real changes"
# Where the built-in prompt shown to the person has what each conversation makes
MADE_HERE = (
    "[Made for each conversation: the person's instructions, the bench now"
    " and the procedures]"
)


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


def instructions_section(instructions: str) -> str:
    """The person's instructions under their heading; empty without any."""
    text = instructions.strip()
    return f"{INSTRUCTIONS}\n\n{INSTRUCTIONS_RANK}\n\n{text}" if text else ""


def _joined(made: Sequence[str]) -> str:
    """The fixed parts in order with what a conversation made between them
    (an empty part left out)."""
    parts = (
        guides.guide(guides.ASSISTANT).strip(),
        guides.section(guides.AGENTS, guides.RULES),
        *made,
        guides.section(guides.AGENTS, guides.OWN_MEASUREMENT),
    )
    return "\n\n".join(part for part in parts if part)


def system_prompt(reach: Reach, instructions: str) -> str:
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
    return _joined(
        (instructions_section(instructions), "\n".join(bench), "\n".join(procedures))
    )


def built_in() -> str:
    """The built-in prompt as the person reads it: its fixed parts in order,
    one line where each conversation adds its own."""
    return _joined((MADE_HERE,))
