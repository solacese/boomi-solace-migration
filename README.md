# Solace Migration Pipeline for Boomi Atom Queues

This repository provides an open source Solace pipeline for migrating Boomi Atom Queue integrations to Solace PubSub+. It is designed for large migration programs where each change must be repeatable, auditable, validated, and rollback safe.

The pipeline is intentionally conservative:

- The original Boomi process is never modified.
- The plan phase is offline and deterministic.
- Every Boomi write is recorded in a run manifest.
- Rollback deletes only components recorded in the manifest.
- Secrets are read from environment variables and are redacted in output.
- Unknown queue-like connectors and unsupported actions fail closed.
- Solace queues are the default target for Atom Queue parity.

## Repository Contents

| Path | Purpose |
|---|---|
| `src/boomi_solace_migration/` | Python package and CLI implementation. |
| `examples/` | Starter migration, connector profile, and naming policy files. |
| `schemas/` | JSON schemas for pipeline inputs and outputs. |
| `tests/fixtures/` | Anonymized Boomi XML fixtures used by regression tests. |
| `reference/` | Background Boomi and Solace migration references. |
| `skills/atom-queue-to-solace/` | Agent skill wrapper that calls the CLI. |
| `.devcontainer/` | Python 3.12 and Java 21 development container. |
| `.github/workflows/ci.yml` | Open source CI workflow. |

## Runtime Requirements

- Python 3.12
- Java 21 for a stable migration workstation and optional JVM-based validation tasks
- Boomi AtomSphere API token for online discovery and apply
- Solace PubSub+ broker or Solace Cloud service
- Optional SEMP access for queue validation and provisioning

The local machine may have another Python or Java version installed. The repository pins the supported versions through `.python-version`, `.java-version`, the devcontainer, and CI.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]" -c requirements-dev.lock
```

The same setup is available through the devcontainer:

```bash
code .
```

Open the folder in the container when prompted. The container installs Python 3.12, OpenJDK 21, and the development dependencies.

## Pipeline Inputs

Create working copies from the examples:

```bash
cp .env.example .env
cp examples/migration.example.yaml migration.yaml
cp examples/connector-profile.example.yaml connector-profile.yaml
cp examples/naming-policy.example.yaml naming-policy.yaml
```

### `.env`

`.env` is not committed. Use it to provide runtime credentials:

```bash
BOOMI_ACCOUNT_ID=account-placeholder
BOOMI_USERNAME=account-user@placeholder.invalid
BOOMI_API_TOKEN=replace-me

SOLACE_SEMP_BASE_URL=https://broker.placeholder.invalid:943
SOLACE_SEMP_USERNAME=semp-user
SOLACE_SEMP_PASSWORD=replace-me
SOLACE_MESSAGE_VPN=default

SOLACE_HOST=smfs://broker.placeholder.invalid:55443
SOLACE_CLIENT_USERNAME=boomi-client
SOLACE_CLIENT_PASSWORD=replace-me
```

Load it before online operations:

```bash
set -a
source .env
set +a
```

### `connector-profile.yaml`

The connector profile captures the Boomi Solace connector subtype and field IDs. Keep it account-specific and review it before any write:

```yaml
sub_type: officialboomi-solace-pubsubplus
connection_fields:
  host: host
  vpn: vpn
  username: clientUsername
  password: clientPassword
operation_fields:
  destination: destination
  destination_type: destinationType
  delivery_mode: deliveryMode
```

### `naming-policy.yaml`

The naming policy makes generated queue and topic names deterministic. Queue names default to lowercase, bounded length, and a stable hash suffix from the source process ID:

```yaml
queue:
  prefix: boomi
  separator: _
  max_length: 80
  case: lower
  collision_hash_length: 8
topic:
  separator: /
  max_length: 250
  taxonomy: "Domain/Noun/Verb/Version/Properties"
```

### `migration.yaml`

The migration file selects source processes and target settings:

```yaml
migration_version: "2026.05"
output_dir: out/pipeline-plan
target_folder_id: target-folder-guid
source_connector_types:
  - atomqueue
  - queue
connection:
  name: shared-solace-connection
  host_env: SOLACE_HOST
  vpn_env: SOLACE_MESSAGE_VPN
  username_env: SOLACE_CLIENT_USERNAME
  password_env: SOLACE_CLIENT_PASSWORD
defaults:
  destination_type: QUEUE
  delivery_mode: PERSISTENT
  queue_access_type: exclusive
  provision_dmq: true
processes:
  - id: source-process-guid
    name: Sample Producer Process
    folder_id: source-folder-guid
    target_folder_id: target-folder-guid
    xml_path: tests/fixtures/producer.xml
```

For online account inventory, `xml_path` can be omitted after discovery identifies the target process IDs.

## Pipeline Steps

### Safe Pipeline Entry Point

For controlled execution, use the `pipeline` command. By default it validates inputs, generates the deterministic plan, and stops before any Boomi write:

```bash
boomi-solace pipeline \
  --config migration.yaml \
  --connector-profile connector-profile.yaml \
  --naming-policy naming-policy.yaml
```

Run the same pipeline with Solace preflight in dry-run mode:

```bash
boomi-solace pipeline \
  --config migration.yaml \
  --connector-profile connector-profile.yaml \
  --naming-policy naming-policy.yaml \
  --provision-solace \
  --dry-run
