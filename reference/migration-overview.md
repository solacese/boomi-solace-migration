# Migration Overview: Atom Queues -> Solace PubSub+

## Why Migrate

Atom Queues are in maintenance mode (no new features since September 2025). Solace PubSub+ is a full-featured enterprise messaging platform with persistent queues, topic hierarchies, guaranteed delivery, replay, and rich observability - and is the target platform for many organizations moving to a strategic message broker.

---

## Architecture Comparison

| Concern | Atom Queues | Solace PubSub+ |
|---|---|---|
| Message Properties | DDPs auto-propagated | Explicit User Properties (header) |
| Authentication | Implicit (runtime-level) | Client username + password (or client certificate) per VPN |
| Destination models | P2P queue / Pub-Sub topic | Queues (exclusive/non-exclusive) + Topic subscriptions |
| Protocol | Boomi internal | SMF (native), AMQP 1.0, MQTT, REST, JMS |
| Delivery guarantee | Best-effort queue | Persistent queues with acknowledgement |
| Message replay | None | Queue replay, topic replay (if replay log enabled) |
| Batching | Configurable | Per-operation configuration |
| Retry/DLQ | Limited | Configurable per queue; DMQ (Dead Message Queue) |
| Observability | None | Solace Cloud Console: queue depth, rate, DLQ |

---

## Operation Mapping

| Atom Queue Operation | Shape Position | Solace Operation |
|---|---|---|
| Send | Connector step only | **Send** - connector step, to queue or topic |
| Listen | Start shape only | **Listen** - start shape, event-driven |
| Get | Start or connector step | **Get/Receive** - polling, from queue |

**Migration types:**
- **Producer**: process has Send operations only -> replace with Solace Send
- **Consumer**: process has Get and/or Listen operations -> replace with Solace Get/Listen
- **Mixed**: process has both Send and Get/Listen -> replace both types

---

## End-to-End Data Flow

```
1. Parse process XML
   -> Find all <connectoraction> with connectorType in ('atomqueue', 'queue')
   -> Extract: actionType, connectionId, operationId, userLabel
   -> Extract DDPs: all <trackparameter propertyId> containing "dynamicdocument."
   -> Classify: producer / consumer / mixed

2. Collect Solace configuration (no API calls - user-provided)
   -> Solace host URL (SMF), Message VPN, client username, client password
   -> Send destination: queue or topic name + type
   -> Receive destination: queue name + type

3. Create Boomi Components (via REST API POST /Component)
   -> Solace Connection (connector-settings, subType = Solace connector subType)
   -> Send Operation (one per Send group, with userProperties for each DDP)
   -> Listen Operation (one per Listen shape)
   -> Get/Receive Operation (one per Get group)

4. Transform Process XML
   -> Clone original XML, clear componentId + version
   -> For each queue connector shape:
     - connectorType: 'atomqueue'/'queue' -> SOLACE_SUBTYPE
     - actionType: 'Send' -> 'Send', 'Get' -> 'Get', 'Listen' -> 'Listen'
     - connectionId -> new Solace connection GUID
     - operationId -> matching new Solace operation GUID
   -> For Send shapes: add <dynamicProperties> mapping each DDP to userProperties
   -> Update userLabel: replace "Queue" with "Solace"

5. Push converted process (via REST API POST /Component)
   -> Validate: pull back and verify all connectors have connectionId + operationId

6. Report
   -> Process ID, destinations, components created, DDPs handled, validation
```

---

## DDP -> User Property Migration (Critical Pattern)

Atom Queues automatically propagate Dynamic Document Properties (DDPs). Solace uses User Properties (message header key-value pairs) for the same purpose - but they require explicit mapping.

### Producer side - define and populate User Properties

**Connector step XML** - map DDP values at runtime:
```xml
<connectoraction actionType="Send" ...>
  <dynamicProperties>
    <propertyvalue childKey="entityId" key="userProperties"
                   name="User Properties" valueType="track">
      <trackparameter defaultValue="" propertyId="dynamicdocument.ENTITY_ID"
                      propertyName="Dynamic Document Property - ENTITY_ID"/>
    </propertyvalue>
  </dynamicProperties>
</connectoraction>
```

**DDP name -> childKey conversion rule:**
Strip `DDP_` prefix -> lowercase -> snake_case to camelCase.
Example: `DDP_ENTITY_ID` -> strip prefix -> `ENTITY_ID` -> lowercase -> `entity_id` -> camelCase -> `entityId`

### Consumer side - extract User Properties back to DDPs

Add a **Set Properties** step immediately after the Solace connector:
```xml
<shape shapetype="documentproperties" userlabel="Extract User Properties" ...>
  <setproperties>
    <propertyvalue childKey="ENTITY_ID" valueType="connector">
      <connectorparameter connectorOperation="Solace PubSub+"
                          connectorProperty="entityId"
                          connectorSource="User Properties"/>
    </propertyvalue>
  </setproperties>
</shape>
```

The exact `connectorOperation` and `connectorSource` values depend on the Solace connector's metadata. Check in the Boomi UI when building the Set Properties step to get the exact values.

---

## Component Dependency Order

When creating components, always respect this order:
1. Solace Connection component (holds host/VPN/credentials)
2. Solace Operation components (Send, Listen, Get - each references no other components)
3. Converted Process (references connection + operation IDs)

---

## Destination Design: Queue vs Topic

When migrating from Atom Queues, use **Solace Queues** unless you have a specific reason for topics:

| Scenario | Use |
|---|---|
| Reliable point-to-point (mirrors Atom Queue P2P) | Queue (Exclusive) |
| Competing consumers / load-balanced workers | Queue (Non-Exclusive) |
| Fan-out / broadcast to multiple subscribers | Topic + durable topic endpoint |
| Fire-and-forget, high-throughput, no guarantee needed | Topic (Direct) |

---

## Solace Queue and Topic Provisioning

**This skill creates Boomi components only.** You must ensure the Solace destination exists before deploying the migrated process. Options:

1. **Solace Cloud Console** - create queues/topics in the UI
2. **SEMP API** - programmatic queue creation:
   ```bash
   curl -X POST "https://api.solace.cloud/api/v2/services/{serviceId}/requests/queues" \
     -H "Authorization: Bearer {api_token}" \
     -H "Content-Type: application/json" \
     -d '{"queueName":"my_queue","accessType":"exclusive","permission":"consume"}'
   ```
3. **Solace CLI** - for on-premises brokers

---

## Post-Migration Checklist

After a successful migration, the engineer must:

1. **Provision** queue/topic in Solace if it doesn't exist
2. **Verify** Solace client credentials have publish/consume access to the destination
3. **Deploy** the converted process to the target environment
4. **Execute** a test run with a sample payload
5. **Verify** messages appear in Solace Console (queue depth, message rate)
6. **Update consumers** - any downstream processes consuming the old Atom Queue need their own migration
7. **Drain the original queue** - let any in-flight messages process before cutover
8. **Deactivate/delete the original process** after confirming the new one is stable

**Cutover order is critical:**
- Consumer process deployed FIRST (starts listening before producers begin)
- Producer process deployed SECOND
- Deactivate original producer FIRST, then drain, then deactivate original consumer

---

## Known Limitations

- DDP propagation through conditional branches needs manual validation on the consumer side
- Solace topic hierarchies use `/` separators (e.g. `domain/entity`) - the skill uses flat names; adjust if your Solace architecture uses hierarchy
- On-premises Solace brokers may use different ports or require SSL certificate configuration not covered by the basic XML templates
- The Boomi Solace connector's exact XML field names are discovered dynamically in Phase 1b - if the discovered field names differ from the templates, adapt before running
