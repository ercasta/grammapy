# REST/CRUD Domain — Decision Points (Roadmap Step 2)

**Status:** design artifact, done on paper before code (roadmap §8 step 2).
**Purpose:** enumerate the real decision points of the first target domain, wire each into one of
the four combinators (§3.4), and fix the **channel vocabulary** and **soundness obligation** each
one imposes. Step 3 (the channel-type system and disjointness checker) implements exactly what
this document specifies.

This is a *spike-scale* enumeration: eight decision points chosen to exercise **all four
combinators**, not a complete REST domain (which needs dozens — §6.4). Extensions are listed in
§10.

---

## 1. The resource model

The unit of generation is a **resource** (`UserAccount`, `Order`) — a named entity with fields,
persisted, exposed over HTTP CRUD endpoints, guarded by authorization, validated on write, and
optionally augmented with bespoke business logic. A resource is itself a `record` (an `Accumulate`
over named slots, §3.4); the slots below are its decision points.

---

## 2. Channel vocabulary

Every decision point composes only through these typed channels. `<name>` denotes a family
parameterized by an identifier.

| Channel | Meaning | Kind |
|---|---|---|
| `field.<name>` | the value/definition of a named field | data |
| `store` | the persistence backend binding | data |
| `record` | the persisted-entity mapping (field set ↔ store) | data |
| `request.subject` | authenticated principal of the inbound request | data |
| `request.action` | the CRUD action being attempted | data |
| `request.body` / `request.query` | inbound payload / query params | data |
| `auth.decision` | authorization outcome (`grant`/`deny`/`n-a`) | data |
| `violations.<field>.<rule>` | one validation-rule outcome slot | data (accumulation slot) |
| `route.<method>:<path>` | one installed HTTP route | data |
| `response` | the outbound representation | data |
| `tx` | a transaction binding | binder |
| `ValidationError` `Forbidden` `NotFound` `Conflict` `TransientError` | control signals | control |

**Severity order** (a join-semilattice, §3.2), least → greatest:
`n-a < ValidationError < Forbidden < NotFound < Conflict < TransientError`.
(Distinct-but-incomparable signals would join to a common supertype; this first cut keeps them in a
chain for simplicity. Refine when a real incomparability appears.)

---

## 3. Persistence strategy — `Choice`

Which backend stores the resource.

- **Combinator:** `Choice` (exclusive-choice).
- **Guard fragment:** presence/enum on the `persistence` key — `sql` | `document` | `in_memory` |
  *absent* → `sql`. Decidable (§4.3).
- **reads:** `field.*` (needs the schema to build a table/collection).
- **writes:** `store`; binds `record`.
- **Soundness obligation:** guard **disjointness + exhaustiveness** — exactly one production fires
  for any spec (including the absent-key default).

```
persistence: sql(table = orders)      # or document(collection=…), in_memory()
```

---

## 4. Resource fields (schema) — `Accumulate<Field>`

The set of fields the resource has.

- **Combinator:** `Accumulate<Field>` (a named-slot record).
- **reads:** —.
- **writes:** each field writes `field.<name>` — **pairwise disjoint by name**.
- **Soundness obligation:** disjoint writes ⇒ two fields cannot share a name. A name collision is a
  design-time rejection naming both field declarations and the channel `field.<name>`.

```
fields: name: Str, email: Str, age: Int
```

---

## 5. Validation rules — `Accumulate<Validation>`

Constraints checked before a write is persisted.

- **Combinator:** `Accumulate<Validation>`.
- **reads:** `field.<name>` for each rule's target.
- **writes:** each rule writes a **distinct slot** `violations.<field>.<rule>` (not a shared
  scalar) — so `required(age)` and `range(age,…)` compose by disjoint-footprint accumulation, even
  though both concern `age`. This slot-per-rule modeling is what keeps the frame rule literally
  applicable; the alternative (all rules append to one `violations` sink under a list-monoid) is a
  `Fold` and is noted as an option if slot identity proves awkward.
- **emits:** the aggregate check may raise `ValidationError` — which therefore **requires a
  covering binder** (§8).
- **Soundness obligation:** disjoint write slots.

```
validation: required(name, email), range(age, 0, 120)
```

