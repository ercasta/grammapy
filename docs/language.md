# The grammapy Language — An Introduction

**Status:** draft v0.1 — first cut. The design decisions here are stable (see
[`vision.md` §11](vision.md)); the concrete syntax is provisional and expected to change against
the first end-to-end implementation.

**Audience:** someone who wants to read and write grammapy grammars and specs, without first
reading the whole design rationale. For *why* the language is shaped this way, follow the `§`
pointers into [`vision.md`](vision.md).

---

## 1. The one-paragraph mental model

grammapy generates software from a **spec that states only deviations from declared defaults**.
There is **one language**, used two ways:

- write a **grammar** — name a *derivation* and abstract it over its decision points, and
- write a **spec** — fill those decision points in, mentioning only where you deviate from the
  default.

A spec is a grammar rule with its holes filled; a grammar rule is a spec with some choices left
open. The built-in vocabulary is tiny — **four combinators** — and a domain adds only *atoms* and
*wiring*, never new combinators (§11.2).

---

## 2. Building blocks

### 2.1 Channels and footprints

Everything composes through typed **channels** — named units of data or control that a piece of
the derivation `reads`, `writes`, or `emits` (a control signal). A piece's set of channels is its
**footprint**. Composition safety is decided entirely from footprints, so they are the load-bearing
declaration in the language.

### 2.2 Atoms (the terminals)

An **atom** is a leaf: bespoke behavior whose interior the system does not analyze, wrapped in a
declared footprint. Its body lives in a **separate, user-owned file** that regeneration never
overwrites; the generator emits a typed callback interface and checks the body against it (§3.6).

```
atom compute_discount:
  reads  order.total, customer.tier      # → callback inputs
  writes order.discount                  # → callback outputs
  emits  TransientError                  # optional control signal, ranked in the severity order
  impl   ./business/discount.py:compute_discount
```

