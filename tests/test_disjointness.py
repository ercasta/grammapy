"""Tests for the disjoint-writes check (roadmap step 3, first slice).

Uses stdlib unittest so the suite runs with no dependencies (`python -m unittest`).
hypothesis-based property tests for order-independence arrive at roadmap step 6.

Scenarios are drawn from the real REST decision points in docs/rest-domain.md so the
substrate is validated against the domain it must serve, not toy data.
"""

import unittest

from grammapy import Accumulate, Channel, CompositionError, Footprint, Item, disjoint_writes


def w(*names: str) -> Footprint:
    """A footprint that writes the named channels (type left as placeholder)."""
    return Footprint.of(writes=[Channel(n) for n in names])


class DisjointFields(unittest.TestCase):
    """REST §4: two fields must not share a name (`field.<name>`)."""

    def test_distinct_fields_compose(self):
        items = [
            Item("name: Str", w("field.name")),
            Item("email: Str", w("field.email")),
            Item("age: Int", w("field.age")),
        ]
        Accumulate.check(items)  # no raise

    def test_field_name_collision_is_rejected(self):
        items = [
            Item("name: Str", w("field.name")),
            Item("name: Text", w("field.name")),  # duplicate field name
        ]
        with self.assertRaises(CompositionError) as ctx:
            Accumulate.check(items)
        msg = str(ctx.exception)
        self.assertIn("field.name", msg)
        self.assertIn("name: Str", msg)
        self.assertIn("name: Text", msg)


class DisjointValidation(unittest.TestCase):
    """REST §5: rules on the same field compose via distinct violation slots."""

    def test_required_and_range_on_same_field_compose(self):
        # `required(age)` and `range(age,...)` both concern age but write distinct
        # slots — the slot-per-rule modeling that keeps the frame rule applicable.
        items = [
            Item("required(age)", w("violations.age.required")),
            Item("range(age, 0, 120)", w("violations.age.range")),
        ]
        Accumulate.check(items)  # no raise

    def test_two_rules_sharing_a_slot_conflict(self):
        items = [
            Item("range(age, 0, 120)", w("violations.age.range")),
            Item("range(age, 1, 130)", w("violations.age.range")),  # same slot
        ]
        with self.assertRaises(CompositionError):
            Accumulate.check(items)


class DisjointRoutes(unittest.TestCase):
    """REST §7: no two endpoints may claim the same method+path."""

    def test_distinct_routes_compose(self):
        items = [
            Item("create", w("route.POST:/orders")),
            Item("read", w("route.GET:/orders/{id}")),
        ]
        Accumulate.check(items)

    def test_route_collision_is_rejected(self):
        items = [
            Item("create", w("route.POST:/orders")),
            Item("bulk_create", w("route.POST:/orders")),
        ]
        with self.assertRaises(CompositionError):
            Accumulate.check(items)


class CheckSemantics(unittest.TestCase):
    def test_reads_do_not_conflict(self):
        # Only writes are constrained by disjointness; shared reads are fine.
        a = Footprint.of(reads=[Channel("store")], writes=[Channel("route.GET:/x")])
        b = Footprint.of(reads=[Channel("store")], writes=[Channel("route.GET:/y")])
        Accumulate.check([Item("a", a), Item("b", b)])

    def test_order_independence(self):
        a = Item("a", w("c"))
        b = Item("b", w("c"))
        forward = disjoint_writes([(a.label, a.footprint), (b.label, b.footprint)])
        reverse = disjoint_writes([(b.label, b.footprint), (a.label, a.footprint)])
        self.assertEqual(len(forward), 1)
        self.assertEqual(len(reverse), 1)
        self.assertEqual(forward[0].channel, reverse[0].channel)

    def test_same_label_is_not_a_self_conflict(self):
        # A single item appearing once must not conflict with itself.
        Accumulate.check([Item("solo", w("c"))])


if __name__ == "__main__":
    unittest.main()
