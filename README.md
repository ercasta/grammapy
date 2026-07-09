# grammapy

**A grammar-based system for generating software from deviations-from-default.**

> Status: design document / implementation driver. No code yet — see [roadmap](#roadmap).

## The problem

Most software within a given category (REST services, CRUD backends, data pipelines) is
structurally similar. Scaffolding tools and wizards exploit this, but they combine options
with hand-written glue code, not an algebra — so each new feature risks silently
reinteracting with existing ones. This is the **feature interaction problem**, first named
in 1990s telecom switching software, and it has no general post-hoc detection algorithm.

## The idea

Instead of generating code from scratch, grammapy generates it from a spec that states only
**deviations from declared defaults**, via a grammar where every decision point has an
explicit, provably safe way of combining simultaneous deviations. Concretely:

- A feature is only admitted if its combination behavior with every other feature at the same
  decision point is provably sound — checked once, at design time, not discovered later at
  runtime or in production.
- Every decision point is one of just **four combination shapes**, realized as four built-in
  combinators, each proven sound once:

  | Shape | Combination law |
  |---|---|
  | **Exclusive-choice** | guards partition the spec space; pick the one satisfied production |
  | **Disjoint-footprint accumulation** | independently-applicable items with pairwise-disjoint writes |
  | **Semilattice fold** | combine via a declared commutative/associative join |
  | **Binder-scoped reachability** | every control-emitting leaf has a covering handler ancestor |

- Those four are the *entire* built-in vocabulary. A domain adds only **atoms** (bespoke behavior
  behind a declared footprint) and **wiring** (which combinator hosts which atoms) — never new
  combinators — so adding a feature is a **local** change that inherits its host combinator's
  proof, never a global re-verification.
- Bespoke business logic enters as a **typed callback atom**: a declared input/output footprint,
  checked against the channels the grammar exposes to it, otherwise unanalyzed, with its body in a
  user-owned file the generator never overwrites.
- **Grammars compose across domains.** There is one grammar per software category (REST services,
  data pipelines, …), but a nonterminal from one domain can be used inside another as a typed atom
  — checked structurally through the shared substrate, without inspecting or trusting the other
  domain's internals. Cross-domain composition is a designed feature, not a boundary.

This is **not** a claim that generated programs are bug-free or terminate. The guarantee is
narrower and more practical: **composing already-accepted deviations never silently breaks
other already-accepted deviations** — including after the spec changes and the code is
regenerated.

## What it looks like

There is **one language**, used two ways: to define a grammar (name a derivation abstracted over
its decision points) and to write a spec (state only deviations from defaults). The built-in
nonterminal vocabulary is exactly four combinators — `Choice`, `Accumulate`, `Fold`, `Scope` — and
a domain adds only *atoms* and *wiring*, never new combinators. Syntax below is illustrative, not
frozen.

**An atom** (bespoke logic — a typed callback, body in a user-owned file the generator never
overwrites):

```
atom compute_discount:
  reads  order.total, customer.tier
  writes order.discount
  emits  TransientError
  impl   ./business/discount.py:compute_discount
```

**A grammar rule** (a nonterminal is a derivation term abstracted over its holes; its shape is the
outermost combinator, its footprint is synthesized from the parts):

```
nonterminal Persistence = Choice {
  key.absent | key=sql -> sql(table: Ident)
  key=document         -> document(collection: Ident)
  key=in_memory        -> in_memory()
}

nonterminal Resource(name: Ident) = record {          # record = Accumulate over named slots
  persistence:   Persistence                default sql(table: name)
  validation:    Accumulate<Validation>     default {}
  authorization: Fold[deny_overrides]<Auth> default {}
  logic:         Accumulate<Business>       default {}
}
```

**A spec** (a sparse overlay of deviations, each addressed by a dot-path; `+=` adds to
accumulation/fold points):

```
Order : Resource("orders")
  .validation    += required(name), range(age, 0, 120)
  .authorization += grant(role: admin, action: *), deny(role: guest, action: delete)
  .logic         += compute_discount
```

Here `compute_discount` writes `order.discount`; if another atom under `.logic` also wrote it, the
disjointness check would reject the spec **at design time**, naming both deviations and the shared
channel — not at runtime.

**A spec is a new nonterminal when it keeps a hole** — abstract an overlay over a decision point,
name it, and it becomes a reusable production:

```
nonterminal AuditedResource(name) = Resource(name)
  .logic += audit(sink: audit_log)     # `table` stays a parameter ⇒ still a nonterminal
```

The full language design (one-language rationale, the hard line on combinators, how a composite's
properties are derived, and dot-path semantics) is [§11 of the design doc](docs/vision.md), with a
standalone introduction in [`docs/language.md`](docs/language.md).

## Why this, not X

- **vs. scaffolding tools** (Rails/Django generators, Yeoman): no algebra for combining
  options, no story for regenerating after code diverges.
- **vs. IDL/schema codegen** (OpenAPI, gRPC): generates the contract surface faithfully, but
  leaves behavior composition (authorization × validation × persistence × transactions) to
  hand-written glue — exactly where interactions arise.
- **vs. an LLM generating the whole service**: faster and broader for bespoke logic, but no
  composition guarantee — regenerating after a requirement change can silently shift
  unrelated behavior. The most promising framing is complementary: **LLM front-end, sound
  back-end** — an LLM drafts the deviation spec from natural-language intent, and the
  grammar guarantees the composition of those deviations is non-interfering and
  deterministically emitted.

## Design foundations

The architecture borrows deliberately from established results rather than inventing new
theory: the **frame rule** from separation logic (disjoint footprints compose safely),
**algebraic effects and handlers** for control flow, **attribute grammars** and **two-level
(W-) grammars** for spec-driven derivation, and **MLIR's dialect architecture** for
composing domain-specific vocabularies over one shared typed substrate. Full literature
mapping is in the design doc.

## Scope and limits

- No single universal grammar — one per software category. Grammars **do** compose across
  domains through the shared typed substrate (not a shared vocabulary), but the cross-domain
  data adapters that composition needs are not automatic (cf. MLIR lowering passes).
- Soundness, not completeness — interaction shapes not served by a combinator are refused
  admission, not silently assumed safe.
- No termination or general runtime-correctness guarantee, by design.
- The guarantee is conditional on productions honestly declaring their read/write footprint,
  which is checked empirically (a non-interference diff test), not statically proven.

## Roadmap

1. Pick one target domain (REST/CRUD services).
2. Enumerate 5–8 real decision points and wire each into one of the four combinators (a spike
   scale — a genuinely useful domain needs dozens; the wiring is the real design cost).
3. Implement the channel-type system and a disjointness checker, with rejection messages
   that name the conflicting deviations and shared channel.
4. Implement the control-severity lattice, binder/reachability checking, and a DCG-style
   derivation engine.
5. Implement deterministic emission to Python.
6. Property-test every combinator for order-independence.
7. Implement the non-interference diff test: regenerate after one deviation change, assert
   the diff stays within that deviation's declared footprint.
8. Generate one working module end-to-end, including an opaque atom and a regeneration
   cycle, before expanding further.
9. Only then: add a second domain and cross-domain import (§4.4), using MLIR's dialect model
   as the architectural reference.

## Documentation

- [`docs/vision.md`](docs/vision.md) — the full design document: worked examples, literature
  survey, decidability limits, and the language design (§11).
- [`docs/language.md`](docs/language.md) — a standalone introduction to the specification and
  grammar language, for readers who want the language without the whole design rationale.
