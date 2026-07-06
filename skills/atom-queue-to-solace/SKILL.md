---
name: atom-queue-to-solace
description: >
  Migrate Boomi Atom Queue integrations to Solace. The agent reviews each
  process flow, validates inputs/outputs, proposes Solace destinations, confirms
  the migration plan with the user, then executes and verifies.
---

# Atom Queue → Solace Migration

## For Colleagues: How to Run This

Use **Claude Code** (CLI) with:
- Model: **Claude Sonnet 4**
- Effort: **medium**
- Skill loaded automatically when working from this repo

Prompt example:
```
Migrate processes [list IDs or names] from Atom Queues to Solace.
Target folder: [folder ID or name].
Connector subType: [from an existing Solace component in the account].
```

The agent will analyze each flow, propose destinations, confirm with you,
then execute. **Expect 15–20 minutes** for a thorough session.

---

## Agent Workflow

### Phase 1: Understand (per process)

For EACH process, the agent must:

1. **Export the process XML** from Boomi API
2. **Read and understand the flow** — what does this process do? What data does
   it move? What are the steps between start and end?
3. **Identify queue operations** — which shapes use Atom Queue / JMS connectors?
   What action (send, listen, get)? What's the current destination?
4. **Check for complexity** — multi-destination routing? DDPs (dynamic document
   properties) setting queue names? Request/reply patterns? Error handling paths?
5. **Summarize findings to the user** — "This process listens on queue X,
   transforms the payload, then sends to queue Y. I propose migrating to
   Solace queues with the same names."

### Phase 2: Design (propose the migration plan)

Based on the analysis, propose:

- **Solace destination names** for each operation (queue or topic)
- **Destination type** — QUEUE for point-to-point (Atom Queue parity), TOPIC if
  the user wants pub/sub fan-out
- **Topic subscriptions** — if using topics, which queue subscribes to what
- **Queue ownership** — typically `boomi_user` for all migrated queues
- **Any concerns** — "This process uses DDPs to dynamically set the queue name
  at runtime — the migration will set a static destination. Is that acceptable?"

**Wait for user confirmation before executing.**

### Phase 3: Execute

Once confirmed:

1. Write `migration.yaml` from the template below
2. Run the migration:
   ```bash
   PYTHONPATH=src .venv/bin/python -c "from boomi_solace_migration.cli import main; main(['run', '--config', 'migration.yaml'])"
   ```
3. This single command does everything: plan, provision Solace queues/ACLs,
   create Solace connection + operations in Boomi, transform process XML,
   create migrated process.

### Phase 4: Verify

1. Check exit code 0
2. Read the generated `migration-report.md`
3. For each migrated process, fetch it back from Boomi and confirm:
   - Process name is unchanged
   - Solace connector shapes point to valid connection/operation IDs
   - No leftover JMS/Atom Queue connector references
4. Report results to user with a per-process summary

---

## Export Process XML

```python
import sys; sys.path.insert(0, 'src')
from boomi_solace_migration.boomi_client import BoomiClient
from pathlib import Path
client = BoomiClient.from_env()
for pid, filename in [('PROCESS_ID', 'name.xml')]:
    Path(f'out/processes/{filename}').parent.mkdir(parents=True, exist_ok=True)
    Path(f'out/processes/{filename}').write_text(client.get_component_xml(pid))
```

---

## Config Template (migration.yaml)

```yaml
migration_version: "2026.07"
output_dir: out/migration
target_folder_id: "{TARGET_FOLDER_ID}"
source_connector_types:
  - {jms_or_atomqueue}

connection:
  host_env: SOLACE_HOST
  vpn_env: SOLACE_MESSAGE_VPN
  username_env: SOLACE_CLIENT_USERNAME
  password_env: SOLACE_CLIENT_PASSWORD

connector_profile:
  sub_type: {CONNECTOR_SUBTYPE}
  display_name: Solace
  connection_fields:
    host: host
    vpn: vpn_name
    username: username
    password: password
  operation_fields:
    destination: destination
    destination_type: endpointType
    delivery_mode: mode

defaults:
  send_destination_type: QUEUE
  receive_destination_type: QUEUE
  delivery_mode: PERSISTENT
  queue_access_type: exclusive
  queue_owner: boomi_user
  queue_permission: no-access
  provision_dmq: true
  max_redelivery_count: 5
  max_spool_usage_mb: 5000

processes:
  - id: "{PROCESS_ID}"
    name: "{Process Name}"
    folder_id: "{SOURCE_FOLDER_ID}"
    xml_path: out/processes/{filename}.xml
    send_destination: "{queue_or_topic_name}"      # for producers
    receive_destination: ""                         # blank for producers
  # For consumers: send_destination: "", receive_destination: "{queue_name}"
  # Add topic_subscriptions: ["topic/pattern"] if needed
```

---

## Naming Rules (enforced by the tool, non-negotiable)

- **Process name**: NEVER changes
- **Connection**: `{Process Name} - Solace Connection [{hash}]`
- **Operation**: `{Process Name} - Solace {Action} {destination} [{hash}]`
- **Shape labels**: "Listen on Solace Queue" / "Send Message" / "Receive from Solace Queue"
- **No "PubSub+"** anywhere
- **Queue names**: exactly as specified in config

---

## What to Look For During Analysis

| Pattern | How to Handle |
|---------|--------------|
| Simple send (producer) | Map to `send_destination` — propose a queue name |
| Simple listen (consumer) | Map to `receive_destination` — propose a queue name |
| Request/reply (send + get) | Both `send_destination` and `receive_destination` needed |
| Multi-destination (multiple send shapes) | Use `operation_mappings` with `original_connection_id` per shape |
| DDP-based routing | Flag to user — migration uses static destinations |
| Error handling sub-process | Usually no queue ops — skip unless it has its own connectors |
| Shared connection across processes | Each migrated process gets its own connection (by design) |

---

## If It Fails

| Error | Fix |
|-------|-----|
| "Connector does not exist" | Solace connector not installed in Boomi — tell user to install it |
| "cannot read properties of undefined" | componentId bug — tool handles this (removes attribute) |
| SEMP 400 / timeout | Check SEMP URL, increase `SOLACE_SEMP_MIN_INTERVAL_SECONDS` |
| "migration_version is required" | Add `migration_version: "2026.07"` to yaml |
| Anything else | Read `references/troubleshooting.md` |

---

## Do NOT

- Skip the analysis phase — understanding the flow IS the value
- Run the migration without user confirmation on destinations
- Call `discover`, `plan`, `provision`, `apply` separately — always use `run`
- Rename processes or add suffixes
- Set `componentId` to empty string
- Customize naming policy (defaults are correct)
- Explain SEMP internals unless asked

---

## References (load only when troubleshooting)

- `references/troubleshooting.md` — production failures and fixes
- `references/xml-templates.md` — corrected XML for debugging transform issues
- `references/api-reference.md` — Boomi/SEMP endpoint details
- `references/solace-reference.md` — queue/topic/ACL configuration details
