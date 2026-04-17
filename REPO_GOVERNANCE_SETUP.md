# GitHub Repository Governance Setup

This document outlines the required GitHub repository settings and branch protection rules to enforce the `AGENT_FINALIZATION_PROTOCOL.md` and ensure a stable `main` branch.

**Note:** These settings must be configured manually by a repository administrator in the GitHub settings panel.

## Branch Protection Rules
Navigate to **Settings > Branches** and add a new rule for `main`.

### 1. Require Pull Request Reviews Before Merging
- **Required Approvals:** 1 (from CODEOWNERS).
- **Dismiss stale pull request approvals when new commits are pushed:** Ensure reviewers look at the latest changes.
- **Require review from Code Owners:** Enforce reviews from the users specified in the `CODEOWNERS` file.

### 2. Require Status Checks to Pass Before Merging
Enable this setting to require CI pipelines to complete successfully before allowing a merge.

**Required Status Checks** (defined in `.github/workflows/personal-brain-gates.yml`):

- `lint-and-hooks` — runs `pre-commit run --all-files` (ruff, mypy, trailing-whitespace, …).
- `personal-brain-tests (3.11)` / `personal-brain-tests (3.12)` — installs deps from `requirements.lock`, runs `pip-audit` for known CVEs, executes `release_audit.py`, then the full `pytest` smoke suite under `PYTHONPATH=bummdidumm_os_v5_final_release`.
- `finalization-protocol-check` — verifies that `AGENT_FINALIZATION_PROTOCOL.md`, `CODEOWNERS`, `.pre-commit-config.yaml`, and `REPO_GOVERNANCE_SETUP.md` all exist and that the protocol file contains the Personal Brain acceptance checklist.

### 3. Require Conversation Resolution Before Merging
- Ensure all comments and review threads are resolved before the PR can be merged.

## Recommended Merge Strategy
Navigate to **Settings > General > Pull Requests**.
- **Allow squash merging:** Enable this option.
- **Allow merge commits / Allow rebase merging:** Consider disabling these options to enforce a clean, linear commit history using Squash and Merge. This keeps the `main` branch tidy and easier to trace when bugs arise.

## CI Workflow Expectations
The CI pipelines defined in `.github/workflows/` (such as `lint-and-hooks`) strictly enforce these governance rules.

If a pre-commit hook auto-fixes a formatting issue during the CI run, the workflow will fail because the remote code is now out of sync. Developers must run `pre-commit run --all-files` locally and commit the formatted changes before pushing.
