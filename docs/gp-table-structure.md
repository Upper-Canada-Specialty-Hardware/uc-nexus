# GP / Custom Tables — Structure Reference

Source: `UCSHSQL2\MSSQL2014` (SQL Server 2014 SP3-CU4)  
Auth: Windows Integrated (SSPI)  
Extracted: 2026-05-06

Schema parity verified: `UBC` ≡ `UCSH`, `PMUBC` ≡ `PMUCSH` — only one schema shown per table.

## POP10110 — PO Line Items (in UBC, UCSH)

Column count: 105

### Indexes (unique = effective key candidates)

| Index | Type | Unique | Keys |
|---|---|---|---|
| `AK2POP10110` | NONCLUSTERED | yes | ITEMNMBR, PONUMBER, ORD |
| `AK3POP10110` | NONCLUSTERED | yes | VNDITNUM, PONUMBER, ORD |
| `AK4POP10110` | NONCLUSTERED | yes | POLNESTA, PONUMBER, ORD, DEX_ROW_ID |
| `AK5POP10110` | NONCLUSTERED | yes | PONUMBER, ITEMNMBR, ORD |
| `AK6POP10110` | NONCLUSTERED | yes | PONUMBER, VNDITNUM, ORD |
| `AK7POP10110` | NONCLUSTERED | yes | ITEMNMBR, REQDATE, DEX_ROW_ID |
| `AK8POP10110` | NONCLUSTERED | yes | ITEMNMBR, QTYUNCMTBASE, LOCNCODE, DEX_ROW_ID |
| `AK9POP10110` | NONCLUSTERED | yes | Product_Indicator, JOBNUMBR, COSTCODE, PONUMBER, ORD |
| `PKPOP10110` | NONCLUSTERED | yes | PONUMBER, ORD, BRKFLD1 |

### Columns