```

Apply through the pipeline only after reviewing generated XML and the plan:

```bash
boomi-solace pipeline \
  --config migration.yaml \
  --connector-profile connector-profile.yaml \
  --naming-policy naming-policy.yaml \
  --provision-solace \
  --apply \
  --manifest run-manifest.json
```

### 1. Discover

Run discovery against local XML fixtures:

```bash
boomi-solace discover \
  --config migration.yaml \
  --connector-profile connector-profile.yaml \
  --naming-policy naming-policy.yaml \
  --output inventory.json
```

Run discovery against Boomi:

```bash
boomi-solace discover \
  --config migration.yaml \
  --connector-profile connector-profile.yaml \
  --naming-policy naming-policy.yaml \
  --output inventory.json \
  --online
```

Discovery reports:

- source process ID
- process folder
- Atom Queue connector actions
- migration type: producer, consumer, or mixed
- Dynamic Document Properties found in process XML
- unknown queue-like connector variants
- unsupported actions

Review `inventory.json` before planning.

### 2. Plan

Generate a deterministic offline plan:

```bash
boomi-solace plan \
  --config migration.yaml \
  --connector-profile connector-profile.yaml \
  --naming-policy naming-policy.yaml
```

The command writes:

- `migration-plan.json`
- canonical Solace connection XML
- canonical Solace operation XML
- canonical migrated process XML
- optional consumer Set Properties snippets

The plan ID is derived from migration version, source XML hashes, connector subtype, source connector types, destinations, and operations. Running the same inputs twice produces the same plan ID and canonical XML.

### 3. Validate

Validate schemas and plan structure:

```bash
boomi-solace validate \
  --config migration.yaml \
  --connector-profile connector-profile.yaml \
  --naming-policy naming-policy.yaml \
  --plan out/pipeline-plan/migration-plan.json \
  --offline-only
```

Validation checks include:

- required config fields
- connector field mappings
- no Atom Queue connector remains after transform
- every Solace connector action has connection and operation IDs
- Listen operations use `operationType="Listen"`
- connection XML includes the encrypted password field path
- unsupported connector variants fail closed

### 4. Preflight Solace

Run a dry-run SEMP preflight:

```bash
boomi-solace provision-solace \
  --plan out/pipeline-plan/migration-plan.json \
  --dry-run
```

Apply Solace queue provisioning and validation:

```bash
boomi-solace provision-solace \
  --plan out/pipeline-plan/migration-plan.json
```

The Solace step validates or creates queue resources for planned queue destinations. When `provision_dmq` is enabled, the pipeline uses `{queue}_dmq` as the default per-queue DMQ.

Recommended Solace defaults:

- Use durable queues for Atom Queue parity.
- Use `PERSISTENT` delivery mode for queue sends.
- Use exclusive queues for single-consumer point-to-point flows.
- Use non-exclusive queues for competing consumers.
- Use topics only when the migration explicitly requires topic fan-out.
- Prefer topic hierarchy and queue subscriptions over selectors.

### 5. Apply to Boomi

Run a Boomi apply dry run:

```bash
boomi-solace apply \
  --plan out/pipeline-plan/migration-plan.json \
  --manifest run-manifest.json \
  --dry-run
```

Apply the plan:

```bash
boomi-solace apply \
  --plan out/pipeline-plan/migration-plan.json \
  --manifest run-manifest.json
```

The apply phase creates:

1. Solace connection component
2. Solace operation components
3. migrated Boomi process copy

The run manifest records:

- plan ID
- process ID
- source XML hash
- destination queue or topic
- created component IDs
- migrated process ID
- status and error details
- timestamps

If a run fails, keep the manifest. Fix the cause and rerun `apply`; successful entries are skipped.

### 6. Cut Over

Use this deployment order:

1. Provision and validate Solace queues, DMQs, and permissions.
2. Deploy migrated consumer processes.
3. Confirm consumer bindings in Solace.
4. Deploy migrated producer processes.
5. Pause original producers.
6. Drain source queues.
7. Deactivate original consumers.
8. Run end-to-end validation.
9. Monitor queue depth, redelivery, DMQ depth, and process errors.
10. Retire original Atom Queue components only after operational approval.

### 7. Roll Back

Preview rollback:

```bash
boomi-solace rollback \
  --manifest run-manifest.json \
  --dry-run
```

Execute rollback:

```bash
boomi-solace rollback \
  --manifest run-manifest.json
```

Rollback deletes only component IDs recorded in the manifest. It does not touch original Boomi processes or manually created Solace resources.

### 8. Report

Generate a markdown report:

```bash
boomi-solace report \
  --manifest run-manifest.json \
  --output migration-report.md
```

Generate a JSON report:

```bash
boomi-solace report \
  --manifest run-manifest.json \
  --output migration-report.json
```

## Quality Gates

Run all local checks before opening a pull request or pushing a release branch:

```bash
make check
```

The check target runs:

- `ruff`
- `mypy`
- `pytest`
- example schema validation

CI runs the same check target on Python 3.12 and Java 21.

## Open Source Hygiene

Before publishing:

```bash
git status --short
rg -n "local-home-placeholder|real-token-placeholder|real-password-placeholder" .
make check
```

Only placeholders should appear in examples. Do not commit `.env`, manifests, generated plans, reports, cache directories, or local editor files.
