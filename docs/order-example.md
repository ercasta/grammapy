# Worked Example — an `Order` Service, and Exactly Where the Boundary Is

**Status:** illustrative walkthrough. Uses the REST domain of [`rest-domain.md`](rest-domain.md)
and the language of [`language.md`](language.md). Syntax is provisional; the *classification* is
the point.

**What this document is for.** The design docs state the guarantee abstractly. This one takes a
single service with four business rules and three cross-cutting features, and walks each combination
to one of three fates: **composed-and-checked**, **rejected at design time**, or **quarantined in an
opaque atom**. The goal is to make the dividing line concrete — and to answer the question that
motivated it: *if the system can express loops, why can't it just combine business logic?* It can.
The line is not "grammar vs. business logic." It is **footprint vs. interior**, and this example
shows exactly where that line falls.

---

## 1. The service

An `Order` resource that, on create, must:

1. compute a **discount** from the subtotal and the customer's tier,
2. compute **tax** — on the *discounted* amount,
3. compute the **total**,
4. **decrement inventory**, which can fail if stock is short,
5. be **authorized** (admins may do anything; guests may not delete),
6. be **audited** (every mutating request is logged),
7. run inside a **transaction** that rolls back on any failure,
8. **retry** on transient database errors.

Seven of these are the kind of thing people reach for a generator to handle. Each lands on a
different combinator, and two of them force a decision the system refuses to make for you.

---

## 2. The atoms (bespoke interiors, declared footprints)

The four business rules are **callback atoms** (§3.6): the system sees only their `reads`/`writes`/
`emits`, never their bodies, which live in user-owned files.

```
atom compute_discount:
  reads  order.subtotal, customer.tier
  writes order.discount
  impl   ./business/pricing.py:compute_discount

atom compute_tax:
  reads  order.subtotal, order.discount     # ← note: reads the discount
  writes order.tax
  impl   ./business/pricing.py:compute_tax

atom compute_total:
  reads  order.subtotal, order.discount, order.tax
  writes order.total
  impl   ./business/pricing.py:compute_total

atom decrement_inventory:
  reads  order.line_items
  writes inventory.stock
  emits  OutOfStock                          # ← a control signal
  impl   ./business/fulfilment.py:decrement

atom audit:
  reads  request.subject, request.action
  writes audit_log                           # ← a sink nobody else touches
  impl   ./business/audit.py:record
```

The system will not read one line of `pricing.py`. Everything below is decided from the five
footprints above plus the wiring.

---

## 3. The pricing rules — the interesting case

### 3.1 The naive version, and why it is *rejected*

The way this is written in ordinary code is: start with the subtotal in `order.total`, then mutate
it in place — apply the discount, then apply the tax.

```
Order : Resource("orders")
  .logic += apply_discount, apply_tax        # both mutate order.total in place
```
where
```
atom apply_discount:  reads order.subtotal ; writes order.total
atom apply_tax:       reads order.total     ; writes order.total
```

`.logic` is an `Accumulate`, whose one law is *pairwise-disjoint writes*. Both atoms write
`order.total`. The checker rejects the spec before generating anything:

```
Accumulate rejected: writes are not disjoint
  - channel `order.total` is written by both `apply_discount` and `apply_tax`
```

This is the whole thesis in one message. In ordinary code, `apply_discount(order); apply_tax(order)`
compiles and runs; the fact that **swapping the two lines silently produces wrong invoices** is an
invisible, unenforced ordering assumption. grammapy refuses to accept the composition *because it
cannot see, from the footprints, which order is meant* — both just "write `total`." It does not
guess. You now have three ways forward.

### 3.2 Fix A — make the data-flow explicit (composed *and* checked)

Give each rule its own output channel, and let the rules that depend on an earlier result **read
that channel**:

```
Order : Resource("orders")
  .logic += compute_discount, compute_tax, compute_total
```
with the footprints from §2. Now:

- **Writes are disjoint** — `order.discount`, `order.tax`, `order.total` are three distinct
  channels. The `Accumulate` law is satisfied.
