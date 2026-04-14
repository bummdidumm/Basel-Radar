## 2025-03-05 - Fast String Prefix Checking
**Learning:** Python's `.startswith()` and `.endswith()` methods are significantly faster when passed a tuple of strings instead of iterating with `any(s.startswith(prefix) for prefix in prefixes)`. The tuple approach leverages the underlying C implementation directly.
**Action:** Always use the tuple form for string prefix/suffix checking when checking against multiple possibilities, and ensure the tuple is defined outside of loops.

## 2025-04-10 - Static Collection Hoisting
**Learning:** Defining static collections like `frozenset`, `tuple`, or `list` inside frequently called methods (e.g. `determine_target`) or nested loops incurs redundant object creation overhead.
**Action:** Always hoist static variables to the module level or outside of loops to prevent redundant object creation.
