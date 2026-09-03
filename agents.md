# Repository Guide for Agents

## Mission

Build the smart parking system described in `2026-09-03-smart-parking-design.md` and summarized in `architecture.md`. Keep it runnable without hardware while preserving a clean path to the ESP32-CAM and ESP32 DevKit prototype.

## Source-of-Truth Order

When documents differ, use this order:

1. The user's current instruction.
2. Accepted entries in `decisions.md`.
3. `2026-09-03-smart-parking-design.md` for product scope and requirements.
4. `architecture.md` for component boundaries and data flow.
5. `progress.md` for current execution state.

Do not silently resolve contradictions. Record a decision or ask for clarification when the higher-priority source does not settle the issue.

## Working Rules

- Read the four project documents before planning a material change.
- Keep `progress.md` current whenever a milestone starts, completes, or becomes blocked.
- Add an entry to `decisions.md` for choices that affect public interfaces, dependencies, data models, hardware pins, algorithms, or repository structure.
- Prefer the smallest implementation that completes a vertical slice in demo mode.
- Keep hardware access behind interfaces so unit and integration tests do not require devices.
- Never commit secrets, Wi-Fi credentials, calibrated private configuration, model datasets, generated artifacts, or the SQLite runtime database.
- Do not change optimizer weights, slot count, endpoint contracts, or evaluation metrics without recording the decision.
- Preserve deterministic seeds in tests and benchmark fixtures.

## Implementation Order

1. Repository and Python project scaffolding.
2. Domain models, configuration, SQLite initialization, and five-slot seed data.
3. Shared allocation cost interface plus GA, PSO, and ACO comparison.
4. Entry/exit and parking-status API flows in demo mode.
5. Occupancy heuristic, ROI configuration, and camera update flow.
6. Shared prediction preprocessing, deterministic fallback, and model comparison scripts.
7. Dashboard and complete simulated lifecycle.
8. ESP32-CAM and controller firmware integration.
9. CNN and trained sequence-model artifacts after datasets exist.

Each stage should leave a runnable, tested state. Avoid scaffolding later stages before the interfaces they depend on are established.

## Expected Engineering Practices

- Use Python type hints and explicit request/response schemas.
- Keep domain logic outside FastAPI route handlers.
- Use migrations or idempotent initialization for schema changes.
- Test safety invariants, fallback paths, and persistence side effects.
- Compare algorithms on identical seeded inputs.
- Treat timestamps as timezone-aware UTC in storage and convert only for presentation.
- Return structured errors suitable for both firmware and dashboard clients.
- Document firmware pin assignments before committing sketches.

## Verification Baseline

Until project tooling is created, documentation changes must pass whitespace checks and internal-link/path review. Once the Python project exists, every change should run the relevant focused tests plus the full configured test and lint commands. Firmware changes must compile for their target board and include reproducible build instructions.

## Commit Workflow

Create commits only after the requested change is complete and verified.

1. Run `git status --short --branch` and confirm the current branch and pre-existing user changes.
2. Review `git diff` and keep unrelated changes out of the commit.
3. Run the focused tests for the changed behavior, followed by the repository's configured full test and lint commands when available.
4. Update `progress.md` and, when the change establishes or supersedes an architectural choice, `decisions.md`.
5. Stage explicit files with `git add <path>...`; do not use broad staging when unrelated changes are present.
6. Review `git diff --cached --check`, `git diff --cached --stat`, and the complete cached diff before committing.
7. Make one logical commit with a concise imperative message, preferably using a conventional prefix such as `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, or `chore:`.
8. Confirm the commit with `git show --stat --oneline HEAD` and ensure the remaining working-tree state is understood.

Do not rewrite, amend, squash, or discard commits or changes created by someone else unless the user explicitly requests it. Never bypass failing checks just to create a commit.

## Push Workflow

Push only when the user requested it or the agreed workflow explicitly includes it.

1. Run `git remote -v` and confirm the intended remote; do not invent or replace a remote URL.
2. Run `git status --short --branch` and confirm that the intended commits and branch are ready.
3. Check the upstream with `git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'`.
4. If an upstream exists, use a normal `git push`. If none exists and the intended remote is `origin`, use `git push --set-upstream origin HEAD`.
5. Report the pushed branch and commit hash, then rerun `git status --short --branch`.

Never force-push, delete a remote branch, push secrets, or push unrelated local commits without explicit user authorization. If no remote exists, stop after the local commit and report that a remote URL or repository is required.

## Session Handoff

Before ending a work session, update `progress.md` with:

- what changed,
- what was verified,
- the active branch and latest relevant commit,
- the next concrete task,
- any blocker or unresolved decision.

Then provide a handoff using this structure:

```markdown
## Session Handoff

- Objective: <the requested outcome>
- Completed: <files or behavior changed>
- Verification: <commands run and their results>
- Git state: <branch, latest commit, clean/dirty worktree, push status>
- Decisions: <ADR entries added or "None">
- Blockers: <specific blocker or "None">
- Next step: <one concrete action>
```

Keep the handoff factual and concise. Do not claim tests, commits, or pushes succeeded without fresh command output. Git remains the detailed history, while `progress.md` carries durable context across sessions.
