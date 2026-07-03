# Solace Reference for Boomi Migration

## Overview

Solace is an enterprise event broker that supports multiple messaging protocols (SMF, AMQP 1.0, MQTT, REST, JMS) and provides guaranteed delivery, message replay, topic hierarchies, and a rich management API.

---

## Messaging Primitives

### Queues
- **Durable**, **persistent** storage for messages
- Access types:
  - **Exclusive**: only one consumer at a time (P2P pattern - closest to Atom Queue)
  - **Non-Exclusive**: competing consumers share the queue (load-balanced)
- Messages are removed once acknowledged by the consumer
- Support Dead Message Queue (DMQ) for undeliverable messages
- CLI: `show queue my-queue`
- Recommended migration pattern: publish events to topics, then add matching
  subscriptions to durable queues for consumers
- Direct queue publishing is supported for strict point-to-point compatibility,
  but topic-to-queue mapping is more flexible for routing and future reuse

### Topics
- **Pub/Sub** destinations using a hierarchical name such as `domain/entity/created`
- Publishers send to a topic; subscribers receive from matching topic subscriptions
- Topics are not stored - messages are lost unless a durable queue subscribes to the topic
- Use topic wildcards: `domain/>` (match all under `domain/`), `domain/*/created`
- Recommended event topic root: `Domain/Noun/Verb/Version`
- Keep generated nouns in one camelCase level, for example `orderCreatedEvent`
- Do not place environment names or tracing IDs in topic levels
- Prefer topic hierarchy and queue subscriptions over selectors

### Topic Endpoints (Durable Topic Subscriptions)
- A queue that automatically subscribes to a topic pattern
- Combines topic routing with queue persistence

---

## Connection Parameters

| Parameter | Description | Example |
|---|---|---|
| Host | SMF URL(s) for the broker | `smf://hostname:55555` |
| TLS Host | SMF over TLS | `smfs://hostname:55443` |
| Solace Cloud | Typically TLS | `tcps://mrXXXXXX.messaging.solace.cloud:55443` |
| Message VPN | Isolated messaging namespace | `default`, `production-vpn` |
| Client Username | Authentication identity | `boomi-client` |
| Client Password | Authentication credential | (encrypted in Boomi) |
| Client Name | Optional, for identification | `boomi-migration-process` |

### HA / Multi-Host
For High Availability, provide a comma-separated list:
```
smf://primary-host:55555,smf://backup-host:55555
```

---

## SMF Protocol Ports

| Port | Protocol | TLS |
|---|---|---|
| 55555 | SMF | No |
| 55443 | SMF | Yes |
| 55003 | SMF compressed | No |
| 943 | SEMP (management) | No |
| 943 | SEMP over HTTPS | Yes |

---

## Delivery Modes

| Mode | Guarantee | Use Case |
|---|---|---|
| `PERSISTENT` | Guaranteed, survives restart | Default for queue-based migration |
| `NON_PERSISTENT` | Best-effort, may lose on restart | High-throughput, tolerant flows |
| `DIRECT` | Fire-and-forget to topic | Telemetry, monitoring, non-critical |

---

## Solace SEMP v2 API (Queue Provisioning)

The SEMP (Solace Element Management Protocol) v2 REST API creates and manages broker resources. For production migrations, always use SEMP v2 directly (not the Solace Cloud REST API) — it's the same API regardless of whether the broker is cloud-hosted or on-premises.

### Authentication
```
Base URL: https://{semp-host}:{port}
Auth:     Basic (admin username:password)
Endpoint: /SEMP/v2/config/msgVpns/{vpn-name}/queues
```

For Solace Cloud: find the SEMP URL in the service's "Manage" tab under "SEMP - REST API".

### Create a queue (idempotent pattern)
```
# 1. Check if queue exists
GET {base}/SEMP/v2/config/msgVpns/{vpn}/queues/{queue_name}
# Returns 200 if exists, or 400 with NOT_FOUND (not 404!) if it doesn't

# 2. Create if not found
POST {base}/SEMP/v2/config/msgVpns/{vpn}/queues
Content-Type: application/json

{
  "queueName": "my_queue",
  "accessType": "exclusive",
  "egressEnabled": true,
  "ingressEnabled": true,
  "permission": "consume"
}
```

> **CRITICAL:** Solace Cloud returns HTTP 400 with `{"meta":{"error":{"status":"NOT_FOUND"}}}` instead of 404. Always parse the response body when status is 400.

> **CRITICAL:** Always set `egressEnabled: true` and `ingressEnabled: true`. Without these, the queue exists but cannot send or receive messages.

