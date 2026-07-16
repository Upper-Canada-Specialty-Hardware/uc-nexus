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
    class PopTransaction
    {
        //public static bool RunPoCreate(ref ObservableCollection<dc.PurchaseOrderLineItem> recLines)
        public static bool RunPoCreate()
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
                for voided POs.]
            */
            bool _compl = false;
            string _poNum = "";

            using (eConnectMethods eConCall = new eConnectMethods())
            {
                try
                {
                    string sConnectionString = @"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=TUCSH;Integrated Security=SSPI;"; //GlobalVars.GpConnectionString; 
                    _poNum = GetPoNumGp();
                    ObservableCollection<dc.PurchaseOrderLineItem> _poLines = GenerateDummyPoData();
                    SerializePoReceiptObjects("PoRecLines.xml", sConnectionString, _poLines, _poNum);

                    XmlDocument xmldoc = new XmlDocument();
                    xmldoc.Load("PoRecLines.xml");

                    string purchaseOrderDocument = xmldoc.OuterXml;
                    string purchaseOrder = eConCall.CreateTransactionEntity(sConnectionString, purchaseOrderDocument);
                    //purch order number goes here
                    if (VerifyPoCreation(_poNum) == false)
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
                        RollBackRecNumGp(_poNum);

                    eConCall.Dispose();
                }
                return _compl;
            }
        }

        private static void SerializePoReceiptObjects(string filename, string connStr, ObservableCollection<dc.PurchaseOrderLineItem> poLines, string poNum)
        {
            try
            {

                //taPopRcptLineInsert_ItemsTaPopRcptLineInsert[] _lineItems = new taPopRcptLineInsert_ItemsTaPopRcptLineInsert[recLines.Count]; //non-zero based when setting the number of array entries.
                //int _rcptLnm = 16384;

                taPoLine_ItemsTaPoLine[] _lineItems = new taPoLine_ItemsTaPoLine[poLines.Count];
                int _order = 16384;

                for (int x = 0; x <= poLines.Count - 1; x++)
                {
                    if (poLines[x].QuantityOrdered > 0)
                    {
                        taPoLine_ItemsTaPoLine poLine = new taPoLine_ItemsTaPoLine();

                        poLine.POTYPE = 1;  //POP10500 has a type of 2 yet for eConnect it only allows 1 or 3....
                         
                        //poLine.ORD = poLines[x].Order;
                        //poRecLine.CostCatID = "210-200-2";
                        poLine.RequesterTrx = 1;
                        //poRecLine.CURNCYID = "CAD";
                        poLine.LOCNCODE = "MARKHAM";
                        
                        poLines[x].PoNumber = poNum; //"RCT061198"; 
                        poLines[x].Order = _order;

                        poLine.PONUMBER = poLines[x].PoNumber; //"PO030518";
                        poLine.ITEMNMBR = poLines[x].ItemNumber; //"BAL 0465.040";
                        poLine.ITEMDESC = poLines[x].ItemDescription;
                        poLine.VENDORID = poLines[x].VendorId; //"BAL150";
                        poLine.VNDITNUM = poLines[x].ItemNumber; //"BAL 0465.040";        //should be the same as item number.  Assuming 1:1 relationship.
                        poLine.UNITCOST = 0;// poLines[x].UnitCost; //0

                        poLine.QUANTITY = poLines[x].QuantityOrdered;
                        poLine.NONINVEN = Convert.ToInt16(poLines[x].NonInventory);


                        if (poLines[x].Polnesta < 4)
                        {
                            _lineItems[x] = poLine;
                            _order = _order + 16384;
                        }
                    }
                }

                taPoHdr _header = new taPoHdr();
                _header.POTYPE = 1;
                _header.PONUMBER = poLines[0].PoNumber;
                _header.DOCDATE = DateTime.Today.ToString("yyyy/MM/dd");
                //_header.BACHNUMB = "EC-" + DateTime.Today.ToString("yyyy/MM/dd");
                _header.VENDORID = poLines[0].VendorId;
                _header.SUBTOTAL = 0;


                POPTransactionType _poRecType = new POPTransactionType();
                _poRecType.taPoHdr = _header;
                _poRecType.taPoLine_Items = _lineItems;

                POPTransactionType[] _poTransArr = { _poRecType };

                eConnectType _eConnect = new eConnectType();
                _eConnect.POPTransactionType = _poTransArr;

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

        private static string GetPoNumGp()
        {
            //string TARGET_DB = GlobalVars.GpDatabaseName;
            string TARGET_DB = "TUCSH";
            GetNextDocNumbers _getNextDoc = new GetNextDocNumbers();
            string _poNum = "";
            string connStr = @"data source=UCSHSQL2\MSSQL2014;initial catalog=" + TARGET_DB + ";integrated security=SSPI;persist security info=False;packet size=4096";

            try
            {
                _poNum = _getNextDoc.GetNextPONumber(IncrementDecrement.Increment, connStr);
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
            return _poNum;
        }

        private static void RollBackRecNumGp(string _poNum)
        {
            //string TARGET_DB = GlobalVars.GpDatabaseName;
            string TARGET_DB = "TUCSH";
            GetNextDocNumbers _getNextDoc = new GetNextDocNumbers();
            string connStr = @"data source=UCSHSQL2\MSSQL2014;initial catalog=" + TARGET_DB + ";integrated security=SSPI;persist security info=False;packet size=4096";

            try
            {
                _getNextDoc.GetNextPONumber(IncrementDecrement.Decrement, connStr);
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

        private static bool VerifyPoCreation(string poNum)
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext tempdtCtx = new lq.DataContext(@"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=TUCSH;Integrated Security=SSPI;");
            // @"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=TUCSH;Integrated Security=SSPI;"
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(@"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=TUCSH;Integrated Security=SSPI;", um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<string> recList = null;

            try
            {
                var offerQuery = from recs in dtCtx.GetTable<gp.Pop10110>()
                                 where recs.PoNumber == poNum
                                 select new
                                 {
                                     PoNumber = recs.PoNumber
                                 };

                recList = offerQuery.AsEnumerable().Select(x => x.PoNumber).ToList();

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
                MessageBox.Show("GP did not actually create this receipt number - " + poNum);
                return false;
            }
            else
                return true;
        }

        public static ObservableCollection<dc.PurchaseOrderLineItem> GenerateDummyPoData()
        {
            ObservableCollection<dc.PurchaseOrderLineItem> _poList = new ObservableCollection<dc.PurchaseOrderLineItem>();
            dc.PurchaseOrderLineItem _poItemOne = new dc.PurchaseOrderLineItem();
            dc.PurchaseOrderLineItem _poItemTwo = new dc.PurchaseOrderLineItem();

            _poItemOne.Order = 16384;
            _poItemOne.QuantityOrdered = 1;
            _poItemOne.VendorId = "GAL100";
            _poItemOne.ItemDescription = "Test Item Line 1";
            _poItemOne.ItemNumber = "NONSTOCKHD";
            _poItemOne.NonInventory = true;

            _poItemTwo.Order = 32768;
            _poItemTwo.QuantityOrdered = 1;
            _poItemTwo.VendorId = "GAL100";
            _poItemTwo.ItemDescription = "Test Item Line 2";
            _poItemTwo.ItemNumber = "NONSTOCKHD";
            _poItemTwo.NonInventory = true;

            _poList.Add(_poItemOne);
            _poList.Add(_poItemTwo);

            return _poList;
        }
    }
}
