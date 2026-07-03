---
name: atom-queue-to-solace
description: >
  Use this skill to migrate Boomi Atom Queue integrations to Solace.
  Covers the full lifecycle: discover queue operations in processes, provision
  Solace queues via SEMP, create Solace connection/operation components in Boomi,
  transform process XML to swap connectors, verify all components post-creation,
  and organize results into proper folders. Emphasizes strict post-creation
  verification, correct Solace connector XML structure (operationType=CREATE for
  Send, Listen for Listen), SEMP 400/NOT_FOUND handling, and safe Boomi API usage.
---

# Atom Queue to Solace Migration

Do not mutate original Boomi processes. The original process is a source artifact
only; migrated components are created as new Boomi components in a dedicated
folder (e.g. `Process 1 - Solace`).

## Proven Workflow (from production migrations)

1. **Configure** — create `migration.yaml` with:
   - Boomi API credentials (env var references)
   - Solace SEMP credentials (env var references)
   - Connector profile (subType + field IDs discovered from existing component)
   - Connection values (host, vpn, username, password as env var references)
   - Target folder ID
   - Process entries with destinations/operation mappings
   - `.env` file with actual credential values

2. **Run migration** — single command:
   ```bash
   uv run python -m boomi_solace_migration run --config migration.yaml
   ```
   This performs all steps with parallel execution:
   - Plan (offline, deterministic)
   - Provision Solace access control (ACL + client profile + client username)
   - Provision Solace queues (parallel, 5 workers via SOLACE_PROVISION_WORKERS)
   - Apply to Boomi (parallel, 3 workers via BOOMI_APPLY_WORKERS):
     - Create Solace connection → **verify all fields non-empty**
     - Create Solace operation(s) → **verify destination/type correct**
     - Transform process XML (swap connectors, **keep original process name**)
     - Create migrated process → **verify type=process, all IDs populated**

   Target: complete in **under 15 minutes** for typical migrations.

3. **Organize** — move components into dedicated folders:
   - Create `{Process Name} - Solace` folder under the parent
   - Move connection, operations, and process into it
   - Move any orphans from failed runs to `_Orphaned (safe to delete)`

## Naming Conventions

- **Process name**: unchanged (never rename the migrated process)
- **Connection**: `{Process Name} - Solace Connection [{hash}]`
- **Operation**: `{Process Name} - Solace {Action} {destination} [{hash}]`
- **Shape labels**: "Listen on Solace Queue" / "Send Message" / "Receive from Solace Queue"
- **Display name**: "Solace" (not "Solace PubSub+" — keep it short)
- **Queue names**: per config, no "Solace"/"PubSub+" in queue names

## Performance Tuning

- `SOLACE_SEMP_MIN_INTERVAL_SECONDS=0.05` (default 50ms between SEMP calls)
- `SOLACE_PROVISION_WORKERS=5` (parallel queue provisioning threads)
- `BOOMI_APPLY_WORKERS=3` (parallel Boomi component creation threads)
- `--monitor-queues` flag (off by default, adds stats fetch per queue)
- Queue monitoring is informational only — skip for speed

## Safety Rules

- **Never mutate the original process** — always create new components.
- Keep credentials in `.env` files excluded from git.
- Verify every component after creation (fetch back and check fields).
- Boomi API cannot delete components — if a run fails mid-way, orphaned
  components will exist. Move them to a cleanup folder.
- If a component name already exists in the folder, Boomi appends " 2" — clean
  up orphans before re-running to avoid this.
- Strip `SharedCommOverrides` and `PartnerOverrides` from process XML before
  creation (they contain dangling trading partner references).
- Strip all read-only attributes including `copiedFromComponentId` and
  `copiedFromComponentVersion`.
- **Remove `componentId` from new components** — do NOT set it to empty string
  (causes Boomi UI error "cannot read properties of undefined"). Let the API
  assign the ID on creation.

## Critical Technical Facts (Verified in Production)

