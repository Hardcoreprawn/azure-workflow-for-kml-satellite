# Engineering Council

A small review pipeline, not an AI committee. Seven optimisation functions,
one coordinator, one pass, one human decision. No model SDK, daemon, database,
message bus, autonomous edits or merge permissions.

Inspired by [Ponytail](https://ponytail.dev)'s simplicity-first principles.
These are original prompts, not a copy of Ponytail's implementation. We make
no claim to reproduce its published benchmark results.

## Why these components exist (and how to live without them)

| Component | Why it exists | Without it |
| --- | --- | --- |
| Seven specialist prompts | Give reviewers distinct optimisation functions, not personalities | Use one general reviewer; appropriate for trivial changes |
| Finisher | Apply termination pressure and expose the remaining path to usable software | Delivery scopes the work; the human must enforce completion pressure |
| Feynman | Expose inherited assumptions with evidence and plain explanations | Existing reviewers still simplify; the human challenges inherited conventions |
| Council coordinator | Select a bounded sequence and stop; does not review again | Invoke a single specialist manually |
| Python CLI | Enforce adapter budgets, validate reports and rank evidence deterministically | Native Copilot still reviews; humans enforce limits and prioritise findings |
| JSON packet/report | Bind findings to the exact supplied context and enable offline checks | Attach files and review manually; less reproducible |
| Two configuration examples | Make cost ceilings explicit without new configuration machinery | Defaults embedded in the CLI suffice |
| Dockerfile | Run the same CLI/tests with isolated dependencies and constrained access | Run Python locally; native adapters have host-user privileges |
| Behavioral tests | Prove that failures and missing reviews cannot look like approval | Humans must exercise every failure mode; not a safe basis for replacing agents |

Do not add a component unless observed failures justify its maintenance cost.
The installer is just file copying with collision checks; manual copying works
too. It intentionally does not manage extensions, auth, editor settings or Git.

## Architecture and repository structure

For normal delivery, choose one relevant specialist and add a complementary
review only when its risk or expected benefit justifies the cost. The following
pipeline applies when the engineer explicitly chooses Council:

```text
Human supplies goal, acceptance checks, relevant evidence and effort estimate
  -> summarise requirement and acceptance signal
  -> packet (bounded, never silently truncated)
  -> sequential selected reviewers (same context, no cross-review conversation)
  -> strict ordered reports
  -> decide (safety precedence, deterministic ranking, human escalation)
  -> human verifies evidence
  -> normal Copilot Agent Mode implements the smallest useful change
  -> focused tests + repository delivery gates
```

```text
engineering_council/
  council.py                 # packet, run, decide, install; Python stdlib only
  test_council.py             # portable unittest suite
  config.json                # seven-call ceiling, same total time budget
  config.full.json            # seven-call ceiling, explicit 240-second cap
  prompts/review.md           # shared one-pass JSON contract
  .github/agents/
    council.agent.md
    ponytail.agent.md
    hamilton.agent.md
    lambda.agent.md
    architect.agent.md
    delivery.agent.md
    finisher.agent.md
    feynman.agent.md
  Dockerfile
  .dockerignore              # allowlisted build context; no repository/secrets
```

Keep this folder name when copying the project to another repository. It is a
standalone package: no imports from Canopex and no application dependencies.
Run examples from its parent directory. Python 3.11+ is sufficient; Docker
uses Python 3.12. The host repository imports its unittest suite into its
existing pytest gate without duplicating tests.

## Council model and roles

| Agent | Optimisation function | Must not become |
| --- | --- | --- |
| Ponytail | Delete unnecessary code, dependencies and unearned abstractions | A code-golf reviewer that removes safety |
| Hamilton | Correctness, typing, validation, bounded execution, visible failure, recovery | Speculative defensive scaffolding |
| Lambda | Pure transforms, explicit transitions, less hidden state, debuggability | Functional-pattern theatre or a rewrite mandate |
| Architect | Fewer services, infrastructure dependencies and moving parts | A generator of architecture diagrams and future platforms |
| Delivery | Concrete persona/JTBD, measurable acceptance, smaller shippable slices | Permission to ship unsafe behavior |
| Finisher | Minimum shippable outcome, termination pressure and fastest validation | Permission to bypass safety or pretend incomplete work is done |
| Feynman | First-principles challenges, hidden assumptions and inherited complexity | A veto, an endless questioning loop or another architecture exercise |

Finisher returns **recommended MVP, scope reductions, deferred work and shipping
recommendation**. Feynman returns **hidden assumptions, simplification
opportunities, alternatives and areas needing stronger justification**.
Direct reviews use these concise headings. Packet reviews label them within the
existing finding fields; no extra report format or orchestration component exists.

All specialists have only `read` and `search` tools. They cannot delegate or
edit through their configured tools. Council additionally has `agent`, but no
terminal/edit tools. Files use the shared Copilot custom-agent fields; no
model pins, Local-only `agents` allowlists, handoffs or custom extension API.
Actual discovery/tool restrictions remain runtime-dependent: inspect them in
VS Code rather than trusting a YAML file.

### Refactor proposals, not just defect lists

For a focused refactor, invoke a specialist directly with the owning function,
nearest callers/tests and required behavior. The reviewer can challenge internal
structure, algorithms and mutation rather than treating every existing detail as
a requirement. Demonstrated maintenance or reasoning cost justifies a proposal;
a runtime bug is not required. Explicit constraints in your brief still govern.

Keep the lenses distinct even when all reviewers start from the same function:

| Agent | Review surface | Concrete proposal |
| --- | --- | --- |
| Ponytail | Code, branches, duplication, dependencies | Smaller implementation and net maintenance benefit |
| Hamilton | Invariants, boundaries, failure/recovery paths | Safer control flow and checks preserving required guarantees |
| Lambda | Mutation, state ownership, data flow, I/O | Explicit transitions or independently testable transforms |
| Architect | Relevant system/runtime/service/storage boundaries | Current/proposed system flow and operational trade-offs |
| Delivery | Persona value, scope, cost of rework | Worthwhile deliverable slice with measurable acceptance |
| Finisher | Remaining work, validation, stopping criteria | Fastest completion path and deferrals |
| Feynman | Assumptions behind the approach | Falsifiable alternative and evidence needed to choose |

Architect uses a function as a system entry point, not an invitation to shorten
it. Supply relevant callers and architecture context; a packet lacking that
evidence cannot support a system-level conclusion. Direct reviews may read
necessary supporting context; packet reviews cannot assume unsupplied facts.
Do not require every role to propose code or reward manufactured disagreement.

Ask for one concrete role-appropriate alternative, what it removes, necessary
dependent changes, trade-offs and exact validation checks. Judge total maintained
code, branches, state and indirection, not merely the length of the original
function. A helper must earn its existence through clearer boundaries or
independent testability. Trivial cuts need not earn an implementation cycle.
Leave unchanged is a valid conclusion; different agents need not invent different
findings. Bug fixes and intentional contract changes must be labelled separately.

Example direct brief:

> Review this function and relevant context through your specialist lens.
> Preserve required outputs, safety guarantees, fallback order and failure
> visibility. You may challenge internal structure; show dependent changes.
> Architect should trace relevant system boundaries,
> not perform local cleanup; Delivery and Finisher should select scope/completion;
> Feynman should test assumptions. Give your strongest concrete alternative,
> benefit, risks and validation, or explain why leaving it unchanged is better.
> One pass, at most three findings; do not edit or run commands.

Direct reviews use evidence, proposed implementation, trade-offs, validation and
the smallest worthwhile next step. Packet reviews put sketches in the existing
recommendation string; there are no new JSON fields or execution permissions.
Budgets and one-pass limits still apply. Prompt changes invite better proposals,
but do not prove model quality; a follow-up trial must measure that separately.

### Selection and cost

| Kind | Selection |
| --- | --- |
| normal focused work | One relevant specialist; selective complementary review |
| safety-sensitive work | Include Hamilton and required safety checks; a full council is not automatic |
| explicitly requested council for change / pr / plan / architecture work | Ponytail -> Architect -> Hamilton -> Lambda -> Feynman -> Delivery -> Finisher |
| explicit full council | Same seven-agent sequence; no extra round |

Use normal single-agent review for typos, trivial changes and focused work.
For an explicit council review, summarise the requirement, run the seven concise
reviews in order, produce the final recommendation, then implement through normal
Agent Mode. Creating a CLI packet opts into that council sequence; it is not a
requirement for every non-trivial task. Adoption of the specialist prompts is
provisional: the trials showed useful differentiated findings, not lower total
delivery cost or proof that every role adds value on every task.
Input is explicitly supplied, not the whole repository. Include the owning
code and nearest tests, not just the changed lines. For PRs, fetch context using
`gh pr view N` and `gh pr diff N` yourself; there is no GitHub API integration.
Remove credentials, personal/customer data and unrelated files before review.

Defaults: 7 calls, 180 seconds total, 24,000 context bytes, 12,000 combined
stdout/stderr bytes per adapter call, 3 findings per agent. Review time is
`min(max_seconds, implementation_minutes * 60 * review_fraction)`, with a default
fraction of 0.25. A one-minute implementation therefore gets 15 seconds of
review, not three minutes of committee work. One round; no retries or rebuttals.
Stop on budget exhaustion, malformed response, adapter failure or a blocker.
The seven-call ceiling is not a requirement to consume the budget: stopping
early retains missing reviews and never implies approval. The old three-call
configuration now fails explicitly for non-trivial work rather than silently
skipping requested reviewers. `--full` remains accepted but selects the same
sequence, not extra discussion.

Finisher aggressively applies:
**STOP DISCUSSING. IMPLEMENT THE SIMPLEST WORKING VERSION.**
when planning, architecture, abstraction debate or optimisation costs more than
building and validating the solution. Its exact recommendation is carried into
the decision's next action. The runner also stops automatically at the existing
fraction-of-implementation time budget, even if Finisher has not yet run.
No new completion loop, follow-up conversation or autonomous implementation is
introduced. Required safety evidence and validation must still be resolved.

The adapter runner mechanically enforces these bounds. Native Copilot enforces
them through instructions and report validation, not a VS Code execution hook.
Its model/tool tokens and billing cannot be hard-capped by these files. Character
limits are not token accounting. Use the adapter path when enforced elapsed-time
and output limits matter; use available Copilot telemetry to measure actual cost.
The effort estimate is supplied by the engineer, not invented by the model.

## VS Code / GitHub Copilot Agent Mode

Install without removing anything:

```sh
python3 -m engineering_council.council install --repo .
```

Open **Chat: Open Customizations -> Agents**, confirm the eight agents appear,
and inspect their actual tools. Select Council in the Copilot harness. The
host implements sub-agent calls; there is no new VS Code extension to maintain.
If your installed Copilot runtime does not expose delegation, use specialists
manually in the same bounded order. Never simulate successful delegation.

Prepare a small context file containing the plan/architecture or diff plus
necessary surrounding code, tests, known validation results and non-goals:

```sh
python3 -m engineering_council.council packet \
  --input /tmp/review-context.txt \
  --brief 'Preserve upload behavior; remove the duplicated retry loop; prove it with a focused test' \
  --kind change --risk high --implementation-minutes 10 \
  --config engineering_council/config.json --output /tmp/council-packet.json
```

Attach the packet to Council: "Review this packet, return the ordered report
array, and do not implement." Save the returned JSON array, without fences or
the explanatory handoff, then:

```sh
python3 -m engineering_council.council decide \
  --packet /tmp/council-packet.json --reports /tmp/council-reports.json \
  --output /tmp/council-decision.json
```

Output paths must be new files. Existing paths are rejected before adapter calls;
exclusive final creation still protects against overwriting if a path appears
during execution. Keep useful reports as local artifacts, not permanent agent memory.
For the explicit 240-second cap use `--full --config engineering_council/config.full.json`.
Never use `--full` to restart or bypass an exhausted review.

## Optional adapter execution

`run` invokes an **explicitly approved executable**, without a shell, once per
selected agent. The adapter reads one JSON envelope from stdin:

```json
{
  "agent": "Ponytail",
  "instructions": "Shared contract plus specialist prompt",
  "packet": {"request_id": "...", "roles": ["Ponytail", "Architect", "Hamilton", "Lambda", "Feynman", "Delivery", "Finisher"]}
}
```

The packet shown here is abbreviated; the real envelope contains the complete
versioned packet. Stdout must contain exactly the JSON report specified in
`prompts/review.md`; stderr is bounded diagnostic output. No Markdown, banners
or extra fields. An adapter can bridge an approved Copilot CLI/SDK runtime;
none is bundled because runtime/auth/tool APIs differ and native Copilot
already supplies inference. Do not pass arbitrary CLI output off as a review.

```sh
python3 -m engineering_council.council run \
  --packet /tmp/council-packet.json --output /tmp/council-decision.json \
  --adapter /absolute/path/to/approved-review-adapter
```

`--adapter` and its arguments must come last. No command is derived from PR text
or configuration. The runner uses nonblocking pipes, simultaneous stream bounds,
monotonic deadlines and a dedicated POSIX process group, cleaned up on exit.
Windows users can use native Copilot or Docker.

**Native adapters are trusted code, not sandboxed.** They inherit the caller's
environment and privileges and could read credentials or change files. Run them
in a restricted container with only explicitly allowed inputs when isolation
is required. An adapter must not daemonise or escape its process group. Container
PID/memory/CPU limits contain broader process abuse; a container is not a hostile
code sandbox or a replacement for authorisation.

## Decisions, weighting and escalation

No majority vote and no numerical quality score:

1. Any evidence-linked safety/correctness blocker requires human resolution.
2. Missing, failed, mismatched, duplicated, oversized or out-of-order reports
   never create a complete review.
3. User requirements are the governing contract. Conflict priority is Hamilton
   (safety/correctness), Ponytail (simplicity), Delivery (value), Finisher
   (completion), Architect (architecture), then Lambda (functional purity).
   Humans verify findings against the brief; ranking does not overrule the user.
4. Non-advisory safety/blocker findings rank first, then role priority, severity,
   category weight, lower fix effort and stable target/name tie-breakers.
   Category weights remain tie-breakers: safety 5; simplicity, delivery and
   completion 3; state/topology 2; assumptions 1.
   Feynman ranks last and is advisory: its challenges cannot veto decisions,
   trigger conflict escalation or stop Delivery/Finisher from reviewing.
   Credible safety evidence from Feynman still needs human/Hamilton verification;
   advisory status is not permission to ignore a real defect.
5. Identical full findings are deduplicated across agents. Different severity,
   evidence or other finding fields are retained, even when the recommended
   action matches, so blocker evidence is never hidden. Different
   non-advisory actions on the same exact target trigger human escalation,
   guided by the priority order, not another round.
   Semantic conflicts across different identifiers still require human review.
6. The engineer records each disposition: accept and test, reject with evidence,
   or defer with a linked follow-up. The harness does not fabricate dispositions.

Decision JSON includes `version`, `request_id`, `status`, `completed`, `missing`,
`disagreements`, ranked `findings`, and `next_action`. Adapter execution adds
`errors` and `elapsed_seconds`. Packet SHA-256 binds the supplied context/config,
not the working tree or reviewer identity; it is not a signature.

| Exit | Meaning |
| --- | --- |
| 0 | Packet/install succeeded, or complete recommendation (**not approval**) |
| 1 | Invalid input, configuration, filesystem or installation failure |
| 2 | Complete review needs a human to resolve blockers/disagreement |
| 3 | Incomplete review; stop discussion and resolve missing evidence/blockers |

On failure, valid earlier findings are retained. Choose the simplest reversible
implementation only **after** necessary safety evidence is resolved. Neither
an empty finding list nor a timeout means "ship it".

## Docker model

An ephemeral CLI container, not a service or another developer platform.
Build once, run that image for packet creation, decisions and offline tests:

```sh
docker build -t engineering-council:local engineering_council
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 128m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --entrypoint python engineering-council:local \
  -m unittest discover -s engineering_council -t . -v
```

For offline packet/decision commands mount only a curated input directory
read-only and a separate output directory writable, using `--user "$(id -u):$(id -g)"`
if host file ownership requires it:

```sh
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 128m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --mount type=bind,src=/absolute/curated-input,dst=/input,readonly \
  --mount type=bind,src=/absolute/council-output,dst=/output \
  engineering-council:local decide \
  --packet /input/packet.json --reports /input/reports.json \
  --output /output/decision.json
```

No source repository, secrets, host Docker socket or shared application network
is mounted by default. Offline Docker does **not** run model inference. To execute
an approved adapter, build a derived image containing it and use `run`; permit
only its necessary network/auth explicitly. Never bake credentials into layers.
No cloud deployment or shared-environment promotion is introduced. The image is
replaceable tooling; rollback is using the previous image/agent definitions.

## Tests and delivery plan

MVP slices, in dependency order:

1. **Contract/core:** packet and strict report validation, deterministic ranking,
   incomplete review handling and original specialist prompts.
2. **Execution:** native workflow plus optional bounded adapter, process cleanup,
   output/timeout/failure tests and isolated offline Docker execution.
3. **Migration:** after local and Docker checks pass, copy the eight agents,
   explicitly remove the five previous agents and repair dependent prompt/skill
   routing. Then repeat repository gates. No roadmap/Project updates.

```sh
python3 -m unittest discover -s engineering_council -t . -v
```

Tests cover the actual call/time/byte limits, simultaneous stream floods,
descendant-held pipes, schema failures (including duplicate JSON keys), stale packets, safety precedence,
deduplication/conflicts, compact UTF-8 report budgets, CLI evidence persistence
and output preflight, and explicit installation.
Report count and each compact UTF-8 report's byte size bound native report input;
the adapter additionally bounds actual combined stdout/stderr bytes.
The host's focused command is
`make test-fast TESTS="tests/test_engineering_council.py"`; handoff is `make check`.

Offline correctness is not model quality. Before relying on the council, run a
real Copilot trial on a known small defect, an unnecessary abstraction and a
correct change. Verify evidence, false positives, actual tool permissions and
elapsed/cost telemetry against a single general reviewer. Keep the council only
if it produces useful fixes at less total delivery cost. Never claim tokens
saved or review parity from fixture tests alone.

### Canopex migration mapping

Reusable agents do not embed Canopex product policy. Existing repository
instructions and routed prompts retain its source-of-truth and owner gates:

| Previous role | Replacement routing | Preserved concern |
| --- | --- | --- |
| Code Review Critic | Hamilton; Council for multi-lens review | Defects, regression tests, engineering standards |
| Release Safety Guard | Hamilton | Promotion, authenticated smoke, rollback, observability |
| Contract and Docs Keeper | Hamilton | Canonical contracts, operational docs, matching tests |
| Persona Auditor | Delivery | Persona/JTBD, evidence confidence, batch/non-GIS usability |
| Roadmap Orchestrator | Architect + Delivery via execution workflow | Ordered slices, dependencies, measurable value |

After the explicit test gate:

```sh
python3 -m engineering_council.council install --repo . --replace-old
```

The installer deletes only the five named legacy files; unrelated agents are
untouched. It refuses different existing council definitions and rejects
symlinked `.github`, agent directories or council destination files before
writing or removing agents. An explicitly supplied repository root is resolved
first; these checks prevent accidental child-path redirection, not concurrent
filesystem attacks. Dependent routing
edits are human-reviewed repository changes, not a generic rewrite tool.
Restore the previous tracked agent/prompt/skill versions from Git through a
reviewed revert if the trial regresses. Do not silently retain both competing
agent sets indefinitely.

## Risks, trade-offs and extension policy

- **Correlated reviewers:** different goals are not independent model evidence.
  Mechanical tests and human review remain authoritative.
- **Token multiplication:** seven reviewers see the same context. This is more
  expensive than the original three-reviewer default; concise reviews, unchanged
  total time/byte budgets and no follow-up rounds control overhead. No guaranteed
  savings; use one relevant reviewer for focused work.
- **False positives / false confidence:** strict JSON proves shape, not truth.
  Evidence must be reproduced. Missing review never passes.
- **Shallow context:** bounded slices can omit behavior outside the diff. Include
  owning code/tests; escalate if necessary context cannot fit.
- **Native enforcement:** prompts are not hard runtime budgets. Prefer one agent
  for small work; use the adapter runner for mechanical resource bounds.
- **Lost specialist depth:** merged contract/release responsibilities need real
  comparative trials. Repository-specific routed prompts preserve their checks.
- **Configuration abuse:** increasing time/size budgets is explicit, capped and
  auditable, but cannot establish value or replace a small scope.

Recommended stack: Markdown agents + JSON + Python stdlib + unittest + an
ephemeral Docker image + existing Copilot/VS Code and `gh`. No LangChain,
CrewAI, AutoGen, vector store, MCP server, queue, web dashboard or Kubernetes.
Without any of those, the same bounded file-in/file-out workflow already works.

Extend only after a repeated observed failure: update the small role/profile
tables, add one prompt and a focused behavioral test. Keep one-pass semantics.
For another provider, write a single stdin/stdout adapter; do not add a provider
registry. Version the packet contract directly and update producers/tests
together. Add hooks or telemetry only when measured savings repay their
maintenance cost. Delete an agent or this runner if a single reviewer wins.
