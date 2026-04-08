---
description: "Use when writing or modifying Python code, tests, activities, parsers, or pipeline logic. Enforces test-first development, functional style, and high-reliability engineering discipline."
name: "Engineering Standards"
applyTo:
  - "**/*.py"
  - "tests/**"
  - "treesight/**"
  - "blueprints/**"
  - "scripts/**"
  - "rust/**"
---
# Engineering Standards

Write idiomatic, clean, high-reliability Python. Every function should be testable in isolation. Every behavior should be proven by a test before it ships.

## Test First

- Write the test before the implementation. The test defines the contract.
- A failing test is the starting point, not a follow-up task.
- Tests should assert behavior, not implementation. Test what the function does, not how.
- Name tests after the behavior they verify: `test_rejects_zip_bomb`, not `test_validate_3`.
- Prefer small, focused test functions over large parametrized matrices unless the cases are truly uniform.
- Test edge cases and failure modes, not just the happy path.

## Functional Style

- Prefer pure functions: data in, data out, no side effects.
- Push side effects (I/O, storage, network) to the boundaries. Keep core logic pure.
- Compose small functions rather than building large ones with branches.
- Avoid mutable state. Prefer returning new values over mutating arguments.
- Use dataclasses or Pydantic models for structured data, not dicts-of-dicts.

## Error Handling — Let It Crash

- Validate at system boundaries (API handlers, blob trigger, activity entry points).
- Inside core logic, let exceptions propagate. Do not catch-and-swallow.
- Raise specific exceptions with clear messages. `ValueError("KML exceeds 10 MiB")`, not `Exception("error")`.
- Catch only at orchestration boundaries where you can report, retry, or refund (e.g. quota release).
- Never silence exceptions with bare `except: pass`.

## Python Idioms

- Use `from __future__ import annotations` in all modules.
- Type-annotate all function signatures. Avoid `Any` unless the type is genuinely unknown.
- Use `pathlib.Path` over `os.path`. Use `f-strings` over `.format()` or `%`.
- Constants in `treesight/constants.py`, not magic numbers inline.
- Imports: stdlib → third-party → local, separated by blank lines.

## Reliability

- Defend against malicious input at every ingestion point: uploaded files, API payloads, webhook events.
- Size-check before parsing. Schema-check before processing. Never trust content-type headers alone.
- Log at decision points with structured context: `logger.info("msg", extra={...})` or at minimum `logger.info("msg key=%s", value)`.
- Make operations idempotent where possible. A retry should not create a duplicate or corrupt state.

## Code Simplicity (adapted from NASA/JPL Power of 10)

Write code that a sleep-deprived on-call engineer can trace at 3 AM. Prefer boring clarity over clever brevity. These rules apply going forward — fix existing violations opportunistically, not retroactively.

- **Simple control flow.** No recursion. No chained ternaries. Use flat `if`/`elif`/`else`. One exit point per function when practical.
- **Bounded loops.** Every loop must have a clear termination condition. No `while True` without a provable bounded exit (e.g. `break` within a counted retry or a `for` with `max_attempts`).
- **Short functions.** Target ≤40 lines of logic per function. If it doesn't fit on one screen, split it. Each function should do one thing.
- **Validate at entry.** Assert or guard preconditions at the top of every public function. Don't trust callers — verify inputs before proceeding.
- **Smallest scope.** Declare variables where they're first used, not at the top of a function. Avoid reusing variable names for different purposes.
- **Check every return.** Never ignore a return value silently. If a function can fail, the caller must handle the failure or propagate it explicitly.
- **Zero warnings.** Lint and type-check must be clean. Every suppression (`noqa`, `type: ignore`, `nosemgrep`) requires an inline comment justifying why.
- **No metaprogramming.** No `exec`, `eval`, or `getattr`-chains for dispatch. No dynamic class construction. If the reader can't follow the call chain by searching for the function name, it's too clever.
- **One nesting level inside loops.** If the body of a loop needs an `if` that needs another `if`, extract the inner logic to a named function.
- **Comments explain why, not what.** If you need a comment to explain what the code does, the code is too complex. Rewrite it. Comments should explain intent, constraints, and non-obvious trade-offs.

## Rust (PyO3 Extension)

The `rust/` crate (`treesight_rs`) is a PyO3 extension for performance-critical raster operations. It is called from Python and must be correct, fast, and safe.

- All public functions exposed via `#[pyfunction]` must have doc comments explaining inputs, outputs, and invariants.
- Use `rayon` for data parallelism on large arrays. Do not spawn raw threads.
- Validate array dimensions and contiguity at the PyO3 boundary. Panic on invariant violations inside pure compute — PyO3 converts Rust panics to Python exceptions.
- Prefer flat buffer iteration over 2D indexing for cache-friendly access.
- No `unsafe` unless required by FFI. Justify every `unsafe` block with a safety comment.
- Test via Python-side tests in `tests/test_rust_accel.py` — the Rust functions are consumed as a Python module, so test the interface users see.
- Keep the crate small and single-purpose. If a new operation doesn't need native speed, write it in Python.

### Rust Simplicity (Power of 10, adapted)

The original NASA rules were written for C — Rust already enforces several of them via the type system. Apply the rest explicitly:

- **Simple control flow.** No recursion. Prefer `match` with explicit arms over nested `if let` chains. Avoid `loop` without a bounded exit condition.
- **Short functions.** Target ≤40 lines per function. Extract compute kernels into named helpers.
- **No `unwrap()` or `expect()` at the PyO3 boundary.** Use `PyResult` and `?` to propagate errors. `unwrap()` is acceptable only inside pure compute where the invariant is already validated at the boundary.
- **One nesting level inside iterators.** If a `.map()` or `.for_each()` closure needs nested conditionals, extract the inner logic to a named function.
- **Zero warnings.** `#![deny(warnings)]` in the crate root. Every `#[allow(...)]` requires an inline comment justifying why.
- **No trait magic for dispatch.** Keep the call graph grep-able. If you can't find a function by searching for its name, it's too indirect. Use concrete types over dynamic dispatch (`dyn Trait`) unless the design requires it.