---

## 6. Authorization — `Fold[deny_overrides]<AuthRule>`

Who may perform which action.

- **Combinator:** `Fold[deny_overrides]` — the §7.3 case: `grant`/`deny` on the same
  (subject, action) **conflict**, so accumulation is unsound; a commutative join resolves them.
- **reads:** `request.subject`, `request.action`.
- **writes:** `auth.decision`.
- **join:** `deny_overrides` over `n-a < grant < deny` (commutative, associative by construction).
  The choice of algorithm (`deny_overrides` vs `permit_overrides` vs `first_applicable`) is itself
  a spec decision.
- **emits:** `Forbidden` when the decision is `deny`.
- **Soundness obligation:** the join's semilattice laws — hold by construction of the order.

```
authorization: deny_overrides, grant(role=admin, action=*), deny(role=guest, action=delete)
```

---

## 7. Endpoints exposed — `Accumulate<Endpoint>`

Which CRUD operations the resource offers.

- **Combinator:** `Accumulate<Endpoint>` (list / create / read / update / delete).
- **reads:** `store`, `auth.decision`, `violations.*`, `field.*` — an endpoint wires these
  together.
- **writes:** each endpoint writes `route.<method>:<path>` — **disjoint by method+path**.
- **Soundness obligation:** disjoint routes (no two endpoints claim the same method+path).

```
endpoints: list, create, read, update, delete
```

---

## 8. Transaction boundary — `Scope[…] { … }`

Write endpoints run in a transaction and map raised signals to HTTP responses.

- **Combinator:** `Scope` (binder-scoped reachability, §3.3).
- **binds:** `tx`.
- **catches:** `ValidationError`, `Forbidden`, `NotFound`, `Conflict`, `TransientError` →
  rollback + map to status (422/403/404/409/503).
- **Soundness obligation:** **reachability** — *every* signal emitted by validation (§5),
  authorization (§6), persistence, or business logic (§9) must have a covering `Scope` ancestor.
  Checked by preorder traversal with a handler stack. Remove the boundary and any spec whose
  validation/auth can emit is rejected.

```
transaction: on(create, update, delete), on_error = rollback
```

---

## 9. Business logic hooks — `Accumulate<Business>`

Bespoke behavior, as typed callback atoms (§3.6), attached at lifecycle points.

- **Combinator:** `Accumulate<Business>`.
- **reads/writes:** each atom's **declared footprint** (opaque interior, user-owned file).
- **emits:** whatever the atom declares (e.g. `TransientError`) — requires coverage by §8.
- **Soundness obligation:** disjoint writes among atoms **and** among atoms vs. generated writes;
  plus reachability for any `emits`.

```
logic: before_create(compute_discount)      # impl in ./business/discount.py
```

---

## 10. Summary and what step 3+ must implement

| # | Decision point | Combinator | Soundness check | Roadmap step |
|---|---|---|---|---|
| 3 | Persistence | `Choice` | guard disjointness + exhaustiveness (decidable fragment) | 3 (guards), 4 |
| 4 | Fields | `Accumulate` | disjoint writes (`field.<name>`) | **3** |
| 5 | Validation | `Accumulate` | disjoint write slots (`violations.…`) | **3** |
| 6 | Authorization | `Fold` | semilattice join laws | 4 |
| 7 | Endpoints | `Accumulate` | disjoint routes | **3** |
| 8 | Transaction | `Scope` | binder reachability (handler stack) | 5 |
| 9 | Business logic | `Accumulate` | disjoint writes + reachability | 3, 5 |

**Immediate step-3 target (this is what the first code implements):** the channel-type system and
the **disjoint-writes check** that decisions 4, 5, 7, 9 all share. Getting one check right against
four real decision points is the cheapest way to validate the substrate before the guard, fold, and
reachability checks (steps 4–5) are built.

**Extensions (out of scope for the spike, real in a full domain):** pagination/filtering strategy
(`Choice`), serialization format (`Choice`), soft-delete (`Choice`), rate limiting and audit
(`Accumulate` observers), caching and retry (`Scope` control-rewriters, with the ordering decision
of §3.4), optimistic-concurrency versioning (`Fold` or `Scope`).