### Add a topic subscription to a queue
```
POST {base}/SEMP/v2/config/msgVpns/{vpn}/queues/{queueName}/subscriptions
Content-Type: application/json

{"subscriptionTopic": "domain/entity/>"}
```

### Rate limiting
Keep SEMP calls throttled with at least 110ms between requests. The migration tool defaults to `_min_interval = 0.11` seconds. Use exponential backoff on 429/5xx responses.

### URL encoding
Queue names with special characters must be URL-encoded in path segments:
```python
from urllib.parse import quote
f"/queues/{quote(queue_name, safe='')}"
```

---

## Solace Cloud Console

1. Log in at [console.solace.cloud](https://console.solace.cloud/)
2. Select your messaging service
3. Navigate to **Queues** to create/inspect queues
4. Navigate to **Try Me!** for test publishing and subscribing
5. Navigate to **Monitor** for real-time queue depth and message rates

---

## Client Authorization

Solace uses **Client Profiles** and **ACL Profiles** to control what clients can do:
- **Client Profile**: defines connection limits, throughput, max subscriptions
- **ACL Profile**: defines which topics/queues a client can publish/subscribe to

Before migrating, confirm the client username you're using has:
- `Publish` permission on the send destination
- `Subscribe` or `Consume` permission on the receive destination

Check in Solace Console: **Access Control -> Client Usernames -> your-username -> ACL Profile**.

### Provisioning a Dedicated Client Username for Boomi

For production migrations, create a dedicated `boomi_user` client-username with
matching client-profile and ACL-profile. This provides:
- Isolation: Boomi traffic is identifiable in monitoring/logs
- Least-privilege: queue ownership restricts access to only the Boomi client
- Auditability: all Boomi operations are attributable to a single identity

#### SEMP v2 Provisioning Order

1. **ACL Profile** — must exist before assigning to client-username
2. **Client Profile** — must exist before assigning to client-username
3. **Client Username** — references both profiles
4. **Queues** — set `owner` to the client-username

#### ACL Profile (boomi_user)

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

Mirror the `default` ACL profile. Tighten publish/subscribe exceptions later if
needed (e.g. restrict to `boomi/>` topic namespace).

#### Client Profile (boomi_user)

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

Mirror the `default` client profile. Key: `allowGuaranteedEndpointCreateEnabled`
is `false` — Boomi should NOT dynamically create queues; provisioning is managed
by the migration tool via SEMP.

#### Client Username (boomi_user)

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

Password can be blank (`""`) or set to `"boomi_user"` for non-production. For
production, use a strong password stored in Boomi's encrypted connection field.

#### Queue Ownership Settings

All migrated queues should set:
```json
{
  "owner": "boomi_user",
  "permission": "no-access"
}
```

- **owner = boomi_user**: grants full access (publish, consume, browse, delete)
  to any client authenticated as `boomi_user`
- **permission = no-access**: denies all access to non-owner clients

This is the Solace equivalent of private queue access in Atom Queues.

---

## User Properties (Message Headers)

Solace messages carry **User Properties** - key-value string pairs in the message header. These are analogous to:
- Boomi Event Streams **Message Properties**
- JMS **Message Properties**
- AMQP **Application Properties**

When migrating DDPs to User Properties:
- **Producer**: set User Properties in the connector step's `dynamicProperties`
- **Consumer**: extract User Properties in a Set Properties step after the Solace connector

User Property names are case-sensitive. The migration tool uses camelCase (e.g. `entityId`).

---

## Dead Message Queue (DMQ)

Solace can route undeliverable messages to a DMQ. Prefer a per-queue DMQ such as
`{queue}_dmq` so ownership, monitoring, and cleanup remain scoped to the migrated
flow:

```json
{
  "deadMsgQueue": "my_queue_dmq",
  "maxRedeliveryCount": 5,
  "redeliveryEnabled": true
}
```

If the consumer fails to acknowledge a message after `maxRedeliveryCount`
attempts, the message is moved to the DMQ. Monitor both the primary queue and
the DMQ in Solace Console under **Queues**.

---

## Connector Discovery in Boomi

The Boomi Solace connector is installed as a **Tech Partner Connector** (or first-party connector depending on account). Its `subType` is the unique identifier Boomi uses in component XML.

**To find it manually:**
1. Boomi Build tab -> New Component -> Connector
2. Search for "Solace" in the connector type picker
3. Once selected, create and save a minimal connection component
4. Note the component ID from the URL (`?componentId=...`)
5. Pull the XML: `GET https://api.boomi.com/api/rest/v1/{accountId}/Component/{id}`
6. The `subType` attribute on the root `<bns:Component>` element is the value you need

**Automatic discovery:** Phase 1b of the migration skill does this for you by querying all connector-settings components and searching for any with "solace" in the name.