| # | Name | Type | Nullable |
|---:|---|---|---|
| 1 | `PONUMBER` | char(17) | no |
| 2 | `ORD` | int | no |
| 3 | `POLNESTA` | smallint | no |
| 4 | `POTYPE` | smallint | no |
| 5 | `ITEMNMBR` | char(31) | no |
| 6 | `ITEMDESC` | char(101) | no |
| 7 | `VENDORID` | char(15) | no |
| 8 | `VNDITNUM` | char(31) | no |
| 9 | `VNDITDSC` | char(101) | no |
| 10 | `NONINVEN` | smallint | no |
| 11 | `LOCNCODE` | char(11) | no |
| 12 | `UOFM` | char(9) | no |
| 13 | `UMQTYINB` | numeric(19,5) | no |
| 14 | `QTYORDER` | numeric(19,5) | no |
| 15 | `QTYCANCE` | numeric(19,5) | no |
| 16 | `QTYCMTBASE` | numeric(19,5) | no |
| 17 | `QTYUNCMTBASE` | numeric(19,5) | no |
| 18 | `UNITCOST` | numeric(19,5) | no |
| 19 | `EXTDCOST` | numeric(19,5) | no |
| 20 | `INVINDX` | int | no |
| 21 | `REQDATE` | datetime | no |
| 22 | `PRMDATE` | datetime | no |
| 23 | `PRMSHPDTE` | datetime | no |
| 24 | `REQSTDBY` | char(21) | no |
| 25 | `COMMNTID` | char(15) | no |
| 26 | `DOCTYPE` | smallint | no |
| 27 | `POLNEARY_1` | numeric(19,5) | no |
| 28 | `POLNEARY_2` | numeric(19,5) | no |
| 29 | `POLNEARY_3` | numeric(19,5) | no |
| 30 | `POLNEARY_4` | numeric(19,5) | no |
| 31 | `POLNEARY_5` | numeric(19,5) | no |
| 32 | `POLNEARY_6` | numeric(19,5) | no |
| 33 | `POLNEARY_7` | numeric(19,5) | no |
| 34 | `POLNEARY_8` | numeric(19,5) | no |
| 35 | `POLNEARY_9` | numeric(19,5) | no |
| 36 | `DECPLCUR` | smallint | no |
| 37 | `DECPLQTY` | smallint | no |
| 38 | `ITMTRKOP` | smallint | no |
| 39 | `VCTNMTHD` | smallint | no |
| 40 | `BRKFLD1` | smallint | no |
| 41 | `PO_Line_Status_Orig` | smallint | no |
| 42 | `QTY_Canceled_Orig` | numeric(19,5) | no |
| 43 | `OPOSTSUB` | numeric(19,5) | no |
| 44 | `JOBNUMBR` | char(17) | no |
| 45 | `COSTCODE` | char(27) | no |
| 46 | `COSTTYPE` | smallint | no |
| 47 | `CURNCYID` | char(15) | no |
| 48 | `CURRNIDX` | smallint | no |
| 49 | `XCHGRATE` | numeric(19,7) | no |
| 50 | `RATECALC` | smallint | no |
| 51 | `DENXRATE` | numeric(19,7) | no |
| 52 | `ORUNTCST` | numeric(19,5) | no |
| 53 | `OREXTCST` | numeric(19,5) | no |
| 54 | `LINEORIGIN` | smallint | no |
| 55 | `FREEONBOARD` | smallint | no |
| 56 | `ODECPLCU` | smallint | no |
| 57 | `Capital_Item` | tinyint | no |
| 58 | `Product_Indicator` | smallint | no |
| 59 | `Source_Document_Number` | char(11) | no |
| 60 | `Source_Document_Line_Num` | smallint | no |
| 61 | `RELEASEBYDATE` | datetime | no |
| 62 | `Released_Date` | datetime | no |
| 63 | `Change_Order_Flag` | smallint | no |
| 64 | `Purchase_IV_Item_Taxable` | smallint | no |
| 65 | `Purchase_Item_Tax_Schedu` | char(15) | no |
| 66 | `Purchase_Site_Tax_Schedu` | char(15) | no |
| 67 | `PURCHSITETXSCHSRC` | smallint | no |
| 68 | `BSIVCTTL` | tinyint | no |
| 69 | `TAXAMNT` | numeric(19,5) | no |
| 70 | `ORTAXAMT` | numeric(19,5) | no |
| 71 | `BCKTXAMT` | numeric(19,5) | no |
| 72 | `OBTAXAMT` | numeric(19,5) | no |
| 73 | `Landed_Cost_Group_ID` | char(15) | no |
| 74 | `PLNNDSPPLID` | smallint | no |
| 75 | `SHIPMTHD` | char(15) | no |
| 76 | `BackoutTradeDiscTax` | numeric(19,5) | no |
| 77 | `OrigBackoutTradeDiscTax` | numeric(19,5) | no |
| 78 | `LineNumber` | smallint | no |
| 79 | `ORIGPRMDATE` | datetime | no |
| 80 | `FSTRCPTDT` | datetime | no |
| 81 | `LSTRCPTDT` | datetime | no |
| 82 | `RELEASE` | smallint | no |
| 83 | `ADRSCODE` | char(15) | no |
| 84 | `CMPNYNAM` | char(65) | no |
| 85 | `CONTACT` | char(61) | no |
| 86 | `ADDRESS1` | char(61) | no |
| 87 | `ADDRESS2` | char(61) | no |
| 88 | `ADDRESS3` | char(61) | no |
| 89 | `CITY` | char(35) | no |
| 90 | `STATE` | char(29) | no |
| 91 | `ZIPCODE` | char(11) | no |
| 92 | `CCode` | char(7) | no |
| 93 | `COUNTRY` | char(61) | no |
| 94 | `PHONE1` | char(21) | no |
| 95 | `PHONE2` | char(21) | no |
| 96 | `PHONE3` | char(21) | no |
| 97 | `FAX` | char(21) | no |
| 98 | `ADDRSOURCE` | smallint | no |
| 99 | `Flags` | smallint | no |
| 100 | `ProjNum` | char(15) | no |
| 101 | `CostCatID` | char(15) | no |
| 102 | `Print_Phone_NumberGB` | smallint | no |
| 103 | `QTYCommittedInBaseOrig` | numeric(19,5) | no |
| 104 | `DEX_ROW_TS` | datetime | no |
| 105 | `DEX_ROW_ID` | int | no |

