# A Grammar-Based System for Generating Software from Deviations-from-Default

**Status:** design document / implementation driver
**Scope:** core idea, universal interaction substrate, combination shapes, worked examples, literature, open questions, implementation roadmap

---

## 1. Core Idea

Most software within a given category (REST services, CRUD backends, data pipelines, etc.)
is structurally similar. Hand-written "wizards" and scaffolding tools try to exploit this by
generating code from a small set of options, but they do so **without an algebra for
combining options** — each new feature is added by a human reading the existing generator
code and figuring out, ad hoc, how it should interact with what's already there. This does
not scale: added features silently reinteract with existing ones (the *feature interaction
problem*, first named and studied in telecom switching software, see §5).

This document specifies an alternative: software is generated from a **specification that
states only deviations from declared defaults**, via a **grammar** whose derivation is driven
by the specification (which production fires at each decision point is determined by the
spec, not by parsing input text). The grammar is designed so that:

- every decision point (*nonterminal*) has an explicit, provably safe way of combining
  multiple simultaneous deviations,
- adding a new deviation, or a new nonterminal, requires only a **local** proof (about that
  nonterminal alone), never a global re-verification of the whole system,
- the specification language and the derivation engine can, in principle, be reused across
  different software categories ("domains"), provided each domain expresses its
  data/control/scope interactions in one shared, typed interface calculus.

The central design discipline is: **a feature is only admitted into the grammar if its
combination behavior with every other feature at the same decision point is provably sound**
(disjoint, commutative, or otherwise coherent) — checked once, at design time, not discovered
later at runtime or in production.

This is explicitly **not** a claim that generated programs are guaranteed to terminate, be
free of runtime bugs, or otherwise behave better than hand-written code at the level of
ordinary program semantics. The guarantee is narrower and more useful in practice: **composing
already-accepted deviations never silently breaks other already-accepted deviations** — and it
holds *after* the spec changes and the code is regenerated, not only on first generation (§10).

The guarantee is conditional on one trusted input: that each production's declared footprint
honestly describes the code it emits (§6.6), which is enforced empirically by the
non-interference diff test (§8, §10) rather than by static verification of templates. How this
design compares to scaffolding tools, IDL generators, and LLM codegen is §9.

---

## 2. Two Failure Modes This Design Avoids

1. **The wizard/scaffolding-tool failure**: options are combined by ad hoc, hand-written glue
   code, written by someone looking at all prior options simultaneously. Adding option N+1
   risks silently changing the meaning of options 1..N. No proof obligation exists anywhere.

2. **The feature-interaction failure** (telecom, 1980s–90s, §5.1): independently-correct
   features, each tested in isolation, produce undefined or wrong behavior in combination
   (Call Forwarding + Call Waiting, Call Forwarding loops, etc.). Detection was attempted
   post-hoc via formal methods; no general algorithm can detect all interactions for
   arbitrarily added features (this is a real ceiling, not an oversight — see §6).

The system specified here avoids both by requiring, as a condition of a feature's admission
into the grammar, an explicit combination law with a locally-checkable soundness proof.

---

## 3. The Universal Interaction Substrate

To allow both (a) domain-specific nonterminal vocabularies and (b) safe composition within
and across domains, every domain's grammar must express its interactions using one shared,
typed substrate. This is modeled directly on MLIR's dialect architecture (§5.4): one universal
operation/interface contract, many domain-specific vocabularies ("dialects") built on top of it.

### 3.1 Typed Data Channels

Every nonterminal declares:

- `reads: Set[TypedChannel]` — channels it consumes
- `writes: Set[TypedChannel]` — channels it produces or mutates

A `TypedChannel` is `(name, type)`. Composition of two nonterminals at the same scope is
**sound by disjointness** if their `writes` sets are disjoint and each `reads` set is a subset
of the union of currently-exposed channels (channels bound by an enclosing nonterminal, or
written by a nonterminal earlier in a proven-safe order).

