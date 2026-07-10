# Worked Example — Swapping Frameworks & Persistence, and Composing Domains

**Status:** illustrative walkthrough, companion to [`order-example.md`](order-example.md). Cross-domain
import syntax is **not yet frozen** (language.md §9 lists it as open); the `adapter` keyword and the
dialect layout below are provisional. The *classification* — what the system checks, what it refuses,
and what it makes you write by hand — is the stable content.

**The question this answers.** *If I define a pandas domain, a FastAPI domain, a Flask domain, a
database-persistence domain, and a file-persistence domain — can the system generate the different
compositions (swap the framework, swap the persistence) without my hand-writing every combination?*

The honest answer is **yes, with a precise boundary**, and it splits into two mechanisms that look
like one:

- **Swapping an alternative *within* one axis** (file ↔ database, FastAPI ↔ Flask) is an
  exclusive-**`Choice`** — one deviation, everything downstream untouched. §2–§3.
- **Combining different axes into one program** (a FastAPI endpoint running a pandas pipeline,
  persisted to a database) is **cross-domain composition** (§4.4) — checked at the seams, but the
  *adapters* between domains are hand-written, not free. §4–§5.

---

## 1. Why "swap the framework" is not cross-domain composition

FastAPI and Flask are not different *domains*. They are two ways to satisfy the **same decision
point** — "how is this served?" — and they present the **same typed channel interface**. The rest of
the spec never names FastAPI; it names channels (`route.*`, `response`, `app`). That indirection is
the entire trick: code written against a channel doesn't care which production filled it.

Same for persistence: `sql_store` and `file_store` both bind `store` and `record`. Endpoints read
`store`; they never read "sql". So swapping either is **one deviation**, and the substitutability is
a property of the *channel contract*, not of any per-combination glue you write.

---

## 2. The two swap axes, as `Choice`

```
# ── serving axis ── both productions consume the SAME contract: route.*, response → app
nonterminal Serving = Choice {
  key=fastapi | key.absent -> fastapi_app()    # reads route.*, response ; writes app
  key=flask                -> flask_app()       # reads route.*, response ; writes app
}

# ── persistence axis ── both bind store + record; they DIFFER in what else they provide
nonterminal Persistence = Choice {
  key=sql | key.absent -> sql_store(table: Ident)   # binds store, record ; PROVIDES tx
  key=file             -> file_store(path: Path)      # binds store, record ; NO tx
}
```

A resource is written against the contract, mentioning neither framework nor backend:

```
nonterminal Service(name) = record {
  serving:       Serving        default fastapi
  persistence:   Persistence    default sql(table: name)
  endpoints:     Accumulate<Endpoint>   default { list, create, read, update, delete }
  boundary:      Scope[ValidationError, Conflict, TransientError] {
    transactional(on_error: rollback)      # ← binds/uses tx
  }
}
```

Now a spec swaps by touching one line each:

```
Orders : Service("orders")
  .serving     = flask       # was fastapi — endpoints, persistence, boundary all untouched
  .persistence = file(path: ./data)   # was sql — see §3, this one may not typecheck
```

The `endpoints` Accumulate emits `route.<method>:<path>` **regardless of framework**, and the
persistence-reading endpoints read `store` **regardless of backend**. You did not hand-write the
flask×file combination; you selected it.

---

## 3. Not every swap is valid — and the system tells you *which*, at design time

This is where the system earns its keep. `sql_store` provides a `tx` binder; `file_store` does not.
`Service.boundary` is a `Scope` whose `transactional(...)` **uses `tx`**. Reachability/binder
resolution (§3.3) checks that every channel a `Scope` needs is provided in scope. So:

- `.persistence = sql` → `tx` is provided → the boundary resolves → **accepted**.
- `.persistence = file` → nothing provides `tx` → the boundary has an unmet requirement →
  **rejected at design time**:

```
CompositionError: `transactional` boundary requires channel `tx`,
  not provided by production `file_store` (spec line: .persistence = file).
  Either choose a tx-providing persistence, or drop the transaction boundary.
```

The system refuses to emit a file-backed "transaction" that silently isn't one. **That is the value
of the swap machinery: it decides which compositions typecheck, before generating code**, instead of
producing a plausible-looking app whose transactional guarantee is fiction.

Same discipline on the serving axis: if a route needs an async streaming `response` that
`flask_app()` can't consume, that route production requires a channel Flask's production doesn't
expose → rejection. A leaky abstraction surfaces as a **named channel mismatch**, not a production
surprise.

### 3.1 The swap matrix

For the **transactional** `Orders` spec above (its `boundary` uses `tx`):

| serving | persistence | verdict | why |
|---|---|---|---|
| fastapi | sql  | ✅ accepted | `tx` provided; contract satisfied |
| fastapi | file | ❌ rejected | `boundary` needs `tx`; `file_store` provides none |
| flask   | sql  | ✅ accepted | serving swap is contract-preserving |
| flask   | file | ❌ rejected | same `tx` gap — serving is irrelevant to it |

Drop the transaction boundary (a read-only `Reports` service that never writes) and **all four
persistence×serving cells become valid** — because nothing demands `tx` any more. The validity of a
swap is not a fixed property of the backend; it is decided against *what the rest of the spec
demands from the channel contract*. That per-spec decision is exactly what you would otherwise make
by hand, silently, and get wrong.

---

## 4. Composing *across* axes: a pandas pipeline behind an endpoint

Now the genuinely cross-domain case. pandas is a real, different domain — dataframe transformations,
not HTTP and not storage. Its dialect has its own decision points over its own channels
(`col.<name>`, `frame`):