## POP30000 — PO History Header (in UBC, UCSH)

Column count: 5

### Indexes (unique = effective key candidates)

| Index | Type | Unique | Keys |
|---|---|---|---|
| `AK2POP30000` | NONCLUSTERED | yes | BACHNUMB, BCHSOURC, DEX_ROW_ID |
| `AK3POP30000` | NONCLUSTERED | yes | GLPOSTDT, DEX_ROW_ID |
| `PKPOP30000` | NONCLUSTERED | yes | TRXSORCE |

### Columns

| # | Name | Type | Nullable |
|---:|---|---|---|
| 1 | `BACHNUMB` | char(15) | no |
| 2 | `TRXSORCE` | char(13) | no |
| 3 | `BCHSOURC` | char(15) | no |
| 4 | `GLPOSTDT` | datetime | no |
| 5 | `DEX_ROW_ID` | int | no |

## POP30300 — PO Receipt History (in UBC, UCSH)

Column count: 106

### Indexes (unique = effective key candidates)

| Index | Type | Unique | Keys |
|---|---|---|---|
| `AK2POP30300` | NONCLUSTERED | yes | VENDORID, VNDDOCNM, POPRCTNM |
| `AK3POP30300` | NONCLUSTERED | yes | receiptdate, VENDORID, POPRCTNM |
| `AK4POP30300` | NONCLUSTERED | yes | TRXSORCE, POPRCTNM |
| `AK5POP30300` | NONCLUSTERED | yes | VCHRNMBR, POPRCTNM |
| `PKPOP30300` | NONCLUSTERED | yes | POPRCTNM |

### Columns

