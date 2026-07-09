"""Typed channels and footprints — the substrate every combinator composes through.

A ``Channel`` is a ``(name, type)`` pair (vision.md §3.1). A ``Footprint`` is the set
of channels a nonterminal or atom ``reads``/``writes`` plus the control signals it
``emits`` (§3.2). Composition safety is decided entirely from footprints, so this is
the load-bearing declaration in the system.

Types are placeholders for now: the type/channel-compatibility rules are deliberately
deferred (docs/language.md §9), so ``type`` is a free-form string and channel identity
is ``(name, type)``. When the type system lands, only ``Channel`` changes here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

__all__ = ["Channel", "Footprint", "WriteConflict", "disjoint_writes"]


@dataclass(frozen=True)
class Channel:
    """A named, typed unit of data interaction. Identity is ``(name, type)``."""

    name: str
    type: str = "?"  # placeholder until the type system lands (language.md §9)

    def __str__(self) -> str:
        return self.name if self.type == "?" else f"{self.name}:{self.type}"


@dataclass(frozen=True)
class Footprint:
    """What a piece of the derivation reads, writes, and emits (vision.md §3.1–§3.2).

    ``reads``/``writes`` are channels; ``emits`` are control-signal names ranked in a
    severity order (§3.2). Footprints are *declared* at atom leaves and *synthesized*
    at internal nodes (§11.3) — this class carries the declaration; synthesis lands
    with the derivation engine (roadmap step 4).
    """

    reads: frozenset[Channel] = field(default_factory=frozenset)
    writes: frozenset[Channel] = field(default_factory=frozenset)
    emits: frozenset[str] = field(default_factory=frozenset)

    @staticmethod
    def of(
        *,
        reads: Iterable[Channel] = (),
        writes: Iterable[Channel] = (),
        emits: Iterable[str] = (),
    ) -> "Footprint":
        """Build a Footprint from any iterables (convenience over frozenset() calls)."""
        return Footprint(frozenset(reads), frozenset(writes), frozenset(emits))


@dataclass(frozen=True)
class WriteConflict:
    """Two items write the same channel — the disjointness violation (vision.md §3.4).

    Carries everything a good rejection message needs (roadmap step 3): the shared
    channel and the labels of both offending items.
    """

    channel: Channel
    left: str
    right: str

    def __str__(self) -> str:
        return (
            f"channel `{self.channel}` is written by both "
            f"`{self.left}` and `{self.right}`"
        )


def disjoint_writes(items: Iterable[tuple[str, Footprint]]) -> list[WriteConflict]:
    """The frame rule, made operational (vision.md §3.1, §7.4).

    Given labelled items, return every write-channel collision between distinct items.
    Empty list ⇒ the items compose by disjoint footprint. This is the single check
    shared by REST decision points 4, 5, 7, and 9 (docs/rest-domain.md §10).

    Detection is order-independent by construction (it inspects unordered pairs), which
    is what the accumulation shape requires — property-tested at roadmap step 6.
    """
    conflicts: list[WriteConflict] = []
    owner: dict[Channel, str] = {}
    for label, fp in items:
        for channel in fp.writes:
            prior = owner.get(channel)
            if prior is not None and prior != label:
                conflicts.append(WriteConflict(channel, prior, label))
            else:
                owner.setdefault(channel, label)
    return conflicts
