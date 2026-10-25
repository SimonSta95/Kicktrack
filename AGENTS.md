# KickTrack Repository Guide

This file extends the global engineering rules for this repository.

## Stack and layout

- Desktop runtime: Tauri 2 with Rust in `src-tauri/`.
- UI: React 19, TypeScript, Vite and TanStack Query in `src/`.
- Persistence: local SQLite managed by `src-tauri/src/db/`.
- External data: the unofficial Kickbase API and FotMob portrait assets.

Keep UI, application commands, Kickbase transport/parsing, and persistence responsibilities separate. Tauri commands are the trusted boundary: validate input and enforce write preconditions there even when the UI performs the same checks.

## Required checks

For frontend changes run:

```text
npm test
npm run typecheck
npm run build
```

For Rust changes run:

```text
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path src-tauri/Cargo.toml
```

The repository contains older Rust formatting that is not yet globally normalized. Format edited Rust files, but do not create repository-wide formatting-only diffs as part of unrelated work.

## Domain and safety invariants

- Treat Kickbase and FotMob payloads as untrusted. Validate IDs before interpolating them into request paths.
- Do not log tokens, passwords, complete private payloads, or personal data.
- Persist credentials only in the operating-system credential store and only after explicit opt-in. Logout must remove persisted session and credentials.
- Never retry a state-changing Kickbase request automatically. A renewed token may be obtained before a write, but the write itself must execute at most once.
- Use bounded concurrency and batch commands for per-player network data; avoid request-per-table-row behavior.
- Keep all local calendar-day calculations explicit. KickTrack's product timezone is `Europe/Berlin`; SQLite timestamps and date-only values must not be compared through implicit browser timezone parsing.
- SQLite migrations are append-only and idempotent. Every table required by a fresh install must be created by migrations. Never delete or rewrite a user's AppData database during development or tests.
- For one value per player/day, update the authoritative daily row instead of deleting history. Kickbase history wins over local snapshots for the same day.
- Do not hold a `rusqlite` connection across an `.await`.
- Preserve the 18-player squad and 33% credit rules as named fallbacks; live Kickbase values take precedence when available.

## Change discipline

The working tree may contain user changes. Inspect the diff before editing and do not revert unrelated work. Keep generated output (`dist/`, `target/`, release archives, local databases, logs, and secrets) out of version control. Update this guide and the README when commands, architecture, persistence, or authentication behavior changes.
