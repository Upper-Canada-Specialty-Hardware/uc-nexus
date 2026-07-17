using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using Microsoft.Dynamics.GP.eConnect;
using Microsoft.Dynamics.GP.eConnect.Serialization;
using System.Xml;
using System.Xml.Serialization;
using System.IO;
using System.Data.SqlClient;
using System.Windows;
using System.Collections.ObjectModel;
using dc = PM_Project_Tracking.DataClasses;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;


namespace PM_Project_Tracking.EConnect
{
    class PopRcptLineInsert
    {
        public static bool RunEconnect(ref ObservableCollection<dc.ReceivingLine> recLines, WarehouseReceiptType whType)
        {
            //https://community.dynamics.com/gp/f/32/t/112307
            //http://threads536.rssing.com/chan-4210285/all_p753.html

            //READ -> https://community.dynamics.com/gp/f/32/t/112298 //STATGRP field?


            //https://dynamicserppros.com/solving-microsoft-dynamics-gps-unable-enter-invoice-po-receipt-issue/


            /*
              https://victoriayudin.com/gp-tables/pop-tables/
                STATGRP (Status Group):
                0 – Voided [this is not a valid according to the SDK, but we have seen it for voided PO’s]
                1 – Active (includes New, Open and Modified)
                2 – Closed (includes Cancelled and Closed)

                [Note: In our experience, when a PO is voided and it moves to the history tables, in POP30100 the STATGRP will be 1 or 0 
                whereas for a regularly closed PO the STATGRP will be 2. Also, there is a value starting with POPVT in TRXSORCE of POP30100 
                for voided PO’s.]
            */
            bool _compl = false;
            string _receiptNum = "";

            using (eConnectMethods eConCall = new eConnectMethods())
            {
                try
                {
                    string sConnectionString = GlobalVars.GpConnectionString;  //@"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=TEST;Integrated Security=SSPI;";  
                    _receiptNum = GetReceiptNumGp();
                    SerializePoReceiptObjects("PoRecLines.xml", sConnectionString, recLines, _receiptNum, whType);

                    XmlDocument xmldoc = new XmlDocument();
                    xmldoc.Load("PoRecLines.xml");

                    string purchaseOrderDocument = xmldoc.OuterXml;
                    string purchaseOrder = eConCall.CreateTransactionEntity(sConnectionString, purchaseOrderDocument);
                    //purch order number goes here
                    if (VerifyReceiptCreation(_receiptNum) == false)
                        return false;

                    _compl = true;
                }
                catch (eConnectException exp)
                {
                    MessageBox.Show(exp.ToString());
                }
                catch (SqlException sqlEx)
                {
                    MessageBox.Show(sqlEx.ToString());
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
                finally
                {
                    if (_compl == false)
                        RollBackRecNumGp(_receiptNum);

                    eConCall.Dispose();
                }
                return _compl;
            }
        }

        private static void SerializePoReceiptObjects(string filename, string connStr, ObservableCollection<dc.ReceivingLine> recLines, string popRecNum, WarehouseReceiptType whType)
        {
            try
            {
                string _locnCode = recLines[0].LocnCode;
                taPopRcptLineInsert_ItemsTaPopRcptLineInsert[] _lineItems = new taPopRcptLineInsert_ItemsTaPopRcptLineInsert[recLines.Count]; //non-zero based when setting the number of array entries.
                int _rcptLnm = 16384;
                
                for (int x = 0; x <= recLines.Count - 1; x++)
                {
                    if (recLines[x].QtyRecForGp > 0)
                    {
                        taPopRcptLineInsert_ItemsTaPopRcptLineInsert poRecLine = new taPopRcptLineInsert_ItemsTaPopRcptLineInsert();
                        
                        poRecLine.POPTYPE = 1;  //POP10500 has a type of 2 yet for eConnect it only allows 1 or 3....
                        poRecLine.POPRCTNM = popRecNum;
                        //poRecLine.RCPTLNNM = 0;

                        poRecLine.POLNENUM = recLines[x].Polnenum;
                        //poRecLine.CostCatID = "210-200-2";
                        poRecLine.RequesterTrx = 1;
                        //poRecLine.CURNCYID = "CAD";
                        poRecLine.LOCNCODE = _locnCode; // "MARKHAM";
                        poRecLine.JOBNUMBR = recLines[x].JobNumber;

                        recLines[x].PopRctNum = popRecNum; //"RCT061198"; 
                        recLines[x].RcptLnNm = _rcptLnm;
                        poRecLine.PONUMBER = recLines[x].PoNumber; //"PO030518";
                        poRecLine.ITEMNMBR = recLines[x].ItemNumber; //"BAL 0465.040";
                        poRecLine.VENDORID = recLines[x].VendorId; //"BAL150";
                        poRecLine.VNDITNUM = recLines[x].ItemNumber; //"BAL 0465.040";        //should be the same as item number.  Assuming 1:1 relationship.
                        poRecLine.AUTOCOST = 1;
                        poRecLine.UNITCOST = 0;// recLines[x].UnitCost; //0
                        poRecLine.EXTDCOST = 0;// recLines[x].UnitCost * recLines[x].QtyRecForGp; //0
                        //poRecLine.JOBNUMBR = ""; //not on this po
                        poRecLine.QTYSHPPD = recLines[x].QtyRecForGp; //1;     //make sure quantity shipped does not exceed the original order for the line.
                        //poRecLine.QTYINVCD = recLines[x].QtyRecForGp;// 0;  // poptype is 1 (shipment only, no invoice) so not a required field.
                        poRecLine.POLNENUM = recLines[x].Polnenum;  //32768;
                        poRecLine.NONINVEN = recLines[x].NonInventory;

                        //poRecLine.Landed_Cost_Group_ID = "MISC";
                        poRecLine.receiptdate = DateTime.Today.ToString("yyyy/MM/dd");
                        if (recLines[x].Polnesta < 4)
                        {
                            _lineItems[x] = poRecLine;
                            _rcptLnm = _rcptLnm + 16384;
                        }
                    }
                }

                taPopRcptHdrInsert _header = new taPopRcptHdrInsert();
                _header.POPRCTNM = popRecNum;
                _header.POPTYPE = 1;
                _header.VNDDOCNM = recLines[0].PoNumber;
                _header.receiptdate = DateTime.Today.ToString("yyyy/MM/dd");
                if (whType != WarehouseReceiptType.Showroom)
                    _header.BACHNUMB = "EC-" + DateTime.Today.ToString("yyyy/MM/dd");
                else
                    _header.BACHNUMB = "SH-" + DateTime.Today.ToString("yyyy/MM/dd");

                _header.VENDORID = recLines[0].VendorId; //"BAL150";
                _header.SUBTOTAL = 0;
                //_header.AUTOCOST = 1;
                //_header.CREATEDIST = 1;
                //_header.RequesterTrx = 1;


                POPReceivingsType _poRecType = new POPReceivingsType();
                _poRecType.taPopRcptHdrInsert = _header;
                _poRecType.taPopRcptLineInsert_Items = _lineItems;

                POPReceivingsType[] _poTransArr = { _poRecType };

                eConnectType _eConnect = new eConnectType();
                _eConnect.POPReceivingsType = _poTransArr;

                FileStream fs = new FileStream(filename, FileMode.Create);
                XmlTextWriter writer = new XmlTextWriter(fs, new UTF8Encoding());
                XmlSerializer serializer = new XmlSerializer(_eConnect.GetType());
                serializer.Serialize(writer, _eConnect);
                writer.Close();

            }
            catch (eConnectException ecEx)
            {
                MessageBox.Show(ecEx.ToString());
            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
            }
        }

        private static string GetReceiptNumGp()
        {
            //Getting Receipt document numbers from eConnect
        //string TARGET_DB = Properties.Settings.Default.InitCatalog;
            string TARGET_DB = GlobalVars.CurrentGpDatabaseName;
            GetNextDocNumbers _getNextDoc = new GetNextDocNumbers();
            string _popRcptNum = "";
            string connStr = @"data source=UCSHSQL2\MSSQL2014;initial catalog=" + TARGET_DB + ";integrated security=SSPI;persist security info=False;packet size=4096";
            //string connStr = @"Data Source=UCSHSQL\MSSQL2014;Initial Catalog=TEST;Integrated Security=SSPI;";

            try
            {
                _popRcptNum = _getNextDoc.GetNextPOPReceiptNumber(IncrementDecrement.Increment, connStr);
            }
            catch (SqlException sqlEx)
            {
                throw new Exception(sqlEx.ToString());
            }
            catch (eConnectException exp)
            {
                throw new Exception(exp.ToString());
            }
            catch (Exception ex)
            {
                throw new Exception(ex.ToString());
            }
            finally
            {
                _getNextDoc.Dispose();
            }
            return _popRcptNum;
        }

        private static void RollBackRecNumGp(string _popRctNum)
        {
            ////Would pass a document number through this method to _rollBack
            //RollBackDocument _rollBack = new RollBackDocument(TransactionType.POPReceipt, 0, _docNumGoesHere);
            string TARGET_DB = GlobalVars.CurrentGpDatabaseName;
            GetNextDocNumbers _getNextDoc = new GetNextDocNumbers();
            string connStr = @"data source=UCSHSQL2\MSSQL2014;initial catalog=" + TARGET_DB + ";integrated security=SSPI;persist security info=False;packet size=4096";
            //string connStr = @"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=TEST;Integrated Security=SSPI;";

            try
            {
                _getNextDoc.GetNextPOPReceiptNumber(IncrementDecrement.Decrement, connStr);
                //RollBackDocument asdf = new RollBackDocument(TransactionType.POPReceipt, 1, "asdf");
            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (eConnectException exp)
            {
                MessageBox.Show(exp.ToString());
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                _getNextDoc.Dispose();
            }
        }

        private static bool VerifyReceiptCreation(string receiptNum)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));        
            List<string> recList = null;

            try
            {
                var offerQuery = from recs in dtCtx.GetTable<gp.Pop10500>()
                                 where recs.PopRctNum == receiptNum
                                 //where recs.PopRctNum == "asdfasdfadsf"
                                 select new
                                 {
                                     PopRctNum = recs.PopRctNum
                                 };

                recList = offerQuery.AsEnumerable().Select(x => x.PopRctNum).ToList();

            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (eConnectException exp)
            {
                MessageBox.Show(exp.ToString());
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            if (recList.Count == 0)
            {
                MessageBox.Show("GP did not actually create this receipt number - " +  receiptNum);
                return false;
            }
            else
                return true;
        }
    }
}
