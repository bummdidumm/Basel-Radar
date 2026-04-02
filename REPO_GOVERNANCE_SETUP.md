# Repo Governance Setup

This repository now contains:
- `AGENT_FINALIZATION_PROTOCOL.md`
- `CODEOWNERS`
- `.pre-commit-config.yaml`

To complete the governance setup, configure the following in GitHub repository settings.

## Recommended branch/ruleset settings for `main`

Enable these protections for the default branch:
- Require a pull request before merging
- Require approvals (recommended: at least 1)
- Dismiss stale approvals when new commits are pushed
- Require review from Code Owners
- Require status checks to pass before merging
- Require conversation resolution before merging
- Do not allow bypassing the above settings
- Optional later: require merge queue

## Recommended required status checks

Use unique job names and require them before merge:
- `lint-and-hooks`
- `personal-brain-tests`
- `finalization-protocol-check`

## Local developer setup

Install pre-commit locally:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Agent working mode

Agents should work on the same PR branch until all required gates are satisfied.
Do not open a new PR for review-fix follow-ups unless explicitly requested.

Before any merge, the agent must satisfy `AGENT_FINALIZATION_PROTOCOL.md`.