```
# ── pandas dialect: transforms are atoms with COLUMN-level footprints ──
atom clean_names:    reads col.raw_name ; writes col.name
atom compute_margin: reads col.price, col.cost ; writes col.margin
atom bucket_tier:    reads col.margin ; writes col.tier

nonterminal Pipeline = Scope[frame] { Accumulate<Transform> }   # frame bound; transforms accumulate
```

The `Accumulate` law gives you a real, useful check for free: two transforms that both write
`col.margin` **collide on disjointness → design-time rejection** — catching silent column overwrite,
a genuine pandas bug class, before it runs.

To host this pipeline behind a REST endpoint that persists its output, the pipeline enters the REST
domain **as a typed atom** (§4.4), and its channels are threaded through the endpoint:

```
Reports : Service("reports")
  .serving = fastapi
  .persistence = sql(table: reports)
  .logic  += run_reports_pipeline      # hosts the pandas Pipeline as an atom
```

The seam looks like this — and here is the catch:

```
request.body ──[adapter body_to_frame]──▶ frame ──▶ Pipeline ──▶ frame
                                                                   ├─[adapter frame_to_record]──▶ record   (persist)
                                                                   └─[adapter frame_to_response]─▶ response (return)
```

---

## 5. What is *not* free: the adapters

The shared substrate makes the cross-domain composition **checkable** — it does **not** make the
**data adapters free** (vision.md §6 limit 5, §7.6). pandas speaks `frame` (a DataFrame);
persistence speaks `record` (rows); HTTP speaks `request.body`/`response` (JSON). Something must
convert between these channel *types*, and that something is hand-written — MLIR calls these
**lowering passes** and they are nontrivial by design:

```
# provisional syntax — cross-domain import/adapter surface is not yet frozen (language.md §9)
adapter body_to_frame:     request.body -> frame     impl ./adapters/http_pandas.py:body_to_frame
adapter frame_to_record:   frame        -> record    impl ./adapters/pandas_sql.py:frame_to_record
adapter frame_to_response: frame        -> response  impl ./adapters/pandas_http.py:frame_to_response
```

What the system *does* give you: it will **refuse the seam if no adapter exists** for a channel-type
pair that meets (a `frame` handed to something expecting a `record`, with no `frame_to_record` in
scope, is a design-time rejection, not a runtime `AttributeError`). What it does **not** do: write
the adapter, or guarantee anything *inside* it — an adapter is an opaque atom like any other (§3.5).

Each adapter is written **once per channel-type pair**, and then reused by every app that crosses
that seam.

---

## 6. The cost accounting — why this beats hand-writing the matrix

| You author **once** | You get **without hand-composing each combination** |
|---|---|
| each domain (its decision points + productions) — serving, persistence, pandas, REST | any spec that *selects* a combination, checked not glued |
| each **adapter** per channel-type pair that actually meets — `body↔frame`, `frame↔record`, `frame↔response` | reuse of that seam in every app that crosses it |

From `{fastapi, flask} × {sql, file} × {pipeline, no-pipeline}` you get **8 apps out of 4 domains + 3
adapters**. Adding a fifth serving framework is **`+1` production**, not `+4` apps; adding a Mongo
persistence is `+1` production plus at most one new adapter. **The cost is additive (domains +
adapters), not multiplicative (every combination).** That additive-vs-multiplicative gap *is* the
scaling claim — and it is the cross-domain form of the "library of defaults that saturates"
hypothesis: once the domains and the adapters exist, the marginal cost of app N+1 is *selecting
deviations*, near-zero in structural additions.

This is the product-line dream (AHEAD/FeatureIDE, vision.md §5.4) — with the difference those systems
never closed: they resolve feature interactions by **hand-ordered composition**, where here the
interaction is checked through footprints and the invalid combinations (the `tx`-on-`file` cell) are
*rejected*, not silently generated.

---

## 7. What the system can and cannot do here — the honest summary

**Can:**

- **Swap within an axis for one deviation.** File↔database, FastAPI↔Flask, when the alternatives
  share a channel contract. Downstream spec is untouched.
- **Reject invalid swaps at design time.** `tx`-on-`file`, a leaked async-only route on Flask, a
  missing adapter — named channel mismatches, before code is emitted.
- **Compose domains at checked seams.** A pandas pipeline hosted inside REST, with the column-level
  disjointness check catching silent overwrites for free.
- **Keep the cost additive.** Domains + adapters authored once; combinations selected, not written.

**Cannot:**

- **Make two alternatives substitutable without a shared channel contract.** Designing that
  framework-/storage-neutral contract is the real up-front work; the system makes a leak *visible*
  (a rejection), it does not design the contract for you.
- **Generate the cross-domain adapters.** `frame → record`, `body → frame` are hand-written lowering
  passes, opaque atoms with no interior guarantee — and this is the **least-proven, furthest-out**
  part of the design (roadmap step 9).
- **Guarantee anything inside a transform or an adapter.** pandas is a *thin* domain: the pipeline
  *wiring* and column footprints are checked; the transformation logic is bespoke (§3.5). Don't
  expect the guarantee to cover the transforms themselves.
- **Invent a composition that isn't one of the four shapes** over declared channels — across
  domains exactly as within one (see [`order-example.md`](order-example.md) §10).

**Net:** the system gives you the cross-product of compositions from *additively-defined* parts, and
tells you at design time which cells of that cross-product actually typecheck. The swaps are the
cleanest case; the multi-domain combination is real but its cost is *domains + adapters authored
once*, not zero, and the adapters are the part still furthest from proof.
