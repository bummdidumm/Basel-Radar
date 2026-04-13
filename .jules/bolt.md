## 2026-04-13 - Optimization of sorting rules
**Learning:** Creating frozenset in a function call inside a loop has high overhead. Additionally, using generator expressions in any() with inline tuple creations inside a tight loop creates high overhead.
**Action:** Hoist constant sets/lists outside of tight loop functions to static module-level variables. Use any() with generator loops containing hoisted tuple variables instead of inline instantiations.