- **Send operation:** `operationType="CREATE"` (NOT `"EXECUTE"` with `customOperationType`)
- **Listen operation:** `operationType="Listen"` (mixed case, NOT `"EXECUTE"`)
- **Get operation:** `operationType="GET"`
- **No `customOperationType` attribute** on any operation
- **Both request and response profile types are `"binary"`** for all operations
- **Connection field IDs vary per account** — always discover from existing component
- **Solace Cloud SEMP returns 400 with NOT_FOUND** instead of 404
- **SEMP queues need `ingressEnabled: true` and `egressEnabled: true`** explicitly
- **WSS/HTTP connectors legitimately have empty connectionId** — skip them in verification
- **Multi-destination processes** need per-connectionId operation mapping

## Solace Defaults

- Default to topic-to-queue routing: publish to topics, subscribe queues to those topics.
- When strict Atom Queue parity is required (point-to-point), use direct queue
  publishing with `endpointType: queue`.
- Use `PERSISTENT` delivery mode for queue sends.
- Use `PERSISTENT_TRANSACTED` mode for Listen/Get operations.
- Provision queues as `exclusive` with `consume` permission.
- Use `Domain/Noun/Verb/Version` topics when topic routing is appropriate.
- Deploy consumers before producers during cutover.

## Solace Access Control Provisioning

Each migration project should provision a dedicated client-username with matching
client-profile and ACL-profile. This isolates Boomi traffic and enforces
least-privilege queue ownership.

### Client Username

Create a client-username (e.g. `boomi_user`) with password blank or matching the
username. All Boomi connections use this username.

```
POST {base}/SEMP/v2/config/msgVpns/{vpn}/clientUsernames
{
  "clientUsername": "boomi_user",
  "password": "boomi_user",
  "enabled": true,
  "clientProfileName": "boomi_user",
  "aclProfileName": "boomi_user"
}
```

### Client Profile

Create a client-profile called `boomi_user` with the same settings as the
`default` client profile. Key fields to mirror from `#client-profile/default`:

```
POST {base}/SEMP/v2/config/msgVpns/{vpn}/clientProfiles
{
  "clientProfileName": "boomi_user",
  "allowGuaranteedMsgSendEnabled": true,
  "allowGuaranteedMsgReceiveEnabled": true,
  "allowTransactedSessionsEnabled": true,
  "allowBridgeConnectionsEnabled": false,
  "allowGuaranteedEndpointCreateEnabled": false,
  "maxConnectionCountPerClientUsername": 200,
  "maxEgressFlowCount": 1000,
  "maxIngressFlowCount": 1000,
  "maxSubscriptionCount": 500000,
  "maxTransactedSessionCount": 10,
  "maxTransactionCount": 50
}
```

### ACL Profile

Create an ACL-profile called `boomi_user` with the same settings as the
`default` ACL profile:

```
POST {base}/SEMP/v2/config/msgVpns/{vpn}/aclProfiles
{
  "aclProfileName": "boomi_user",
  "clientConnectDefaultAction": "allow",
  "publishTopicDefaultAction": "allow",
  "subscribeTopicDefaultAction": "allow",
  "subscribeShareNameDefaultAction": "allow"
}
```

### Queue Ownership

All migrated queues must set `owner` to `boomi_user` and restrict non-owner
access to `no-access`:

```json
{
  "queueName": "my_queue",
  "owner": "boomi_user",
  "permission": "no-access",
  "accessType": "exclusive",
  "egressEnabled": true,
  "ingressEnabled": true
}
```

This ensures only the `boomi_user` client-username can publish to and consume
from migrated queues. Non-owner clients receive "Permission Denied" if they
attempt access.

## References

Load only what is needed:

- `references/migration-overview.md`: migration semantics, deployment order, DDP handling.
- `references/api-reference.md`: Boomi REST + Solace SEMP endpoints, auth, and gotchas.
- `references/xml-templates.md`: **corrected** component XML (operationType=CREATE for Send).
- `references/solace-reference.md`: Solace queue/topic/SEMP guidance.
- `references/troubleshooting.md`: all production failures and fixes.

## Verification Expectations

Before presenting a migration as complete:

1. **Every created component** must be fetched back and verified:
   - Connection: all field values non-empty (except password which is encrypted)
   - Operation: destination matches expected, operationType correct
   - Process: type="process", no source connector types remain, all Solace connectors have non-empty connectionId and operationId

2. **Solace queues** must be confirmed on the broker:
   - Queue exists with ingressEnabled=true, egressEnabled=true

3. **Unit tests** pass: `pytest tests/ -x -q`

4. **Components organized** into dedicated folders matching source structure
