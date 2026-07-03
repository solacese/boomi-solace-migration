# XML Templates: Solace Components

All Boomi component XML must be wrapped in the `bns:Component` envelope. The `componentId` is assigned by the API on creation - leave it empty when posting. All namespace declarations are required.

> **Important:** The `subType` value and connection field IDs vary per account/connector installation. Discover them by fetching an existing Solace connection component from the target account. Do NOT assume field IDs — they must be read from a real component.

---

## Namespace Declarations

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Component Name]"
               type="[type]"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
```

---

## Solace Connection Component

> **Field IDs are account-specific.** The example below uses field IDs observed in the Culina2 migration (`host`, `vpn_name`, `username`, `password`). Other accounts may use `vpn`, `clientUsername`, `clientPassword`. Always discover field IDs from an existing component before building XML.

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Name] - Solace Connection"
               type="connector-settings"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
  <bns:encryptedValues>
    <bns:encryptedValue isSet="true"
                        path="//GenericConnectionConfig/field[@id='[PASSWORD_FIELD_ID]']"/>
  </bns:encryptedValues>
  <bns:description></bns:description>
  <bns:object>
    <GenericConnectionConfig>
      <field id="[HOST_FIELD_ID]"     type="string"   value="tcps://mr-xxxx.messaging.solace.cloud:55443"/>
      <field id="[VPN_FIELD_ID]"      type="string"   value="my-vpn"/>
      <field id="[USERNAME_FIELD_ID]" type="string"   value="solace-cloud-client"/>
      <field id="[PASSWORD_FIELD_ID]" type="password" value="my-password"/>
    </GenericConnectionConfig>
  </bns:object>
</bns:Component>
```

Key fields:
- Host: SMF URL — `smf://host:55555` (plain) or `tcps://host:55443` (TLS/Solace Cloud)
- VPN: Solace Message VPN name
- Username / Password: Solace client credentials
- The `<bns:encryptedValue>` block tells Boomi to encrypt the password on save
- **Always use a `connector-profile.yaml` or similar config to map logical field names to actual field IDs**

---

## Send (Publish) Operation Component

> **CORRECTED from production:** Send operations use `operationType="CREATE"` (not `"EXECUTE"` with `customOperationType`). No `customOperationType` attribute. Field IDs are `mode`, `endpointType`, `destination`.

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Name] - Solace Send [destination]"
               type="connector-action"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
  <bns:encryptedValues/>
  <bns:description></bns:description>
  <bns:object>
    <Operation returnApplicationErrors="false" trackResponse="false">
      <Archiving directory="" enabled="false"/>
      <Configuration>
        <GenericOperationConfig operationType="CREATE"
                                requestProfileType="binary" responseProfileType="binary">
          <field id="mode"         type="string" value="PERSISTENT"/>
          <field id="endpointType" type="string" value="queue"/>
          <field id="destination"  type="string" value="[queue-or-topic-name]"/>
          <Options/>
        </GenericOperationConfig>
      </Configuration>
      <Tracking><TrackedFields/></Tracking>
      <Caching/>
    </Operation>
  </bns:object>
</bns:Component>
```

Key fields:
- `operationType="CREATE"` — this is the actual value for Send operations (not `"EXECUTE"`)
- No `customOperationType` attribute
- `requestProfileType="binary"`, `responseProfileType="binary"` (both binary)
- `mode`: `PERSISTENT` (default), `NON_PERSISTENT`, or `DIRECT`
- `endpointType`: `queue` or `topic` (lowercase)
- `destination`: queue or topic name

---

## Listen Operation Component

> **CORRECTED from production:** Listen operations use `operationType="Listen"` (mixed case). Fields include `mode`, `destination`, `batchSize`, `receiveTimeout`, `maxConcurrentExecutions`, `selector`.

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Name] - Solace Listen [destination]"
               type="connector-action"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
  <bns:encryptedValues/>
  <bns:description></bns:description>
  <bns:object>
    <Operation returnApplicationErrors="false" trackResponse="true">
      <Archiving directory="" enabled="false"/>
      <Configuration>
        <GenericOperationConfig operationType="Listen"
                                requestProfileType="binary" responseProfileType="binary">
          <field id="mode"                     type="string"  value="PERSISTENT_TRANSACTED"/>
          <field id="destination"              type="string"  value="[queue-name]"/>
          <field id="batchSize"                type="integer" value="500"/>
          <field id="receiveTimeout"           type="integer" value="10000"/>
          <field id="maxConcurrentExecutions"  type="integer" value="3"/>
          <field id="selector"                 type="string"  value=""/>
          <Options/>
        </GenericOperationConfig>
      </Configuration>
      <Tracking><TrackedFields/></Tracking>
      <Caching/>
    </Operation>
  </bns:object>
</bns:Component>
```

Key fields:
- `operationType="Listen"` — **must be mixed case** (critical, not `"EXECUTE"`)
- No `customOperationType` attribute
- `requestProfileType="binary"`, `responseProfileType="binary"` (both binary)
- `mode`: `PERSISTENT_TRANSACTED` for guaranteed delivery with transaction support
- `batchSize`: messages per batch (default 500)
- `receiveTimeout`: milliseconds to wait for messages (default 10000)
- `maxConcurrentExecutions`: parallel listener threads (default 3)
- `selector`: JMS selector expression (empty string = no filtering)

---

## Get/Receive Operation Component

