---
name: atom-queue-to-solace
description: >
  Migrate Boomi Atom Queue processes to Solace. Single command does everything:
  provision queues, create Solace components, transform processes. Agent just
  needs to build the config and run it.
---

# Atom Queue → Solace Migration

**One command does everything.** The agent's job is to collect info, write config, run, verify.

## Quick Start (the whole workflow)

```bash
# 1. Export process XMLs from Boomi
python -c "
import sys; sys.path.insert(0, 'src')
from boomi_solace_migration.boomi_client import BoomiClient
from pathlib import Path
client = BoomiClient.from_env()
for pid, name in [('PROCESS_ID', 'filename.xml')]:  # repeat per process
    Path(f'out/processes/{name}').parent.mkdir(parents=True, exist_ok=True)
    Path(f'out/processes/{name}').write_text(client.get_component_xml(pid))
"

# 2. Write migration.yaml (template below)

# 3. Run the migration
PYTHONPATH=src .venv/bin/python -c "from boomi_solace_migration.cli import main; main(['run', '--config', 'migration.yaml'])"

# 4. Check exit code 0 + read migration-report.md
```

## What to Collect from the User

| Required | Source |
|----------|--------|
| Boomi account_id, username, api_token | User provides or already in `.env` |
| Solace SEMP URL, VPN, admin creds | User provides or already in `.env` |
| Solace client host, username, password | User provides or already in `.env` |
| Target folder ID in Boomi | User specifies or create one via API |
| Process IDs + names | User provides the list |
| Destinations (queue/topic names) | User specifies per process |
| Source connector type | Usually `jms` or `atomqueue` |

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
  sub_type: officialboomi-solace-pubsubplus
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
    send_destination: "{queue_or_topic_name}"  # for producers
    receive_destination: ""
  # For consumers, flip: send_destination: "", receive_destination: "{queue_name}"
  # Add topic_subscriptions: ["topic/pattern"] if needed
```

## Naming Rules (enforced by the tool)

- **Process name**: NEVER changes
- **Connection**: `{Process Name} - Solace Connection [{hash}]`
- **Operation**: `{Process Name} - Solace {Action} {destination} [{hash}]`
- **Shape labels**: "Listen on Solace Queue" / "Send Message" / "Receive from Solace Queue"
- **No "PubSub+"** anywhere in names or labels
- **Queue names**: exactly as specified in config (no prefixes added by tool)

## If It Fails

| Error | Fix |
|-------|-----|
| "Connector does not exist" | Solace PubSub+ connector not installed in Boomi account — tell user |
| "cannot read properties of undefined" | Bug in componentId handling — tool already fixes this |
| SEMP 400 / timeout | Increase `SOLACE_SEMP_MIN_INTERVAL_SECONDS` or check SEMP URL |
| "migration_version is required" | Add `migration_version: "2026.07"` to yaml |
| Anything else | Read `references/troubleshooting.md` |

## Do NOT

- Call `discover`, `plan`, `provision`, `apply` separately — use `run`
- Customize naming policy — defaults are correct
- Rename processes or add "Migrated" suffix
- Set `componentId` to empty string (remove it entirely)
- Explain SEMP/Solace internals to the user unless asked
- Manually build XML — the tool handles transformation

## Performance (already configured)

- `SOLACE_SEMP_MIN_INTERVAL_SECONDS=0.05` — 50ms between SEMP calls
- `SOLACE_PROVISION_WORKERS=5` — parallel queue provisioning
- `BOOMI_APPLY_WORKERS=3` — parallel Boomi API calls
- No `--monitor-queues` unless explicitly asked

## References (only load on failure)

- `references/troubleshooting.md` — production failures and fixes
- `references/xml-templates.md` — corrected XML if debugging transform issues
- `references/api-reference.md` — Boomi/SEMP endpoints and auth
- `references/solace-reference.md` — queue/topic/ACL details
