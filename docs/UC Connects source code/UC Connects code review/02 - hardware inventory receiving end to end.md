# hardware / inventory receiving, end to end

assumes you've read `00 - shared foundations.md` and ideally `01 - purchase orders end to end.md`.
this is the workflow where UC Connects WRITES back to GP (posting PO receipts) and stores its own
rack-level receiving data. it is the most important and most complete workflow in the app.

contents:
- what "receiving" means here and the four receipt types
- the create-receipts tab in MainWindow
- the four select-PO dialogs and the data each one loads
- ReceivingLine - the WHRECLINE101 model, field by field
- how receiving lines are loaded (and the default-quantity differences per type)
- the grid helpers (populate all, copy-down rack)
- the commit pipeline, step by step (the heart of the workflow)
- the eConnect receipt push (PopRcptLineInsert), field by field
- persisting to WHRECLINE101 and the rollback behaviour
- the dangerous failure mode (GP receipt created, UC insert fails)
- deficiencies (WHRECEIPTDEFICIENCY101) and the deficiency window
- the view-receipts tab (after a receipt exists)
- what happens downstream (rack draw-downs, tagging)
- dormant / disabled bits (landed cost, the receipt email)

-------------------------------------------------------------------------------

what "receiving" means here, and the four receipt types

receiving = recording that physical goods arrived against a GP purchase order, which does two things:
1. posts a PO RECEIPT into GP via eConnect (so GP's `POP10500` reflects the received quantity), and
2. writes UC's own receiving record into `WHRECLINE101` capturing what GP cannot store - the warehouse
   RACK LOCATION the goods were put on, plus a revision number and full audit.

the receipt TYPE is an enum, `WarehouseReceiptType` (in `DropDowns.cs`):

| value | int | how you reach it | what it receives against |
|---|---|---|---|
| `PurchaseOrder` | 1 | "Get PO List" | a plain PO (job POs), select by PO number |
| `RetailOrder` | 2 | "Get PO/SOP List" | a PO tied to a sales order (retail), select by PO+SOP |
| `Unusual` | 3 | "Get PO List (Unusual)" | POs with no job, no SOP, not showroom |
| `Showroom` | 4 | "Get PO List (Showroom)" | POs whose location is SHOWROOM |

the type matters in three places: which select-dialog opens, which data-source query runs (and thus
what the received quantity DEFAULTS to), and the eConnect batch name (`SH-` for showroom, `EC-`
otherwise).

-------------------------------------------------------------------------------

the create-receipts tab in MainWindow

file: `MainWindow.xaml.cs`, region `Receiving Create`. state:
- `ObservableCollection<dc.ReceivingLine> _whPoRecCol` - the working set of lines being received,
  bound to the grid `DG_Warehouse_CreateReceipts_RecLineList`.
- `WarehouseReceiptType _whType` - the type chosen for the current batch.

the four "get list" handlers all follow the same shape: set `_whType`, open the matching select
dialog (passing `_whPoRecCol`, the grid, and the "exclude fully received" checkbox value), and after it
closes, populate the job/sop labels and - if the dialog flagged it - show the
`LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies` warning label.

| handler | sets `_whType` | opens dialog |
|---|---|---|
| `BTN_Warehouse_CreateReceipts_GetPoList_Click` | PurchaseOrder | `WhRecSelectPo` |
| `BTN_Warehouse_CreateReceipts_GetPoListSopList_Click` | RetailOrder | `WhRecSelectPoSop` |
| `BTN_Warehouse_CreateReceipts_GetPoListShowroom_Click` | Showroom | `WhRecSelectPoShowroom` |
| `BTN_Warehouse_CreateReceipts_GetPOListUnusual_Click` | Unusual | `WhRecSelectPoUnusual` |

the "exclude fully received" toggle is `ChkBox_Warehouse_CreateReceipts_HideFullReceivedLines` - when
checked, lines whose previously-received qty already equals the ordered qty are dropped from the list.

once lines are loaded, the user fills in, per line, how much is being received (`QtyRecForGp`) and the
rack `Location`, then commits.

-------------------------------------------------------------------------------

the four select-PO dialogs

all four are small modal windows that (a) list candidate POs, (b) let the user search by PO number with
a debounced filter, (c) on double-click load the receiving lines for the chosen PO into `_whPoRecCol`
and the parent grid, then (d) on close, set a `DeficiencyCheck` bool = "does this PO have any
INCOMPLETE deficiency?" which the tab uses to show the warning label.

WhRecSelectPo (type PurchaseOrder) - file `WhRecSelectPo.xaml.cs`:
- lists PO headers via `PurchaseOrderHeaders.GetPoHeaders()` (all POs with a job).
- on double-click: `WhReceivingLines.GetPoReceivingLineItemsByPoNum(po.PoNumber, excludeComplete)`.
- `Window_Closed` sets `DeficiencyCheck` = any `WHRECEIPTDEFICIENCY101` row for the PO with
  `Completed == false`.
- this file also defines `DoNotShipConverter` - the row-colour cue: future do-not-ship date -> Tomato
  red; else grey `#FF575555`.

WhRecSelectPoSop (type RetailOrder) - file `WhRecSelectPoSop.xaml.cs`:
- lists PO/SOP links via `WhReceivingLines.GetPoWithSopList()` (SOP60100 grouped by PO+location+SOP,
  excluding SHOWROOM, with buyer id from POP10100).
- on double-click: `WhReceivingLines.GetPoLinesFromSop(po.PoNumber, po.SopNumber, excludeComplete)`.

WhRecSelectPoShowroom (type Showroom) - file `WhRecSelectPoShowroom.xaml.cs`:
- lists via `WhReceivingLines.GetPoWithSopListShowroom()` (same as above but location == SHOWROOM).
- on double-click: `WhReceivingLines.GetPoLinesFromSopShowroom(...)`.

WhRecSelectPoUnusual (type Unusual) - file `WhRecSelectPoUnusual.xaml.cs`:
- lists via `PurchaseOrderHeaders.GetPoHeadersUnusual()` (POs with blank job, not showroom, no SOP link).

-------------------------------------------------------------------------------

ReceivingLine - the WHRECLINE101 model (the central class)

file: `DataClasses/WhReceivingLines.cs`. class `ReceivingLine : IJobNumberHaver, INotifyPropertyChanged`,
mapped `[Table(Name="[WHRECLINE101]")]`, `TableFamily = UCSH`.

read the class's own header comment - it is the design intent verbatim: this class is dual-purpose. it
is nominally the LINQ entity for `WHRECLINE101` in the PM database, but it ALSO carries extra,
non-stored properties (`QtyRecForGp`, `VendorDatagridDispOnly`, etc) so the SAME object can be passed
to the eConnect receipt procedure. the WHOLE REASON the table exists is to capture `RevisionNumber` and
`Location` (the rack - NOT the GP `LOCNCODE`), which GP has no field for. the other columns are there
so a `WHRECLINE101` row can be joined back to its GP receipt.

composite primary key (4 columns): `PONUMBER` + `POLNENUM` + `POPRCTNM` + `RCPTLNNM`.

stored columns (mapped to WHRECLINE101):

| property | column | meaning |
|---|---|---|
| `PoNumber` | `PONUMBER` (PK) | PO number this receipt line is against |
| `Polnenum` | `POLNENUM` (PK) | the PO line (= POP10110.ORD) |
| `PopRctNum` | `POPRCTNM` (PK) | GP receipt number, set during the eConnect push |
| `RcptLnNm` | `RCPTLNNM` (PK) | receipt line number, set during the push (16384 steps) |
| `SopNumber` | `SopNumber` | linked sales order (retail/showroom) |
| `ItemNumber` | `ITEMNMBR` | item number |
| `ItemDescription` | `ITEMDESC` | item description |
| `VendorId` | `VENDORID` | vendor id |
| `VendorName` | `VENDNAME` | vendor name |
| `JobNumber` | `JobNumber` | job number |
| `JobName` | `JobName` | job name |
| `RevisionNumber` | `RevisionNumber` | UC revision number (GP has no equivalent) |
| `Location` | `Location` | RACK location in the warehouse (the key UC-only field) |
| `Comments` | `Comments` | free-text receipt comment |
| `DateReceived` | `DateReceived` | date received (stamped at insert) |
| `TimeReceived` | `TimeReceived` (time) | time received (stamped at insert) |
| `UpdatingUser` | `UpdatingUser` | who received it (WindowsIdentity full name) |
| `UpdatingMachine` | `UpdatingMachine` | machine name |
| `QtyOrdFromGp` | `QuantityOrdered` | qty ordered on the PO line (carried for the grid + eConnect) |
| `QtyRecForGp` | `QuantityReceived` | qty being received NOW = GP `POP10500.QTYSHPPD`; setter raises PropertyChanged |
| `QtyRemainingOnRec` | `QuantityRemainingOnRack` | remaining rack qty available for shipment draw-down |

non-stored / display-only / eConnect-carrier properties (NOT columns):

| property | purpose |
|---|---|
| `Polnesta` | PO line status (1..6) - used to gate which lines get pushed (only `< 4`), but cannot be passed to GP |
| `CustomerName` | display only (from sales-order union) |
| `BuyerId` / `ChangeId` | display only |
| `GlPostDate` | from POP30300 (posted receipt gl date) - view side only |
| `LocnCode` | GP location code; used as the eConnect `LOCNCODE`. distinct from `Location` (rack). added because Vancouver couldn't receive POs without the PO's own location code |
| `NonInventory` | passed to eConnect (`NONINVEN`) |
| `QtyCumulativePrevRecFromGp` | aggregate previously-received qty (synthetic) |
| `QtyActualShip` | qty actually shipped (view side) |
| `VendorDatagridDispOnly` | vendor name for the grid only |
| `TaggedQuantityCumulative` | qty already tagged (from the tagging table) |
| `UnitCost` | unit cost (carried; pushed as 0 - see eConnect section) |
| `UiQuantityToTransfer` | UI field for transferring qty to a shipment |
| `InsertedToDb` | tracks which lines made it into WHRECLINE101, for rollback |
| `TaggingLine` | a 1:1 tagging line for grid binding |
| `UcHeaderCommentText` / `UcLineCommentText` + the two `...Col` collections | UC PO comments surfaced on the receiving line |
| `DoNotShipBeforeDate` | the PO's do-not-ship date |

the class has FOUR constructors, one per loading scenario - this matters because each scenario defaults
`QtyRecForGp` differently (see next section). the constructors are: (a) the view/edit constructor
[19 args], (b) `GetPoReceivingLineItemsByPoNum` constructor, (c) `GetPoLinesFromSop` constructor,
(d) `GetPoRecLinesWithUcshRecLines` (view) constructor.

-------------------------------------------------------------------------------

how receiving lines are loaded (and the default-quantity differences)

all loaders are static methods on `WhReceivingLines` and use the cross-database pattern. the IMPORTANT
behavioural difference between them is what `QtyRecForGp` (the qty-to-receive) defaults to:

| method | used by type | base query | `QtyRecForGp` default |
|---|---|---|---|
| `GetPoReceivingLineItemsByPoNum(poNum, excludeComplete)` | PurchaseOrder, Unusual | POP10110 + POP10500(prev rec) + POP10100 + JC00102 + PM00200 + UC comments; `LOCNCODE != SHOWROOM`, PO == poNum | 0 (user must type each qty) |
| `GetPoLinesFromSop(poNum, sopNum, excludeComplete)` | RetailOrder | POP10110 + POP10500 + POP10100 + JC00102 + PM00200 + SOP60100; `LOCNCODE != SHOWROOM`, SOP == sopNum | FULL remaining (`ordered - prevReceived`) |
| `GetPoLinesFromSopShowroom(poNum, sopNum, excludeComplete)` | Showroom | same but `LOCNCODE == SHOWROOM` | FULL remaining |

the "exclude complete" flag adds `where prevReceived != ordered` to drop already-fully-received lines.

why the default differs (from the code): for plain job POs the qty defaults to 0 because the warehouse
was accidentally fully-receiving POs they shouldn't have (comment dated 11 Nov 2016). retail/showroom
orders default to the full remaining quantity because those are typically received complete.

`QtyRemainingOnRec` (the rack remaining qty) is initialised to `ordered - previouslyReceived` in the PO
constructor. `QtyCumulativePrevRecFromGp` holds the previously-received total. previously-received is
computed as the SUM of `POP10500.QTYSHPPD` grouped by PO line.

-------------------------------------------------------------------------------

the grid helpers

while lines are loaded in the grid the user has two convenience actions:

- `BTN_Warehouse_CreateReceipts_PopulateReceipts_Click` - sets every line's `QtyRecForGp = QtyOrdFromGp`
  (receive everything in full), then refreshes the grid.
- `BTN_Warehouse_CreateReceipts_CopyDownLocation_Click` - copies the rack value typed into
  `TB_Warehouse_CreateReceipts_LineItemLocationCopy` down into every line's `Location`.

these are pure in-memory edits on `_whPoRecCol`; nothing is saved until commit.

-------------------------------------------------------------------------------

the commit pipeline (the heart of the workflow)

handler: `BTN_Warehouse_CreateReceipts_CommitRecLines_Click`. step by step, exactly as coded:

1. ONE-PO GUARD. count distinct PO numbers among lines with `QtyRecForGp > 0`. if more than one,
   message "You're attempting to receive more than one PO at a time on this retail order. Operation
   terminating." and return. (a single receipt is always against a single PO.)

2. disable the commit button.

3. RACK + FULLY-RECEIVED VALIDATION - `CheckRackFieldsForBlanksFullyReceived(_whPoRecCol)`:
   - if any line has `QtyRecForGp > 0` but a blank `Location` -> message "Some rack locations have been
     left blank ..." and abort (returns false).
   - if EVERY line is already fully received (`QtyOrdFromGp - QtyCumulativePrevRecFromGp == 0` for all)
     -> message "PO has already been fully received; cannot commit anymore receipts." and abort.
   only if this passes does it continue.

4. DROP ZERO LINES - `RemoveNoQuantityPoReceipts.Removal(ref _whPoRecCol)` removes every line with
   `QtyRecForGp == 0` from the collection. if nothing remains: message "No lines have any quantities to
   receive on them", re-enable the button, return.

5. POST TO GP - `EConnect.PopRcptLineInsert.RunEconnect(ref _whPoRecCol, _whType)` (detailed below).
   this reserves a receipt number, posts the eConnect receipt, verifies it landed in `POP10500`, and on
   the way assigns each line's `PopRctNum` + `RcptLnNm`. returns true only if GP confirmed the receipt.

6. IF GP SUCCEEDED - write UC's own rows: `dc.WhReceivingLines.AddReceivingLines(_whPoRecCol)`.
   - if that returns false, roll back: `dc.WhReceivingLines.DeleteReceivingLines(_whPoRecCol)`.
   - if it returns true, message "Receipts successfully created in GP and in UCSH databases. Receipt
     number is: <PopRctNum>", then clear `_whPoRecCol`.

7. re-enable the commit button.

note the large code comment at this handler pointing to an external error-correction document
("IF YOU GET THE ERROR WHERE A PO RECEIPT GETS MADE IN GP BUT NOT CONNECTS, GO HERE ..."). that is the
known dangerous failure mode - see its own section below.

-------------------------------------------------------------------------------

the eConnect receipt push (PopRcptLineInsert)

file: `EConnect/PopRcptLineInsert.cs`, `RunEconnect(ref ObservableCollection<ReceivingLine> recLines,
WarehouseReceiptType whType)`. this is the live eConnect path. flow:

1. reserve a receipt number: `GetReceiptNumGp()` -> SDK `GetNextPOPReceiptNumber(Increment)` against the
   current GP db (`UCSHSQL2\MSSQL2014` + `CurrentGpDatabaseName`). format `RCT######`.
2. `SerializePoReceiptObjects(...)` builds the eConnect document (below) into `PoRecLines.xml`.
3. load the xml, post: `eConnectMethods.CreateTransactionEntity(GpConnectionString, xml.OuterXml)`.
4. `VerifyReceiptCreation(receiptNum)` queries `POP10500` for that `POPRCTNM`. if zero rows -> message
   "GP did not actually create this receipt number ...", return false.
5. `finally`: if not completed, `RollBackRecNumGp` -> `GetNextPOPReceiptNumber(Decrement)` to return the
   reserved number. dispose `eConnectMethods`.

what the serialized document contains - per receipt LINE
(`taPopRcptLineInsert_ItemsTaPopRcptLineInsert`), only for lines with `QtyRecForGp > 0` AND
`Polnesta < 4`:

| eConnect field | value set from | note |
|---|---|---|
| `POPTYPE` | `1` | shipment-only receipt (POP10500 is type 2, but eConnect only allows 1 or 3) |
| `POPRCTNM` | reserved receipt number | |
| `POLNENUM` | `recLine.Polnenum` | the PO line being received |
| `RequesterTrx` | `1` | |
| `LOCNCODE` | `recLines[0].LocnCode` | the GP location code of the FIRST line (the PO's site) |
| `JOBNUMBR` | `recLine.JobNumber` | |
| `PONUMBER` | `recLine.PoNumber` | |
| `ITEMNMBR` | `recLine.ItemNumber` | |
| `VENDORID` | `recLine.VendorId` | |
| `VNDITNUM` | `recLine.ItemNumber` | assumes vendor item number == item number (1:1) |
| `AUTOCOST` | `1` | let GP auto-cost |
| `UNITCOST` | `0` | hardcoded 0 (NOT recLine.UnitCost) |
| `EXTDCOST` | `0` | hardcoded 0 |
| `QTYSHPPD` | `recLine.QtyRecForGp` | the quantity received |
| `NONINVEN` | `recLine.NonInventory` | |
| `receiptdate` | today (`yyyy/MM/dd`) | |

while building each line the code ALSO writes back onto the `ReceivingLine`: `PopRctNum = receiptNum`
and `RcptLnNm = _rcptLnm`, where `_rcptLnm` starts at 16384 and increments by 16384 per included line.
that's how the PK values get onto the object before it's later inserted into WHRECLINE101.

the receipt HEADER (`taPopRcptHdrInsert`):

| eConnect field | value | note |
|---|---|---|
| `POPRCTNM` | reserved receipt number | |
| `POPTYPE` | `1` | |
| `VNDDOCNM` | `recLines[0].PoNumber` | vendor document number = the PO number |
| `receiptdate` | today | |
| `BACHNUMB` | `EC-<today>` normally, `SH-<today>` if Showroom | the GP batch the receipt lands in |
| `VENDORID` | `recLines[0].VendorId` | |
| `SUBTOTAL` | `0` | |

the header + lines wrap into `POPReceivingsType` -> `eConnectType`, serialize, post. costing is left to
GP (`AUTOCOST = 1`, costs pushed as 0).

-------------------------------------------------------------------------------

persisting to WHRECLINE101 and rollback

after GP confirms, `WhReceivingLines.AddReceivingLines(rlCol)` writes UC's rows:

- iterates the collection; for each line with `QtyRecForGp > 0`:
  - `QtyRemainingOnRec = QtyRecForGp` (the full received qty is initially available on the rack)
  - `DateReceived = DateTime.Today`, `TimeReceived = DateTime.Now`
  - `UpdatingUser = WindowsIdentity.GetCurrent().Name`, `UpdatingMachine = Environment.MachineName`
  - `InsertOnSubmit` + `SubmitChanges` (one submit PER line, inside the loop)
  - `InsertedToDb = true`
- on any SQL/exception: message box, set `_cont = false`, break the loop.
- returns `_cont`. if false, the method itself also calls `DeleteReceivingLines(rlCol)` (and the
  MainWindow caller calls it again as a belt-and-braces rollback).

`DeleteReceivingLines` only deletes rows where `InsertedToDb == true`, so it removes exactly the UC rows
that were inserted in this batch (it does NOT touch the GP receipt).

related write methods on the same class: `AddReceivingLine` (single), `UpdateReceivingLine` /
`UpdateReceivingLines` (Attach + Refresh KeepCurrentValues - used by the view-receipts rack edits).

-------------------------------------------------------------------------------

the dangerous failure mode (GP ok, UC insert fails)

this is the one operational hazard the legacy code explicitly warns about. the commit order is: post to
GP FIRST, then insert into WHRECLINE101. if the GP post succeeds but the WHRECLINE101 insert throws,
`AddReceivingLines` rolls back ONLY the UC rows - the GP receipt remains. result: a receipt exists in
GP that UC Connects has no record of (no rack location, won't appear in "view receipts").

the code comment at the commit handler points staff to a manual error-correction procedure document
(an external P: drive path) to repair this by hand. there is no automatic GP-side rollback of a posted
receipt. anyone reproducing this workflow should note the ordering and the absence of a true
distributed transaction across the two databases.

-------------------------------------------------------------------------------

deficiencies (WHRECEIPTDEFICIENCY101)

a "deficiency" is a per-PO warehouse note that something is wrong/outstanding with a received PO. file:
`DataClasses/WhDeficiencies.cs`. class `WhDeficiency : IJobNumberHaver, INotifyPropertyChanged`, mapped
`[Table(Name="[WHRECEIPTDEFICIENCY101]")]`, `TableFamily = UCSH`, PK `ID` (manual MAX(ID)+1).

| property | column | meaning |
|---|---|---|
| `Id` | `ID` (PK) | manual id |
| `PoNumber` | `PONUMBER` | PO the deficiency is against |
| `JobNumber` | `JobNumber` | job number |
| `Completed` | `Completed` | bool; setter stamps `CompletingUser`/`DateCompleted`/`TimeCompleted` when set true, clears them when false |
| `CompletingUser` | `CompletingUser` | who closed it |
| `DateCompleted` / `TimeCompleted` | same | when closed |
| `Remarks` | `Remarks` | the deficiency text; setter flags `IsModified` |
| `UpdatingUser` / `UpdatingMachine` | same | audit |
| `DateCreated` / `TimeCreated` | same | create audit |
| `IsModified` / `IsDeleted` / `IsNew` | (not mapped) | UI state flags |

methods: `GetDeficienciesByPo(poNumber)` (load), `AddWhDeficiency` (insert, manual id),
`UpdateWhDeficiency` (Attach + Refresh KeepCurrentValues). there's a convenience constructor
`WhDeficiency(PurchaseOrderHeader)` that pre-fills PO/job and create audit and marks `IsNew`.

the deficiency window - `WhDeficiencyListWindow.xaml.cs`:
- opened from the create-receipts tab via `BTN_Warehouse_CreateReceipts_ReportDeficiency_Click`, which
  builds a `PurchaseOrderHeader` from the first loaded receiving line (NOTE: it calls
  `PurchaseOrderHeaders.GetPoHeaderSingle`, which currently returns null - see the PO doc - so the
  header passed in may be null; the window is constructed from `_whPoRecCol[0].PoNumber` context).
- lists existing deficiencies for the PO; `BTN_CreateDeficienty_Click` adds a new one.
- `Window_Closing`: inserts all `IsNew` rows, updates all `IsModified` rows, toggles the
  create-receipts tab's incomplete-deficiency warning label based on whether any remain `Completed == false`,
  and EMAILS the newly created deficiencies via `OutlookConverters.OutlookGenerator`.

how deficiencies tie back to receiving: each select-PO dialog, on close, sets its `DeficiencyCheck`
bool by querying `WHRECEIPTDEFICIENCY101` for incomplete rows on the chosen PO; the create-receipts tab
shows `LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies` when that's true - a heads-up that the
PO you're about to receive has open deficiencies.

-------------------------------------------------------------------------------

the view-receipts tab (after a receipt exists)

region in `MainWindow.xaml.cs`. lets staff browse, search, edit rack locations, and generate documents
for receipts that already exist.

- `BTN_Warehouse_ViewReceipts_RefreshList_Click` loads via
  `WhReceivingLines.GetPoRecLinesWithUcshRecLines(null, maxOneYear)`. that query JOINS UC's
  `WHRECLINE101` to the GP world to give the full picture per received line: `POP10500` (received qty),
  `POP10110` (PO line / item / vendor / job), `JC00102` (job name), `PM00200` (vendor name),
  `SOP60100` + sales union (sop/customer), `POP10100` (buyer), `POP30300` (gl post date),
  UC `ShippingLine` (qty actually shipped, draw-down), and UC `TaggingLine` (qty tagged). filtered to
  the last year when the checkbox is set. bound with the in-memory `WhReceivingsViewFilter`.
- `BTN_Warehouse_ViewReceipts_UpdateRackLocations_Click` - BULK rack rename: requires a PO filter (>= 5
  chars), an old-rack filter, and a new rack value; rewrites `Location` on every currently-filtered row
  and saves via `UpdateReceivingLines`.
- single-line edit: `WhRecLinesPopUpWindow` (`WhRecLinesPopUpWindow.xaml.cs`) binds one `ReceivingLine`
  and `Btn_CommitEdit_Click` saves it via `UpdateReceivingLine` ("Receipt has been updated").
- `BTN_Warehouse_ViewReceipts_GeneratePreShipmentDocument` - builds a pre-shipment/receipt document via
  the `WordConverters` project (`ExportReceiptsPoHeaderBlankLines`), gated by the
  `WhRecsBlankLinesShippingMemo` dialog (asks how many blank lines).
- excel export: `ExcelExporter.ReportName.WarehouseReceiptsAll`.

-------------------------------------------------------------------------------

what happens downstream (brief - not part of receiving creation)

these consume the receiving data and are documented only enough to show where `WHRECLINE101` flows:

- rack draw-downs: when goods are later SHIPPED, the received rack quantity (`QtyRemainingOnRec` /
  `QuantityRemainingOnRack`) is drawn down and recorded in `WHRECLINEDRAWDOWNS101`
  (`RecLineTracker` / `RecLineTrackers` in `UtilityClasses/ReceiptLineRackQuantityTracker.cs`), keyed by
  shipment `MemoNumber` + PO + line + receipt. rollbacks delete by memo number.
- tagging: received quantities can be "tagged" (allocated) via `TaggingLine` / `WhTaggingLines`; the
  view-receipts tab enforces you can't tag more than `received - alreadyTagged`
  (`Warehouse_ViewReceipts_CommitTagQuantities`).

both are part of the shipping workflow, not receiving creation; out of scope here.

-------------------------------------------------------------------------------

dormant / disabled bits

- landed cost: `EConnect/SupportProcedures/taPopRcptLandedCost.cs` (`taPopRcptLandedCostNew` /
  `taPopRcptLandedCostOld`) calls a `dbo.taPopRcptLandedCost` stored proc, but with HARDCODED test
  values (receipt `RCT062522`, landed-cost id `MISC`, vendor `SHE101`/blank). it is only referenced
  from COMMENTED-OUT lines in the commit handler. landed cost is NOT applied in the live receiving flow.
- the receipt confirmation email: in the commit handler, after a successful non-SOP receipt, an
  `OutlookConverters.OutlookGenerator` email was generated - now commented out with the note
  "EMAIL FUNCTIONALITY TURNED OFF SINCE THE MAIL SERVER HAS NOW MIGRATED TO THE CLOUD - 22 JUNE 2025".
  so no receipt email is sent today. (the deficiency email in the deficiency window is still active.)