- **The ordering is *derived*, not declared.** `compute_tax` reads `order.discount`, which
  `compute_discount` writes; `compute_total` reads both. These read-after-write links form an
  acyclic dependency graph, and emission sequences the atoms by it (§7.4, and the "internalized
  channels" of §11.3). The order `discount → tax → total` is now a **fact about the footprints**,
  deterministic and reviewable — not a line-ordering someone can quietly flip.

The ordering assumption didn't disappear; it moved from *implicit and unenforced* to *explicit in
the interface and enforced by the checker*. That move is the product.

### 3.3 Fix B — propose a `Fold`, and watch it get refused too

You might think: the rules conflict on `order.total`, and §7.3 says conflicts are resolved by a
`Fold` with a join. So declare `.total` a `Fold` and combine the two writes with a join.

The system refuses this too, and correctly. A `Fold` join must be **commutative and associative** —
that is what makes it order-independent (§3.2). "Apply a discount, then a tax" is neither:
`tax(discount(x)) ≠ discount(tax(x))`. There is no honest commutative join over "successive
arithmetic adjustments to a running total," so there is no `Fold` to declare. Propose-and-check
(§11.3) catches the wrong shape: the derived properties refute the proposed combinator. You cannot
launder an order-dependent computation through a `Fold` — which is exactly the discipline working.

### 3.4 Fix C — quarantine (legal, but you opt out of the guarantee)

If the discount/tax interplay is genuinely tangled — mutual conditions, shared intermediate state
that isn't a clean DAG — collapse it into one atom:

```
atom compute_charges:
  reads  order.subtotal, customer.tier
  writes order.discount, order.tax, order.total
  impl   ./business/pricing.py:compute_charges
```

Now the system sees *one* opaque unit with an honest footprint. It composes `compute_charges` with
everything else safely (its writes are disjoint from `inventory.stock`, `audit_log`, …), but it
offers **no guarantee about the discount-vs-tax interaction inside it** — that's back to ordinary
code, behind a declared boundary. This is the right answer when the interaction really is
irreducible; it is the *wrong* answer used as a habit, because it shrinks the checked surface
(§3.5). The choice is visible either way.

---

## 4. Inventory — a control signal needs a binder

`decrement_inventory` can fail: `emits OutOfStock`. A leaf that emits a control signal is only
admitted if some **ancestor `Scope` covers that signal** (§3.3). The transaction boundary is that
`Scope`:

```
nonterminal OrderResource(name) = Resource(name)
  boundary: Scope[OutOfStock, TransientError, ValidationError, Forbidden] {
    transactional(on_error: rollback)
  }
```

The reachability check (a preorder traversal with a handler stack) confirms every emitted signal —
`OutOfStock` from inventory, `ValidationError` from validation, `Forbidden` from authorization — has
a covering handler that maps it to a rollback + HTTP status. **Delete the `boundary` and the spec is
rejected**, naming the uncovered signal and the atom that emits it. An emitting business rule is
checked exactly like a built-in one; there is no separate machinery for "your code."

---

## 5. Authorization — a genuine conflict, resolved by a declared join

`grant` and `deny` on the same `(subject, action)` genuinely conflict — this is the case where
`Accumulate` *would* be unsound and the system makes you say how to resolve it:

```
  .authorization += grant(role: admin, action: *), deny(role: guest, action: delete)
```

`.authorization` is `Fold[deny_overrides]`. The join is `deny_overrides` over `n-a < grant < deny`,
which *is* commutative and associative — so any number of grant/deny rules compose
**order-independently**. Add a tenth rule and you cannot change the meaning of the first nine by
where you put it. (Contrast §3.3: here a `Fold` is *right*, because the join is honest; there it was
wrong, because it wasn't. Same shape, opposite verdict, decided by whether the law actually holds.)

---

## 6. Audit — the trivial case, and why it stays trivial

```
  .logic += audit
```

`audit` writes only `audit_log`, which nothing else reads or writes. Its writes are disjoint from
every other atom's, so it drops into `Accumulate` with **no obligation beyond the disjointness
check** and no ordering constraint — it can run anywhere. This is the observer case (§3.4): logging,
metrics, and audit are "free" precisely because their footprint is a private sink. An observer that
tried to write a channel someone else uses would fail disjointness at design time — which is the
correct outcome, not a limitation.

---

## 7. Retry — and the one decision the system will not make for you

Add retry-on-transient-error, and later add a cache:

```
  boundary: Scope[…] {
    transactional(on_error: rollback)
    retry(max: 3, on: TransientError)
    cache(key: order.id)
  }
```

`retry` and `cache` are both **control-rewriters** — they re-enter or bypass the region based on a
signal (§3.4). Two of them over one region are **order-dependent**: `retry`-outside-`cache` retries
a cache *miss*; `cache`-outside-`retry` caches the *post-retry* result. These are different programs.

There is no commutative join to hide behind (as in §3.3) and no data-flow to derive an order from
(as in §3.2). So the system does the only honest thing: it **refuses to pick, and demands an
explicit order**:

```
CompositionError: `retry` and `cache` are order-dependent over region `boundary`.
  Declare an order, e.g.  retry(order_vs: [cache])   or   cache(order_vs: [retry])
```

Non-commutativity is surfaced as a spec-level decision, never resolved silently (§7.7). This is the
same move as choosing `deny_overrides` vs. `permit_overrides` in §5 — the system's job is to make
the choice *visible and yours*, not to make it disappear.

---

## 8. The scorecard

| Feature | Combinator | Fate | Why |
|---|---|---|---|
| discount / tax / total | `Accumulate` (data-linked) | **composed**, order *derived* | disjoint writes; read-after-write links induce the order (§3.2 above) |
| the *naive* discount/tax | `Accumulate` | **rejected** | both write `order.total` — no disjointness, no derivable order |
| discount/tax as a `Fold` | `Fold` | **refused** | no commutative join for order-dependent arithmetic |
| inventory | atom under a `Scope` | **composed** | emitted `OutOfStock` covered by the transaction boundary |
| authorization | `Fold[deny_overrides]` | **composed**, order-free | the join genuinely is commutative/associative |
| audit | `Accumulate` (observer) | **composed**, free | private sink, disjoint from all |
| transaction | `Scope` | **composed** (binder) | covers every emitted signal |
| retry + cache | ordered `Scope` | **forced decision** | two control-rewriters — order is not inferable |

Every feature landed in exactly one of: composed-and-checked, rejected, refused, or
decision-forced. Nothing was silently ordered, and nothing was silently assumed safe.

---

## 9. What this bought you over ordinary code

The ordinary-code version of §1 is a function:

```python
def create_order(order, req):
    authorize(req)                 # ordering + interaction, all implicit
    validate(order)
    order.total = order.subtotal
    apply_discount(order)          # ← swap these two lines → wrong invoices, no error
    apply_tax(order)
    decrement_inventory(order)     # ← what if this raises after the discount wrote? tx? rollback?
    audit(req)
```

Every line encodes an ordering and an interaction assumption that is **invisible and unenforced**.
Adding a feature means re-reading the whole function to check you didn't break an assumption; there
is no vocabulary for "these two combine like *this*," so the combination logic is smeared through
the body and re-verified by hand, or by production.

grammapy does not make you write less business logic — `pricing.py`, `fulfilment.py`, `audit.py` are
still entirely yours, still unanalyzed. What it does is take every **seam between** those pieces and
force it to be one of three visible things:

- **explicit** — the discount→tax order lives in the footprints, derived and reviewable (§3.2);
- **rejected** — a real conflict is named at design time, with the channel and both culprits (§3.1);
- **a declared decision** — a non-commutative order is surfaced and handed back to you (§7).

The bet (the thing your validation corpus should measure) is that **most cross-feature defects live
in those seams, not in the interiors** — so guaranteeing the minority of the code that is wiring
kills a majority of the interaction bugs. The interiors keep the risk profile of ordinary code, no
better; the seams get design-time certainty. That boundary is the value proposition, stated exactly.

---

## 10. Why loops are not a special case

It is tempting to think a loop is "real logic the system understands," and business logic is not.
That asymmetry does not exist. Look at the loop of §7.4 beside the pricing rules of §3.2:

| | loop (`sum`, `count`) | pricing (`discount`, `tax`, `total`) |
|---|---|---|
| structure | `Scope` (iteration channels) over `Accumulate` of ops | `Accumulate` of atoms (a `Scope` around it for `tx`) |
| the "ops" | atoms with declared footprints | atoms with declared footprints |
| what the system sees | `sum` writes `acc_sum`, `count` writes `acc_count` | `discount` writes `order.discount`, `tax` reads it |
| what the system does *not* see | how `sum` adds | how `compute_discount` computes a discount |
| safety decided by | disjoint accumulators (frame rule) | disjoint writes + derived order (frame rule) |

A loop is `Scope` + `Accumulate` over footprint-declared atoms. Business logic is `Accumulate` (and
`Scope`, and `Fold`) over footprint-declared atoms. **It is the identical mechanism.** The system
never "understood" the loop body's arithmetic any more than it understands a discount; in both cases
it reasons over the footprint and treats the interior as opaque.

So: *yes, you can combine elements of business logic with this system* — that is precisely what §3–§7
did. What you cannot do is get the system to **invent** a combination law that is not one of the four
shapes over declared channels. When the way two rules combine is a choice (`Choice`), an independent
list (`Accumulate`), a commutative reduction (`Fold`), or a scoped handler (`Scope`) — expressed
through honest footprints — the system composes and checks them. When it is a bespoke, data-dependent
dance, you either **make the data-flow explicit** (and it becomes composable, §3.2) or you
**quarantine it in one atom** (§3.4). The one thing that never happens is a silent guess.