This is a direct application of the **frame rule** from separation logic (O'Hearn, Reynolds):
if two operations' footprints are disjoint, they compose safely with no further proof.

### 3.2 Control Channels

Control transfer (`break`, `continue`, `return`, exception raise, early-exit generally) is
**not** modeled as a data write. It is a distinguished channel type with:

- a **severity order** — a declared **join-semilattice**, *not* required to be total, e.g. the
  chain `CONTINUE < SKIP < BREAK < RETURN < RAISE`, or a partial order in which two distinct
  exception types are incomparable and join to a common supertype (or `RAISE`) at their least
  upper bound. Domain-specific, but required to be declared and to have a least upper bound for
  every pair of signals that can co-occur (or be embeddable into a shared cross-domain lattice,
  §4.4),
- a combination law: `combine_control(signals) = join(signals)` — commutative and associative
  by construction (it's a join in a semilattice). A total order is the common special case, not
  a requirement; forcing totality would falsely claim that two unrelated exception types are
  ranked against each other.

This models control effects the way **algebraic effects and handlers** (Plotkin & Pretnar,
§5.3) model non-local behavior: as a declared effect with an explicit handler/combination
rule, not as an ambient side channel.

### 3.3 Binder / Scope Discipline

Some control transfer is **non-local**: exceptions, labeled break/continue, return-from-outer.
These require:

- a `handler_install(catches, scope_covers, recovery)` node type — a genuine binder over a
  region of the derivation tree (cf. lambda-binding, or `try`/`except` block scoping),
- a **static reachability check** over the derivation tree: every control-emitting leaf must
  have, among its ancestors in the derivation tree, a handler/label declaration covering its
  signal type. This is checked by a single preorder traversal maintaining a stack of
  in-scope handlers (§4.3, §4.5 for worked examples).

This is structurally the same proof technique as **checked exceptions** (Java) or **binder
scope resolution** (lexical scoping, De Bruijn indices) — transplanted from "checking a
hand-written program" to "checking a specification before a program is generated."

### 3.4 Summary: the four combination shapes

Every nonterminal in every domain must be classified as exactly one of:

| Shape | Combination law | Soundness proof | Worked example |
|---|---|---|---|
| **Exclusive-choice** | guards partition spec-space; pick the one satisfied production | guard disjointness (static, decidable) | persistence strategy (§7.1) |
| **Disjoint-footprint accumulation** | list-generate; each item independently applicable | writes are pairwise disjoint | validation rules, sum+count (§7.2, §7.4) |
| **Semilattice fold** | combine via a declared commutative/associative join | join laws hold by construction of the order | authorization / deny-overrides (§7.3), control severity (§3.2) |
| **Binder-scoped reachability** | every emitting leaf has a covering ancestor handler | reachability over the derivation tree (preorder, stack-based) | exception handler coverage, labeled break (§7.5) |

**These four combinators are the entire built-in nonterminal vocabulary (hard line).** A domain
does not author nonterminals or combinators; it contributes **atoms** (§3.6) and **wiring** —
statements of which combinator hosts which atoms at which channel. The four combination laws are
proven once, in the system, and every domain inherits them; there is no per-feature soundness
proof. If experience ever shows a genuinely new combination shape is needed, it is added **to the
system** as a new built-in combinator with its own once-and-for-all soundness proof — never
authored by a user, and never admitted ad hoc. Records, sequences, and loops are **composites** of
these four (a record is `Accumulate` over disjoint named slots; the §7.4 loop is a `Scope` binding
iteration channels around an `Accumulate` of operations), not new primitives. Keeping the
vocabulary this small is precisely what makes a composite nonterminal's properties mechanically
derivable from its parts (§11.3).

A composition need that no built-in combinator serves is **not** silently accepted: it either
justifies a new system-provided combinator (with proof, as above) or is pushed into the
opaque-atom escape hatch (§3.5), where no compositional guarantee is offered.

**Cross-cutting / middleware features do not need a fifth shape.** The features people most want
from a generator — transactions, logging, caching, retries, audit — look at first like a distinct
"wrapper" shape (they enclose a region and interpose on it). But once middleware is required to
interact only through *declared channels* (§3.1), like every other nonterminal, it splits into
three cases, two of which the four shapes above already cover and the third of which reduces to an
established pattern:

- **Observers** (logging, audit, metrics) read region channels and write **only to a disjoint
  sink channel**. This is **disjoint-footprint accumulation** — provably safe in any order, no new
  theory. An observer that tried to write a non-sink channel would fail the disjointness check at
  design time, which is the correct outcome.
- **Binders** (transaction boundary, resource acquisition) install a handler over a derivation
  region, declaring what they catch and their recovery (`RAISE → rollback`). This is exactly
  **binder-scoped reachability** (§3.3). *This is how transactions enter the grammar* — modeled as
  a binder, not a wrapper, they are covered, so the earlier "v1-blocking" status is resolved.
- **Control-rewriters** (retry, cache short-circuit, circuit-breaker) re-enter or bypass the
  region based on a control signal. This is the only genuinely residual case, and it reduces to a
  **binder whose recovery re-invokes the region** (retry) or **returns a cached channel in place of
  running it** (short-circuit). Two control-rewriters on one region are order-dependent
  (retry-outside-cache ≠ cache-outside-retry), so — exactly as with `deny_overrides` vs
  `first_applicable` in §7.3 — **their order is promoted to an explicit spec-level decision (a
  combinator nonterminal), surfaced to the user and never silently chosen.** Non-commutativity is
  made visible rather than hidden; that is the whole discipline (§2), applied here.

So there is no fifth soundness theory: observers are accumulation, binders are §3.3, and
control-rewriters are ordered binder composition with a declared order. Business logic and
middleware alike reach the grammar as **typed callback atoms** (§3.6); the escape hatch (§3.5) is
only for behavior that cannot even declare an honest channel footprint.

### 3.5 The Opaque-Atom Escape Hatch

Some behavior is genuinely bespoke (a business rule, a novel algorithm) and does not belong in
any grammar. This is admitted as a **typed, boundary-declared atom**: a function with a
declared input/output type signature, whose interior is unanalyzed. Composition guarantees
hold up to the boundary and no further — the same discipline as Rust's `unsafe` blocks
(encapsulated behind a safe API), Haskell's `IO` monad (arbitrary effects behind a monadic
interface), Coq's `axiom`/`postulate`, and ordinary FFI. Two opaque atoms interacting with each
other are, in general, **not** checkable (this is where Rice's theorem bites, §6) — this is
accepted as a bounded, visible risk, not hidden.

**Coverage honesty.** In a real service, bespoke business logic is the *majority* of the code, so
opaque atoms will be numerous — the grammar generates the skeleton and its safe composition, not
the interior of most handlers. This bounds the value proposition: the guarantee covers the wiring
*between* atoms and *around* them, not the atoms themselves. Consequently the boundary that
matters most in practice is **atom-vs-grammar** — does an atom's declared type signature match the
channels the surrounding grammar exposes to it? — which *is* checked, rather than atom-vs-atom,
which is not. A standing design goal for each domain is therefore to keep an atom's declared
boundary narrow (few channels in/out) so the checked surface stays large relative to the unchecked
interior. Whether a given domain reaches useful coverage is an empirical question to settle with
the first end-to-end module (§8), not to assert here.

### 3.6 Business Logic as Typed Callback Atoms

An opaque atom's declared `reads`/`writes` footprint (§3.1, §3.5) *is already* a typed callback
contract — the design just has to emit it as one. This is the mechanism by which bespoke business
logic and middleware live in **separate, user-owned files that the generator picks up**, rather
than inside generated code that regeneration would clobber.

**The seam.** A spec declares a business-logic atom by its footprint plus an implementation
pointer:
```
business_logic:
  - atom: compute_discount
    reads:  [order.total, customer.tier]        # → callback parameters
    writes: [order.discount]                     # → callback outputs / mutations
    emits:  [TransientError]                      # optional; declared vs the severity lattice (§3.2)
    impl:   ./business/discount.py:compute_discount   # user-owned; never overwritten
```

**What the generator owns vs. what the user owns.** For each such atom the generator emits, and
*exclusively owns* (regeneration overwrites wholesale, §10.1):

1. **A typed interface** derived mechanically from the footprint — `reads` become parameters,
   `writes` become return values / declared mutations, `emits` become the control signals the
   callback may raise. In Python this is a `Protocol` (structural) or an ABC.
2. **A call site** in the generated skeleton that threads the exposed channels in and the written
   channels out, at the derivation point where the atom is declared.
3. **A stub** at `impl` *only if that file does not yet exist* — a signature-correct function body
   raising `NotImplementedError`, so the first generation is runnable and the human has a typed
   starting point.

The user owns, and the generator **never touches**, the body at `impl`. This is dependency
injection / callback wiring, chosen as the v1 default over the generation-gap subclass pattern
because it is the most testable (implementations are plain functions), avoids inheritance
coupling, and produces the cleanest regeneration diff. Subclass and plugin-registry wiring are
*alternate emission strategies for the same seam* — the contract (the channel footprint) and the
soundness law (below) are identical regardless of how the call site is physically wired, so the
choice is an emission backend, not a semantic one.

**The atom-vs-grammar boundary check, made mechanical.** At generation time the generator checks
the supplied implementation's signature at `impl` against the emitted interface (structural /
type check). A mismatch — the callback reads a channel the grammar does not expose at that point,
or fails to produce a declared `writes` channel — is a **design-time rejection**, with the error
UX of §8 step 3. This is precisely the "is the atom's declared boundary honest?" question from
§3.5's coverage-honesty note, turned from an aspiration into a check.

**Composition guarantee at the seam.** Because callback atoms interact only through declared
channels, the four shapes (§3.4) govern them unchanged, *even though their interiors are opaque*:

- Two atoms at the same scope compose safely iff their declared `writes` are pairwise disjoint
  (the frame rule, §3.1). If `compute_discount` and another atom both write `order.discount`, the
  disjointness checker rejects the spec at design time — a caught conflict, not a runtime race.
- An atom that raises a control signal must have a covering binder among its ancestors (§3.3),
  checked by the same reachability traversal — so a business-logic callback declaring
  `emits: [TransientError]` is only admitted where an enclosing handler (e.g. a `retry` or
  `transactional` binder) covers it.

The interiors stay unanalyzed (Rice's theorem, §6); the *composition of the interiors* is
guaranteed by their honest, checked footprints. That is the whole value proposition (§1) extended
to cover the bespoke majority of a real service, without pretending to analyze it.

---

## 4. Specification Language

The specification is a set of **deviation statements** against declared defaults. In v1 the spec
is **structured data** (YAML or an equivalent typed literal, per §4.2) validated directly against
the nonterminal tree — no natural-language parsing on the critical path, because ambiguity is
exactly the property this design cannot afford at its own input. A controlled-natural-language
(CNL) front-end is **deferred to a later phase as optional sugar** over the same typed structure:
a frame schema with typed slots corresponds one-to-one to a nonterminal with typed decision
points, so a CNL layer, if built, compiles down to — and is checked against — the structured
form; it never becomes an independent source of truth. Deferring it removes the highest-risk,
lowest-certainty component from the v1 critical path.

### 4.1 Decision points

Each nonterminal declares:
```
nonterminal <name>(<inputs>) -> <output type>
  shape: exclusive-choice | disjoint-accumulation | semilattice-fold | binder-reachability
  default: <production, guarded by "spec silent on this slot">
  productions: [...]
  combinator: <required for accumulation/fold shapes>
```

### 4.2 Spec vocabulary

A spec is a set of key/value deviation statements resolved against the nonterminal tree, e.g.:
```
resource UserAccount:
  persistence: sql(table=users)
  validation: required(name, email), range(age, 0, 120)
  authorization: combining_algorithm(deny_overrides), grant(role=admin, action=*), deny(role=guest, action=delete)
```

### 4.3 Determinacy requirement

For exclusive-choice nonterminals: guards over the spec must be pairwise disjoint and jointly
exhaustive (including an explicit "absent" default guard) — checkable as a static
disjointness/exhaustiveness analysis, directly analogous to **moding/determinacy analysis in
logic programming** and to semantic-predicate-guarded alternatives in **attribute grammars**
(Knuth) and parser generators (ANTLR).

Disjointness is only *statically decidable* if the guard language is deliberately restricted. v1
fixes it to a **decidable fragment**: a guard is a boolean combination of (a) presence/absence of
a spec key and (b) equality of a spec key against a literal drawn from a declared finite enum.
Under this fragment, pairwise disjointness and joint exhaustiveness reduce to a finite
propositional / enum-cover check (decidable and cheap). Guards requiring arithmetic, string
relations, or arbitrary predicates are **not** admitted at an exclusive-choice point — that logic
belongs inside an opaque atom (§3.5), not in a guard whose disjointness we claim to prove. This
restriction is what makes the decidability claim above *earned* rather than aspirational.

### 4.4 Cross-domain import

A nonterminal `N` from domain `B` may be invoked from domain `A`'s grammar (`N` treated as an
atom in `A`) if and only if:
- `N`'s declared data channels are typed in the shared channel-type system,
- `N`'s control channel severities are declared against the shared lattice (or an explicit,
  reviewed embedding is supplied between `A`'s and `B`'s lattices),
