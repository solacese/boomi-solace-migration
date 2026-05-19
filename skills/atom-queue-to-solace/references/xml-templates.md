# XML Templates: Solace PubSub+ Components

All Boomi component XML must be wrapped in the `bns:Component` envelope. The `componentId` is assigned by the API on creation - leave it empty when posting. All namespace declarations are required.

> **Important:** The `subType` value for the Solace connector is discovered dynamically in Phase 1b of the migration skill. Replace `[SOLACE_SUBTYPE]` in all templates with the value extracted from your account. The field IDs inside `GenericConnectionConfig` and `GenericOperationConfig` are based on common Boomi Solace connector conventions - verify them against the sample XML returned in Phase 1b and adjust if needed.

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
                        path="//GenericConnectionConfig/field[@id='clientPassword']"/>
  </bns:encryptedValues>
  <bns:object>
    <GenericConnectionConfig>
      <field id="host"           type="string"   value="smf://hostname:55555"/>
      <field id="vpn"            type="string"   value="default"/>
      <field id="clientUsername" type="string"   value="my-username"/>
      <field id="clientPassword" type="password" value="my-password"/>
    </GenericConnectionConfig>
  </bns:object>
</bns:Component>
```

Key fields:
- `host`: SMF URL - `smf://host:55555` (plain) or `smfs://host:55443` (TLS)
- `vpn`: Solace Message VPN name
- `clientUsername` / `clientPassword`: Solace client credentials
- The `<bns:encryptedValue>` block tells Boomi to encrypt the password on push

---

## Send (Publish) Operation Component

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Name] - Send to [destination]"
               type="connector-action"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
  <bns:encryptedValues/>
  <bns:description></bns:description>
  <bns:object>
    <Operation xmlns="" returnApplicationErrors="false" trackResponse="false">
      <Archiving directory="" enabled="false"/>
      <Configuration>
        <GenericOperationConfig customOperationType="SEND" operationType="EXECUTE"
                                requestProfileType="binary" responseProfileType="none">
          <field id="destination"     type="string" value="[queue-or-topic-name]"/>
          <field id="destinationType" type="string" value="QUEUE"/>
          <field id="deliveryMode"    type="string" value="PERSISTENT"/>
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
- `customOperationType="SEND"`, `operationType="EXECUTE"`
- `requestProfileType="binary"`, `responseProfileType="none"`
- `destinationType`: `QUEUE` (reliable) or `TOPIC` (pub/sub)
- `deliveryMode`: `PERSISTENT` (default), `NON_PERSISTENT`, or `DIRECT`

---

## Listen Operation Component

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Name] - Listen on [destination]"
               type="connector-action"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
  <bns:encryptedValues/>
  <bns:description></bns:description>
  <bns:object>
    <Operation xmlns="" returnApplicationErrors="false" trackResponse="true">
      <Archiving directory="" enabled="false"/>
      <Configuration>
        <GenericOperationConfig customOperationType="LISTEN" operationType="Listen"
                                requestProfileType="none" responseProfileType="binary">
          <field id="destination"     type="string" value="[queue-or-topic-name]"/>
          <field id="destinationType" type="string" value="QUEUE"/>
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
- `operationType="Listen"` - **must be mixed case**, not `"EXECUTE"` (critical)
- `requestProfileType="none"`, `responseProfileType="binary"`
- `destinationType`: `QUEUE` for queue-based listening, `TOPIC` for topic subscription

---

## Get/Receive Operation Component

```xml
<?xml version='1.0' encoding='UTF-8'?>
<bns:Component xmlns:bns="http://api.platform.boomi.com/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               componentId=""
               version="1"
               name="[Name] - Receive from [destination]"
               type="connector-action"
               subType="[SOLACE_SUBTYPE]"
               folderId="[folder-guid]">
  <bns:encryptedValues/>
  <bns:description></bns:description>
  <bns:object>
    <Operation xmlns="" returnApplicationErrors="false" trackResponse="true">
      <Archiving directory="" enabled="false"/>
      <Configuration>
        <GenericOperationConfig customOperationType="GET" operationType="EXECUTE"
                                requestProfileType="none" responseProfileType="binary">
          <field id="destination"     type="string" value="[queue-name]"/>
          <field id="destinationType" type="string" value="QUEUE"/>
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
- `customOperationType="GET"`, `operationType="EXECUTE"`
- `requestProfileType="none"`, `responseProfileType="binary"`
- `destinationType`: typically `QUEUE` for polling

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
      <connectorparameter connectorOperation="Solace PubSub+"
                          connectorProperty="entityId"
                          connectorSource="User Properties"/>
    </propertyvalue>
    <propertyvalue childKey="ATTRIBUTE_ID" valueType="connector">
      <connectorparameter connectorOperation="Solace PubSub+"
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
