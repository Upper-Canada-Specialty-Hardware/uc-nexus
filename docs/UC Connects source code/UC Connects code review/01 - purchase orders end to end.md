# purchase orders, end to end

assumes you've read `00 - shared foundations.md`. this doc is exhaustive at the field/method level.

contents:
- where POs come from (GP, not this app)
- the PO tab in MainWindow - loading, the table-valued functions, filtering
- PurchaseOrderLineItem - the PO line read model, field by field
- PurchaseOrderHeader - the PO header read model and its three loaders
- the GP source tables behind the PO read models
- the UC comment overlay (header + line comments) and the do-not-ship-before date
- the comment editing window (PoAddNewUcshComment) and its edit-permission rule
- PO confirmations (PROCPOCONF101)
- PO deficiencies (cross-reference)
- the dormant PO-creation eConnect stub - exactly what it does and why it isn't a real workflow
- excel export

-------------------------------------------------------------------------------

where POs come from

purchase orders are entered in Microsoft Dynamics GP's purchasing module, outside this app. UC Connects
reads the open PO work tables (`POP10100` header, `POP10110` lines) and the receipt table (`POP10500`)
to show the state of every PO line, and overlays its own comments / dates / confirmations / deficiencies.

there is no live "create PO" action in UC Connects. the only writes UC Connects makes against PO data
are: (a) its own overlay tables in the PM database, and (b) PO RECEIPTS via eConnect (documented in
`02 - hardware inventory receiving end to end.md`). the dormant create-stub is covered at the end of
this doc.

-------------------------------------------------------------------------------

the PO tab in MainWindow

file: `MainWindow.xaml.cs`. the PO list lives in a `DataGrid` named `PurchaseOrders_DG_HardwarePos`,
backed by `ObservableCollection<dc.PurchaseOrderLineItem> _poCol`.

loading the list - `BTN_PO_PurchaseOrders_GetAllPoLines_Click` (around line 1321):

- disables the window, then loads PO lines via a SQL table-valued function (TVF), NOT via the LINQ
  read models. which TVF depends on two switches:
  - the `ChkBox_PO_PurchaseOrders_MaxOneYear` checkbox (limit to one year of POs or all history)
  - the current GP company (`GlobalVars.CurrentGpDatabaseName` == "UCSH" vs "UBC")
- the four `DataContext` wrappers that call the TVFs are defined at the bottom of
  `PurchaseOrderLineItems.cs`:

| wrapper class | TVF it calls | scope |
|---|---|---|
| `PoListFunctionV1` | `[UCSH].[dbo].[ConnectsPoLineAllJobs_Oct_30_2019]` | UCSH, all history |
| `PoListFunctionLimitYear` | `[UCSH].[dbo].[ConnectsPoLineAllJobs_Aug_16_2020_1Year]` | UCSH, last 1 year |
| `PoListFunctionV1UBC` | `[UBC].[dbo].[ConnectsPoLineAllJobs_Oct_30_2019]` | UBC, all history |
| `PoListFunctionLimitYearUBC` | `[UBC].[dbo].[ConnectsPoLineAllJobs_Aug_16_2020_1Year]` | UBC, last 1 year |
| `PoListFunctionByJob` / `...ByJobUBC` | `...ConnectsPoLineByJob_Oct_17_2019` | one job (param) |

  each wrapper is a `DataContext` subclass with a `[Function(...)]`-decorated method
  (`ConnectsPoLineTestAllJobs`) that LINQ maps to the TVF via `CreateMethodCallQuery<PurchaseOrderLineItem>`.
  the TVF returns rows shaped exactly like `PurchaseOrderLineItem` (the `[Column]` names on that class
  match the TVF's output columns). so the heavy join logic lives in SQL, in the database, not in C#.
- result is wrapped into `_poCol` and bound to the grid, with a live filter
  (`PoPurchaseOrderFilter`).

IMPORTANT: the C# methods `GetAllPurchaseOrdersWithReceipts()` and
`GetAllPurchaseOrderLinesByProject(jobNumber)` in `PurchaseOrderLineItems.cs` contain the FULL LINQ
join (POP10110 + POP10100 + POP10150 + JC00102 + PM00200 + POP10550 + POP10500 + SOP60100 + sales
union + ShippingLine) that the TVFs replicate in SQL. the LINQ versions are NOT what the PO tab calls
at runtime (`GetAllPurchaseOrdersWithReceipts` is only referenced from commented-out lines 342-343 in
MainWindow). they are the authoritative readable description of HOW a PO line is assembled, and the
`ProjectManagementMain` window does use `GetAllPurchaseOrderLinesByProject`. treat the LINQ as the
spec; treat the TVF as the optimized production path.

what the join produces per PO line (from `GetAllPurchaseOrdersWithReceipts`):
- base: one row per `POP10110` line, excluding lines where `LOCNCODE == "SHOWROOM"`.
- header fields from `POP10100`: `BuyerId`, and `AddressThree` reused as `ChangeId`.
- header comment text from `POP10150` (`CmmtText`, newlines stripped).
- job name from `JC00102`.
- vendor name from `PM00200`.
- line comment text from `POP10550`.
- quantity RECEIVED = SUM of `POP10500.QTYSHPPD` grouped by PO+line (the code calls the property
  `QuantityShipped` but comments it "this is actually quantity received").
- quantity MATCHED = SUM of `POP10500.QTYMATCH`.
- quantity ACTUALLY SHIPPED = SUM of UC `ShippingLine.QuantityShipped` (the UC shipment table).
- sales order number via `SOP60100`, and customer name via the union of `SOP10100` + `SOP30200`.
- two booleans: `UcHeaderHasComments` / `UcLineHasComments` - whether any UC comment rows exist for the
  PO / PO+line (used to flag the row so the user knows there's a comment to open).

filtering - `PoPurchaseOrderFilter` (line ~1522): an in-memory `CollectionView` filter over eight text
boxes (po number, job number, job name, change order, buyer id, sop number, item description, vendor
name). a checkbox `ChkBox_PO_PurchaseOrders_AndOr` toggles between OR (any field matches) and AND (all
fields match). matching is case-insensitive substring (`IndexOf(..., OrdinalIgnoreCase) >= 0`). each
filter textbox change triggers a debounced refresh via `DeferredAction` (~1.1s). `ClearFilters` blanks
all boxes and reapplies the filter.

other PO-tab interactions:
- clicking the job-folder column (DisplayIndex 1) opens the job's folder in explorer
  (`BTN_PO_PurchaseOrders_LaunchJobFolder`) using `PurchaseOrderLineItem.JobFolder`.
- clicking the header-comment column (DisplayIndex 25) opens the comment window in HEADER mode.
- clicking the line-comment column (DisplayIndex 26) opens the comment window in LINE mode.
  (both handled in `PurchaseOrders_DG_HardwarePos_PreviewMouseLeftButtonDown`, line ~1553.)

-------------------------------------------------------------------------------

PurchaseOrderLineItem - the PO line read model

file: `DataClasses/PurchaseOrderLineItems.cs`. class `PurchaseOrderLineItem : INotifyPropertyChanged`,
decorated `[Table]` (no name) so LINQ maps it to the TVF result set. each property carries an `[Order]`
attribute (a positional index used to line up with the TVF columns) and most carry a `[Column]` mapping.

field reference (property -> mapped column -> type -> meaning):

| property | column (`Name`) | type | meaning |
|---|---|---|---|
| `PoNumber` | `PONUMBER` | char(17) | GP PO number (e.g. `PO092160`) |
| `Order` | `ORD` | int | GP line sequence within the PO (16384, 32768, ... step 16384) |
| `JobFolder` | `JobFolder` | char | resolved windows path to the job's folder (for explorer launch) |
| `JobNumber` | `JOBNUMBR` | char(17) | GP job-cost job number |
| `JobName` | `WS_Job_Name` | char(31) | project/job name (from JC00102) |
| `SopNumber` | `SOPNUMBE` | char | linked sales order number (via SOP60100) |
| `BuyerId` | `BUYERID` | char(15) | GP buyer id (from POP10100) |
| `ChangeId` | `ChangeId` | char | change-order id - GP `POP10100.ADDRESS3` reused |
| `VendorId` | `VENDORID` | char(15) | GP vendor id |
| `VendorName` | `VENDNAME` | char(65) | vendor name (from PM00200) |
| `LineNumber` | `LineNumber` | smallint | GP `POP10110.LineNumber` (display order) |
| `Polnesta` | `POLNESTA` | smallint | line status code; SETTER also sets `LineStatus` text (see status map) |
| `LineStatus` | (derived) | string | "New"/"Released"/"Change Order"/"Received"/"Closed"/"Cancelled" |
| `ItemNumber` | `ITEMNMBR` | char(31) | GP item number |
| `ItemDescription` | `ITEMDESC` | char(101) | GP item description |
| `NonInventory` | (not mapped) | bool | non-inventory flag; only used by the eConnect procedures |
| `QuantityOrdered` | `QTYORDER` | numeric(19,5)->int | qty ordered on the line |
| `QuantityReceived` | `QTYREC` | int | qty received (sum of POP10500.QTYSHPPD) |
| `QuantityMatched` | (not in TVF) | int | qty matched to invoice (sum of POP10500.QTYMATCH) |
| `QuantityInvoiced` | `QTYINVCD` | numeric(19,5)->int | qty invoiced |
| `BackOrder` | `BACKORDER` | int | derived in ctor = `QuantityOrdered - QuantityReceived` |
| `QuantityShipped` | `QTYSHIP` | int | qty actually shipped out of UC's warehouse (UC ShippingLine) |
| `PoCreationDate` | `DOCDATE` | datetime | PO document date |
| `FirstReceiveDate` | `DateReceived` | datetime | first receive date |
| `LastReceiveDate` | `LSTRCPTDT` | datetime | last receive date (GP; only set after the receipt batch posts) |
| `LocationCode` | `LOCNCODE` | char(11) | GP location code (the site, e.g. MARKHAM/SHOWROOM) |
| `CostCode` | `COSTCODE` | char(27) | job cost code |
| `RequiredDate` | `REQDATE` | datetime | required date |
| `PromisedShipDate` | `PRMSHPDTE` | datetime | promised ship date |
| `LineCommentText` | `LINECMMTTEXT` | string | GP line comment (POP10550) |
| `HeaderCommentText` | `HEADERCMMTTEXT` | string | GP header comment (POP10150) |
| `CustomerName` | (not mapped) | string | customer name (via sales-order union) |
| `UcLineComment` | `UcLineCommentsConcat` | string | UC line comments concatenated; setter sets `UcLineHasComments` |
| `UcHeaderComment` | `UcHeaderCommentsConcat` | string | UC header comments concatenated; setter sets `UcHeaderHasComments` |
| `UcHeaderHasComments` | (not mapped) | bool | row flag: UC header comments exist |
| `UcLineHasComments` | (not mapped) | bool | row flag: UC line comments exist |
| `UcHeaderCommentCol` | (not mapped) | `ObservableCollection<PoUcshHeaderComment>` | lazy-loaded list of UC header comments |
| `UcLineCommentCol` | (not mapped) | `ObservableCollection<PoUcshLineComment>` | lazy-loaded list of UC line comments |

behaviour worth knowing:
- the two `...CommentCol` setters wire `CollectionChanged` + per-item `PropertyChanged` handlers so
  that editing a comment re-concatenates the `UcHeaderComment` / `UcLineComment` display string
  (newline-joined). that's how the grid's comment column updates live.
- `LastReceiveDate` is GP's `LSTRCPTDT`, which the code comments warn is only populated once GP's
  receipt batch is POSTED - a receipt created but left un-batched for days shows no date until then.
- there is a commented-out `FillUcCommentCollections` that used to bulk-load comments; the live design
  lazy-loads comments only when the user clicks the comment cell (see comment window section).
- the trailing helper classes (`OrderAttribute`, `CustTypeAtt`, `ValEnum`) are marked `//NOT USED`
  except `ValEnum`, whose values are the `[Order]` indices.

-------------------------------------------------------------------------------

PurchaseOrderHeader - the PO header read model

file: `DataClasses/PurchaseOrderHeaders.cs`. class `PurchaseOrderHeader`, mapped `[Table(Name="[POP10100]")]`,
`TableFamily = GP`. it READS the GP PO header. fields:

| property | column | type | meaning |
|---|---|---|---|
| `PoNumber` | `PONUMBER` | string | PO number |
| `PoStatus` | `POSTATUS` | short | GP PO header status |
| `JobNumber` | (joined) | string | job number (from POP10110 line) |
| `JobName` | (joined) | string | job name (from JC00102) |
| `LocationCode` | (joined) | string | location, taken from a PO line |
| `BuyerId` | `BUYERID` | string | buyer id |
| `DoNotShipBeforeDate` | (joined) | DateTime? | UC's do-not-ship-before date (from POUCSHHEADERCOMMENT101) |

three loader methods (all use the cross-database `DatabaseSwitcher` pattern):

1. `GetPoHeaders()` - all POs. joins `POP10100` -> `POP10110` (for job number) -> `JC00102` (job name)
   -> `POUCSHHEADERCOMMENT101` (for `DoNotShipBeforeDate`), where job number is non-blank, ordered by
   PO number descending. this is the list the receiving "select PO" dialog uses.

2. `GetPoHeadersUnusual()` - the "unusual" subset: PO lines with a BLANK job number, location not
   SHOWROOM, and no SOP link (`SOP60100.SopNumber == null`). i.e. POs that aren't tied to a job, a
   showroom, or a sales order. used by the "unusual" receipt type.

3. `GetPoHeaderSingle(poNumber)` - intended to return one header, BUT note the projection's
   `.Select(...).FirstOrDefault()` line is commented out, so this method ALWAYS RETURNS `null` today.
   callers that use it (e.g. pre-shipment document generation, deficiency reporting from the receiving
   tab) therefore get null back. this is a live bug/dead-spot in the legacy code - flag it; don't
   assume `GetPoHeaderSingle` works.

(there's also a commented-out `GetPoHeadersWithSop`.)

-------------------------------------------------------------------------------

the GP source tables behind the PO read models

field references for the GP entity classes (under `DataClasses/GpObjects/`):

POP10100 (`Pop10100`) - PO header:

| property | column | meaning |
|---|---|---|
| `PoNumber` | `PONUMBER` | PO number |
| `PoStatus` | `POSTATUS` | header status |
| `AddressThree` | `ADDRESS3` | reused by UC as the change-order id |
| `BuyerId` | `BUYERID` | buyer id |
| `DocDate` | `DOCDATE` | document date |

POP10110 (`Pop10110`) - PO line:

| property | column | meaning |
|---|---|---|
| `PoNumber` | `PONUMBER` | PO number |
| `Order` | `ORD` | line sequence (16384 steps) |
| `JobNumber` | `JOBNUMBR` | job number |
| `VendorId` | `VENDORID` | vendor id |
| `LineNumber` | `LineNumber` | display line number |
| `Polnesta` | `POLNESTA` | line status (1..6) |
| `ItemNumber` | `ITEMNMBR` | item number |
| `ItemDescription` | `ITEMDESC` | item description |
| `UnitCost` | `UNITCOST` | unit cost |
| `NonInventory` | `NONINVEN` | non-inventory flag (0/1) |
| `QtyOrder` | `QTYORDER` | quantity ordered |
| `ReleaseDate` | `Released_Date` | release date |
| `FirstReceiveDate` | `FSTRCPTDT` | first receipt date |
| `LastReceiveDate` | `LSTRCPTDT` | last receipt date |
| `LocationCode` | `LOCNCODE` | site/location |
| `CostCode` | `COSTCODE` | cost code |
| `RequiredDate` | `REQDATE` | required date |
| `PromisedShipDate` | `PRMSHPDTE` | promised ship date |
| `PoLineCreationDate` | `DEX_ROW_TS` | GP row timestamp (used as line creation date) |

POP10500 (`Pop10500`) - PO receipt line (this is where receiving writes; it's also how "qty received"
is computed). composite PK `PONUMBER`+`POLNENUM`+`POPRCTNM`+`RCPTLNNM`:

| property | column | meaning |
|---|---|---|
| `PoNumber` | `PONUMBER` | PO number |
| `Polnenum` | `POLNENUM` | the PO line this receipt is against (= POP10110.ORD) |
| `PopRctNum` | `POPRCTNM` | receipt number (e.g. RCT######) |
| `RcptLnNm` | `RCPTLNNM` | receipt line number (16384 steps) |
| `QuantityShipped` | `QTYSHPPD` | qty received on this receipt line |
| `QuantityMatched` | `QTYMATCH` | qty matched to invoice |
| `QuantityInvoiced` | `QTYINVCD` | qty invoiced |

POP10150 (`Pop10150`) - PO header comment: `POPNUMBE`, `COMMNTID`, `COMMENT_1..4`, `CMMTTEXT`.
POP10550 (`Pop10550`) - PO line comment: `POPNUMBE`, `ORD`, `CMMTTEXT`.
POP30300 (`Pop30300`) - posted receipt header history: `POPRCTNM`, `GLPOSTDT`.
SOP60100 (`Sop60100`) - sales-order ⇄ PO link: `SOPNUMBE`, `SOPTYPE`, `LNITMSEQ`, `CMPNTSEQ`,
`PONUMBER`, `ORD`, `LOCNCODE` (plus a non-stored `BuyerId` derived from POP10100).

-------------------------------------------------------------------------------

the UC comment overlay + do-not-ship-before date

GP already has PO comments (POP10150/POP10550), but UC Connects keeps its OWN separate comments in the
PM database so warehouse/PM staff can annotate POs without touching GP. two tables, parallel design.

POUCSHHEADERCOMMENT101 (`PoUcshHeaderComment`, file `PoUcshHeaderComments.cs`) - per-PO header comment:

| property | column | meaning |
|---|---|---|
| `Id` | `ID` (PK) | manual id (MAX(ID)+1) |
| `PoNumber` | `PONUMBER` | PO number |
| `JobNumber` | `JobNumber` | job number |
| `CommentText` | `CommentText` | the comment; setter flags `IsModified` + stamps edit audit if existing |
| `DoNotShipBeforeDate` | `DoNotShipBeforeDate` | the do-not-ship-before date for the PO |
| `DateEdited`/`TimeEdited`/`EditingUser` | same | edit audit |
| `DateCreated`/`TimeCreated`/`CreatingUser`/`CreatingMachine` | same | create audit |
| `IsModified` | (not mapped) | dirty flag |

POUCSHLINECOMMENT101 (`PoUcshLineComment`, file `PoUcshLineComments.cs`) - per-PO-LINE comment. same
shape PLUS an `Order` column (`ORD`) so it ties to a specific PO line; it has NO do-not-ship date:

| property | column | meaning |
|---|---|---|
| `Id` | `ID` (PK) | manual id |
| `PoNumber` | `PONUMBER` | PO number |
| `Order` | `ORD` | PO line sequence |
| `JobNumber` | `JobNumber` | job number |
| `CommentText` | `CommentText` | the comment |
| audit columns | same as header | create/edit audit |

the do-not-ship-before date is significant: it rides on the HEADER comment row, is surfaced in the PO
header read model, and drives a UI colour cue in the receiving "select PO" dialog -
`DoNotShipConverter` (in `WhRecSelectPo.xaml.cs`) paints the row TOMATO red when the do-not-ship date
is in the future, grey otherwise. so a warehouse user trying to receive against a PO sees red if it's
flagged not-to-ship-yet.

both comment classes:
- implement `IPoUcshComment` + `INotifyPropertyChanged`.
- declare `TableFamily = UCSH`.
- expose `GetPoUcsh...Comments(poNumber[, order])` to load, and `InsertUpdatePoUcsh...Comment(col)` to
  save. save logic: new rows (Id == 0) get a manual id and `InsertOnSubmit`; existing rows with
  `IsModified == true` are `Attach`ed and refreshed `KeepCurrentValues`; one `SubmitChanges` at the end.

-------------------------------------------------------------------------------

the comment editing window (PoAddNewUcshComment)

file: `PoAddNewUcshComment.xaml.cs`. one window serves both header and line comments via a `bool
lineHeader` (true = header mode). it holds two grids (`DG_HeaderCommentList`, `DG_LineCommentList`) and
shows whichever matches the mode.

launch (from the PO tab grid, `PurchaseOrders_DG_HardwarePos_PreviewMouseLeftButtonDown`):
- click header-comment cell (DisplayIndex 25): if the row already `UcHeaderHasComments`, load them via
  `PoUcshHeaderComments.GetPoUcshHeaderComments(poNumber)`; else assign an empty collection (so the
  collection-changed binding is live). open the window in header mode (`ref _selItem, true, ref _poCol`).
- click line-comment cell (DisplayIndex 26): same but `GetPoUcshLineComments(poNumber, order)` and line
  mode. so comments are LAZY-loaded only when you open the cell, not when the PO list loads.

inside the window:
- `BTN_NewComment_Click` adds a fresh `PoUcshHeaderComment(jobNumber, poNumber)` or
  `PoUcshLineComment(jobNumber, poNumber, order)` to the bound collection (id stays 0 = "new").
- `Window_Closed` is where persistence happens: it removes any rows with blank `CommentText`, then
  calls `InsertUpdatePoUcsh...Comment(col)`. if any comments remain it sets the PO line's
  `UcHeaderHasComments` / `UcLineHasComments` flag true so the grid shows the row as commented.
- there's a THIRD constructor `PoAddNewUcshComment(IEnumerable<IPoUcshComment>)` used elsewhere
  (receiving "view" side) that opens the grid READ-ONLY and hides the new-comment button.

edit-permission rule - `DG_HeaderCommentList_PreviewMouseLeftButtonDown`: a comment can only be edited
by the user who created it. on a full-row selection, if `Environment.UserName != comment.CreatingUser`,
the row's selection is cancelled so the user can't edit someone else's comment.

-------------------------------------------------------------------------------

PO confirmations (PROCPOCONF101)

file: `DataClasses/PROC_PoConfirmations.cs`. class `PoConfirmation`, mapped
`[Table(Name="[PROCPOCONF101]")]`, `TableFamily = UCSH`. a per-PO confirmation/acknowledgement tracking
record (e.g. did we email the supplier, did they acknowledge, what's the anticipated ship date). PK is
`PONUMBER`.

| property | column | meaning |
|---|---|---|
| `PoNumber` | `PONUMBER` (PK) | PO number |
| `JobNumber` | `JobNumber` | job number |
| `EmailToSupplier` | `EmailToSupplier` | bool - emailed the supplier |
| `ShipToLocation` | `ShipToLocation` | ship-to location |
| `AcknowReceived` | `AcknowReceived` | bool - supplier acknowledged |
| `AnticiShipDate` | `AnticiShipDate` | anticipated ship date |
| `Notes` | `Notes` | free text |
| `Flex01` / `Flex02` | same | flexible/spare fields |
| `FileLocation` | `FileLocation` | path to a related file |
| `DateReceived` / `TimeReceived` | same | audit |
| `UpdatingUser` / `UpdatingMachine` | same | audit |

only a read method is present in this file - `GetProcPoReceipts()` loads all rows ordered by PO number
descending, and pops a message box if none are found. (writes to this table happen elsewhere or are not
in this class; for replication purposes treat the schema above as authoritative and the in-app surface
as read-only.) there's also a nested `PoReceiptDataContext` exposing `Table<PoConfirmation> PoReceipt`.

-------------------------------------------------------------------------------

PO deficiencies (cross-reference)

PO-level warehouse deficiencies (`WHRECEIPTDEFICIENCY101`) are created/edited from the receiving tab
but are keyed by PO. full field reference and the deficiency window are documented in
`02 - hardware inventory receiving end to end.md`. relevant to POs: a PO can have open deficiencies,
and the receiving "select PO" dialogs warn when the selected PO has any incomplete ones.

-------------------------------------------------------------------------------

the dormant PO-creation eConnect stub (do not treat as a real workflow)

file: `EConnect/PopTransaction.cs`, method `RunPoCreate()`. this is the ONLY code that would push a NEW
PO into GP, and it is a developer test artifact. evidence it isn't live:
- it's only referenced from commented-out lines in MainWindow (1975, 3378) - never actually called.
- it hardcodes the TEST database connection: `Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=TUCSH;...`.
- it builds its line data from `GenerateDummyPoData()` - two hardcoded fake lines (vendor `GAL100`,
  item `NONSTOCKHD`, descriptions "Test Item Line 1/2", qty 1, non-inventory).
- it hardcodes `LOCNCODE = "MARKHAM"`.

that said, it's the clearest template for how a PO push WOULD be built with eConnect, so here's what it
does, mechanically (same skeleton as the live receipt push in doc #2):

1. reserve a PO number: `GetPoNumGp()` -> `GetNextPONumber(Increment)` against TUCSH.
2. `SerializePoReceiptObjects(...)` builds:
   - per line, a `taPoLine_ItemsTaPoLine` with: `POTYPE = 1`, `RequesterTrx = 1`, `LOCNCODE = "MARKHAM"`,
     `PONUMBER`, `ITEMNMBR`, `ITEMDESC`, `VENDORID`, `VNDITNUM` (= item number, assumes 1:1),
     `UNITCOST = 0`, `QUANTITY = QuantityOrdered`, `NONINVEN`. line sequence `ORD` starts 16384, +16384.
     only lines with `Polnesta < 4` are included.
   - a `taPoHdr` header with: `POTYPE = 1`, `PONUMBER`, `DOCDATE = today`, `VENDORID`, `SUBTOTAL = 0`.
   - wraps them in `POPTransactionType` -> `eConnectType`, serializes to `PoRecLines.xml`.
3. posts via `eConnectMethods.CreateTransactionEntity`.
4. `VerifyPoCreation(poNum)` queries `POP10110` for the PO number; if absent, rolls back the reserved
   number (`RollBackRecNumGp` -> `GetNextPONumber(Decrement)`) and returns false.

`POTYPE = 1` = standard PO. the code comment notes POP10500 carries type 2 but eConnect only accepts
1 or 3. again: dummy data + test db + never called. if you want PO creation in the new system you are
designing it fresh, not porting this.

-------------------------------------------------------------------------------

excel export

`BTN_PO_PurchaseOrders_ExportToExcel_Click` -> `ExcelConverters.ExcelExporter.DatabaseToExcel(
ExcelExporter.ReportName.PurchaseOrderAll, _curUserTwo)`. exports the PO list to excel via the
`ExcelConverters` project. (the excel layer is out of scope here; noted for completeness.)
