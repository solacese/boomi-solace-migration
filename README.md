# Solace Migration Pipeline for Boomi Atom Queues

This repository provides an open source Solace pipeline for migrating Boomi Atom Queue integrations to Solace PubSub+. It is designed for large migration programs where each change must be repeatable, auditable, validated, and rollback safe.

The pipeline is intentionally conservative:

- The original Boomi process is never modified.
- The plan phase is offline and deterministic.
- Every Boomi write is recorded in a run manifest.
- Rollback deletes only components recorded in the manifest.
- Secrets are read from environment variables and are redacted in output.
- Unknown queue-like connectors and unsupported actions fail closed.
- The recommended target is topic publish with durable queue consumption.
- Direct queue publish is still supported for strict compatibility migrations.

## Solace Best Practices Encoded

The pipeline follows the Solace guidance in the official best practices, topic architecture, guaranteed messaging, and SEMP documentation:

- Generated topics follow `Domain/Noun/Verb/Version` and keep the noun as one camelCase level.
- Published topics are validated against Solace topic limits: 250 characters, 128 levels, no spaces, and no publisher wildcards.
- Application topics are rejected when they start with reserved `#` or `_` prefixes.
- Topic levels reject deployment environments such as `dev`, `qa`, and `prod`, and tracing identifiers such as `traceId` and `spanId`.
- Custom topic destinations must start with the configured domain prefix by default.
- Queue names are bounded, deterministic, hash-suffixed, and checked for invalid Solace characters.
- Producers publish to topics by default; consumers bind to durable queues by default.
- DMQs are provisioned per queue by default with `{queue}_dmq`.
- Queue provisioning supports explicit access type, permission, owner, max redelivery count, TTL, and message spool limits.
- Optional queue topic subscriptions are provisioned through SEMP so routing can use topic hierarchy instead of selectors.
- SEMP calls use retries, request timeouts, and a default interval of 0.11 seconds between calls.
- Cutover deploys consumers before producers and monitors queue depth, redelivery, DMQ depth, and bound consumers.

Primary references:

