# grammapy

**A grammar-based system for generating software from deviations-from-default.**

> Status: implementation started. Roadmap step 2 (domain decision points) is documented and
> step 3 (channel substrate + disjoint-writes check) has a first tested slice — see
> [roadmap](#roadmap).

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

- **vs. a DSL with good defaults**: for a single, static program the two are close in what you
  write — a good combinator library gets you far. The difference is what an ordinary DSL *doesn't*
  guarantee: it makes you spell out the whole composition every time (no deviation-from-default
  model), it lets two composed pieces secretly touch the same state (no footprint check), and
  combining two DSLs means hand-writing the interop where interactions hide. grammapy's win is not
  fewer characters on one program; it is three multipliers a DSL doesn't give you — **change**
  (edit one deviation, regenerate, and non-interference is *asserted*, not hoped), **N-way
  combination** (the O(N²) interaction surface of hand-composition becomes N local checks that each
  inherit one proof), and **cross-domain** (composing dialects through the shared substrate is
  *checked*, not hand-wired — §4.4, the least-proven and highest-upside axis).
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

## The dividing line: footprint, not category

A recurring question: if the system can express *loops*, why can't it just combine *business
logic*? It can — that is not the boundary. A loop is `Scope` + `Accumulate` over
footprint-declared atoms; business logic is `Accumulate`/`Fold`/`Scope` over footprint-declared
atoms. **It is the identical mechanism**, and the system understands a loop body's arithmetic no
better than it understands a discount rule — in both cases it reasons over the declared footprint
and treats the interior as opaque. The line is not *grammar constructs vs. your code*. It is:

> the system composes over each piece's **declared footprint** (its interface), never over its
> **interior**.

So business logic composes exactly to the extent its interaction with other logic is captured by
its footprint and fits one of the four shapes. What the system will never do is *invent* a
combination law that isn't one of the four — it refuses rather than guesses. Concretely, an
ordering assumption between two rules gets exactly one of three visible fates — made **explicit**
in the footprints (and thus derived and checked), **rejected** at design time with the shared
channel named, or **quarantined** in a single opaque atom — but *never a silent guess*, which is
what ordinary code does every time you write two statements in sequence.
[`docs/order-example.md`](docs/order-example.md) walks a full `Order` service through all three
fates.

## Swapping and composing across domains

Define a database-persistence and a file-persistence backend, a FastAPI and a Flask serving layer,
a pandas pipeline domain — can you generate all their compositions (swap the backend, swap the
framework) without hand-writing each combination? **Yes, within a precise boundary**, and the
answer splits in two:

- **Swapping alternatives *within* one axis** (file ↔ database, FastAPI ↔ Flask) is an
  exclusive-**`Choice`**: both productions present the *same typed channel interface* (`store`,
  `record`, `route.*`, `response`), the rest of the spec is written against those channels and never
  names the backend, so a swap is **one deviation** with everything downstream untouched.
- **Combining *different* axes** (a FastAPI endpoint running a pandas pipeline, persisted to a
  database) is **cross-domain composition** — a nonterminal from one domain is hosted as a typed
  atom in another, and the seams are checked through footprints.

**What this genuinely buys you:** the cost is **additive** (author each domain once, each
cross-domain adapter once) rather than **multiplicative** (hand-write every combination). And the
system decides *which* compositions actually typecheck, at design time — e.g. a spec with a
transaction boundary swapped onto file persistence is **rejected**, because `file_store` provides no
`tx` channel, instead of silently emitting a file-backed "transaction" that isn't one.

**What it does *not* do**, stated plainly:

- it does **not** make two alternatives substitutable for free — designing the framework-/storage-
  neutral **channel contract** both satisfy is the real up-front work; the system makes a leak in it
  *visible* (a channel-mismatch rejection), it does not design the contract;
- it does **not** generate the **cross-domain adapters** (`frame → record`, `body → frame`) — those
  are hand-written lowering passes (opaque atoms, no interior guarantee), and this is the
  least-proven, furthest-out part of the design;
- it does **not** cover a *thin* domain's interiors — a pandas pipeline's *wiring* and column
  footprints are checked (catching silent column overwrites for free), but the transforms themselves
  are bespoke.

[`docs/cross-domain-example.md`](docs/cross-domain-example.md) works this end to end — the two
`Choice` axes, the pandas dialect, the adapters, and a swap matrix showing which cells typecheck and
which are rejected.

## Two ways to make a choice

Can the system choose *for* you — say, pick database over file persistence because you asked for
transactions and only the database provides them? Yes, but only in a disciplined form, and the
distinction matters. There are two structurally different ways a spec fixes a decision point:

- **Point deviations** (the model today) are *extensional*: name one decision point by dot-path and
  set it — `.persistence = sql`. Local, explicit, but it presupposes you know *which* point to set
  and says nothing about the others.
- **Cross-cutting constraints** (a compatible extension) are *intensional*: state a property of the
  whole system — `requires tx` — addressed to no single path, that must hold at **every** decision
  point where it is relevant, simultaneously. The system then works out *where* it bites.

A cross-cutting constraint resolves by **narrowing** each open point's admissible productions, then:

- **exactly one survives → forced** — deterministic and unique (this is constraint propagation, not
  search: `requires tx` leaves only `sql_store`);
- **several survive → surfaced** as a design-time decision, never a silent pick — unless a
  *declared, versioned* preference tie-breaks among the survivors;
- **none survives → rejected**, naming the requirement and the point.

The one rule that keeps this from becoming a hidden "optimizing planner" — the very thing the system
exists to avoid: **forced where unique, declared where preferred, surfaced where ambiguous — never
inferred.** An *inferred* preference (the system silently optimizing a cost function it chose) would
repick a production on regeneration and reintroduce default drift. A *declared* preference is a
reviewable policy, exactly like choosing `deny_overrides`. And every forced choice is emitted as a
diffable note (*"persistence ← sql, forced by requirement `tx`"*) — a choice made for you that you
can't see is still a silent choice. Full treatment in [§12 of the design doc](docs/vision.md).

## Estimating complexity in the generative era

When a model can emit thousands of lines from a short prompt, **lines of code stop measuring
anything** — the generated artifact is derived, cheap, and disposable. What stays scarce is the
set of decisions someone had to get right and must review. grammapy puts that set in the
representation: a system is a grammar of decision points plus a spec that states only **deviations
from declared defaults**. So a natural complexity driver sits in the model itself —

> the **shape-weighted count of deviations** a spec makes against its grammar.

This is essential complexity in Brooks's sense, and a design-time cousin of established structural
metrics — McCabe's cyclomatic complexity counts decision points in control flow; function points
count user-visible functions. Unlike lines of code, it **survives generation**: re-emit the same
spec in another language or framework and the count is unchanged.

The estimate is weighted, not a raw sum, because combination shape drives cognitive load:

- an independent **`Accumulate`** item (one more validation rule) is light;
- a **`Fold`** where items conflict — especially a non-commutative one needing an explicit
  ordering decision — is heavier;
- a **`Scope`** with deep reachability obligations, or a cross-domain seam, heavier still.

**What it deliberately does not measure:** the interior of opaque atoms — the bespoke business
logic, which is most of a real service. Two specs with equal deviation counts can hide a one-liner
or a 2000-line solver behind an atom. So this drives **composition/specification complexity** — the
wiring you reason about and review — not total complexity. The boundary is exactly the atom's
declared footprint, and it is visible, not hidden.

Two honest caveats, in keeping with the rest of this project: the measure is **grammar-relative**
(comparable only within a grammar version — richer defaults mean fewer deviations), and it is a
**hypothesis, not a validated metric**. It needs calibration against real effort and defect data
before any number it produces is trusted — and especially before it is ever billed against, or
people will push complexity into atoms to game the count.

## Design foundations

The architecture borrows deliberately from established results rather than inventing new
theory: the **frame rule** from separation logic (disjoint footprints compose safely),
**algebraic effects and handlers** for control flow, **attribute grammars** and **two-level
(W-) grammars** for spec-driven derivation, and **MLIR's dialect architecture** for
composing domain-specific vocabularies over one shared typed substrate. Full literature
mapping is in the design doc.

## Scope and limits

- No single universal grammar — one per software category. Grammars **do** compose across
  domains through the shared typed substrate (not a shared vocabulary), and swapping alternatives
  within one axis (persistence backend, serving framework) is a single deviation when they share a
  channel contract — but the cross-domain data adapters that combining *different* axes needs are
  hand-written, not automatic (cf. MLIR lowering passes). See
  [`docs/cross-domain-example.md`](docs/cross-domain-example.md).
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
- [`docs/rest-domain.md`](docs/rest-domain.md) — roadmap step 2: the first domain's decision
  points, each wired to a combinator, with the channel vocabulary the code implements against.
- [`docs/order-example.md`](docs/order-example.md) — a full `Order` service walked end to end:
  each feature classified, each conflict the checker raises, and the one decision it refuses to
  make for you. The concrete form of "footprint, not category."
- [`docs/cross-domain-example.md`](docs/cross-domain-example.md) — swapping persistence backends and
  serving frameworks (a `Choice` per axis) and composing a pandas pipeline across domains: what the
  system swaps for free, which swaps it rejects at design time, and where hand-written adapters are
  unavoidable.
