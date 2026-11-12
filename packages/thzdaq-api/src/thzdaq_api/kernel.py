"""The kernel of a console of the window: IPython's kernel (ipykernel) that
completes the bench, run as a program with the scripts' Python:

    python -m thzdaq_api.kernel -f <connection file>

It runs only where ipykernel is (the window's Python, a build), started by the
window (thzdaq_api.console). Any Jupyter kernel completes the same after
%load_ext thzdaq_api.kernel.

IPython completes live objects itself: lab["…"] by the devices' refs
(Bench._ipython_key_completions_), the attributes of a device by its __dir__.
Its matchers here say more, as the completion's type: after the dot of a
device its quantities with their units and limits and its actions with their
arguments, and in lab.run("…") the names of the procedures. Completion never
reads a quantity: a device is described, not looked at.
"""

import re
from typing import Any, Dict, List, Optional

from ipykernel.kernelapp import IPKernelApp
from IPython.core.completer import CompletionContext, SimpleCompletion, context_matcher

from thzdaq_api.devices import ActionInfo, QuantityInfo, shown
from thzdaq_api.errors import LabError
from thzdaq_api.lab import Bench, Device

# bias.vol| or lab["sis_bias_1"].vol| (the cursor at |)
ATTRIBUTE = re.compile(
    r"""(?P<name>[A-Za-z_]\w*)(?:\[\s*(?P<quote>["'])(?P<ref>[^"']+)(?P=quote)\s*\])?"""
    r"""\.(?P<typed>\w*)$"""
)
# lab.run("sis.cur| or lab.start('...
PROCEDURE = re.compile(
    r"""(?P<name>[A-Za-z_]\w*)\.(?:run|start)\(\s*["'](?P<typed>[\w.]*)$"""
)
QUANTITY, ACTION, PROCEDURE_TYPE = "quantity", "action", "procedure"


def quantity_hint(quantity: QuantityInfo) -> str:
    """What a quantity is, as its completion says: its unit, the range it
    takes, or that it is only read."""
    unit = quantity.unit or quantity.kind
    if not quantity.settable:
        return f"{QUANTITY}, {unit}, read only"
    if quantity.minimum is None or quantity.maximum is None:
        return f"{QUANTITY}, {unit}"
    low = shown(quantity.minimum, quantity.unit, quantity.prefixes)
    high = shown(quantity.maximum, quantity.unit, quantity.prefixes)
    return f"{QUANTITY}, {unit}, {low} … {high}"


def action_hint(action: ActionInfo) -> str:
    arguments = ", ".join(a.key for a in action.arguments)
    return f"{ACTION}({arguments})" + (f": {action.danger}" if action.danger else "")


class BenchCompletions:
    """The bench's matchers of a shell: they look its names up, never run code."""

    def __init__(self, shell):
        self.shell = shell

    def named(self, name: str, ref: Optional[str]) -> Any:
        """The object a name of the shell is (lab["ref"]: that device)."""
        found = self.shell.user_ns.get(name)
        if ref is None:
            return found
        return found[ref] if isinstance(found, Bench) else None

    def device(self, context: CompletionContext) -> Dict[str, Any]:
        typed = ATTRIBUTE.search(context.text_until_cursor)
        found = None if typed is None else self.named(typed["name"], typed["ref"])
        if not isinstance(found, Device):
            return {"completions": []}
        try:
            described = found.describe()
        except LabError:  # the daemon does not answer: nothing of the bench to offer
            return {"completions": []}
        completions: List[SimpleCompletion] = [
            SimpleCompletion(q.key, type=quantity_hint(q)) for q in described.quantities
        ]
        completions += [
            SimpleCompletion(a.key, type=action_hint(a)) for a in described.actions
        ]
        completions = [c for c in completions if c.text.startswith(typed["typed"])]
        # A device has only these: IPython's own would list them again, untold
        return {
            "completions": completions,
            "matched_fragment": typed["typed"],
            "suppress": True,
        }

    def procedure(self, context: CompletionContext) -> Dict[str, Any]:
        typed = PROCEDURE.search(context.text_until_cursor)
        found = None if typed is None else self.named(typed["name"], None)
        if not isinstance(found, Bench):
            return {"completions": []}
        try:
            procedures = found.procedures()
        except LabError:
            return {"completions": []}
        return {
            "completions": [
                SimpleCompletion(p.name, type=f"{PROCEDURE_TYPE}: {p.title}")
                for p in procedures
                if p.name.startswith(typed["typed"])
            ],
            "matched_fragment": typed["typed"],
            "suppress": True,
        }


def load_ipython_extension(shell) -> None:
    """The bench's matchers in a shell (%load_ext thzdaq_api.kernel)."""
    completions = BenchCompletions(shell)

    @context_matcher(identifier="thzdaq.device")
    def device(context: CompletionContext) -> Dict[str, Any]:
        return completions.device(context)

    @context_matcher(identifier="thzdaq.procedure")
    def procedure(context: CompletionContext) -> Dict[str, Any]:
        return completions.procedure(context)

    shell.Completer.custom_matchers.extend((device, procedure))


def main() -> None:
    app = IPKernelApp.instance()
    app.initialize()
    load_ipython_extension(app.shell)
    app.start()


if __name__ == "__main__":
    main()
