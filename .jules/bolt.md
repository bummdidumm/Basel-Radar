## 2025-03-05 - Fast String Prefix Checking
**Learning:** Python's `.startswith()` and `.endswith()` methods are significantly faster when passed a tuple of strings instead of iterating with `any(s.startswith(prefix) for prefix in prefixes)`. The tuple approach leverages the underlying C implementation directly.
**Action:** Always use the tuple form for string prefix/suffix checking when checking against multiple possibilities, and ensure the tuple is defined outside of loops.