| # | Name | Type | Nullable |
|---:|---|---|---|
| 1 | `POPRCTNM` | char(17) | no |
| 2 | `POPTYPE` | smallint | no |
| 3 | `VNDDOCNM` | char(21) | no |
| 4 | `receiptdate` | datetime | no |
| 5 | `GLPOSTDT` | datetime | no |
| 6 | `ACTLSHIP` | datetime | no |
| 7 | `BCHSOURC` | char(15) | no |
| 8 | `BACHNUMB` | char(15) | no |
| 9 | `VENDORID` | char(15) | no |
| 10 | `VENDNAME` | char(65) | no |
| 11 | `SUBTOTAL` | numeric(19,5) | no |
| 12 | `TRDISAMT` | numeric(19,5) | no |
| 13 | `TRDPCTPR` | numeric(23,0) | no |
| 14 | `FRTAMNT` | numeric(19,5) | no |
| 15 | `MISCAMNT` | numeric(19,5) | no |
| 16 | `TAXAMNT` | numeric(19,5) | no |
| 17 | `TEN99AMNT` | numeric(19,5) | no |
| 18 | `PYMTRMID` | char(21) | no |
| 19 | `DSCPCTAM` | smallint | no |
| 20 | `DSCDLRAM` | numeric(19,5) | no |
| 21 | `DISAVAMT` | numeric(19,5) | no |
| 22 | `DISCDATE` | datetime | no |
| 23 | `DUEDATE` | datetime | no |
| 24 | `REFRENCE` | char(31) | no |
| 25 | `VOIDSTTS` | smallint | no |
| 26 | `RCPTNOTE_1` | numeric(19,5) | no |
| 27 | `RCPTNOTE_2` | numeric(19,5) | no |
| 28 | `RCPTNOTE_3` | numeric(19,5) | no |
| 29 | `RCPTNOTE_4` | numeric(19,5) | no |
| 30 | `RCPTNOTE_5` | numeric(19,5) | no |
| 31 | `RCPTNOTE_6` | numeric(19,5) | no |
| 32 | `RCPTNOTE_7` | numeric(19,5) | no |
| 33 | `RCPTNOTE_8` | numeric(19,5) | no |
| 34 | `POPHDR1` | binary(4) | no |
| 35 | `POPHDR2` | binary(4) | no |
| 36 | `POPLNERR` | binary(4) | no |
| 37 | `POSTEDDT` | datetime | no |
| 38 | `PTDUSRID` | char(15) | no |
| 39 | `USER2ENT` | char(15) | no |
| 40 | `CREATDDT` | datetime | no |
| 41 | `MODIFDT` | datetime | no |
| 42 | `TRXSORCE` | char(13) | no |
| 43 | `VCHRNMBR` | char(21) | no |
| 44 | `Tax_Date` | datetime | no |
| 45 | `CURNCYID` | char(15) | no |
| 46 | `CURRNIDX` | smallint | no |
| 47 | `RATETPID` | char(15) | no |
| 48 | `EXGTBLID` | char(15) | no |
| 49 | `XCHGRATE` | numeric(19,7) | no |
| 50 | `EXCHDATE` | datetime | no |
| 51 | `TIME1` | datetime | no |
| 52 | `RATECALC` | smallint | no |
| 53 | `DENXRATE` | numeric(19,7) | no |
| 54 | `MCTRXSTT` | smallint | no |
| 55 | `ORSUBTOT` | numeric(19,5) | no |
| 56 | `ORTDISAM` | numeric(19,5) | no |
| 57 | `ORFRTAMT` | numeric(19,5) | no |
| 58 | `ORMISCAMT` | numeric(19,5) | no |
| 59 | `ORTAXAMT` | numeric(19,5) | no |
| 60 | `OR1099AM` | numeric(19,5) | no |
| 61 | `ORDDLRAT` | numeric(19,5) | no |
| 62 | `ORDAVAMT` | numeric(19,5) | no |
| 63 | `SIMPLIFD` | tinyint | no |
| 64 | `WITHHAMT` | numeric(19,5) | no |
| 65 | `ECTRX` | tinyint | no |
| 66 | `TXRGNNUM` | char(25) | no |
| 67 | `TAXSCHID` | char(15) | no |
| 68 | `BSIVCTTL` | tinyint | no |
| 69 | `Purchase_Freight_Taxable` | smallint | no |
| 70 | `Purchase_Misc_Taxable` | smallint | no |
| 71 | `FRTSCHID` | char(15) | no |
| 72 | `MSCSCHID` | char(15) | no |
| 73 | `FRTTXAMT` | numeric(19,5) | no |
| 74 | `ORFRTTAX` | numeric(19,5) | no |
| 75 | `MSCTXAMT` | numeric(19,5) | no |
| 76 | `ORMSCTAX` | numeric(19,5) | no |
| 77 | `BCKTXAMT` | numeric(19,5) | no |
| 78 | `OBTAXAMT` | numeric(19,5) | no |
| 79 | `TaxInvReqd` | tinyint | no |
| 80 | `BackoutFreightTaxAmt` | numeric(19,5) | no |
| 81 | `OrigBackoutFreightTaxAmt` | numeric(19,5) | no |
| 82 | `BackoutMiscTaxAmt` | numeric(19,5) | no |
| 83 | `OrigBackoutMiscTaxAmt` | numeric(19,5) | no |
| 84 | `TaxInvRecvd` | tinyint | no |
| 85 | `APLYWITH` | tinyint | no |
| 86 | `PPSTAXRT` | smallint | no |
| 87 | `SHIPMTHD` | char(15) | no |
| 88 | `Total_Landed_Cost_Amount` | numeric(19,5) | no |
| 89 | `CBVAT` | tinyint | no |
| 90 | `VADCDTRO` | char(15) | no |
| 91 | `REVALJRNENTRY` | int | no |
| 92 | `REVALTRXSOURCE` | char(13) | no |
| 93 | `TEN99TYPE` | smallint | no |
| 94 | `TEN99BOXNUMBER` | smallint | no |
| 95 | `REPLACEGOODS` | tinyint | no |
| 96 | `INVOICEEXPECTED` | tinyint | no |
| 97 | `PrepaymentAmount` | numeric(19,5) | no |
| 98 | `OriginatingPrepaymentAmt` | numeric(19,5) | no |
| 99 | `POP_HDR_Errors_4` | binary(4) | no |
| 100 | `DISTKNAM` | numeric(19,5) | no |
| 101 | `ORDISTKN` | numeric(19,5) | no |
| 102 | `DISAVTKN` | numeric(19,5) | no |
| 103 | `ORDATKN` | numeric(19,5) | no |
| 104 | `InvoiceReceiptDate` | datetime | no |
| 105 | `Workflow_Status` | smallint | no |
| 106 | `DEX_ROW_ID` | int | no |

