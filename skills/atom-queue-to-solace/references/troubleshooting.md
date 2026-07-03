# Troubleshooting: Solace Migration Issues

> These issues were identified and resolved during production migrations of the Culina2 processes. Each section reflects real failures encountered against the Boomi AtomSphere API and Solace Cloud SEMP v2.

---

## Boomi API Gotchas (Critical — Read First)

### Components cannot be deleted via API

**Symptom:** `DELETE /Component/{id}` returns HTTP 400.

**Cause:** The Boomi AtomSphere REST API does not support component deletion. This is an intentional platform limitation.

**Workaround:** Move unwanted components to a cleanup folder (e.g. `_Orphaned (safe to delete)`) using the update endpoint:
```
POST /Component/{id}/update
```
Set `folderId` to the cleanup folder ID in the XML body. Components can only be deleted via the Boomi UI.

### Server-side read-only attributes cause 400 on component create/update

Strip **all** of these attributes from XML before POST/update:
- `folderFullPath`, `createdDate`, `createdBy`, `modifiedDate`, `modifiedBy`
- `currentVersion`, `deleted`, `folderName`, `branchName`, `branchId`
- `copiedFromComponentId`, `copiedFromComponentVersion`

The last two are commonly missed and cause silent failures on cloned processes.

### SharedCommOverrides and PartnerOverrides cause "ComponentId is invalid" on process creation

**Symptom:** `POST /Component` for a process returns 400 with message like `"ComponentId 742f730b-... is invalid"`.

**Cause:** The original process XML contains `<SharedCommOverrides>` or `<PartnerOverrides>` elements that reference trading partner component IDs. When creating a new process in a different folder, these references may point to components that don't exist or aren't accessible.

**Fix:** Strip all `SharedCommOverrides` and `PartnerOverrides` elements from the process XML before creation:
```python
for parent in list(root.iter()):
    to_remove = [child for child in parent 
                 if local_name(child.tag) in ("SharedCommOverrides", "PartnerOverrides")]
    for child in to_remove:
        parent.remove(child)
```

### Folder query with empty nestedExpression fails

**Symptom:** `POST /Folder/query` with `{"QueryFilter": {"expression": {"operator": "and", "nestedExpression": []}}}` returns 400 with "Grouping expression must contain at least one simple expression".

**Fix:** Use a concrete expression for folder queries:
```json
{"QueryFilter": {"expression": {"argument": ["Solace"], "operator": "EQUALS", "property": "name"}}}
```
Or use LIKE for broader searches:
```json
{"QueryFilter": {"expression": {"argument": ["%"], "operator": "LIKE", "property": "name"}}}
```

### Component move/rename uses the update endpoint

There is no dedicated "move" API. To move a component between folders or rename it:
```
POST /Component/{id}/update
Content-Type: application/xml
```
Fetch the component XML, change `folderId` and/or `name`, strip read-only attributes, then POST.

### `operationType` for Send is `"CREATE"` not `"EXECUTE"`

**CRITICAL CORRECTION:** The Solace connector's Send operation uses `operationType="CREATE"` — not `"EXECUTE"` with `customOperationType="SEND"` as some documentation suggests. No `customOperationType` attribute at all. Verified in production.

Operation type mapping (confirmed):
| Action | operationType |
|--------|--------------|
| Send   | `CREATE`     |
| Listen | `Listen`     |
| Get    | `GET`        |

### `operationType` for Listen must be `"Listen"` (mixed case)

Listen operations use `operationType="Listen"`. Getting this wrong causes the start shape connector to not start. This is the only mixed-case value.

### Folder GUID vs folder path

Always use the actual folder GUID (Base64-encoded ID like `Rjo4NTYyNjIw`) in `folderId`. Path strings are not accepted.

### Boomi auto-appends " 2" to duplicate names

When creating a component with a name that already exists in the same folder, Boomi silently appends ` 2`, ` 3`, etc. to the name. If a previous failed run left orphans, subsequent successful runs will have suffixed names. Clean up orphans and rename via the update endpoint.

---

## Connector Discovery Issues

### "No Solace connection components found" during discovery

**Cause:** No Solace connector components exist in the account yet.

**Fix:** Create a minimal Solace connection in the Boomi Build tab:
1. New Component -> Connector -> select Solace
2. Name it anything (e.g. "Solace Test")
3. Save without filling in credentials
4. Note the component ID from the URL
5. Run: `GET /Component/{id}` with `Accept: application/xml`
6. Copy the `subType` attribute from the root `<bns:Component>` element

### Connection field IDs vary per account

**Cause:** Different Solace connector installations use different field IDs in `GenericConnectionConfig`.

**Known variants:**
| Logical field | Variant A | Variant B |
|---|---|---|
| Host | `host` | `host` |
| VPN | `vpn_name` | `vpn` |
| Username | `username` | `clientUsername` |
| Password | `password` | `clientPassword` |

**Fix:** Always fetch an existing Solace connection from the target account and read the actual `<field id="...">` values. Define them in a connector profile config rather than hardcoding.

---

## Migration Execution Issues

### Process transform produces "empty connectionId" for WSS/HTTP connectors

**Symptom:** Post-transform verification fails with "connectoraction has empty connectionId" on shapes that aren't queue-related.

**Cause:** Some connector types (WSS Web Server listeners, HTTP client connectors) legitimately have empty `connectionId` fields. They use inline configuration or runtime-provided URLs.

