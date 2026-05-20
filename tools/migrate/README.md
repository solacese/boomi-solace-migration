# boomi-solace-migrate

Lean, single-command tool to migrate Boomi Atom Queue processes to Solace PubSub+. Creates new Solace connection, operation, and process components in Boomi with strict post-creation verification.

## Quick Start

```bash
cd tools/migrate
pip install -e .
cp .env.example .env   # fill in real values
cp migration.example.yaml migration.yaml   # configure your processes

python -m migrate --config migration.yaml
```

## What It Does

For each process in `migration.yaml`:

1. Fetches original process XML from Boomi
2. Detects Atom Queue operations (Send/Listen/Get)
3. Provisions Solace queues via SEMP v2 (idempotent)
4. Creates Solace connection component → verifies all fields populated
5. Creates Solace operation component(s) → verifies destination/type correct
6. Transforms process XML (swaps connectors) → verifies no source connectors remain
7. Creates migrated process → verifies type=process, all IDs populated

## Configuration

### `migration.yaml`

See `migration.example.yaml` for the full schema. Key sections:

- `boomi`: API credentials (env var references)
- `solace_semp`: SEMP v2 credentials for queue provisioning
- `connector_profile`: subType and field IDs (account-specific — discover from existing component)
- `connection`: Solace client connection values
- `processes`: list of processes to migrate with destinations

### Multi-Destination Processes

For processes that route to multiple queues via different connections, use `operation_mappings`:

```yaml
processes:
  - id: "process-guid"
    name: "My Router Process"
    provision_queue: true
    operation_mappings:
      - original_connection_id: "old-conn-1"
        destination: "Queue_A"
        destination_type: QUEUE
        delivery_mode: PERSISTENT
      - original_connection_id: "old-conn-2"
        destination: "Queue_B"
        destination_type: QUEUE
        delivery_mode: PERSISTENT
```

## Dry Run

```bash
python -m migrate --config migration.yaml --dry-run
```

Validates configuration, authenticates to both APIs, detects operations, but does not create any components.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

## Key Technical Details

- Send operations use `operationType="CREATE"` (not EXECUTE)
- Listen operations use `operationType="Listen"` (mixed case)
- Connection field IDs vary per account — always discover from existing component
- Solace Cloud SEMP returns 400 with NOT_FOUND instead of 404
- SharedCommOverrides/PartnerOverrides are stripped from process XML
- WSS/HTTP connectors with empty connectionId are skipped during verification
- Boomi API cannot delete components — orphans must be cleaned up manually
