---
name: atom-queue-to-solace
description: >
  Use this skill to migrate Boomi Atom Queue integrations to Solace PubSub+
  with the boomi-solace CLI in this repo. Trigger for requests to discover,
  plan, validate, apply, roll back, or report on Boomi Atom Queue to Solace
  migrations at scale. The skill emphasizes deterministic plans, manifests,
  offline XML validation, Solace queue best practices, and safe Boomi API usage.
---

# Atom Queue to Solace PubSub+ Migration

Use the committed `boomi-solace` CLI. Do not write one-off migration scripts to
`/tmp`, and do not mutate original Boomi processes. The original process is a
source artifact only; migrated components are created as new Boomi components and
tracked in a run manifest.

## Primary Workflow

1. Inspect or create:
   - `migration.yaml`
   - `connector-profile.yaml`
   - `naming-policy.yaml`
   - `.env`
2. Run discovery:
   ```bash
   boomi-solace discover --config migration.yaml --connector-profile connector-profile.yaml --naming-policy naming-policy.yaml --output inventory.json
   ```
3. Generate the deterministic plan:
   ```bash
   boomi-solace plan --config migration.yaml --connector-profile connector-profile.yaml --naming-policy naming-policy.yaml
   ```
4. Validate before any Boomi writes:
   ```bash
   boomi-solace validate --config migration.yaml --connector-profile connector-profile.yaml --naming-policy naming-policy.yaml --plan out/example-plan/migration-plan.json --offline-only
   ```
5. Optionally preflight or provision Solace queues:
   ```bash
   boomi-solace provision-solace --plan out/example-plan/migration-plan.json --dry-run
   ```
6. Apply only after plan review:
   ```bash
   boomi-solace apply --plan out/example-plan/migration-plan.json --manifest run-manifest.json
   ```
7. Report:
   ```bash
   boomi-solace report --manifest run-manifest.json --output migration-report.md
   ```

## Safety Rules

- Run `plan` and `validate` before `apply`.
- Keep Boomi credentials and Solace passwords in environment variables or `.env`
  files excluded from git.
- Treat `run-manifest.json` as the rollback source of truth.
- If a run fails, inspect the manifest and rerun `apply`; do not manually delete
  partial components unless the manifest is also reconciled.
- Use `rollback --dry-run` before rollback without `--dry-run`.
- Fail closed on unknown queue-like connectors, unsupported actions, missing
  connector field IDs, or ambiguous DDP mappings.

## Solace Defaults

- Default migrated producers to Solace topics with persistent sends.
- Default migrated consumers to durable Solace queues.
- Use direct queue publishing only when the migration explicitly requires strict
  Atom Queue parity.
- Use `Domain/Noun/Verb/Version` topics, with the noun as one camelCase topic
  level and no deployment environment or trace IDs in topic levels.
- Prefer topic hierarchy and queue subscriptions over selectors for routing.
- Provision or validate a DMQ for queues; the default generated DMQ is
  `{queue}_dmq`.
- Set finite max redelivery when a DMQ is configured.
- Keep SEMP calls throttled through `SOLACE_SEMP_MIN_INTERVAL_SECONDS`.
- Deploy consumers before producers during cutover.

## References

Load only what is needed:

- `references/migration-overview.md`: migration semantics, deployment order, DDP handling.
- `references/api-reference.md`: Boomi REST endpoints and auth details.
- `references/xml-templates.md`: component XML examples and field conventions.
- `references/solace-reference.md`: Solace queue/topic/SEMP guidance.
- `references/troubleshooting.md`: known failures and fixes.

## Validation Expectations

Before presenting a migration as ready, run:

```bash
make check
```

For a specific plan, also run:

```bash
boomi-solace validate --config migration.yaml --connector-profile connector-profile.yaml --naming-policy naming-policy.yaml --plan <plan-path> --offline-only
```