- `N`'s binder/scope requirements are resolvable within `A`'s enclosing scope structure.

If these hold, the import is checked structurally (interface compatibility), without needing
to inspect or trust `B`'s internal derivation logic — the same guarantee a type signature
gives an ordinary function call, generalized to this system's four combination shapes. This
is the operative content of "island grammar" composition (§5.4, §7.6).

**Two capabilities, one substrate — do not conflate them.** (a) *Swapping* alternatives within one
axis (a `sql` vs `file` persistence, a FastAPI vs Flask serving layer) is **not** cross-domain
import at all; it is an exclusive-`Choice` whose productions present the *same* channel contract, so
a swap is one deviation and everything downstream — written against the channels, not the backend —
is untouched. (b) *Combining* different axes (a pandas pipeline hosted inside a REST endpoint) **is**
cross-domain import, checked at the seam through footprints, but requiring hand-written adapters
between channel types (§6, limit 5). The swap in (a) is also where the system earns its keep by
*rejecting* invalid compositions at design time: a `Scope` that uses `tx` swapped onto a `file_store`
that provides no `tx` is refused, not silently emitted. A full worked treatment — the two `Choice`
axes, the pandas dialect, the adapters, and a swap matrix of which cells typecheck — is in
[`cross-domain-example.md`](cross-domain-example.md).

### 4.5 Emission

Once a derivation tree is fully resolved (every nonterminal reduced to a single production,
every accumulation/fold list-combined, every control/binder check passed), emission to target
source (e.g. Python via the `ast` module or `libcst`, or template-based string emission) is a
deterministic, mechanical tree-to-code transformation — no search, no ambiguity.

---

## 5. Literature and Precedent

### 5.1 Feature interaction (the problem this design targets)
- Telecom feature interaction problem: independently-correct call features (Call Waiting,
  Call Forwarding, Voicemail, etc.) combine into undefined or wrong behavior. Named and
  studied from the early 1990s; spawned the Feature Interaction Workshop series. No general
  detection algorithm exists for arbitrarily added features — motivates *design-time
  prevention* over *post-hoc detection* (§6).
- Pamela Zave, **Distributed Feature Composition (DFC)**: restricts features to a narrow,
  declared signal interface; features cannot reach into each other's internal state;
  interaction becomes structurally hard to produce rather than merely hard to detect. Direct
  model for §3's channel-declaration discipline.

### 5.2 Program verification / composition proofs
- O'Hearn, Reynolds — **separation logic** and the **frame rule**: disjoint footprints compose
  safely with no case-by-case interaction check. Model for §3.1.
- Reiter — **default logic**: formal non-monotonic reasoning built around "assume the default
  unless blocked by an exception." Model for exclusive-choice defaults (§3.4).
- Stable model semantics / ASP (clingo): "generate–define–test" methodology; default negation
  as the formal analogue of default-with-exception.

### 5.3 Effects and composition algebra
- Moggi — **monads for computational effects**: solved an analogous composition problem for
  side-effecting computations by changing representation (raw effectful functions → a
  structure with proven composition laws, Kleisli composition). Direct precedent for "the
  interaction problem is sometimes a representation artifact, not an essential limit" (§6).
- Plotkin & Pretnar — **algebraic effects and handlers**: modular, composable effects without
  monad-transformer stacking; model for §3.2/§3.3 (control channels as declared effects with
  handlers).
- Fong & Spivak — **operads / applied category theory for compositional system design**: boxes
  with typed inputs/outputs, wired together under proven composition laws.

### 5.4 Grammar-driven generation
- Knuth — **attribute grammars**: grammar decorated with synthesized/inherited attributes;
  extended (ANTLR semantic predicates) to let attributes gate which production is legal.
- Van Wijngaarden — **two-level (W-) grammars**: a metagrammar generates the object grammar's
  production rules; used for ALGOL 68's formal semantics. Closest formal precedent for
  "specification drives which productions exist."
- **Definite Clause Grammars (DCGs)** in Prolog: grammar rules threaded with logic-variable
  arguments; production choice driven by unification. Directly implementable using existing
  SLD-resolution machinery.
- Czarnecki & Eisenecker — **generative programming**; Batory — **AHEAD**, step-wise
  refinement, delta-oriented programming; Kang — **FODA** feature models. Established
  isomorphism between cardinality-based feature models and restricted attributed grammars.
  Encountered the feature-interaction problem in practice; typically resolved by hand-specified
  composition order rather than a proven-coherent algebra — the gap this design closes.
- **MLIR** (multi-level IR): one universal operation/interface contract; many domain-specific
  "dialects" built on top; dialects composable and lowerable into each other because every
  operation satisfies the same typed-interface contract regardless of domain. Direct working
  precedent for §3–§4.4 (cross-domain composition via a shared substrate).
- Gulwani et al. — **FlashFill / programming-by-example**: succinct spec (I/O examples) +
  small closed DSL + search for smallest consistent program. Related but distinct: this design
  uses **explicit deviation statements**, not examples, so composition is resolved by
  deterministic rewriting, not CEGIS-style search.
