"""The combination shapes (vision.md §3.4).

The four combinators are the *entire* built-in nonterminal vocabulary; a domain adds
atoms and wiring, never new combinators (§11.2). Each carries its soundness check.

Only ``Accumulate`` is implemented so far — it hosts REST decision points 4, 5, 7, 9
(docs/rest-domain.md) and its check is the shared disjoint-writes rule. ``Choice``,
``Fold``, and ``Scope`` are declared as the next roadmap steps and raise until then, so
the vocabulary is visible and the gaps are explicit rather than silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from grammapy.channels import Footprint, WriteConflict, disjoint_writes

__all__ = ["Item", "CompositionError", "Accumulate"]


@dataclass(frozen=True)
class Item:
    """A labelled footprint — one candidate member of a combinator.

    ``label`` is what a rejection message shows the user (a deviation's source text,
    e.g. ``"range(age, 0, 120)"``); ``footprint`` is what the check reasons over.
    """

    label: str
    footprint: Footprint


class CompositionError(Exception):
    """A combinator's soundness check failed — refused admission at design time.

    Carries the structured cause so callers can render it however they like; ``str``
    gives the human-facing rejection (roadmap step 3: name the conflicting deviations
    and the shared channel, never a combinator soundness trace).
    """

    def __init__(self, shape: str, conflicts: list[WriteConflict]):
        self.shape = shape
        self.conflicts = conflicts
        lines = [f"{shape} rejected: writes are not disjoint"]
        for c in conflicts:
            lines.append(f"  - {c}")
        super().__init__("\n".join(lines))


class Accumulate:
    """Disjoint-footprint accumulation (vision.md §3.4).

    Each item is independently applicable; the shape is sound iff the items' ``writes``
    are pairwise disjoint. Reading and emitting are unconstrained here (they are the
    concern of the frame rule's read-side and of reachability, respectively).
    """

    @staticmethod
    def check(items: Iterable[Item]) -> None:
        """Raise ``CompositionError`` if any two items write the same channel."""
        conflicts = disjoint_writes((it.label, it.footprint) for it in items)
        if conflicts:
            raise CompositionError("Accumulate", conflicts)