**Fix:** Verification must skip connectors with `connectorType` in (`wss`, `http`, `""`) that have empty `connectionId`. Only assert non-empty IDs for the target Solace connector type.

### Multi-destination processes need per-connection operation mapping

**Symptom:** Process has multiple Send shapes each going to different queues (e.g. 11 different destinations), but all get assigned the same operation ID.

**Cause:** Simple action-type mapping (`send` → one operation) doesn't work when a process routes to multiple destinations via different original connections.

**Fix:** Use `connection_operation_map` — a dict mapping each original `connectionId` to its own new Solace operation ID:
```python
connection_operation_map = {
    "original-conn-id-1": "new-solace-op-for-queue-A",
    "original-conn-id-2": "new-solace-op-for-queue-B",
    ...
}
```
Create one Send operation per destination, then map by the original connectionId on each connectoraction element.

### Component creation returns 400 or 422

**Common causes:**
- `subType` is incorrect or has extra whitespace
- Password contains XML-special characters (not escaped as `&amp;`, `&quot;`, etc.)
- Missing namespace declarations
- Read-only attributes not stripped (see above)
- SharedCommOverrides referencing invalid components (see above)

### "No atom queue operations found" for a process you know uses queues

**Cause:** The detection checks `connectorType` values `'atomqueue'` or `'queue'`. Some older processes may use a variant.

**Fix:**
1. Pull the process XML manually
2. Search for `<connectoraction` in the XML
3. Note the exact `connectorType` value
4. If different, add it to `source_connector_types` in the migration config

---

## Solace SEMP API Issues

### Solace Cloud SEMP returns 400 with NOT_FOUND instead of 404

**Symptom:** `GET /SEMP/v2/config/msgVpns/{vpn}/queues/{queue}` returns HTTP 400 (not 404) when the queue doesn't exist.

**Cause:** Solace Cloud's SEMP v2 implementation returns 400 with a JSON body containing `"meta": {"error": {"status": "NOT_FOUND"}}` instead of a standard 404.

**Fix:** Check for NOT_FOUND in both status codes:
```python
def _is_not_found(self, response):
    if response.status_code == 404:
        return True
    if response.status_code == 400:
        try:
            status = response.json().get("meta", {}).get("error", {}).get("status", "")
            return status == "NOT_FOUND"
        except (ValueError, KeyError, AttributeError):
            pass
    return False
```

### SEMP queue creation requires explicit ingress/egress enabled

**Symptom:** Queue created successfully but messages can't be sent to or consumed from it.

**Fix:** Always set both flags when creating queues:
```json
{
  "queueName": "my_queue",
  "accessType": "exclusive",
  "egressEnabled": true,
  "ingressEnabled": true,
  "permission": "consume"
}
```

### SEMP URL-encode queue names

Queue names with special characters must be URL-encoded in SEMP paths:
```python
from urllib.parse import quote
url = f"{base}/SEMP/v2/config/msgVpns/{quote(vpn, safe='')}/queues/{quote(queue_name, safe='')}"
```

---

## Solace Connection Issues

### Process runs but fails to connect to Solace broker

**Checklist:**
- Verify `host` URL is correct and the port is open from the Boomi Atom's network
- For Solace Cloud: use `tcps://mr-xxxx.messaging.solace.cloud:55443` (TLS required)
- Verify Message VPN name matches exactly (case-sensitive)
- Verify client username and password
- Verify the Boomi Atom can reach the Solace host (network/firewall rules)
- For TLS connections: ensure the Atom's JVM trusts the broker's certificate

### "Queue not found" or "topic not found" at runtime

**Cause:** The Solace destination doesn't exist on the broker.

**Fix:** Provision queues via SEMP or Solace Console BEFORE deploying the migrated process. The migration tool can auto-provision via `provision_queue: true` in the config.

### Messages sent but consumer receives nothing

**Causes:**
- Producer is sending to a queue, consumer is subscribing to a different destination
- Producer is sending DIRECT delivery - no persistence; consumer wasn't ready
- Queue access type mismatch (Exclusive queue already has a different consumer bound)
- `ingressEnabled` or `egressEnabled` is false on the queue

**Fix:**
- Verify send and receive destination names match exactly
- Use `PERSISTENT` delivery mode for queues
- Check Solace Console → queue details → "Consumers" tab

---

## DDP Migration Issues

### DDPs not propagating after migration

**Root cause:** DDPs require explicit mapping on both sides.

**Checklist:**
1. Producer connector step has `<dynamicProperties>` with `<propertyvalue key="userProperties">` for each DDP
2. Consumer process has a Set Properties step immediately after the Solace connector
3. Set Properties uses `valueType="connector"` with `connectorSource="User Properties"`
4. Property names match exactly (camelCase on producer, original DDP name on consumer)

---

## Post-Migration Organization

### Place migrated components in dedicated folders

After migration, organize components into per-process folders matching the source structure:
```
Culina/
├── Process 1/              (original components)
├── Process 1 - Solace/     (connection + operations + process)
├── Process 2/              (original components)
└── Process 2 - Solace/     (connection + operations + process)
```

Move components via `POST /Component/{id}/update` with updated `folderId`. Keep one connection per process folder (or share across processes in the same folder if they use the same broker/VPN/credentials).