> **CORRECTED from production:** Get operations use `operationType="GET"`. No `customOperationType` attribute.

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Name] - Solace Receive [destination]"
               type="connector-action"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
  <bns:encryptedValues/>
  <bns:description></bns:description>
  <bns:object>
    <Operation returnApplicationErrors="false" trackResponse="true">
      <Archiving directory="" enabled="false"/>
      <Configuration>
        <GenericOperationConfig operationType="GET"
                                requestProfileType="binary" responseProfileType="binary">
          <field id="mode"        type="string" value="PERSISTENT_TRANSACTED"/>
          <field id="destination" type="string" value="[queue-name]"/>
          <Options/>
        </GenericOperationConfig>
      </Configuration>
      <Tracking><TrackedFields/></Tracking>
      <Caching/>
    </Operation>
  </bns:object>
</bns:Component>
```

Key fields:
- `operationType="GET"` (not `"EXECUTE"`)
- No `customOperationType` attribute
- `requestProfileType="binary"`, `responseProfileType="binary"` (both binary)
- `mode`: `PERSISTENT_TRANSACTED` for guaranteed delivery

---

## Process Connector Step Transformation

### Before (Atom Queue Send -> Solace Send)

```xml
<!-- BEFORE -->
<shape shapetype="connectoraction" userlabel="Send to Sample Queue" ...>
  <connectoraction actionType="Send"
                   connectorType="atomqueue"
                   connectionId="OLD-CONN-GUID"
                   operationId="OLD-OP-GUID">
    <parameters/>
    <dynamicProperties/>
  </connectoraction>
</shape>

<!-- AFTER -->
<shape shapetype="connectoraction" userlabel="Send to Solace" ...>
  <connectoraction actionType="Send"
                   connectorType="[SOLACE_SUBTYPE]"
                   connectionId="NEW-SOLACE-CONN-GUID"
                   operationId="NEW-SOLACE-SEND-OP-GUID">
    <parameters/>
    <dynamicProperties>
      <propertyvalue childKey="entityId" key="userProperties"
                     name="User Properties" valueType="track">
        <trackparameter defaultValue=""
                        propertyId="dynamicdocument.ENTITY_ID"
                        propertyName="Dynamic Document Property - ENTITY_ID"/>
      </propertyvalue>
    </dynamicProperties>
  </connectoraction>
</shape>
```

### Before (Atom Queue Listen -> Solace Listen)

```xml
<!-- BEFORE -->
<shape shapetype="start" userlabel="Listen on Sample Queue" ...>
  <connectoraction actionType="Listen"
                   connectorType="atomqueue"
                   connectionId="OLD-CONN-GUID"
                   operationId="OLD-OP-GUID">
    <parameters/>
    <dynamicProperties/>
  </connectoraction>
</shape>

<!-- AFTER -->
<shape shapetype="start" userlabel="Listen on Solace" ...>
  <connectoraction actionType="Listen"
                   connectorType="[SOLACE_SUBTYPE]"
                   connectionId="NEW-SOLACE-CONN-GUID"
                   operationId="NEW-SOLACE-LISTEN-OP-GUID">
    <parameters/>
    <dynamicProperties/>
  </connectoraction>
</shape>
```

### Before (Atom Queue Get -> Solace Get/Receive)

```xml
<!-- BEFORE -->
<shape shapetype="connectoraction" userlabel="Get from Sample Queue" ...>
  <connectoraction actionType="Get"
                   connectorType="atomqueue"
                   connectionId="OLD-CONN-GUID"
                   operationId="OLD-OP-GUID">
    <parameters/>
    <dynamicProperties/>
  </connectoraction>
</shape>

<!-- AFTER -->
<shape shapetype="connectoraction" userlabel="Receive from Solace" ...>
  <connectoraction actionType="Get"
                   connectorType="[SOLACE_SUBTYPE]"
                   connectionId="NEW-SOLACE-CONN-GUID"
                   operationId="NEW-SOLACE-GET-OP-GUID">
    <parameters/>
    <dynamicProperties/>
  </connectoraction>
</shape>
```

---

## Set Properties Step (Consumer DDP Extraction)

Add this step immediately after the Solace connector in consumer processes to restore DDPs from User Properties:

```xml
<shape shapetype="documentproperties" userlabel="Extract User Properties" ...>
  <setproperties>
    <propertyvalue childKey="ENTITY_ID" valueType="connector">
      <connectorparameter connectorOperation="Solace"
                          connectorProperty="entityId"
                          connectorSource="User Properties"/>
    </propertyvalue>
    <propertyvalue childKey="ATTRIBUTE_ID" valueType="connector">
      <connectorparameter connectorOperation="Solace"
                          connectorProperty="attributeId"
                          connectorSource="User Properties"/>
    </propertyvalue>
  </setproperties>
</shape>
```

**Note:** The `connectorOperation` and `connectorSource` values must match what Boomi uses for the installed Solace connector version. Verify in the Boomi UI when building the Set Properties step - the dropdowns will show the exact strings required.

---

## Atom Queue Detection Patterns

The migration tool detects queue operations in process XML by:

1. `<connectoraction>` where `connectorType` is `'atomqueue'` or `'queue'`
2. `actionType="Send"` -> producer (connector step only)
3. `actionType="Listen"` -> consumer (start shape only)
4. `actionType="Get"` -> consumer (start or connector step)
