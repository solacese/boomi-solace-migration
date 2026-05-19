# API Reference: Boomi AtomSphere REST API

This migration uses only the Boomi AtomSphere REST API. No Solace APIs are called by the migration scripts - Solace broker details are collected from the user and embedded in Boomi component XML.

---

## Authentication

### REST API (AtomSphere)

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

### List All Processes

```
POST https://api.boomi.com/api/rest/v1/{accountId}/Process/query
Content-Type: application/json
Accept: application/json
Body:
{
  "QueryFilter": {
    "expression": {
      "operator": "and",
      "nestedExpression": []
    }
  }
}
Response: {"result": [...], "numberOfResults": N, "queryToken": "..."}
```

Paginate: `POST .../Process/query/more/{queryToken}`

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
Response: Component XML with assigned componentId
```

Rules:
- `componentId=""` in the request body - Boomi assigns a GUID
- `version="1"` in the request body - always start at version 1
- Strip server-side read-only attributes: `folderFullPath`, `createdDate`, `createdBy`, `modifiedDate`, `modifiedBy`, `currentVersion`, `deleted`, `folderName`, `branchName`, `branchId`

---

## Connector Discovery

### List All Connector-Settings Components (find Solace connections)

```
POST https://api.boomi.com/api/rest/v1/{accountId}/ComponentMetadata/query
Content-Type: application/xml
Accept: application/xml
Body:
<QueryConfig xmlns="http://api.platform.boomi.com/"
             xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
             queryToken="" objectType="ComponentMetadata">
  <QueryFilter>
    <expression operator="and" xsi:type="GroupingExpression">
      <nestedExpression operator="EQUALS" property="type" xsi:type="SimpleExpression">
        <argument>connector-settings</argument>
      </nestedExpression>
      <nestedExpression operator="EQUALS" property="deleted" xsi:type="SimpleExpression">
        <argument>false</argument>
      </nestedExpression>
      <nestedExpression operator="EQUALS" property="currentVersion" xsi:type="SimpleExpression">
        <argument>true</argument>
      </nestedExpression>
    </expression>
  </QueryFilter>
</QueryConfig>
```

Filter the results by checking if the component name contains "solace" (case-insensitive), then pull the full XML to extract `subType`.

---

## Folder Operations

### List Folders

```
POST https://api.boomi.com/api/rest/v1/{accountId}/Folder/query
Content-Type: application/json
Accept: application/json
Body: {"QueryFilter": {"expression": {"operator": "and", "nestedExpression": []}}}
Response: {"result": [{"id": "guid", "name": "My Folder"}], "numberOfResults": N}
```

Always use the folder GUID in `folderId` - path strings are not accepted.

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