`reads`, `writes`, `emits` are each optional; `impl` points at `file:function`. Because an atom is
opaque, its footprint is **declared** (it cannot be derived — Rice's theorem, §6). This is the only
place a footprint is written by hand; everywhere above the leaves it is *derived* (§4).

### 2.3 The four combinators (the entire nonterminal vocabulary)

Every decision point is exactly one of four shapes, realized as four built-in combinators, each
proven sound once. You choose which one hosts your atoms; you never write a new one.

| Combinator | Shape | Combination law | Use it for |
|---|---|---|---|
| `Choice { … }` | exclusive-choice | guards partition the spec space; one production fires | pick one of N strategies |
| `Accumulate<T>` | disjoint-footprint | each item independently applied; `writes` pairwise disjoint | lists of independent items |
| `Fold[join]<T>` | semilattice fold | combine via a declared commutative/associative join | items that conflict and must be resolved |
| `Scope[catches] { … }` | binder-scoped | every emitted signal has a covering handler ancestor | transactions, exception coverage, loops |

Records, sequences, and loops are **composites** of these four, not new primitives: a `record` is
`Accumulate` over disjoint *named* slots; a loop is a `Scope` binding iteration channels around an
`Accumulate` of operations. If a genuinely new shape is ever needed, it is added **to the system**
with its own proof — never authored in a user's grammar (§11.2).

**One consequence worth internalizing early: a loop is not privileged over business logic.** A loop
is `Scope` + `Accumulate` over footprint-declared atoms; a set of business rules is
`Accumulate`/`Fold`/`Scope` over footprint-declared atoms — the *identical* mechanism. The system
understands a loop body's arithmetic no better than it understands a pricing rule; in both cases it
reasons over the declared footprint and treats the interior as opaque. So the boundary of what the
language can compose is **not** "grammar constructs vs. your code" but **footprint vs. interior**:
business logic composes exactly to the extent its interaction with other logic is captured by its
footprint and fits one of the four shapes. Where it doesn't, you either make the data-flow explicit
(and it becomes composable) or quarantine it in one atom — never a silent guess.
[`order-example.md`](order-example.md) walks this line on a full service.

---

## 3. Grammar mode: defining nonterminals

A **nonterminal** names a derivation term, optionally parameterized, optionally with per-slot
defaults. Its *shape* is just its outermost combinator; its *footprint* is synthesized from its
parts — so you rarely declare either.

```
nonterminal Persistence = Choice {
  key.absent | key=sql -> sql(table: Ident)          # default branch: guard includes key-absence
  key=document         -> document(collection: Ident)
  key=in_memory        -> in_memory()
}

nonterminal Resource(name: Ident) = record {
  persistence:   Persistence                default sql(table: name)
  validation:    Accumulate<Validation>     default {}
  authorization: Fold[deny_overrides]<Auth> default {}
  logic:         Accumulate<Business>       default {}
}
```

**Guards** (on `Choice`) are restricted to a decidable fragment — boolean combinations of key
presence/absence and equality against a declared finite enum — so that disjointness and
exhaustiveness are statically checkable (§4.3). Anything richer belongs inside an atom, not a
guard.

**Defaults** are what a spec gets when it stays silent about a slot. Changing a default is a
breaking change and is surfaced as an explicit migration note, never applied silently (§10.3).

---

## 4. Spec mode: deviation overlays

A spec instantiates a nonterminal and then states **only its deviations**, each addressed by a
**dot-path**:

```
Order : Resource("orders")
  .validation    += required(name), range(age, 0, 120)
  .authorization += grant(role: admin, action: *), deny(role: guest, action: delete)
  .logic         += compute_discount
```

Two verbs:

- **`=` sets** a single-locus decision — a `Choice`, or a value reached *into* a chosen production
  (`.persistence.table = orders`).
- **`+=` adds** to a many-item decision — an `Accumulate` or a `Fold`. (You do not navigate into a
  single child of a collection; you add items to it.)

Everything not mentioned takes its default. In the example above, `persistence` is silent, so
`Order` is `sql(table: orders)`.

**Design-time rejection is the point.** `compute_discount` writes `order.discount`; if another atom
under `.logic` also wrote it, the disjointness check would reject the spec *before generating
anything*, naming both deviations and the shared channel — not surface a runtime bug later.

### 4.1 Deep paths and propose-and-report

A path may reach deep into the derivation: `.persistence.table` only *exists* if `persistence`
resolved to `sql`. A deep deviation **proposes** the upstream choices needed to reach it —
`.persistence.table = orders` implies `.persistence = sql`. If that proposal conflicts with another
deviation (say you also wrote `.persistence = in_memory`), it is **reported** through the same
conflict machinery as a footprint clash. Path-presupposition failure and feature conflict are one
error channel, not two (§11.4).

Paths address **named** decision points, never positions, so a grammar refactor that preserves
names preserves your specs (§10.3).

---

## 5. A spec is a new nonterminal — when it keeps a hole

Reuse works by **abstraction**. Take a deviation overlay, leave one or more decision points open as
parameters, name it — and it *is* a new production of a nonterminal:

```
nonterminal AuditedResource(name) = Resource(name)
  .logic += audit(sink: audit_log)     # `table` stays a parameter ⇒ still a nonterminal
```

A *ground* spec (no holes) is a value, not a reusable abstraction. Abstraction gives you the
expansion for free, but the new nonterminal is *sound* only once its shape is supplied or (being
built from the four combinators) derived — see §6 (§11.5).

---

## 6. Where properties come from (why you declare so little)

For any grammar built from the four combinators over atoms:

- **Footprint** is synthesized bottom-up — declared only at atom leaves, derived at every
  nonterminal above them.
- **Shape** is read off the outermost combinator.
- **Soundness** is the hosting combinator's law checked over the derived footprints
  (disjointness / reachability / guard-coverage / join-laws), all decidable.

The one thing the system cannot derive is **intent** — which combinator you *meant*. So you
propose a combinator and the derived properties **refute** a wrong choice (two `Accumulate` items
that write the same channel point you at `Fold`). Propose-and-check, never infer-intent (§11.3).

---

## 7. A provisional concrete grammar

A first, illustrative EBNF for the language itself. Provisional — tokens, precedence, and exact
keywords are settled during implementation (§8).

```ebnf
program        = { item } ;
item           = atom_decl | nonterminal_decl | spec_decl ;

atom_decl      = "atom" ident ":" [ "reads" channel_list ]
                                  [ "writes" channel_list ]
                                  [ "emits" ident_list ]
                                  "impl" impl_ref ;
channel_list   = channel { "," channel } ;
channel        = dotted_name ;                     (* e.g. order.total *)
ident_list     = ident { "," ident } ;
impl_ref       = path ":" ident ;                  (* file:function *)

nonterminal_decl = "nonterminal" ident [ params ] "=" term ;
params         = "(" param { "," param } ")" ;
param          = ident ":" type ;

term           = choice | accumulate | fold | scope | record
               | production | ref [ overlay ] ;
ref            = ident [ "(" arg { "," arg } ")" ] ;

choice         = "Choice" "{" guarded { guarded } "}" ;
guarded        = guard "->" production ;
guard          = guard_atom { "|" guard_atom } ;
guard_atom     = "key" "." "absent" | "key" "=" literal | "otherwise" ;
production     = ident "(" [ slot { "," slot } ] ")" ;

accumulate     = "Accumulate" "<" type ">" ;
fold           = "Fold" "[" ident "]" "<" type ">" ;     (* [join] *)
scope          = "Scope" "[" ident_list "]" "{" term "}" ;  (* [catches] *)
record         = "record" "{" slot { "," slot } "}" ;
slot           = ident ":" term [ "default" term ] ;

spec_decl      = ident ":" ref overlay ;
overlay        = { deviation } ;
deviation      = path "=" term                       (* set: Choice / into-production *)
               | path "+=" term { "," term } ;       (* add: Accumulate / Fold *)
path           = "." dotted_name ;

dotted_name    = ident { "." ident } ;
type           = ident ;
literal        = ident | string | number ;
```

---

## 8. Worked example, end to end

```
# --- atoms (user-owned bodies, never overwritten on regeneration) ---
atom compute_discount:
  reads  order.total, customer.tier
  writes order.discount
  emits  TransientError
  impl   ./business/discount.py:compute_discount

atom audit:
  reads  request.actor, request.action
  writes audit_log
  impl   ./business/audit.py:record

# --- domain grammar: atoms wired into the four combinators ---
nonterminal Resource(name: Ident) = record {
  persistence:   Choice {
    key.absent | key=sql -> sql(table: name)
    key=document         -> document(collection: name)
  }
  validation:    Accumulate<Validation>     default {}
  authorization: Fold[deny_overrides]<Auth> default {}
  logic:         Accumulate<Business>       default {}
  boundary:      Scope[TransientError] { retry(max: 3) }   # binder covering emitted signals
}

# --- a reusable, still-abstract nonterminal (keeps `name` open) ---
nonterminal AuditedResource(name) = Resource(name)
  .logic += audit

# --- the actual spec: only the deviations ---
Order : AuditedResource("orders")
  .authorization += grant(role: admin, action: *), deny(role: guest, action: delete)
  .logic         += compute_discount
```

What the checker guarantees before emitting a line of Python:

- `compute_discount` and `audit` write disjoint channels (`order.discount` vs `audit_log`), so
  `.logic` is sound under `Accumulate`.
- `grant`/`deny` conflict on the same subject/action, but `Fold[deny_overrides]` resolves them by a
  commutative join — order-independent.
- `compute_discount` may `emit TransientError`; the `boundary` `Scope` covers that signal, so the
  reachability check passes. Remove the `Scope` and the spec is rejected.
- `persistence` is silent → `sql(table: orders)` by default.

---

## 9. Not yet specified

Deliberately open in v0.1, to be pinned during implementation:

- concrete types and the type/channel-compatibility rules (currently `Ident`, `Money`, etc. are
  placeholders);
- the exact set of built-in joins for `Fold` (`deny_overrides`, `permit_overrides`,
  `first_applicable`, …) and how a spec selects one;
- cross-domain import syntax (§4.4) and how a nonterminal from another domain is named as an atom;
- module/namespace structure and how atoms' `impl` files are resolved;
- the surface for grammar-version pinning (§10.3).

See [`vision.md`](vision.md) for the full rationale, worked examples, and the literature this
design draws on.
