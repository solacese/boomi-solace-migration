# Solace PubSub+ Reference for Boomi Migration

## Overview

Solace PubSub+ is an enterprise event broker that supports multiple messaging protocols (SMF, AMQP 1.0, MQTT, REST, JMS) and provides guaranteed delivery, message replay, topic hierarchies, and a rich management API.

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

### Topics
- **Pub/Sub** destinations using a hierarchical name (e.g. `domain/entity/created`)
- Publishers send to a topic; subscribers receive from matching topic subscriptions
- Topics are not stored - messages are lost unless a durable queue subscribes to the topic
- Use topic wildcards: `domain/>` (match all under `domain/`), `domain/*/created`

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

## Solace SEMP API (Optional Queue Provisioning)

The SEMP (Solace Element Management Protocol) REST API can create and manage broker resources. For Solace Cloud:

### Get services
```
GET https://api.solace.cloud/api/v2/services
Authorization: Bearer {api_token}
```

### Create a queue
```
POST https://api.solace.cloud/api/v2/services/{serviceId}/requests/queues
Authorization: Bearer {api_token}
Content-Type: application/json

{
  "queueName": "my_queue",
  "accessType": "exclusive",
  "permission": "consume",
  "maxMsgSize": 10000000,
  "maxMsgSpoolUsage": 1500
}
```

### Add a topic subscription to a queue
```
POST https://api.solace.cloud/api/v2/services/{serviceId}/requests/queues/{queueName}/subscriptions
Content-Type: application/json

{
  "subscriptionTopic": "domain/entity/>"
}
```

For on-premises Solace brokers, use SEMP v2 at `https://broker-host:943/SEMP/v2/config`.

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

Solace can route undeliverable messages to a special queue called `#DEAD_MSG_QUEUE`. Configure this on the queue:

```json
{
  "deadMsgQueue": "#DEAD_MSG_QUEUE",
  "maxRedeliveryCount": 3
}
```

If the consumer fails to acknowledge a message after `maxRedeliveryCount` attempts, the message is moved to the DMQ. Monitor the DMQ in Solace Console under **Queues -> #DEAD_MSG_QUEUE**.

---

## Connector Discovery in Boomi

The Boomi Solace PubSub+ connector is installed as a **Tech Partner Connector** (or first-party connector depending on account). Its `subType` is the unique identifier Boomi uses in component XML.

**To find it manually:**
1. Boomi Build tab -> New Component -> Connector
2. Search for "Solace" in the connector type picker
3. Once selected, create and save a minimal connection component
4. Note the component ID from the URL (`?componentId=...`)
5. Pull the XML: `GET https://api.boomi.com/api/rest/v1/{accountId}/Component/{id}`
6. The `subType` attribute on the root `<bns:Component>` element is the value you need

**Automatic discovery:** Phase 1b of the migration skill does this for you by querying all connector-settings components and searching for any with "solace" in the name.
