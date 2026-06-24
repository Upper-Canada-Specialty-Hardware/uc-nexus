# shared foundations (read before either workflow doc)

both the PO and receiving workflows are built on the same handful of mechanisms. they are documented
once here so the workflow docs can refer to them instead of re-explaining. everything below is
as-built behaviour of the legacy code.

contents:
- the two-database model and the connection strings
- company / environment switching (GlobalVars)
- the cross-database LINQ trick (DatabaseSwitcher + OverrideMappingSource + EnumTableFamily)
- the eConnect posting mechanism (serialize -> file -> CreateTransactionEntity)
- document-number reservation and rollback (GetNextDocNumbers)
- the verify-then-rollback safety pattern
- the audit-stamp convention
- the manual primary-key (MAX(ID)+1) convention
- LINQ-to-SQL data-context lifecycle

-------------------------------------------------------------------------------

the two-database model and the connection strings

defined in `GlobalVariables.cs` -> `public static class GlobalVars`. all connection strings are
built from `Properties.Settings.Default` values (server + initial catalog) using Windows integrated
security. there are three live connection strings:

| GlobalVars property | points at | built from |
|---|---|---|
| `UcshConnectionString` | the PM application db (`PMUCSH` / `PMUBC` / `TESTPMUCSH`) | `Server` + `CurrentPmDatabaseName` |
| `GpConnectionString` | the GP company db (`UCSH` / `UBC` / `TUCSH`) | `Server` + `CurrentGpDatabaseName` |
| `UcUsersConnectionString` | the `UCUsers` db (login/roles) | `Server` + `UCUsersInitCatalog` |

connection string shape (integrated security, no credentials in code):

```
Data Source=<server>;Initial Catalog=<db>;Integrated Security=SSPI;
```

note on a naming quirk: `UcshConnectionString` is named after the GP company ("UCSH") but actually
targets the PM application database. that naming is a historical wart - do not read "Ucsh" as "the GP
database." the GP database connection is `GpConnectionString`.

separate hardcoded strings exist only inside the eConnect document-number code, which always points at
`UCSHSQL2\MSSQL2014` explicitly (see the doc-number section below).

-------------------------------------------------------------------------------

company / environment switching

`GlobalVars` exposes setters that, when you change the database NAME, automatically rebuild the
matching connection string. switching company or environment is just calling one of:

| method | sets PM db | sets GP db |
|---|---|---|
| `SwitchToUcsh()` | `PMUCSH` | `UCSH` |
| `SwitchToBc()` | `PMUBC` | `UBC` |
| `SwitchToTest()` | `TESTPMUCSH` | `TUCSH` |
| `SwitchToLive(user)` | by `user.CompanyId`: 1 -> `PMUCSH`/`UCSH`, 2 -> `PMUBC`/`UBC` | same |

`CurrentPmDatabaseName` and `CurrentGpDatabaseName` are the live values read throughout the data layer
(and injected into the cross-database table-name rewriting described next). the user's `CompanyId`
(1 = UCSH/Markham, 2 = UBC/Vancouver) decides which company a session runs against.

-------------------------------------------------------------------------------

the cross-database LINQ trick (this is the clever bit)

the workflows constantly JOIN a UC-owned table in the PM database to a GP table in the GP database -
for example `WHRECLINE101` (PM) joined to `POP10500` (GP) - inside a SINGLE LINQ-to-SQL query. SQL
Server allows three-part `[database].[dbo].[table]` names, so the app rewrites every entity's table
name at runtime to be fully database-qualified, then runs one query across both.

the moving parts:

1. `DataClasses/UtilityClasses/EnumTableFamily.cs` - an enum with two values: `GP`, `UCSH`.

2. every entity class declares which family it belongs to with a static field, e.g.
   `public static Enum TableFamily = uc.EnumTableFamily.GP;` (on `Pop10110`) or
   `... = uc.EnumTableFamily.UCSH;` (on `ReceivingLine`).

