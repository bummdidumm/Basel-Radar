# Agent Finalization Protocol

This file defines the mandatory stop/go gates for automated coding agents (Jules, Codex, Claude, etc.) working in this repository.

## Purpose

Do **not** stop after a partial fix, green unit test, or a nice-sounding PR summary.
A change is only considered complete when all required gates below are satisfied.

This protocol exists specifically to prevent:
- partial fixes that leave dependencies broken
- regressions hidden behind passing narrow tests
- path/identity inconsistencies
- destructive incremental behavior
- claiming "done" while important review comments remain unresolved

---

## Core Rule

An agent must iterate until the full chain is consistent:

1. implement fix
2. inspect dependencies and downstream effects
3. run/extend tests
4. re-check from the beginning
5. verify open review comments against the actual code
6. only then report completion

If any gate below fails, the task is **not complete**.

---

## Mandatory Gates

### Gate 1 — Scope discipline
The agent must:
- work only in the intended paths
- avoid creating parallel roots or side architectures unless explicitly requested
- avoid unrelated refactors
- avoid cosmetic-only documentation as a substitute for code fixes

### Gate 2 — Real bug closure
For each reported issue/comment:
- verify the code before claiming it is fixed
- ensure the exact failing behavior is removed
- ensure no equivalent variant of the same bug remains elsewhere

Examples:
- if `preview` was treated as a dict in one parser, check all similar parsers
- if legacy count backfill is required, ensure old on-disk data is preserved on first rerun
- if temp files are used for parsing, ensure deleted temp paths are not persisted as canonical source paths

### Gate 3 — Identity consistency
For any indexing / source / rename / move related change, verify that the same logical source remains the same source across:
- pass 1
- pass 2
- sorting
- apply sort
- rename / move
- personal brain runtime
- final persisted index

Required invariants:
- rename must not create a new logical source
- move must not create a new logical source
- metadata-only change must not create a new logical source
- partial re-index must not lose history
- persisted `source_path` values must be canonical and durable, not deleted temp paths

### Gate 4 — Incremental safety
Any merge/update logic must be checked for first-run and rerun safety.

Required:
- no historical data loss on the first run after schema/merge changes
- no count inflation on repeated runs over the same source
- no destructive overwrite of full-state artifacts from a partial batch
- on-disk merged state must remain coherent after partial re-index

### Gate 5 — Full-state output correctness
If a "master" or "complete" output exists, it must be built from the full merged state, not just the current batch.

Required outputs must reflect the full state of:
- sources
- records
- entities
- relations
- daily memory
- search views

### Gate 6 — Parser safety
For parser additions/changes:
- `can_handle()` must never crash on unexpected preview types
- parser fallback behavior must fail safe
- bundle/archive parsing must not silently swallow important failures
- if archive recursion is added, ensure durable canonical references are persisted, not transient extraction paths

### Gate 7 — Test adequacy
Green tests are not enough unless they cover the bug class.

Required:
- add or update tests for every important bug fix
- include regression coverage for the exact previous failure mode
- prefer thin integration coverage over isolated happy-path-only unit tests when the bug crosses modules

Minimum examples when relevant:
- rename / move / metadata-only update preserving one logical source
- first run after merge-schema change preserving legacy counts
- master output built from full merged state
- archive sub-file parsing not persisting deleted temp paths

### Gate 8 — Review comment closure
Before reporting completion, the agent must re-check all open review comments and verify against the current HEAD.
Do not rely on memory or prior summaries.

For each unresolved comment, explicitly determine:
- fixed in code
- still open
- partially fixed
- obsolete because of later code changes

### Gate 9 — User-control over knowledge retention
For knowledge/indexing changes, the design must keep room for user-controlled exclusion/purge.
The system must not assume that all extracted knowledge should stay forever.

At minimum, future work must support:
- excluding irrelevant sources
- purging unwanted indexed knowledge intentionally
- reviewing whether original raw exports are still needed before assuming safe deletion

### Gate 10 — Honest completion rule
An agent may only report "done" when:
- all required gates pass
- all critical review comments are either fixed or explicitly explained as intentionally deferred
- the exact remaining gaps, if any, are stated clearly

Never report complete based only on:
- passing a subset of tests
- a plausible summary
- fixing one comment while related dependency bugs remain

---

## Required completion format

When finishing, the agent must report only:
- changed files
- exact fixes
- commit SHA
- test status
- what critical review comments are now closed
- what remains intentionally open, if anything

---

## Personal Brain specific acceptance checklist

For `bummdidumm_os_v5_final_release/...` changes touching the Personal Brain pipeline, the agent must explicitly verify:

- source identity stable across rename/move/re-index
- no deleted temp paths persisted as canonical source paths
- entity merge does not lose historical counts on first rerun
- entity merge does not inflate counts on repeated runs
- master index is derived from the full merged on-disk state
- archive/bundle ingestion is parser-usable, not preview-only
- parser resolution cannot crash on preview type mismatches
- final outputs are coherent for source/record/entity/relation/daily/search/master layers

---

## Default instruction to future agents

If this file exists in the repository, treat it as a mandatory acceptance protocol for repository changes unless the user explicitly overrides it.
