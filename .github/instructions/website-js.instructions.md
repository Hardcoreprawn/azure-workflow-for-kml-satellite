---
description: "Use when writing or modifying JavaScript in the website/ directory. Enforces simplicity, traceability, and defensive coding for vanilla JS with no build step."
name: "Website JavaScript Standards"
applyTo:
  - "website/**/*.js"
  - "website/**/*.html"
---
# Website JavaScript Standards

The website is vanilla JS with no framework and no build step. Code must be simple enough that any developer can open DevTools and trace a bug without a source map, a bundler, or framework knowledge.

## Code Simplicity (adapted from NASA/JPL Power of 10)

Write code a sleep-deprived on-call engineer can trace at 3 AM. These rules apply going forward.

- **Simple control flow.** No recursion. No chained ternaries. Use flat `if`/`else if`/`else`. One return point per function when practical.
- **Bounded loops.** Every loop must have a clear termination condition. No `while (true)` without a provable bounded exit.
- **Short functions.** Target ≤40 lines of logic. If it doesn't fit on one screen, split it. Each function does one thing.
- **Validate at entry.** Guard preconditions at the top of every public function. Check arguments, check DOM elements exist, check API responses have expected shape.
- **Smallest scope.** Use `const` by default, `let` only when mutation is required. Never use `var`. Declare variables at first use, not at function top.
- **Check every return.** Never ignore a return value or a `.catch()`. If a `fetch()` can fail, the caller must handle the failure visibly (error message, retry, or propagation).
- **Zero warnings.** Browser console must be clean in normal operation. No suppressed exceptions, no swallowed `.catch(() => {})`.
- **No metaprogramming.** No `eval()`, no `new Function()`, no dynamic property access chains for dispatch. If you can't find the function by searching for its name, it's too clever.
- **One nesting level inside loops.** If a loop body needs nested conditionals, extract the inner logic to a named function.
- **Comments explain why, not what.** The code should be self-describing. Comments explain intent, constraints, and trade-offs.

## DOM and Events

- Prefer `getElementById` / `querySelector` over traversal chains.
- Bind events with `addEventListener`, not inline `onclick` attributes.
- Keep event handlers thin — they should call a named function, not contain logic.
- Check that target elements exist before binding. Log a clear warning if not.

## Async and Fetch

- Use `async`/`await` over `.then()` chains. Flatter is more traceable.
- Every `fetch()` must check `response.ok` before reading the body.
- Set reasonable timeouts on network calls where the API supports it.
- Show the user a visible loading/error state — never silently fail.

## Security

- Never construct HTML from user input with string concatenation. Use `textContent` or DOM APIs.
- Never use `innerHTML` with dynamic data.
- Validate and sanitize any data before rendering it.
- All API calls must include appropriate auth tokens — never assume the backend will reject bad requests gracefully.