- [Solace best practices](https://docs.solace.com/Get-Started/best-practices.htm)
- [Topic architecture best practices](https://docs.solace.com/Messaging/Topic-Architecture-Best-Practices.htm)
- [Guaranteed messaging endpoints](https://docs.solace.com/Messaging/Guaranteed-Msg/Endpoints.htm)
- [Using SEMP](https://docs.solace.com/Admin/SEMP/Using-SEMP.htm)
- [SEMP features and request frequency](https://docs.solace.com/Admin/SEMP/SEMP-Features.htm)
- [Configuring queues](https://docs.solace.com/Messaging/Guaranteed-Msg/Configuring-Queues.htm)

### Best Practice Implementation Map

| Solace practice | Pipeline contract | Enforced by |
|---|---|---|
| Design event topics with a clear domain, noun, verb, and version. | Topic destinations use `domain/noun/verb/version`; the generated noun is a single camelCase level and long nouns are bounded with a stable hash. | `naming.py`, `planning.py`, `tests/test_naming_redaction_retry.py` |
| Keep topic hierarchies concise and within broker limits. | Published topics fail validation above 250 characters, above 128 levels, with spaces, empty levels, publisher wildcards, or invalid level characters. | `naming-policy.schema.json`, `naming.py`, `planning.py` |
| Keep deployment topology and tracing metadata out of topic levels. | Environment levels and tracing terms are configured as forbidden values in `naming-policy.yaml`. | `examples/naming-policy.example.yaml`, `naming.py` |
| Publish events to topics, then attract them to queues with subscriptions. | `send_destination_type` defaults to `TOPIC`; `receive_destination_type` defaults to `QUEUE`; consumer queues can list `topic_subscriptions`. | `models.py`, `planning.py`, `solace_semp.py`, `tests/test_planning_execution.py` |
| Use topic hierarchy and subscriptions for routing instead of selectors. | Queue topic subscriptions can be listed in `topic_subscriptions` and are provisioned through SEMP. Subscription wildcards are validated before provisioning. | `models.py`, `planning.py`, `solace_semp.py`, `tests/test_solace_semp.py` |
| Use durable queues for guaranteed consumer state. | Consumer operations default to `QUEUE`, persistent sends are the default delivery mode, and generated queues are deterministic. | `examples/migration.example.yaml`, `component_builder.py`, `naming.py` |
| Configure poison-message handling. | `provision_dmq` defaults to true and creates a per-queue `{queue}_dmq`; finite `max_redelivery_count` is supported and validated. | `execution.py`, `solace_semp.py`, `tests/test_solace_semp.py` |
| Bound queue resource usage. | `max_spool_usage_mb` and `max_ttl_seconds` are plan fields and SEMP queue settings. | `models.py`, `schemas/migration.schema.json`, `solace_semp.py` |
| Use SEMP v2 config for provisioning and monitor endpoints for runtime checks. | Provisioning writes to `/SEMP/v2/config`; post-provision checks read `/SEMP/v2/monitor` for queue stats and bind visibility. | `solace_semp.py`, `execution.py` |
| Avoid aggressive SEMP polling. | SEMP calls use retries, request timeouts, and a default minimum interval of `0.11` seconds, which keeps average request rate below 10 requests per second. | `.env.example`, `solace_semp.py`, `http_retry.py` |

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
```

The migration config now supports **inline** `connector_profile` and `naming_policy` sections, eliminating the need for separate files. If you prefer separate files, they still work via `--connector-profile` and `--naming-policy` flags. When omitting `--naming-policy`, built-in defaults are used automatically.

```bash
# Legacy 3-file mode (still supported):
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

SOLACE_SEMP_MIN_INTERVAL_SECONDS=0.11
SOLACE_SEMP_TIMEOUT_SECONDS=30
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
  solace_max_length: 200
  case: lower
  collision_hash_length: 8
  allowed_pattern: "^[a-z0-9_.-]+$"
topic:
  separator: /
  max_length: 250
  max_levels: 128
  case: camel
  collision_hash_length: 8
  domain: boomi/migration
  verb: published
  version: v1
  taxonomy: "Domain/Noun/Verb/Version/Properties"
  allowed_level_pattern: "^[A-Za-z0-9]+$"
  require_domain_prefix: true
  allow_subscription_exceptions: false
  forbidden_levels:
    - dev
    - qa
    - prod
    - production
    - staging
  forbidden_terms:
    - traceid
    - spanid
    - trace
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
  send_destination_type: TOPIC
  receive_destination_type: QUEUE
  delivery_mode: PERSISTENT
  queue_access_type: exclusive
  queue_permission: consume
  provision_dmq: true
  max_redelivery_count: 5
  max_ttl_seconds: 0
  max_spool_usage_mb: 5000
  topic_subscriptions: []
processes:
  - id: source-process-guid
    name: Sample Producer Process
    folder_id: source-folder-guid
    target_folder_id: target-folder-guid
    xml_path: tests/fixtures/producer.xml
  - id: consumer-process-guid
    name: Sample Consumer Process
    folder_id: source-folder-guid
    target_folder_id: target-folder-guid
    xml_path: tests/fixtures/listen_consumer.xml
    topic_subscriptions:
      - boomi/migration/sampleProducerProcess/published/v1
```

For online account inventory, `xml_path` can be omitted after discovery identifies the target process IDs.

### Runtime Field Reference

The same runtime fields can be set under `defaults` or overridden per process:

| Field | Default | Purpose |
|---|---|---|
| `send_destination_type` | `TOPIC` | Destination type for migrated producer actions. This is the recommended publish path. |
| `receive_destination_type` | `QUEUE` | Destination type for migrated consumer actions. This gives consumers durable state. |
| `destination_type` | unset | Legacy shortcut that sets both send and receive types when the specific fields are omitted. Use only for direct queue or direct topic compatibility modes. |
| `delivery_mode` | `PERSISTENT` | Uses Solace guaranteed delivery for migrated sends. |
| `queue_access_type` | `exclusive` | Uses one active consumer by default. Use `non-exclusive` for competing consumers. |
| `queue_permission` | `consume` | Permission assigned to non-owner clients when the queue is provisioned. |
| `queue_owner` | empty | Optional Solace client username to own the provisioned queue. Empty leaves ownership with management. |
| `provision_dmq` | `true` | Creates or validates a per-queue DMQ named `{queue}_dmq`. |
| `max_redelivery_count` | `0` | Maximum redelivery attempts. Use a finite value with a DMQ for poison-message handling. |
| `max_ttl_seconds` | `0` | Queue maximum TTL in seconds. `0` leaves maximum TTL disabled. |
| `max_spool_usage_mb` | unset | Optional queue spool quota in MB. The example sets `5000`. |
| `topic_subscriptions` | `[]` | Topic subscriptions added to queues through SEMP. Use these for routing instead of selectors. |

Recommended mode:

- producers: `send_destination_type: TOPIC`
- consumers: `receive_destination_type: QUEUE`
- consumer queue subscriptions: `topic_subscriptions` matching producer topics

In this mode, a producer operation publishes to a Solace topic. A consumer
operation listens on a durable Solace queue. SEMP then adds the configured
topic subscriptions to that queue so messages published to matching topics are
attracted to the queue.

Strict Atom Queue parity mode:

- producers: `send_destination_type: QUEUE`
- consumers: `receive_destination_type: QUEUE`
- no queue topic subscriptions required

The naming policy is also part of the runtime contract:

| Field | Purpose |
|---|---|
| `queue.max_length` | Internal generated queue length. The example uses 80 for readable names. |
| `queue.solace_max_length` | Solace durable queue name limit. The example uses 200. |
| `queue.allowed_pattern` | Organization policy for queue characters. The Solace invalid characters are rejected regardless. |
| `topic.domain` | Required prefix for generated and custom topic destinations. |
| `topic.verb` | Static event action level used for generated topics. |
| `topic.version` | Static event version level. Must match `vN`. |
| `topic.forbidden_levels` | Levels that cannot appear in topics or subscriptions, for example deployment environments. |
| `topic.forbidden_terms` | Terms that cannot appear anywhere in topics or subscriptions, for example tracing identifiers. |

## Pipeline Steps

### Quick Start: Single Command

The `run` command chains all steps: plan → provision access control → provision queues → apply → report:

```bash
boomi-solace run --config migration.yaml --dry-run
```

When satisfied with the dry-run output:

```bash
boomi-solace run --config migration.yaml
```

### Safe Pipeline Entry Point

For controlled execution, use the `pipeline` command. By default it validates inputs, generates the deterministic plan, and stops before any Boomi write:

```bash
boomi-solace pipeline --config migration.yaml
```

Run the same pipeline with Solace preflight in dry-run mode:

```bash
boomi-solace pipeline --config migration.yaml --provision-solace --dry-run
```

Apply through the pipeline only after reviewing generated XML and the plan:

```bash
boomi-solace pipeline --config migration.yaml --provision-solace --apply --manifest run-manifest.json
```

Note: `--connector-profile` and `--naming-policy` flags are optional when using inline config sections.

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

The plan also carries the Solace runtime contract for each process:

- destination queue or topic
- producer destination type
- consumer destination type
- queue access type and permission
- optional queue owner
- DMQ provisioning flag
- max redelivery count
- max TTL
- max spool usage
- queue topic subscriptions

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

The Solace step validates or creates queue resources for planned queue destinations, applies optional queue topic subscriptions, and reads SEMP monitor data for queue depth and bind checks. When `provision_dmq` is enabled, the pipeline uses `{queue}_dmq` as the default per-queue DMQ.

When `queue_owner` is configured (e.g. `boomi_user`), provisioning also creates:

1. ACL profile (`boomi_user`) — mirrors default, controls pub/sub permissions
2. Client profile (`boomi_user`) — mirrors default, controls connection limits
3. Client username (`boomi_user`) — ties profile + ACL to a login identity
4. Queue ownership — sets `owner=boomi_user` and `permission=no-access`

This ensures only Boomi traffic can publish to and consume from migrated queues.

The SEMP preflight and provision command is idempotent:

- existing queues are reported as `exists`
- missing queues are created only when `--dry-run` is not set
- DMQs are created before the primary queue that references them
- topic subscriptions are checked before creation
- monitor results are summarized after provisioning
- 429 and 5xx responses are retried with backoff
- sensitive response text is redacted before errors are surfaced

Recommended Solace defaults:

- Publish to topics and consume from durable queues with matching queue subscriptions.
- Use `PERSISTENT` delivery mode for migrated sends.
- Use exclusive queues for single-consumer point-to-point flows.
- Use non-exclusive queues for competing consumers.
- Set a finite `max_redelivery_count` when a DMQ is configured so poison messages have a deterministic path.
- Set `max_spool_usage_mb` to an explicit capacity for each migrated queue.
- Use direct queue publishing only when strict point-to-point compatibility is required.
- Prefer topic hierarchy and queue subscriptions over selectors.
- Keep SEMP calls below the documented rate guidance through `SOLACE_SEMP_MIN_INTERVAL_SECONDS`.

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
rg -n --fixed-strings "$HOME" . --glob '!requirements-dev.lock' --glob '!examples/out/**'
rg -n --fixed-strings "$USER" . --glob '!requirements-dev.lock' --glob '!examples/out/**'
rg -n "\\x{2014}|\\x{2013}|\\x{2026}" . --pcre2 --glob '!requirements-dev.lock' --glob '!examples/out/**'
make check
```

Only placeholders should appear in examples. Do not commit `.env`, manifests, generated plans, reports, cache directories, or local editor files.