- Solar-Lezama — **Sketch / syntax-guided synthesis**: programs with holes (`??`) filled by a
  spec-guided counterexample loop. Related; this design's "holes" (decision points) are filled
  by direct spec lookup rather than search, when guards are fully disjoint.

### 5.5 Decidability and its limits (why full generality is not the target)
- Rice's theorem: no algorithm decides any non-trivial semantic property of programs in a
  Turing-complete system, in general — the reason opaque atoms (§3.5) cannot be given
  compositional guarantees, and the reason this design is deliberately domain-scoped rather
  than universal (§6).
- Subrecursive hierarchy (Grzegorczyk, fast-growing hierarchy), Ackermann function: no maximal
  terminating fragment of Turing-completeness exists — noted for completeness; **not** a
  binding constraint on this design, since termination of generated programs is explicitly out
  of scope (per user direction, §1). Included here only because it clarifies why "restrict to
  a safe fragment" cannot be pursued via a termination argument, should that question resurface.
- Bernays–Schönfinkel–Ramsey, Ackermann class, FO², guarded fragment: maximal decidable
  fragments of first-order logic, mutually incomparable — relevant if decision points are ever
  expressed in a fuller relational/descriptive logic than plain guarded productions.

### 5.6 Closest existing implementations (and why none is the whole architecture)

No known system implements the full architecture of this document — deviation-driven grammar
derivation + typed-channel composition via the frame rule + the four combination shapes (§3.4) +
callback-atom escape hatch (§3.6), emitting Python. The *ingredients* each have real, battle-
tested implementations; the load-bearing novelty is their combination into a **proven-coherent
combination algebra** over deviations, rather than hand-ordered composition. The closest real
systems, and the specific gap each leaves, are worth mining for reusable parts and cautionary
tales:

- **Feature-oriented / product-line generators** — AHEAD/Jak, FeatureHouse, FeatureIDE,
  pure::variants (Batory et al., §5.4). Closest in *spirit*: compose a program from selected
  features. But Java-centric, and they resolve feature interactions by **hand-specified
  composition order**, not a proven algebra — the exact gap this design targets. Read for how
  they hit the interaction wall in practice.
- **MLIR / IRDL** — the substrate model (§3, §4.4), real and load-bearing, but a C++ compiler IR,
  not a Python application generator. Precedent for the dialect architecture, not the emission
  target.
- **Language workbenches** — JetBrains MPS, Spoofax: typed, composable transformations with code
  generators, but targets are typically Java/DSLs, and composition safety is not framed as a
  frame-rule / footprint discipline.
- **Nanopass** (Racket/Scheme) — typed, checked compiler passes; structural cousin of "each
  nonterminal checked locally," but compiler-writing, not application codegen, and not Python.
- **Schema→Python generators** — `datamodel-code-generator`, OpenAPI/FastAPI codegen,
  Cookiecutter/Copier. Real and Python-native, but contract-surface or template-only: no channels,
  no combination algebra (the §9 positioning line).
- **Effect libraries in Python** — `returns`, `effect`: runtime plumbing reusable for §3.2/§3.3
  (control channels as declared effects), but libraries, not generators.

**Closest formal analog to the local-proof claim (narrows what is actually novel).** The §1
promise — "adding a deviation needs only a *local* proof, never global re-verification" — is
*not itself* new; it has real precedent that this design borrows rather than invents:
- **Compositional / modular verification of software product lines** (Fisler & Krishnamurthi,
  *modular verification of open features via three-valued model checking*; *variation-point
  obligations*; compositional/algorithmic SPL model checking). These reduce verifying a whole
  product line to verifying individual features against declared interfaces — exactly the "check
  the feature in isolation, compose the results" structure of §3. They verify *properties* by
  model checking, where this design checks *composition safety* by construction; the shared idea
  is the carefully-designed interface that makes local checking sound.
- **Compositional type-checking for delta-oriented programming** (Schaefer, Bettini et al.;
  DeltaJava): a constraint-based type system generates constraints for **each delta module in
  isolation** and guarantees every valid configuration is type-correct — the type-safety analog
  of this design's per-nonterminal admission check. The literature's own recurring caveat is the
  honest warning for §8.2/§6.4: interfaces must carry enough information for local checking *and*
  be inferable by tooling, "because programmers cannot or will not provide it manually."

So the novelty is narrower and more defensible than "local proofs of composition": it is the
**specific synthesis** — deviation-from-default specs driving a *grammar derivation*, composed
through a *typed-channel frame-rule substrate* under the *four shapes*, with bespoke logic entering
as *checked callback atoms* (§3.6), emitting a real target language (Python). Each ingredient is
attested; the combination is not.

**Live corroboration of the positioning (§9).** The 2025–2026 "spec-driven development" wave
around LLM codegen independently reports the exact failure this design's determinism/non-
interference claim targets: LLM generation is **non-deterministic even at temperature 0**, and
"specification gaps resurface in unpredictable forms upon regeneration" (SANER 2026 registered
report on specification-driven code generation; industry write-ups on spec-driven development).
The reliability responses in that literature operate at the *token/syntax* level — grammar-
constrained and type-constrained decoding (SynCode, Pre3, type-constrained decoding), and layered
constraint-guided structured generation for LLM-assisted MDE (ATLAS) — not at the *composition-
algebra* level. This both validates the §9 framing (an LLM front-end needs a deterministic,
non-interfering back-end) and confirms the gap: current work constrains what a model may *emit*,
not whether independently-specified features *interact* — which is this design's subject.

**The honest read after searching (July 2026).** The pieces are all real and, in several cases,
mature; the central unimplemented claim is the proven-coherent deviation algebra driving
application generation, in place of hand-ordered composition. That is both the risk (unproven
end-to-end) and the reason it is worth building (not a reimplementation). No system found in this
survey combines the full architecture; "novel synthesis of attested parts" is a defensible
external claim, "novel local-composition proofs" is **not** — cite the SPL-verification and
delta-typing lineage above when making it.

---

## 6. Explicit Scope and Limits

1. **Domain-scoped, not universal.** One grammar per software category (REST services, data
   pipelines, etc.). Cross-domain composition (§4.4) requires a shared typed substrate, not a
   shared nonterminal vocabulary — proven by MLIR's dialect system, not merely hypothesized.
2. **Soundness, not completeness.** Checks that exist (guard disjointness, footprint
   disjointness, lattice-join laws, reachability) are trustworthy. Interaction shapes not yet
   classified into one of the four categories in §3.4 are not silently declared safe — they
   are refused admission to the grammar and must go through the opaque-atom hatch, where
   failures degrade to ordinary runtime bugs (no worse than hand-written code, never silently
   worse).
3. **No termination or general runtime-correctness guarantee**, by design choice (§1) — this
   system targets composition safety of deviations, not program correctness in general.
4. **Design effort is front-loaded and real.** Classifying each nonterminal's combination shape
   correctly is genuine, non-automatable design work (cf. the authorization and control-flow
   misclassifications found during design, §7.3, §7.5).
5. **Translation between domains' channel types is not automatic.** A shared substrate makes
   compatibility *checkable*; it does not make cross-domain data adapters free (cf. MLIR
   lowering passes, hand-written and nontrivial in practice).
