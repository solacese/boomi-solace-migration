# API Reference: Boomi AtomSphere REST API & Solace SEMP v2

This migration uses the Boomi AtomSphere REST API for component management and Solace SEMP v2 for queue provisioning.

---

## Boomi Authentication

```
Base URL: https://api.boomi.com/api/rest/v1/{accountId}
Auth:     Basic base64("BOOMI_TOKEN.{email}:{apiToken}")
```

Python example:
```python
import base64
auth_string = f"BOOMI_TOKEN.{email}:{api_token}"
encoded = base64.b64encode(auth_string.encode()).decode()
headers = {"Authorization": f"Basic {encoded}"}
```

XML endpoints use `Content-Type: application/xml` and `Accept: application/xml`.
JSON query endpoints use `Content-Type: application/json` and `Accept: application/json`.

---

## Process Discovery

### Query Processes by Folder

```
POST https://api.boomi.com/api/rest/v1/{accountId}/ComponentMetadata/query
Content-Type: application/json
Accept: application/json
Body:
{
  "QueryFilter": {
    "expression": {
      "argument": ["FOLDER_ID_HERE"],
      "operator": "EQUALS",
      "property": "folderId"
    }
  }
}
```

> **WARNING:** Do NOT use empty `nestedExpression: []` — Boomi rejects it with "Grouping expression must contain at least one simple expression". Always use a concrete simple expression.

Paginate: `POST .../ComponentMetadata/query/more/{queryToken}`

---

## Component Operations

### Get Component XML

```
GET https://api.boomi.com/api/rest/v1/{accountId}/Component/{componentId}
Accept: application/xml
Response: Full component XML with all attributes including subType
```

### Create Component

```
POST https://api.boomi.com/api/rest/v1/{accountId}/Component
Content-Type: application/xml
Accept: application/xml
Body: <bns:Component ...>...</bns:Component>
Response: Component XML with assigned componentId (HTTP 200 or 201)
```

Rules:
- `componentId=""` in the request body — Boomi assigns a GUID
- `version="1"` in the request body — always start at version 1
- Strip ALL server-side read-only attributes:
  - `folderFullPath`, `createdDate`, `createdBy`, `modifiedDate`, `modifiedBy`
  - `currentVersion`, `deleted`, `folderName`, `branchName`, `branchId`
  - `copiedFromComponentId`, `copiedFromComponentVersion`
- Strip `SharedCommOverrides` and `PartnerOverrides` elements (contain dangling references)
- If a component with the same name exists in the folder, Boomi appends " 2", " 3", etc.

### Update Component (Move/Rename)

```
POST https://api.boomi.com/api/rest/v1/{accountId}/Component/{componentId}/update
Content-Type: application/xml
Accept: application/xml
Body: <bns:Component ...>...</bns:Component> (with updated folderId/name)
Response: Updated component XML (HTTP 200)
```

Use this to move components between folders or rename them. Same read-only stripping rules apply.

### Delete Component — NOT SUPPORTED

```
DELETE /Component/{id} → HTTP 400 (always fails)
```

The Boomi API does not support component deletion. Use the UI, or move orphans to a cleanup folder.

---

## Connector Discovery

### Find Solace Components by Folder

```
POST https://api.boomi.com/api/rest/v1/{accountId}/ComponentMetadata/query
Content-Type: application/json
Accept: application/json
Body:
{
  "QueryFilter": {
    "expression": {
      "argument": ["FOLDER_ID"],
      "operator": "EQUALS",
      "property": "folderId"
    }
  }
}
```

Filter results by `type` field (`connector-settings`, `connector-action`, `process`) and by name containing "solace". Then fetch full XML with `GET /Component/{id}` to extract `subType` and field IDs.

---

## Folder Operations

### Query Folders

```
POST https://api.boomi.com/api/rest/v1/{accountId}/Folder/query
Content-Type: application/json
Accept: application/json
Body: {"QueryFilter": {"expression": {"argument": ["Culina%"], "operator": "LIKE", "property": "name"}}}
Response: {"result": [{"id": "Rjo4NTYyNjIw", "name": "Culina", "parentId": "Rjo4NTYyNjE2"}], ...}
```

- Folder IDs are Base64-encoded strings (e.g. `Rjo4NTYyNjIw`)
- Always use the folder ID in `folderId` — path strings are not accepted
- Query by `parentId` to find subfolders

### Create Folder

```
POST https://api.boomi.com/api/rest/v1/{accountId}/Folder
Content-Type: application/json
Accept: application/json
Body: {"name": "Process 1 - Solace", "parentId": "Rjo4NTYyNjIw"}
Response: {"id": "Rjo4NTYyOTg1", "name": "Process 1 - Solace", "parentId": "Rjo4NTYyNjIw"}
```

---

## Solace SEMP v2 API

### Authentication

```
Base URL: https://{broker-host}:{port}
Auth:     Basic (SEMP admin username:password)
VPN path: /SEMP/v2/config/msgVpns/{vpn-name}
```

For Solace Cloud: the SEMP URL is found in the service's "Manage" tab under "SEMP - REST API".

### Check VPN exists (auth test)

```
GET {base}/SEMP/v2/config/msgVpns/{vpn}
```

### Get Queue

```
GET {base}/SEMP/v2/config/msgVpns/{vpn}/queues/{queue-name}
Response: 200 with queue config, or 400 with NOT_FOUND (see below)
```

### Create Queue

```
POST {base}/SEMP/v2/config/msgVpns/{vpn}/queues
Content-Type: application/json
Body:
{
  "queueName": "SCE_ASN_Queue",
  "accessType": "exclusive",
  "egressEnabled": true,
  "ingressEnabled": true,
  "permission": "consume"
}
```

### Add Topic Subscription to Queue

```
POST {base}/SEMP/v2/config/msgVpns/{vpn}/queues/{queue}/subscriptions
Content-Type: application/json
Body: {"subscriptionTopic": "domain/entity/>"}
```

### Critical: NOT_FOUND returns 400, not 404

Solace Cloud SEMP returns HTTP 400 (not 404) for non-existent resources. Parse the response body:
```json
{"meta": {"error": {"status": "NOT_FOUND", ...}}}
```

Always check both 404 AND 400+NOT_FOUND when testing for resource existence.

### URL-encode queue names in paths

```python
from urllib.parse import quote
url = f"{base}/SEMP/v2/config/msgVpns/{quote(vpn, safe='')}/queues/{quote(queue_name, safe='')}"
```

---

## Auto-Naming Conventions

When suggesting destination names from a process name:

```python
import re
dest_name = re.sub(r'[^a-z0-9_]', '_', process_name.lower()).strip('_')
dest_name = re.sub(r'_+', '_', dest_name)  # collapse multiple underscores
```

Example: `"Sample Queue Process"` -> `"sample_queue_process"`

Solace queue names support: letters, numbers, underscores, hyphens, dots.
Solace topic names support: letters, numbers, underscores, hyphens, dots, `/` (hierarchy separator).
