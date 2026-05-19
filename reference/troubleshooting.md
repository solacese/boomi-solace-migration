# Troubleshooting: Solace Migration Issues

---

## Connector Discovery Issues

### "No Solace connection components found" during Phase 1b

**Cause:** No Solace connector components exist in the account yet.

**Fix:** Create a minimal Solace connection in the Boomi Build tab:
1. New Component -> Connector -> select Solace PubSub+
2. Name it anything (e.g. "Solace Test")
3. Save without filling in credentials
4. Note the component ID from the URL
5. Run: `GET https://api.boomi.com/api/rest/v1/{accountId}/Component/{id}` with `Accept: application/xml`
6. Copy the `subType` attribute from the root `<bns:Component>` element
7. Pass that value to the migration skill

### "Solace connector not available" in Boomi Build

**Cause:** The Solace connector is not installed in the account.

**Fix:** Install the Solace PubSub+ connector from the Boomi connector marketplace (Build tab -> Browse Connectors or contact Boomi support). The connector may be under "Tech Partner Connectors" or the Boomi marketplace.

### The XML field names in the generated connection component don't match what Boomi expects

**Cause:** The field IDs in `GenericConnectionConfig` (`host`, `vpn`, `clientUsername`, `clientPassword`) are based on common Boomi Solace connector conventions but may differ in your connector version.

**Fix:**
1. In Phase 1b, the skill returns a `sampleXml` excerpt from an existing Solace connection
2. Compare the field IDs in that excerpt to the ones in the generated XML
3. Update the script's `conn_xml` template before running

---

## Migration Execution Issues

### Migration succeeds but validation fails (connectors missing IDs)

**Cause:** Component creation succeeded but the GUIDs weren't substituted correctly in the process XML.

**Fix:**
1. Pull the migrated process XML: `GET /Component/{new-process-id}`
2. Find all `<connectoraction connectorType="[SOLACE_SUBTYPE]">`
3. Verify each has non-empty `connectionId` and `operationId`
4. If empty: re-run migration script with the correct subType and component IDs

### Component creation returns 400 or 422

**Cause:** Usually malformed XML - bad attribute values, wrong subType, or missing required fields.

**Common causes:**
- `subType` is incorrect or has extra whitespace
- Password contains XML-special characters (not escaped as `&amp;`, `&quot;`, etc.)
- Missing namespace declarations

**Fix:** Check `/tmp/boomi_migrate_solace.log` for the exact error response body. Fix the XML template and retry.

### "No atom queue operations found" for a process you know uses queues

**Cause:** The detection checks `connectorType` values `'atomqueue'` or `'queue'`. Some older processes may use a variant.

**Fix:**
1. Pull the process XML manually
2. Search for `<connectoraction` in the XML
3. Note the exact `connectorType` value
4. If different (e.g. `'queue-connector'`), update the `detect_queue_ops` function to include that value

---

## Solace Connection Issues

### Process runs but fails to connect to Solace broker

**Symptoms:** Process executes but the Solace connector shape fails with a connection error.

**Checklist:**
- Verify `host` URL is correct and the port is open from the Boomi Atom's network
- Verify Message VPN name matches exactly (case-sensitive)
- Verify client username and password
- Verify the Boomi Atom can reach the Solace host (network/firewall rules)
- For TLS connections: ensure the Atom's JVM trusts the broker's certificate

### "Queue not found" or "topic not found" at runtime

**Cause:** The Solace destination doesn't exist on the broker.

**Fix:** Create the queue or topic endpoint in Solace Cloud Console or via SEMP before running the process.

### Messages sent but consumer receives nothing

**Causes:**
- Producer is sending to a queue, consumer is subscribing to a different destination
- Producer is sending DIRECT delivery - no persistence; consumer wasn't ready
- Queue access type mismatch (Exclusive queue already has a different consumer bound)

**Fix:**
- Verify send and receive destination names match exactly
- Use `PERSISTENT` delivery mode for queues
- Check Solace Console -> queue details -> "Consumers" tab for bound consumers

---

## DDP Migration Issues

### DDPs not propagating after migration

**Symptom:** Consumer process doesn't receive the expected DDP values.

**Root cause:** DDPs require explicit mapping on both sides.

**Checklist:**
1. Producer connector step has `<dynamicProperties>` with `<propertyvalue key="userProperties">` for each DDP
2. Consumer process has a Set Properties step immediately after the Solace connector
3. Set Properties uses `valueType="connector"` with `connectorSource="User Properties"`
4. Property names match exactly (camelCase on producer, original DDP name on consumer)

### DDP names differ from expected camelCase

**Cause:** The conversion strips `DDP_` prefix then camelCases. DDPs without that prefix produce unexpected results.

**Fix:** Inspect the `ddpsMigrated` list in the migration output. Manually verify the `childKey` values match what the consumer expects.

---

## Boomi API Gotchas (General)

### `operationType` for Listen must be `"Listen"` not `"EXECUTE"`

Listen operations use `operationType="Listen"` (mixed case). All other operations use `operationType="EXECUTE"`. Getting this wrong causes the start shape connector to not start.

### Folder GUID vs folder path

Always use the actual folder GUID in `folderId`. The Boomi API does not accept folder path strings.

### Server-side attributes cause 400 on component create

Strip these attributes from cloned XML before posting: `folderFullPath`, `createdDate`, `createdBy`, `modifiedDate`, `modifiedBy`, `currentVersion`, `deleted`, `folderName`, `branchName`, `branchId`.

### XML special characters in passwords or names

Escape: `&` -> `&amp;`, `"` -> `&quot;`, `<` -> `&lt;`, `>` -> `&gt;`

The migration script calls `escape_xml()` on all user-supplied strings. If you edit the script manually, ensure escaping is applied.