3. `DataClasses/UtilityMethods/DatabaseSwitcher.cs` -> `Convert(ref DataContext)`:
   - `LoadAllEntities` walks a hardcoded list of every mapped entity type
     (`RelationalObjects`, also in that file) and calls `dtCtx.GetTable(type)` so LINQ loads the
     metadata for all of them.
   - `SwapMappingSources` wraps the context's real mapping source in a
     `uc.OverrideMappingSource` (defined in `DataClasses/UtilityClasses/OverDataContext.cs`).
   - `ChangeQualifiedTableNames` loops every mapped table, reads its `TableFamily` static field by
     reflection, and rewrites the table name to:
     - `[<CurrentGpDatabaseName>].[dbo].<table>` if family is GP
     - `[<CurrentPmDatabaseName>].[dbo].<table>` if family is UCSH

4. the standard call pattern you will see at the top of nearly every data method:

   ```csharp
   lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
   lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString,
                                             um.DatabaseSwitcher.Convert(ref tempdtCtx));
   ```

   the connection itself is opened against the PM database, but because every table name is now
   three-part-qualified, the same query reaches into the GP database too. (this is why a query can
   `join` `POP10110` and `WHRECLINE101` freely.)

practical consequence for anyone reading the queries: a LINQ `GetTable<gp.Pop10110>()` resolves to
`[UCSH].[dbo].[POP10110]` (or `[TUCSH]...` in test), and `GetTable<dc.ReceivingLine>()` resolves to
`[PMUCSH].[dbo].[WHRECLINE101]`. the entity class names (`Pop10110`) and the SQL table names
(`POP10110`) are decoupled - the mapping is in the `[Table(Name=...)]` attribute.

if an entity is missing its `TableFamily` static field or its LINQ attributes, `DatabaseSwitcher`
throws with a message naming the offending class. a few composite read-models are deliberately NOT in
`RelationalObjects` because they are built from raw query projections rather than mapped tables
(`PurchaseOrderLineItem`, `CombinedProject`).

-------------------------------------------------------------------------------

the eConnect posting mechanism

eConnect is the GP SDK for pushing transactions into GP through validated stored procedures. UC
Connects uses it in exactly one live place (posting PO receipts) and one dead place (the PO-create
stub). the mechanism is identical in both:

1. reserve a document number from GP (see next section).
2. build strongly-typed eConnect objects from the SDK serialization namespace - for a receipt that is
   `taPopRcptHdrInsert` (header) + an array of `taPopRcptLineInsert_ItemsTaPopRcptLineInsert` (lines),
   wrapped in `POPReceivingsType`, wrapped in `eConnectType`.
3. serialize that `eConnectType` object graph to an xml FILE on disk (always literally `PoRecLines.xml`
   in the working directory) with `XmlSerializer` + `XmlTextWriter`.
4. reload the file into an `XmlDocument`, take `.OuterXml`.
5. post it: `new eConnectMethods().CreateTransactionEntity(gpConnectionString, xmlString)`.
6. verify it actually landed (see verify pattern), else roll back the reserved number.

the round-trip through a physical `PoRecLines.xml` file (serialize to disk, immediately read back) is
not necessary technically - it is just how the original author did it. it means the app needs write
access to its working directory and is not safe for two concurrent posts in the same directory.

`eConnectMethods` is disposed in a `finally`. the whole thing runs inside `using (eConnectMethods ...)`.

-------------------------------------------------------------------------------

document-number reservation and rollback (GetNextDocNumbers)

`GetNextDocNumbers` is an eConnect SDK class (NOT in this repo - it comes from
`Microsoft.Dynamics.GP.eConnect`). it hands out the next document number for a given document type and
increments GP's internal "next number" counter so two clients don't collide.

| call | returns | used by |
|---|---|---|
| `GetNextPONumber(IncrementDecrement.Increment, conn)` | next PO number (e.g. `PO092161`) | PO-create stub |
| `GetNextPOPReceiptNumber(IncrementDecrement.Increment, conn)` | next receipt number (e.g. `RCT062523`) | receiving (live) |

the connection string for these calls is hardcoded and built from the CURRENT GP database name:

```
data source=UCSHSQL2\MSSQL2014;initial catalog=<CurrentGpDatabaseName>;integrated security=SSPI;persist security info=False;packet size=4096
```

rollback = call the SAME method with `IncrementDecrement.Decrement`, which gives the reserved number
back to GP's counter. this is done if the eConnect post fails or the verify step fails, so the
sequence doesn't leave a gap. (the PO-create stub names its rollback `RollBackRecNumGp`, a copy-paste
leftover - it actually rolls back a PO number.)

-------------------------------------------------------------------------------

the verify-then-rollback safety pattern

eConnect can report success on the call but the document may still not materialise (validation,
posting interceptors, etc). so after every post the code independently re-queries GP to confirm the
document exists:

- receipts: `VerifyReceiptCreation(receiptNum)` queries `POP10500` for any row with that `POPRCTNM`.
- the PO stub: `VerifyPoCreation(poNum)` queries `POP10110` for that `PONUMBER`.

if the verify query returns zero rows, the method shows "GP did not actually create this ..." , the
reserved document number is rolled back (decrement), and the method returns `false`. only a verified
post returns `true`.

this is the gate the caller checks before writing anything to the PM database - so the PM database is
only updated AFTER GP has confirmed the receipt. (the reverse failure - GP succeeds but the PM insert
fails - is handled separately and imperfectly; see the receiving doc.)

-------------------------------------------------------------------------------

the audit-stamp convention

UC-owned tables carry a consistent set of audit columns, stamped in code (not by db defaults/triggers):

- create-time: `DateCreated` (date), `TimeCreated` (time), `CreatingUser`, `CreatingMachine`
- edit-time: `DateEdited` (date), `TimeEdited` (time), `EditingUser`
- receiving/shipping records use `DateReceived`/`TimeReceived` + `UpdatingUser`/`UpdatingMachine`

the values come from:
- user: usually `Environment.UserName`; the receiving insert uses the fuller
  `System.Security.Principal.WindowsIdentity.GetCurrent().Name` instead.
- machine: `Environment.MachineName`.
- date: `DateTime.Today`. time: `DateTime.Now` (stored into a SQL `time` column - note it carries a
  full DateTime into a time column, so only the time-of-day part is meaningful).

time columns are mapped with `[Column(DbType = "Time", CanBeNull = true)]`.

-------------------------------------------------------------------------------

the manual primary-key convention (MAX(ID)+1)

the UC comment + deficiency tables do NOT use identity columns. ids are assigned in app code with a
raw ADO.NET `SELECT MAX(ID) FROM [<PM db>].[dbo].[<table>]`, then `+1` (or `1` if the table is empty /
DBNull). examples: `PoUcshHeaderComments.GetNextHeaderCommentId`,
`PoUcshLineComments.GetNextLineCommentId`, `WhDeficiencies.GetNextWhDeficiencyItemId`.

when inserting several new rows at once, only the FIRST new row hits the database for MAX(ID); the rest
are numbered by incrementing in memory (`_newId += 1`). this is not concurrency-safe - two users adding
comments to different POs at the same time can compute the same next id. it is a known characteristic
of the legacy code, not a guarantee.

-------------------------------------------------------------------------------

LINQ-to-SQL data-context lifecycle

two patterns appear:

1. raw `System.Data.Linq.DataContext` + `DatabaseSwitcher.Convert` for cross-database READ queries
   (most `Get...` methods). these are disposed in a `finally`.

2. a small purpose-built `DataContext` subclass per writable table, used inside `using (...)` for
   writes - e.g. `ReceivingLineDataContext` (exposes `Table<ReceivingLine> ReceivingLine`),
   `PoUcshHeaderCommentDataContext`, `WhDeficiencyDataContext`, `RecLineTrackerDataContext`. writes go
   through `InsertOnSubmit` / `DeleteOnSubmit` / `Attach`+`Refresh(KeepCurrentValues)` then
   `SubmitChanges`.

errors are generally swallowed at the data layer with `MessageBox.Show(ex.ToString())` and the method
returning a default/empty collection or a bool. there is essentially no logging - the UI message box IS
the error channel.