6. **The guarantee is conditional on honest footprint declarations.** Every soundness check in §3
   trusts that a production's declared `reads`/`writes`/control/binder footprint accurately
   describes the code it emits. Nothing statically verifies emitted template code against its
   declared footprint — that would run straight into Rice's theorem for non-trivial templates. A
   template that quietly touches an undeclared channel makes every downstream disjointness proof
   fiction. This is mitigated *empirically*, not proven away, by the **non-interference diff
   test** (§8 step 9, §10): regenerate after changing one deviation and assert the output diff
   stays within that deviation's declared footprint — a dishonest declaration surfaces as an
   out-of-footprint diff. The residual risk (an interaction the test's generated spec-changes
   never exercise) is accepted and visible, not hidden.
7. **Cross-cutting / middleware features are covered, but control-rewriters carry a required
   ordering decision.** Observers reduce to accumulation and binders (incl. transactions) to §3.3
   (§3.4); the residual case — retry, cache short-circuit, circuit-breaker — is sound only once the
   user makes their composition order an explicit spec decision (§3.4, §7.7). The design surfaces
   that non-commutativity rather than resolving it silently; it does not eliminate the decision.

---

## 7. Worked Examples (from design sessions)

### 7.1 Exclusive-choice: persistence strategy
Guards over spec presence/absence of a `persistence` key partition disjointly (`sql`,
`document`, `in_memory`, and a default `sql` fallback guarded by key-absence). Exactly one
production fires per spec — verified by construction of the guards, no search needed.

### 7.2 Disjoint-footprint accumulation: validation rules
Each validation rule (`required(...)`, `range(...)`) is independently applicable; rules don't
reference each other, so list-accumulation is sound without needing a fold.

### 7.3 Semilattice fold: authorization (deny-overrides)
Naively modeled as accumulation, but `grant`/`deny` on the same (subject, action) pair
conflict — not independent. Resolved via a declared, commutative combining algorithm
(`deny_overrides` = join over `{not_applicable < grant < deny}`), matching real-world XACML
combining algorithms. The choice of algorithm (`deny_overrides` vs. `permit_overrides` vs.
`first_applicable`, the last being deliberately non-commutative) is itself a spec-level
decision — i.e., a nonterminal whose output is a combinator for another nonterminal.

### 7.4 Loop/operation composition (data channels)
A `loop` nonterminal declares bound and pass-through channels (`item`, `acc`); an `operation`
nonterminal is only composable if its `reads`/`writes` are a subset of what the loop exposes.
Two operations (`sum`, `count`) compose safely in one pass once given disjoint accumulator
channels (`acc_sum`, `acc_count`) — the frame rule made operational.

### 7.5 Control flow: break, severity lattice, exceptions, labeled break
- Naive modeling of `break` as a data write silently changes the meaning of co-composed
  operations (an undetected telecom-shaped interaction) — motivates §3.2's severity lattice.
- Exceptions require binder-scoped reachability (§3.3), structurally distinct from local
  lattice combination — conflating the two reintroduces silent brittleness.
- Labeled break/continue resolved as a reachability/binder-resolution check identical in
  shape to exception coverage; compiled down to Python's flag-variable idiom since Python
  lacks native labeled break.

