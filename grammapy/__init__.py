"""grammapy — generate software from deviations-from-default.

See docs/vision.md for the design and docs/rest-domain.md for the first domain's
decision points. This package is being built following the roadmap in the README;
right now it covers the channel-type substrate and the disjoint-writes check
(roadmap step 3, first slice).
"""

from grammapy.channels import Channel, Footprint, WriteConflict, disjoint_writes
from grammapy.combinators import Accumulate, CompositionError, Item

__all__ = [
    "Channel",
    "Footprint",
    "WriteConflict",
    "disjoint_writes",
    "Accumulate",
    "CompositionError",
    "Item",
]
