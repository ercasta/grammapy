● This is a strong document — better than most design docs of this genre because it commits to specific, checkable
  mechanisms instead of aspirations. Here's my read, focused on what will matter when you actually build it.

  Strengths

  The four-shape taxonomy (§3.4) is the real asset. "Every nonterminal is exactly one of four shapes or it's refused" is
  an enforceable design rule, not a philosophy. It gives you a concrete admission procedure, and the worked examples in
  §7.3/§7.5 show it catching real misclassifications during design — that's evidence the discipline pays for itself.

  Honest scoping. Explicitly renouncing termination/correctness guarantees, admitting the escape hatch exists and is
  unchecked, and stating that shape classification is non-automatable human work (§6.4) — all of this makes the doc
  trustworthy. The narrowed claim in §1 ("composing accepted deviations never silently breaks other accepted
  deviations") is the right claim.

  Roadmap instinct is right. "Generate one working module end-to-end before expanding" (step 9) is the correct ordering,
  and the choice to allow template emission before libcst avoids gold-plating.

  Weaknesses

  1. The core guarantee rests on unverified declarations. The whole soundness story assumes each production's
  reads/writes declarations accurately describe the code it emits — but nothing checks emitted code against its declared
  footprint. A grammar author writes a template that quietly touches a channel it didn't declare, and every downstream
  disjointness proof is fiction. This is the biggest hole in practice, because template code drifts over maintenance.
  It's also fixable (see improvements).

  2. No regeneration/evolution story — the classic code-generator killer. What happens when the user edits generated
  code? When the spec changes and you regenerate, how are opaque atoms and hand-written code preserved? When a default
  changes in the grammar, every spec that was silent on that slot silently changes meaning — that's exactly the "silent
  reinteraction" failure the doc exists to prevent, reintroduced at the meta level. The doc has zero words on this, and
  it's where scaffolding tools historically die (the "generation gap" problem).

  3. The escape hatch will dominate real applications. Real services are mostly bespoke business logic, i.e. opaque
  atoms. If 70% of a real app goes through §3.5, the guaranteed part is a skeleton — which existing scaffolding already
  produces. The doc never estimates coverage, and the more it matters, the more the interesting boundary is
  atom-vs-grammar interaction (constant) rather than atom-vs-atom (acknowledged).

  4. No answer to "why this instead of X" — especially X = LLM codegen. In 2026 the obvious competitor is an LLM
  generating the whole service. The doc's implicit answer (determinism, non-interference, safe regeneration) is actually
  strong, but it's never stated, so the doc reads as solving a 1990s problem with 2000s tools. The strongest
  positioning may be complementary: an LLM writes/edits the deviation spec, the grammar guarantees the composition —
  fuzzy front-end, sound back-end.

  5. Cross-cutting features strain the four shapes. Transactions, logging, caching, audit — the features people most
  want wizards to handle — want to wrap and interpose, not choose, accumulate, or fold. Binder-scoped reachability
  covers some of it, but the doc should either show that middleware-shaped features reduce to the four shapes or admit a
  fifth (wrapper/interposition) is coming.

  6. The CNL layer is a project-sized hand-wave. §4 introduces controlled natural language "directly reusable from prior
  work" — but the §4.2 example is already essentially YAML. CNL adds ambiguity exactly where the design's whole value
  is determinism, and it's a large build.

  7. Smaller inconsistencies.
  - §3.2 requires the severity lattice be totally ordered, but the combination law only needs a join-semilattice (which
  the same section then names). Total order is also wrong for reality: two distinct exception types aren't comparable.
  Weaken the requirement to match the math you actually use.
  - The guard language for exclusive-choice is never pinned down. Disjointness is only "static, decidable" if guards are
  restricted (key presence, enum equality). Say so explicitly, or the §4.3 claim is unearned.
  - Roadmap step 2 says "5–8 decision points"; a useful REST domain realistically needs dozens to hundreds. Fine for a
  spike, but the doc should acknowledge the grammar-authoring cost curve, since that's the actual adoption cost.

  Improvements, in priority order

  1. Add the non-interference diff test — it operationalizes your entire thesis. Property test: take a spec, change
  deviation A, regenerate, and assert the output diff is confined to A's declared footprint. This simultaneously (a)
  tests the core promise end-to-end, (b) catches dishonest reads/writes declarations empirically, closing weakness #1
  without needing static verification of templates, and (c) makes a killer demo. It belongs in the roadmap before step
  9, not as an afterthought to step 8.
  2. Add a §on regeneration and ownership. Simplest workable model: generated files are never hand-edited; opaque atoms
  at the meta level. The doc has zero words on this, and it's where scaffolding tools historically die (the "generation gap" problem).

  3. The escape hatch will dominate real applications. Real services are mostly bespoke business logic, i.e. opaque atoms. If 70% of a real app goes through §3.5, the guaranteed part is a skeleton — which
  existing scaffolding already produces. The doc never estimates coverage, and the more it matters, the more the interesting boundary is atom-vs-grammar interaction (constant) rather than atom-vs-atom
  (acknowledged).

  4. No answer to "why this instead of X" — especially X = LLM codegen. In 2026 the obvious competitor is an LLM generating the whole service. The doc's implicit answer (determinism, non-interference, safe
  regeneration) is actually strong, but it's never stated, so the doc reads as solving a 1990s problem with 2000s tools. The strongest positioning may be complementary: an LLM writes/edits the deviation spec,
  the grammar guarantees the composition — fuzzy front-end, sound back-end.

  5. Cross-cutting features strain the four shapes. Transactions, logging, caching, audit — the features people most want wizards to handle — want to wrap and interpose, not choose, accumulate, or fold.
  Binder-scoped reachability covers some of it, but the doc should either show that middleware-shaped features reduce to the four shapes or admit a fifth (wrapper/interposition) is coming.

  6. The CNL layer is a project-sized hand-wave. §4 introduces controlled natural language "directly reusable from prior work" — but the §4.2 example is already essentially YAML. CNL adds ambiguity exactly
  where the design's whole value is determinism, and it's a large build.

  7. Smaller inconsistencies.
  - §3.2 requires the severity lattice be totally ordered, but the combination law only needs a join-semilattice (which the same section then names). Total order is also wrong for reality: two distinct
  exception types aren't comparable. Weaken the requirement to match the math you actually use.
  - The guard language for exclusive-choice is never pinned down. Disjointness is only "static, decidable" if guards are restricted (key presence, enum equality). Say so explicitly, or the §4.3 claim is
  unearned.
  - Roadmap step 2 says "5–8 decision points"; a useful REST domain realistically needs dozens to hundreds. Fine for a spike, but the doc should acknowledge the grammar-authoring cost curve, since that's the
  actual adoption cost.

  Improvements, in priority order

  1. Add the non-interference diff test — it operationalizes your entire thesis. Property test: take a spec, change deviation A, regenerate, and assert the output diff is confined to A's declared footprint.
  This simultaneously (a) tests the core promise end-to-end, (b) catches dishonest reads/writes declarations empirically, closing weakness #1 without needing static verification of templates, and (c) makes a
  killer demo. It belongs in the roadmap before step 9, not as an afterthought to step 8.
  2. Add a §on regeneration and ownership. Simplest workable model: generated files are never hand-edited; opaque atoms live in user-owned files the spec references by path/signature; regeneration is
  idempotent given (spec, grammar-version). Which leads to:
  3. Version the grammar; make specs pin a version. Defaults changing between grammar versions must be an explicit, diffable migration ("v3 changes default persistence from sql to document; specs silent on
  this slot will change behavior"), not a silent drift. This is the same discipline the doc demands of features, applied to the grammar itself.
  4. Cut CNL from v1. Spec is structured data (YAML/whatever) validating against the nonterminal tree. CNL can return later as sugar. This deletes the highest-risk, lowest-certainty component from the critical
  path.
  5. Add a positioning section answering "why not Rails/Django scaffolding, OpenAPI generators, or an LLM" — and seriously consider the "LLM writes the spec" framing as the primary use case rather than a human
  writing deviation statements by hand.
  6. Make error messages a design deliverable. When guard disjointness or footprint disjointness fails, the user must see "validation rule range(age,...) conflicts with required(age) because both write channel
  X — declared at spec line 4 and line 5," not a combinator soundness trace. For a system whose pitch is design-time rejection, the rejection UX is the product.
  7. Take a stance on middleware-shaped features (transactions at minimum, since no CRUD domain is credible without them) — either a worked reduction to the four shapes or a declared fifth shape.

  The one-sentence summary: the compositional core is sound and unusually well-specified, but the doc is silent on the three things that historically kill code generators — dishonest metadata, regeneration
  after change, and the bespoke-logic majority — and all three have tractable answers you can design in now, cheaply, starting with the non-interference diff test.

  