### 7.6 Cross-domain: compiler embedded in REST, and vice versa
"Compiler behind a REST endpoint" composes safely at a single seam (REST invokes the
compiler's start symbol once, treats the result as a typed atom). "Compiler invoking REST at
each internal step" requires the compiler's per-stage nonterminals to be re-typed as producing
an effect type (Kleisli composition through a REST-call effect), or termination/determinism
guarantees silently stop holding partway through the derivation.

### 7.7 Business logic + middleware via callback atoms (`Order` resource)
A spec combines generated skeleton, hand-written business logic, and three middleware features:
```
resource Order:
  persistence: sql(table=orders)
  business_logic:
    - atom: compute_discount
      reads:  [order.total, customer.tier]
      writes: [order.discount]
      emits:  [TransientError]
      impl:   ./business/discount.py:compute_discount   # user-owned; never overwritten
  middleware:
    - audit(sink=audit_log)              # observer  → disjoint-footprint accumulation (§3.4)
    - transactional(on_error=rollback)   # binder    → binder-scoped reachability (§3.3)
    - retry(max=3, on=TransientError, order_vs=[])   # control-rewriter → ordered binder
```
What the four shapes deliver here:
- `audit` writes only `audit_log`, disjoint from `order.discount` — accumulation, order-free, no
  proof obligation beyond the disjointness check.
- `transactional` is a binder covering the region; `compute_discount` declares
  `emits: [TransientError]`, so the reachability traversal admits it only because `retry`/
  `transactional` cover that signal — a business-logic callback's control effect is checked
  exactly like a built-in one.
- `compute_discount` lives in `./business/discount.py`; the generator emits a `ComputeDiscount`
  Protocol and a call site, checks the hand-written function's signature against the Protocol
  (atom-vs-grammar boundary check, §3.6), and never overwrites the file on regeneration (§10.1).
- **The forced decision:** add a second control-rewriter, `cache(key=order.id)`, and its order
  against `retry` is not inferable — `retry`-outside-`cache` retries a cache miss, `cache`-outside-
  `retry` caches the post-retry result. The generator refuses to pick and requires an explicit
  order (`retry(order_vs=[cache])`), the §7.3 combinator-as-spec-decision pattern applied to
  middleware. Non-commutativity is surfaced, not silently resolved.

### 7.8 Where a callback atom is *not* enough
If a "business rule" cannot declare an honest channel footprint — it reaches into global state,
performs undeclared I/O, or mutates channels it did not list — it is not a §3.6 callback atom; it
is a bare opaque atom (§3.5) with no composition guarantee. The dividing line is empirical and is
caught by the non-interference diff test (§6.6, §8): a footprint that lies shows up as an
out-of-footprint diff on regeneration.

### 7.9 Swapping and composing across domains (`persistence`, `serving`, a pandas dialect)
Two mechanisms that are easily conflated (§4.4): *swapping* `sql`↔`file` persistence or
FastAPI↔Flask serving is a single-deviation `Choice` when the alternatives share a channel contract
(the spec names `store`/`route.*`, never the backend), whereas *combining* a pandas pipeline into a
REST endpoint is genuine cross-domain import over hand-written adapters (`frame`→`record`). The swap
is where design-time rejection pays off: a transaction `Scope` that uses `tx`, swapped onto a
`file_store` that provides none, is refused rather than emitted as a fictional file "transaction".
The cost is *additive* (each domain and each adapter authored once) rather than *multiplicative*
(every combination hand-written). Worked in full, with a swap matrix of which cells typecheck, in
`cross-domain-example.md`.

---

## 8. Implementation Roadmap

1. **Pick one target domain** (recommend: REST/CRUD services — best prior art, clear decision
   points, reusable frame-schema tooling). Spec is structured data in v1 (§4); no CNL yet.
2. **Enumerate 5–8 real decision points** for that domain; classify each into one of the four
   shapes in §3.4 by hand, on paper, before writing any code. Be honest that 5–8 is a *spike*
   figure: a genuinely useful REST domain needs dozens of decision points, and hand-classifying
   each is the real, non-automatable adoption cost (§6.4) — this roadmap validates the mechanism
   on a slice, it does not retire that cost.
3. **Implement the channel-type system** (§3.1) and a disjointness checker. Make its **failure
   output** a first-class deliverable: a rejection must name the two conflicting deviations, the
   shared channel, and their spec locations (e.g. "`range(age,…)` and `required(age)` both write
   channel `age.validated` — spec lines 4 and 5"), never a raw combinator soundness trace. For a
   system whose pitch is *design-time rejection*, the rejection UX **is** the product.
4. **Implement the control-severity lattice** (§3.2) and combinator — a join over a declared
   semilattice, not assuming a total order.
5. **Implement binder/reachability checking** (§3.3) via preorder traversal with a handler
   stack.
6. **Implement the DCG-style derivation engine** (Prolog, or a Python equivalent using guard
   functions + dataclasses if a Prolog runtime dependency is undesirable).
7. **Implement deterministic emission** to Python (`libcst` recommended for round-trippable,
   reformattable output; template-based emission acceptable for a first pass).
8. **Property-test every combinator** (via `hypothesis`): generate random deviation sets,
   assert combination is order-independent for accumulation/fold shapes.
9. **Implement the non-interference diff test** (§10) — the operational form of the whole thesis:
   generate from a spec, change exactly one deviation, regenerate, and assert the output diff is
   confined to that deviation's declared footprint. This tests the core promise end-to-end *and*
   empirically catches dishonest footprint declarations (§6.6). It gates step 10.
10. **Generate one working module end-to-end**, including at least one opaque atom and one
    regeneration cycle (§10), before expanding the nonterminal set further — to surface
    misclassifications, coverage reality (§3.5), and ownership issues early and cheaply.
11. **Only after step 10**: consider a second domain and the cross-domain import mechanics of
    §4.4, using MLIR's dialect model as the architectural reference.

---

## 9. Positioning: Why This, Not X

The design is only worth building if it beats the tools a team would otherwise reach for. Its
distinctive, defensible property is **deterministic, non-interfering, safely-regenerable
composition** — not code generation per se, which is a solved commodity.

- **vs. a DSL / combinator library with good defaults.** This is the closest honest comparison, and
  the one to make explicitly. For a single static program the two are near-equivalent in what a user
  writes — a well-designed combinator DSL already hides most glue. The distinction is not
  expressiveness or terseness; it is three things an ordinary DSL does not provide: (a) a
  **deviation-from-default** model, so a spec states only what differs rather than re-spelling the
  whole composition; (b) a **footprint discipline** that mechanically forbids two composed pieces
  from secretly touching the same state — a normal combinator library will happily let two
  accumulated items both mutate one field; and (c) restriction of the combining forms to **four
  shapes proven non-interfering once**, so the composition law is checked, not merely available. The
  payoff is not on one program; it is across **change** (regeneration asserts non-interference),
  **N-way combination** (local checks inheriting one proof instead of an O(N²) hand-audit), and
  **cross-domain** composition of dialects through the shared substrate (§4.4). Put sharply: an
  ordinary DSL gives you combining *forms*; this gives you combining forms that *default*, *check
  footprints*, and *carry a soundness proof* — and a worked contrast is
  [`order-example.md`](order-example.md).
- **vs. Rails/Django scaffolding, Yeoman, `create-*` generators.** These emit a one-shot starting
  point with no algebra for combining options and no story for re-running after the code diverges
  (the generation-gap problem, §10). This design's entire content is the combination algebra and
  the regeneration discipline they lack.
- **vs. OpenAPI / gRPC / IDL code generators.** These generate faithfully from a schema, but only
  for the *contract surface* (serialization, client/server stubs); behavior composition
  (authorization × validation × persistence × transactions) is left to hand-written glue — the
  exact place feature interactions arise. This design targets that interior.
- **vs. an LLM generating the whole service.** An LLM is faster and broader for the *bespoke*
  interior (i.e. the opaque atoms, §3.5), but offers no composition guarantee: regenerate after a
  requirement change and unrelated behavior can silently shift — precisely the §2 failure mode.
  The two are complementary, and the most promising framing is **LLM front-end, sound back-end**:
  let an LLM draft or edit the *deviation spec* (fuzzy natural-language intent → structured
  deviations) and let the grammar guarantee that the composition of those deviations is
  non-interfering and deterministically emitted. Under this framing the human/LLM works in intent
  space, the grammar owns the interaction discipline, and opaque atoms are where LLM-authored
  bespoke code legitimately lives behind a checked boundary. This inverts the usual worry ("can I
  trust LLM-generated code?") into a bounded one ("is this atom's declared boundary honest?") —
  the §6.6 question the diff test already targets.

The honest one-liner: existing tools generate code; this generates *safe combinations of
deviations* and re-generates them after change without silent reinteraction — and that is the only
claim it needs to win on.

**The sharpest single statement of the benefit.** Every time ordinary code places two statements in
sequence, it bakes in an ordering-and-interaction assumption that is *invisible and unenforced* —
swap `apply_discount(order)` and `apply_tax(order)` and you get wrong invoices with no error. This
design takes every seam between pieces and forces it to be one of three *visible* things instead: an
**explicit** dependency in the declared footprints (derived and reviewable), a **rejected** conflict
named at design time (the shared channel and both culprits), or a **declared decision** where an
order is genuinely non-commutative (surfaced, handed back to the user). It never silently guesses an
order or silently assumes a combination is safe. It does **not** reduce how much bespoke logic is
written — interiors stay opaque and carry ordinary code's risk — it moves the *seams between* that
logic from hand-maintained to design-time-checked. The bet worth validating (§8) is that most
cross-feature defects live in those seams, not the interiors. [`order-example.md`](order-example.md)
makes this concrete on an `Order` service.

---

## 10. Regeneration, Ownership, and Grammar Versioning

A code generator lives or dies on what happens *after* the first generation. The compositional
guarantees of §3 are worthless if a spec change, a hand-edit, or a grammar upgrade silently
reintroduces the interaction problem at the meta level. The discipline:

### 10.1 Ownership boundary
- **Generated files are never hand-edited.** They are build output; regeneration overwrites them
  wholesale.
- **Bespoke logic lives in user-owned files**, referenced by the spec via path + typed signature
  (the opaque-atom boundary, §3.5). Regeneration never touches these; it only re-wires the
  generated skeleton's calls into them. This is the standard resolution of the **generation-gap
  problem** (generated superclass, hand-written subclass), lifted to the spec level.

### 10.2 Idempotent, deterministic regeneration
- Given the same `(spec, grammar-version)`, emission is byte-for-byte reproducible — no search, no
  nondeterministic ordering (§4.5). Regeneration is a pure function of its inputs and yields a
  reviewable diff.
- **Non-interference is a testable property of regeneration, not a hope** (§8 step 9, §6.6):
  changing one deviation must produce a diff confined to that deviation's declared footprint.

### 10.3 Grammar versioning and default drift
The design forbids features from silently reinteracting; it must hold *itself* to the same
standard when the grammar evolves.
- **Specs pin a grammar version.** A spec is only meaningful against the grammar version it was
  authored for.
- **A changed default is a breaking change, surfaced explicitly.** If grammar v3 changes the
  default persistence from `sql` to `document`, every spec that was *silent* on that slot would
  silently change behavior — the §2 failure mode reintroduced at the meta level. Such changes must
  be emitted as an explicit, diffable **migration note** ("v3: default persistence sql→document; N
  specs silent on this slot will change behavior — review or pin"), never applied silently on
  upgrade.
- **Migration is opt-in and reviewable.** Bumping a spec's pinned grammar version is a deliberate
  act that produces a regeneration diff the user reviews, exactly like any other deviation change.

---

## 11. The Specification and Grammar Language

There is **one surface language**, not two. A grammar rule and a specification are the same kind
of object — a *derivation term* — at different degrees of abstraction. This section fixes the
design decisions taken for that language; the concrete surface grammar is pinned during
implementation (§8), and the sketch below is illustrative, not frozen.

### 11.1 One language, two modes

The single underlying object is a **derivation term**. Two usage modes sit on it:

- **Spec mode** — a derivation term with its decision points *filled* (a deviation) or *left to
  default*. A spec is a **sparse overlay** of deviations over the default derivation. Ground
  (fully-filled) specs are terms/values, not reusable abstractions.
- **Grammar mode** — a derivation term *abstracted over* one or more decision points and given a
  name plus a declared interface. This is lambda abstraction: a term with free decision points,
  abstracted and named, becomes a nonterminal; a closed term does not.

Because it is one language, terms, defaults, and the path addressing of §11.4 are shared across
both modes. The two are not two syntaxes compiling to a common core; they are two ways of writing
the same core.

### 11.2 The vocabulary: four system combinators, plus atoms and wiring (hard line)

The built-in nonterminal vocabulary is exactly the four combinators of §3.4 — `Choice`,
`Accumulate`, `Fold[join]`, `Scope[catches]` — each proven sound once, in the system. A domain
author writes only:

- **atoms** (§3.6): terminals with a declared channel footprint and an `impl` pointer, and
- **wiring**: which combinator hosts which atoms at which channel.

Users never author combinators. If development reveals a genuinely new combination shape is
required, it is added as a **new system combinator with its own once-and-for-all soundness
proof** — a change to the system, not something a user supplies ad hoc. Records, sequences, and
loops are composites of the four (§3.4), not new primitives. This hard line is what makes §11.3
possible.

### 11.3 A composite nonterminal's properties are (mostly) derived, not declared

Split the composition-governing properties of a nonterminal `N` that expands to elements
`e₁ … eₖ`:

- **Footprint — synthesized bottom-up (derivable).**
  `reads(N)  = ⋃ reads(eᵢ)` minus channels produced by an earlier `eᵢ` and consumed by a later one
  (internalized); `writes(N) = ⋃ writes(eᵢ)` (minus internalized); `emits(N) = ⋃ emits(eᵢ)` minus
  signals caught by a `Scope` among the `eᵢ` (this subtraction *is* the §3.3 reachability
  discharge). This is a plain synthesized-attribute computation. Note the duality: footprint is
  **declared at the leaves** (atoms are opaque — Rice's theorem, §6) and **synthesized at every
  internal node** (nonterminals are transparent structure).
- **Shape — read off, not inferred.** The shape of a composite *is* its outermost combinator.
- **Soundness obligation — mechanically checked.** The hosting combinator's law over the derived
  footprints: `Accumulate` → pairwise-disjoint `writes`; `Scope` → reachability; `Choice` → guard
  disjointness/exhaustiveness on the decidable fragment (§4.3); `Fold` → the join's laws (which
  hold by construction of the declared order).

What is **not** derivable is *intent* — that `deny_overrides` rather than `permit_overrides` is
what the author meant. The system never infers the shape: the author **proposes** a combinator and
the derived properties **refute** a wrong proposal (e.g. two atoms under `Accumulate` that both
write `auth.decision` fail the disjointness check, pointing at `Fold`). Propose-and-check, not
infer-intent. So for any grammar built from the four combinators over atoms, footprint + shape +
soundness obligation are all mechanically derived from the RHS; the sole irreducible human input
is the choice of combinator (and, for `Fold`, the join), and a wrong choice is caught, not
silently accepted.

### 11.4 Specs as deviation overlays, addressed by dot-path

A spec states only deviations, so it is a sparse patch and each deviation needs an **address**.
Addresses are **dot-paths** over named decision points. This is the *extensional* mode of choosing —
name a locus, set its value; §12 adds an *intensional* mode (state a property, let it resolve across
every point it touches). Decisions taken:

- **Named and structural, never positional.** Decision points carry stable identifiers; paths
  address those, not indices. A path is a name *into the grammar*, hence a versioned artifact
  (§10.3): a grammar refactor that preserves names preserves specs.
- **Navigation for single-locus points; collection verbs for the rest.** Dot-navigation
  (`persistence.table`) addresses `Choice` points and reaches *into* a chosen production. For
  `Accumulate` and `Fold` — which hold many items — deviations use `+=` and set-literals, not
  navigation into a nonexistent single child.
- **Deep paths presuppose upstream choices — propose-and-report.** `order.persistence.table` only
  exists if `persistence` resolved to `sql`. A deep deviation **proposes** the upstream choices
  needed to reach it (`persistence.table = orders` implies `persistence = sql`); if that proposal
  conflicts with another deviation, it is reported through the **same machinery as a
  disjointness/feature conflict** (§7.3, §8 step 3). Path-presupposition failure and feature
  conflict are one error channel, not two.

### 11.5 Spec-as-nonterminal via abstraction

"A spec is the description of a new nonterminal" holds **exactly when the spec has holes**.
Abstract a deviation overlay over one or more decision points, name it, and it is a new production
of some nonterminal — the reuse mechanism, and the delta-oriented model of §5.6 (a spec is a set
of deltas). The caveat, from §11.3: abstraction yields the RHS/expansion for free but *not* the
combination law. Spec-with-holes is a nonterminal **structurally always**, and a **sound**
nonterminal only once its shape is supplied or (being built from the four combinators) derived.

### 11.6 A concrete sketch (illustrative)

```
# ── atoms (terminals): declared footprint, opaque interior ──
atom compute_discount:
  reads  order.total, customer.tier
  writes order.discount
  emits  TransientError
  impl   ./business/discount.py:compute_discount

# ── grammar: name an abstracted derivation term; shape = outermost combinator ──
nonterminal Persistence = Choice {
  key.absent | key=sql -> sql(table: Ident)
  key=document         -> document(collection: Ident)
  key=in_memory        -> in_memory()
}                                     # shape derived: exclusive-choice; footprint synthesized

nonterminal Resource(name: Ident) = record {          # record = Accumulate over named slots
  persistence:   Persistence                default sql(table: name)
  validation:    Accumulate<Validation>     default {}
  authorization: Fold[deny_overrides]<Auth> default {}
  logic:         Accumulate<Business>       default {}
}

# ── spec: a sparse overlay of deviations, addressed by path (a ground term) ──
Order : Resource("orders")
  .validation    += required(name), range(age, 0, 120)
  .authorization += grant(role: admin, action: *), deny(role: guest, action: delete)
  .logic         += compute_discount

# ── spec-as-nonterminal: same overlay, abstracted over a hole → a new production ──
nonterminal AuditedResource(name) = Resource(name)
  .logic += audit(sink: audit_log)     # table stays a parameter ⇒ still a nonterminal
```

### 11.7 Status

The decisions fixed here — one surface language, four system combinators (hard line), derived
properties with proposed-and-checked shape, dot-path addressing with propose-and-report
presupposition — are stable design commitments. The concrete grammar of the language (tokens,
precedence, exact keywords) is deferred to implementation (§8) and is expected to be refined
against the first end-to-end module before being frozen.

---

## 12. Two Modes of Choosing: Point Deviations and Cross-Cutting Constraints

A spec resolves a derivation by fixing its open decision points. There are two **structurally
different** ways to do that, and conflating them is a mistake worth calling out explicitly, because
only the first is in the language today (§11.4) and the second is a compatible extension with one
load-bearing rule.

- A **point deviation** is *extensional*: it names one locus by dot-path and sets its value
  (`.persistence = sql`). Local, imperative, auditable — but it says nothing about any other point,
  and it presupposes the author knows *which* locus to set.
- A **cross-cutting constraint** is *intensional*: it states a property of the *whole system*,
  addressed to no single path, that must (or should) hold at **every decision point where it is
  relevant, simultaneously**. `requires tx` is not a fact about persistence; it is a fact about the
  system that happens to constrain persistence, caching, the transaction boundary, and every other
  point that touches `tx`.

The first says *where* and *what*; the second says *what property*, and lets the system work out
*where* it bites. This section specifies the second mode so that it never degrades into the silent
optimizing planner the whole design exists to avoid (§2).

### 12.1 Two strengths of cross-cutting constraint

- **Requirements (hard)** must hold. A requirement **narrows** the admissible productions at every
  relevant point to those compatible with it. `requires tx` removes `file_store` from the
  persistence `Choice` wherever a `tx`-using boundary is in scope.
- **Preferences (soft)** are a declared bias/order over admissible productions, applied at every
  relevant point to **tie-break** among options a requirement has already left open (`prefer
  in_memory where admissible`). A preference may only choose among requirement-survivors; it can
  never overrule a requirement.

### 12.2 Resolution semantics — narrow, then force / surface / reject

At each still-open point, intersect its admissible productions with what the active requirements
allow. There are exactly three outcomes:

1. **Exactly one survives → forced.** Deterministic and unique — this is unit propagation, the §4.3
   determinacy analysis run in *selection* mode rather than *rejection* mode.
2. **Several survive → surfaced** as a design-time decision, *never* a silent pick — unless a
   *declared* preference tie-breaks to one. This is the §7.3 / §7.7 discipline (promote an
   unforced choice to an explicit spec-level decision) generalized from one point to many.
3. **None survives → rejected**, naming the requirement and the point it emptied.

Mechanically this is arc-consistency / constraint propagation over the `Choice` guards, extended
from spec-keys (§4.3) to capability tags. It is exactly the **cross-tree constraint** of feature
models (FODA `requires`/`excludes` spanning the feature tree, §5.4) and the generate–define–test of
**ASP / default logic** (§5.2) — with the design supplying the one rule those frameworks leave open:
multiplicity of solutions is *surfaced*, not silently collapsed to one.

### 12.3 How the two modes compose

Point pins are hard and win *locally*: set `.persistence = file` and resolution will not override
you. But a pin that **violates** an active requirement is a conflict — `requires tx` together with
`.persistence = file` — reported through the **same propose-and-report channel** as a footprint
clash or a path-presupposition failure (§11.4). The precedence is a lattice, not a priority list:
requirements bound the space, point pins fix loci within it, preferences tie-break what remains, and
**every residual ambiguity or pin-vs-requirement clash is surfaced**. No layer silently overrides
another.

### 12.4 Why a preference may be *declared* but never *inferred*

Resolution must be a **pure function of `(point pins + declared requirements + declared
preferences)`**. Then it is diffable and changes only when one of those inputs changes — an ordinary,
reviewable regeneration diff (§10.2–§10.3). An *inferred* preference — the system optimizing a cost
function it chose for you — reintroduces default drift at the meta level (§2, §10.3): a bespoke,
invisible cost model silently repicks a production on regeneration, which is the exact failure this
design forbids of features, now committed by the resolver itself. So a preference is admitted **only**
as an explicit, versioned policy (the §7.3 pattern), and two preferences that collide at one point
are surfaced, not averaged. The line is sharp: **forced where unique, declared where preferred,
surfaced where ambiguous — never inferred.**

### 12.5 Transparency: a forced choice is not a hidden one

Every forced resolution emits a **diffable derivation note** — *"persistence ← sql (forced by
requirement `tx`; `file_store` excluded: no `tx`)"* — the §10.3 migration-note discipline applied to
selection. A choice made *for* you that you cannot *see* is still a silent choice; the note is what
keeps requirement-driven selection inside the no-silent-choices rule (§2).

### 12.6 Status and what it does *not* add

An extension, not yet in the language surface (§11) or the code. It adds **no new combinator and no
new soundness theory**: it reuses determinacy analysis (§4.3), reachability/binder resolution (§3.3),
and the propose-and-report error channel (§11.4), and it inherits the four shapes unchanged. What it
adds is a **second addressing mode** over the same derivation term — intensional constraints beside
extensional deviations — and the single rule that keeps it from becoming an optimizing planner:
*narrow deterministically, force only when unique, surface every residual choice, and never infer a
preference.* Whether the capability-tag vocabulary is worth its authoring cost is, like everything
here, an empirical question to settle against the first domain that needs it (§8).

---

## Appendix: Glossary

- **Nonterminal / decision point** — a place in the grammar where the specification determines
  which alternative (production) is realized.
- **Production** — one concrete alternative realization of a decision point.
- **Deviation** — a spec statement that selects a non-default production, or adds an item to
  an accumulative/fold nonterminal.
- **Channel** — a named, typed unit of data or control interaction declared by a nonterminal
  as read, written, bound, or passed through.
- **Combinator** — one of the four built-in functions (one per shape, §3.4) by which multiple
  simultaneous deviations at a nonterminal combine into a single result; system-provided and
  proven sound once, never user-authored (§11.2).
- **Derivation term** — the single underlying object of the language (§11.1): a spec is a
  derivation term with its choices filled; a grammar rule is a derivation term abstracted over
  decision points and named.
- **Wiring** — a domain-authored statement of which combinator hosts which atoms at which channel;
  together with atom declarations it constitutes a domain's grammar (§11.2).
- **Deviation path** — a dot-notation address of a decision point in a derivation, used by a spec
  to state a deviation from default (§11.4).
- **Opaque atom** — a typed-boundary, unanalyzed escape hatch for behavior outside the grammar
  (§3.5).
- **Callback atom** — an opaque atom whose declared footprint is emitted as a typed callback
  interface, with its body supplied in a separate user-owned file the generator never overwrites
  (§3.6).
- **Dialect** (borrowed from MLIR) — a domain-specific nonterminal vocabulary built on the
  shared universal substrate (§3, §4.4).
- **Point deviation** — an *extensional* choice: a spec statement that names one decision point by
  dot-path and sets its value (§11.4, §12).
- **Cross-cutting constraint** — an *intensional* choice: a property of the whole system, addressed
  to no single path, that holds at every decision point where it is relevant, simultaneously (§12).
  Comes in two strengths — requirement and preference.
- **Requirement** — a *hard* cross-cutting constraint that narrows the admissible productions at
  every relevant point; unsatisfiable ⇒ rejection (§12.1–§12.2).
- **Preference (tie-break policy)** — a *soft*, explicitly declared and versioned bias over
  admissible productions, used only to tie-break among requirement-survivors; never inferred, never
  overrules a requirement (§12.1, §12.4).
- **Resolution** — the narrow-then-{force | surface | reject} procedure that fills open decision
  points from the active point pins and cross-cutting constraints; deterministic where the narrowed
  set is a singleton, surfaced where it is not (§12.2).