## WHRECLINE101 — Warehouse Receipt Lines (in PMUBC, PMUCSH)

Column count: 21

### Indexes (unique = effective key candidates)

| Index | Type | Unique | Keys |
|---|---|---|---|
| `PK__WHRECLIN__9A02DD8F959068B5` | CLUSTERED | yes | PONUMBER, POLNENUM, POPRCTNM, RCPTLNNM |

### Columns

| # | Name | Type | Nullable |
|---:|---|---|---|
| 1 | `PONUMBER` | char(17) | no |
| 2 | `POLNENUM` | int | no |
| 3 | `QuantityOrdered` | int | YES |
| 4 | `QuantityReceived` | int | YES |
| 5 | `QuantityRemainingOnRack` | int | YES |
| 6 | `POPRCTNM` | char(17) | no |
| 7 | `RCPTLNNM` | int | no |
| 8 | `SopNumber` | char(21) | YES |
| 9 | `ITEMNMBR` | char(31) | YES |
| 10 | `ITEMDESC` | char(101) | YES |
| 11 | `VENDORID` | char(15) | YES |
| 12 | `VENDNAME` | char(65) | YES |
| 13 | `JobNumber` | varchar(255) | YES |
| 14 | `JobName` | varchar(255) | YES |
| 15 | `RevisionNumber` | varchar(255) | YES |
| 16 | `Location` | varchar(255) | YES |
| 17 | `Comments` | varchar(max) | YES |
| 18 | `DateReceived` | date | YES |
| 19 | `TimeReceived` | time | YES |
| 20 | `UpdatingUser` | varchar(255) | YES |
| 21 | `UpdatingMachine` | varchar(255) | YES |

---

## How the workbook macros use these tables

**`POP10110`** — searched 14 columns: `PONUMBER, LINENUMBER, ITEMNMBR, ITEMDESC, VENDORID, LOCNCODE, QTYORDER, UNITCOST, EXTDCOST, JOBNUMBR, COSTCODE, CURNCYID, XCHGRATE, ORIGPRMDATE`. Filtered with `LIKE '%...%'` on text columns; date filter on `ORIGPRMDATE`. Cross-DB UNION across `UBC.dbo.POP10110` and `UCSH.dbo.POP10110` from the `master` connection.

**`WHRECLINE101`** — joined to POP10110 via `PONUMBER` + `POLNENUM` (where `POLNENUM = LINENUMBER * 16384` — GP's internal line-number scaling). Pulls 5 receipt fields per row: `QuantityReceived, POPRCTNM, DateReceived, UpdatingUser, Location`. Multiple receipts per PO line are pivoted into wide columns (`Rec Qty 1, Receipt No. 1, ...`).

**`POP30000`** — full-table dump (`SELECT * ORDER BY <date_field> DESC`). Note: only 5 columns — likely a customized/trimmed copy, not the standard GP POP30000 (which has ~70 cols).

**`POP30300`** — TOP 50 sample dump (`ORDER BY POPRCTNM DESC`). Receipt header.


