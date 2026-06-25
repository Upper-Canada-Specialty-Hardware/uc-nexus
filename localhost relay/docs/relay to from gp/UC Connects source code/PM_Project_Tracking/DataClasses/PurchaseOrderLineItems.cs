using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using PM_Project_Tracking.DataClasses.Interfaces;
using System.ComponentModel;
using System.Collections.Specialized;
using System.Reflection;

namespace PM_Project_Tracking.DataClasses
{
    class PurchaseOrderLineItems
    {
        internal static ObservableCollection<PurchaseOrderLineItem> GetAllPurchaseOrdersWithReceipts()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<PurchaseOrderLineItem> purchOrderList = null;

            //System.Diagnostics.Stopwatch asdf = new System.Diagnostics.Stopwatch();
            //asdf.Start();

            try
            {
                var sopUnion = (from c in dtCtx.GetTable<gp.Sop10100>() select new { c.SopNumber, c.SopType, c.OriginNumber, c.CustomerNumber, c.CustomerName }).Union(
                                (from d in dtCtx.GetTable<gp.Sop30200>() select new { d.SopNumber, d.SopType, d.OriginNumber, d.CustomerNumber, d.CustomerName }));

                //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Shipping, Hardware and Order Tracking Module\Hardware PO Retrieval\POP10110 annotated LEAN reconfig RTL col v5 - simplified version.sql
                var purchOrderQuery = from poLine in dtCtx.GetTable<gp.Pop10110>()
                                      join hdr in dtCtx.GetTable<gp.Pop10100>() on poLine.PoNumber equals hdr.PoNumber into fulla
                                      from hdr in fulla.DefaultIfEmpty()
                                      join hdrComms in dtCtx.GetTable<gp.Pop10150>() on poLine.PoNumber equals hdrComms.PoNumber into fullz
                                      from hdrComms in fullz.DefaultIfEmpty()
                                      join jc in dtCtx.GetTable<gp.Jc00102>() on poLine.JobNumber equals jc.JobNumber into fullb
                                      from jc in fullb.DefaultIfEmpty()
                                      join pays in dtCtx.GetTable<gp.Pm00200>() on poLine.VendorId equals pays.VendorId into fullc
                                      from pays in fullc.DefaultIfEmpty()
                                      join comms in dtCtx.GetTable<gp.Pop10550>() on new { poLine.PoNumber, poLine.Order } equals new { comms.PoNumber, comms.Order } into fulld
                                      from comms in fulld.DefaultIfEmpty()
                                      //join wsLine in dtCtx.GetTable<gp.Ws10101>() on new { poLine.PoNumber, poLine.Order } equals new { wsLine.PoNumber, wsLine.Order }
                                      join poRec in dtCtx.GetTable<gp.Pop10500>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = poRec.PoNumber, b = poRec.Polnenum } into fullr
                                      from poRec in fullr.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum})
                                      join sop in dtCtx.GetTable<gp.Sop60100>().Distinct() on new { poLine.PoNumber, poLine.Order } equals new { sop.PoNumber, sop.Order } into fulltwo
                                      from sop in fulltwo.DefaultIfEmpty()
                                      join sopAll in sopUnion on sop.SopNumber equals sopAll.SopNumber into fullthree
                                      from sopAll in fullthree.DefaultIfEmpty()
                                      join shipLine in dtCtx.GetTable<ShippingLine>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = shipLine.PoNumber, b = shipLine.Polnenum } into fullShip
                                      from shipLine in fullShip.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum })
                                      //join ucPoHdrCom in dtCtx.GetTable<PoUcshHeaderComment>() on poLine.PoNumber equals ucPoHdrCom.PoNumber into fullFour
                                      //from ucPoHdrCom in fullFour.DefaultIfEmpty()
                                      //join ucPoLineCom in dtCtx.GetTable<PoUcshLineComment>() on new { poLine.PoNumber, poLine.Order } equals new { ucPoLineCom.PoNumber, ucPoLineCom.Order } into fullFive
                                      //from ucPoLineCom in fullFive.DefaultIfEmpty()
                                      where poLine.LocationCode != "SHOWROOM" //&& poLine.PoNumber == "PO042857" 
                                      orderby poLine.PoNumber descending, poLine.LineNumber
                                      select new
                                      {
                                          PoNumber = poLine.PoNumber.Trim(),
                                          Order = poLine.Order,
                                          JobNumber = poLine.JobNumber.Trim(),
                                          JobName = jc.JobName.Trim(),
                                          SopNumber = sop.SopNumber.Trim(),
                                          BuyerId = hdr.BuyerId.Trim(),
                                          ChangeId = hdr.AddressThree.Trim(),
                                          VendorId = poLine.VendorId.Trim(),
                                          VendorName = pays.VendorName.Trim(),
                                          LineNumber = poLine.LineNumber,
                                          Polnesta = poLine.Polnesta,
                                          ItemNumber = poLine.ItemNumber.Trim(),
                                          ItemDescription = poLine.ItemDescription.Trim(),
                                          QuantityOrdered = poLine.QtyOrder,
                                          QuantityShipped = fullr.Select(x => x.QuantityShipped).Sum(),  //This is actually quantity received
                                          QuantityMatched = fullr.Select(x => x.QuantityMatched).Sum(), //0, //poRec.Key.QuantityMatched,
                                          //QuantityInvoiced = poRec.QuantityInvoiced,
                                          //QuantityInvoiced = wsLine.QuantityInvoiced,
                                          QuantityActualShippped = fullShip.Select(x => x.QuantityShipped).Sum() == null ? 0 : fullShip.Select(x => x.QuantityShipped).Sum(),
                                          FirstReceiveDate = poLine.FirstReceiveDate,
                                          LastReceiveDate = poLine.LastReceiveDate,
                                          LocationCode = poLine.LocationCode.Trim(),
                                          CostCode = poLine.CostCode.Trim(),
                                          RequiredDate = poLine.RequiredDate,
                                          PromisedShipDate = poLine.PromisedShipDate,
                                          LineCommentText = comms.CmmtText,
                                          HeaderCommentText = hdrComms.CommentText.ToString().Replace("\r"," ").Replace("\n"," "),
                                          CustomerName = sopAll.CustomerName,

                                          //UcHeaderCommentText = dtCtx.GetTable<PoUcshHeaderComment>().Where(n => n.PoNumber == poLine.PoNumber).ToList(), //new List<string>(), // 
                                          //UcLineCommentText = dtCtx.GetTable<PoUcshLineComment>().Where(n => n.PoNumber == poLine.PoNumber && n.Order == poLine.Order).ToList()// ucLineCom.CommentText
                                          //UcHeaderCommentText = new ObservableCollection<PoUcshHeaderComment>(),
                                          //UcLineCommentText = new ObservableCollection<PoUcshLineComment>() 
                                          UcHeaderHasComments = dtCtx.GetTable<PoUcshHeaderComment>().Where(n => n.PoNumber == poLine.PoNumber).Count() > 0,
                                          UcLineHasComments = dtCtx.GetTable<PoUcshLineComment>().Where(n => n.PoNumber == poLine.PoNumber && n.Order == poLine.Order).Count() > 0
                                      };

                purchOrderList = purchOrderQuery.AsEnumerable().Select(x => new PurchaseOrderLineItem(x.PoNumber, x.Order, x.JobNumber, x.JobName, x.SopNumber,  x.BuyerId,
                                                                x.ChangeId, x.VendorId, x.VendorName, x.LineNumber, x.Polnesta, x.ItemNumber,
                                                                x.ItemDescription, Convert.ToInt32(x.QuantityOrdered), Convert.ToInt32(x.QuantityShipped),
                                                                Convert.ToInt32(x.QuantityMatched),
                                                                Convert.ToInt32(x.QuantityActualShippped),
                                                                x.FirstReceiveDate, x.LastReceiveDate, x.LocationCode, x.CostCode, x.RequiredDate,
                                                                x.PromisedShipDate, x.LineCommentText,
                                                                x.HeaderCommentText == null ? "" : x.HeaderCommentText,
                                                                x.CustomerName
                                                                , null //x.UcHeaderCommentText
                                                                , null // x.UcLineCommentText
                                                                , x.UcHeaderHasComments
                                                                , x.UcLineHasComments
                                                                )).ToList();
                                                                //)).Where(r => (r.QuantityOrdered != r.QuantityReceived) && (r.QuantityReceived != 0)).ToList();
                
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<PurchaseOrderLineItem>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            //PurchaseOrderLineItem.FillUcCommentCollections(purchOrderList);

            //asdf.Stop();
            //MessageBox.Show(asdf.Elapsed.Seconds.ToString());

            return new ObservableCollection<PurchaseOrderLineItem>(purchOrderList);
        }

        internal static ObservableCollection<PurchaseOrderLineItem> GetAllPurchaseOrderLinesByProject(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<PurchaseOrderLineItem> purchOrderList = null;

            try
            {
                var sopUnion = (from c in dtCtx.GetTable<gp.Sop10100>() select new { c.SopNumber, c.SopType, c.OriginNumber, c.CustomerNumber, c.CustomerName }).Union(
                               (from d in dtCtx.GetTable<gp.Sop30200>() select new { d.SopNumber, d.SopType, d.OriginNumber, d.CustomerNumber, d.CustomerName }));

                //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Shipping, Hardware and Order Tracking Module\Hardware PO Retrieval\POP10110 annotated LEAN reconfig RTL col v5 - simplified version.sql
                var purchOrderQuery = from poLine in dtCtx.GetTable<gp.Pop10110>()
                                      join hdr in dtCtx.GetTable<gp.Pop10100>() on poLine.PoNumber equals hdr.PoNumber into fulla
                                      from hdr in fulla.DefaultIfEmpty()
                                      join hdrComms in dtCtx.GetTable<gp.Pop10150>() on poLine.PoNumber equals hdrComms.PoNumber into fullz
                                      from hdrComms in fullz.DefaultIfEmpty()
                                      join jc in dtCtx.GetTable<gp.Jc00102>() on poLine.JobNumber equals jc.JobNumber into fullb
                                      from jc in fullb.DefaultIfEmpty()
                                      join pays in dtCtx.GetTable<gp.Pm00200>() on poLine.VendorId equals pays.VendorId into fullc
                                      from pays in fullc.DefaultIfEmpty()
                                      join comms in dtCtx.GetTable<gp.Pop10550>() on new { poLine.PoNumber, poLine.Order } equals new { comms.PoNumber, comms.Order } into fulld
                                      from comms in fulld.DefaultIfEmpty()
                                      //join wsLine in dtCtx.GetTable<gp.Ws10101>() on new { poLine.PoNumber, poLine.Order } equals new { wsLine.PoNumber, wsLine.Order }
                                      join poRec in dtCtx.GetTable<gp.Pop10500>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = poRec.PoNumber, b = poRec.Polnenum } into fullr
                                      from poRec in fullr.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum })
                                      join sop in dtCtx.GetTable<gp.Sop60100>().Distinct() on new { poLine.PoNumber, poLine.Order } equals new { sop.PoNumber, sop.Order } into fulltwo
                                      from sop in fulltwo.DefaultIfEmpty()
                                      join sopAll in sopUnion on sop.SopNumber equals sopAll.SopNumber into fullthree
                                      from sopAll in fullthree.DefaultIfEmpty()
                                      join shipLine in dtCtx.GetTable<ShippingLine>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = shipLine.PoNumber, b = shipLine.Polnenum } into fullShip
                                      from shipLine in fullShip.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum })
                                      where poLine.LocationCode != "SHOWROOM" && poLine.JobNumber == jobNumber
                                      orderby poLine.PoNumber descending, poLine.LineNumber
                                      select new
                                      {
                                          PoNumber = poLine.PoNumber.Trim(),
                                          Order = poLine.Order,
                                          JobNumber = poLine.JobNumber.Trim(),
                                          JobName = jc.JobName.Trim(),
                                          SopNumber = sop.SopNumber.Trim(),
                                          BuyerId = hdr.BuyerId.Trim(),
                                          ChangeId = hdr.AddressThree.Trim(),
                                          VendorId = poLine.VendorId.Trim(),
                                          VendorName = pays.VendorName.Trim(),
                                          LineNumber = poLine.LineNumber,
                                          Polnesta = poLine.Polnesta,
                                          ItemNumber = poLine.ItemNumber.Trim(),
                                          ItemDescription = poLine.ItemDescription.Trim(),
                                          QuantityOrdered = poLine.QtyOrder,
                                          QuantityShipped = fullr.Select(x => x.QuantityShipped).Sum(),  //This is actually quantity received
                                          QuantityMatched = fullr.Select(x => x.QuantityMatched).Sum(), //0, //poRec.Key.QuantityMatched,
                                          //QuantityInvoiced = poRec.QuantityInvoiced,
                                          //QuantityInvoiced = wsLine.QuantityInvoiced,
                                          QuantityActualShippped = fullShip.Select(x => x.QuantityShipped).Sum() == null ? 0 : fullShip.Select(x => x.QuantityShipped).Sum(),
                                          FirstReceiveDate = poLine.FirstReceiveDate,
                                          LastReceiveDate = poLine.LastReceiveDate,
                                          LocationCode = poLine.LocationCode.Trim(),
                                          CostCode = poLine.CostCode.Trim(),
                                          RequiredDate = poLine.RequiredDate,
                                          PromisedShipDate = poLine.PromisedShipDate,
                                          LineCommentText = comms.CmmtText,
                                          HeaderCommentText = hdrComms.CommentText.ToString().Replace("\r", " ").Replace("\n", " "),
                                          CustomerName = sopAll.CustomerName
                                      };

                purchOrderList = purchOrderQuery.AsEnumerable().Select(x => new PurchaseOrderLineItem(x.PoNumber, x.Order, x.JobNumber, x.JobName, x.SopNumber, x.BuyerId,
                                                                x.ChangeId, x.VendorId, x.VendorName, x.LineNumber, x.Polnesta, x.ItemNumber,
                                                                x.ItemDescription, Convert.ToInt32(x.QuantityOrdered), Convert.ToInt32(x.QuantityShipped),
                                                                Convert.ToInt32(x.QuantityMatched),
                                                                Convert.ToInt32(x.QuantityActualShippped),
                                                                x.FirstReceiveDate, x.LastReceiveDate, x.LocationCode, x.CostCode, x.RequiredDate,
                                                                x.PromisedShipDate, x.LineCommentText, 
                                                                x.HeaderCommentText == null ? "" : x.HeaderCommentText, 
                                                                x.CustomerName,
                                                                null, null, false, false)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<PurchaseOrderLineItem>(purchOrderList);
        }
    }

    [mp.Table]      //Should allow us to ignore non-decorated properties now: https://stackoverflow.com/questions/8412430/how-do-i-exclude-a-member-from-linq-to-sql-mapping
    public class PurchaseOrderLineItem : INotifyPropertyChanged
    {
        private string _poNumber;
        private int _order;
        private string _jobFolder;
        private string _jobNumber;
        private string _jobName;
        private string _sopNumber;
        private string _buyerId;
        private string _changeId;
        private string _vendorId;
        private string _vendorName;
        private short _lineNumber;
        private short _polnesta;
        private string _lineStatus;
        private string _itemNumber;
        private string _itemDescription;
        private bool _nonInventory;     //Not initialized in any of the constructors, only used in eConnect procedure
        private int _quantityOrdered;
        private int _quantityReceived;
        private int _quantityMatched;
        private int _quantityInvoiced;
        private int _backOrder;
        private int _quantityShipped;
        private DateTime? _poCreationDate;
        private DateTime? _firstReceiveDate;
        private DateTime? _lastReceiveDate;
        private string _locationCode;
        private string _costCode;
        private DateTime? _requiredDate;
        private DateTime? _promisedShipDate;
        private string _lineCmmtText;
        private string _headerCmmtText;
        private string _customerName;
        private string _ucLineComment;
        private string _ucHeaderComment;

        private bool _ucHeaderHasComments;
        private bool _ucLineHasComments;

        private ObservableCollection<PoUcshHeaderComment> _ucHeaderCommentCol = new ObservableCollection<PoUcshHeaderComment>();
        private ObservableCollection<PoUcshLineComment> _ucLineCommentCol = new ObservableCollection<PoUcshLineComment>();

        //[CustTypeAtt(typeof(String))]
        [Order((int)ValEnum.poNumber)]
        [mp.Column(DbType = "char(17)", Name = "PONUMBER")]
        public string PoNumber                  //1
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [Order((int)ValEnum.order)]
        [mp.Column(DbType = "int", Name = "ORD")]
        public int Order                        //2
        {
          get { return _order; }
          set { _order = value; }
        }


        [mp.Column(DbType = "char", Name = "JobFolder")]
        public string JobFolder
        {
            get
            {
                return _jobFolder;
            }

            set
            {
                _jobFolder = value;
            }
        }


        [Order((int)ValEnum.jobNumber)]
        [mp.Column(DbType = "char(17)", Name = "JOBNUMBR")]
        public string JobNumber                 //3
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [Order((int)ValEnum.jobName)]
        [mp.Column(DbType = "char(31)", Name = "WS_Job_Name")]
        public string JobName                   //4
        {
            get { return _jobName; }
            set { _jobName = value; }
        }

        [Order((int)ValEnum.sopNumber)]
        [mp.Column(DbType = "char", Name = "SOPNUMBE")]
        public string SopNumber                 //5
        {
            get { return _sopNumber; }
            set { _sopNumber = value; }
        }

        [Order((int)ValEnum.buyerId)]
        [mp.Column(DbType = "char(15)", Name = "BUYERID")]
        public string BuyerId                   //6
        {
            get { return _buyerId; }
            set { _buyerId = value; }
        }

        [Order((int)ValEnum.changeId)]
        [mp.Column(DbType = "char", Name = "ChangeId")]
        public string ChangeId
        {
            get { return _changeId; }
            set { _changeId = value; }
        }

        [Order((int)ValEnum.vendorId)]
        [mp.Column(DbType = "char(15)", Name = "VENDORID")]
        public string VendorId                  //7
        {
            get { return _vendorId; }
            set { _vendorId = value; }
        }

        [Order((int)ValEnum.vendorName)]
        [mp.Column(DbType = "char(65)", Name = "VENDNAME")]
        public string VendorName                //8
        {
            get { return _vendorName; }
            set { _vendorName = value; }
        }

        [Order((int)ValEnum.lineNumber)]
        [mp.Column(DbType = "smallint", Name = "LineNumber")]
        public short LineNumber                 //9
        {
            get { return _lineNumber; }
            set { _lineNumber = value; }
        }

        [Order((int)ValEnum.polnesta)]
        [mp.Column(DbType = "smallint", Name = "POLNESTA")]
        public short Polnesta                   //10
        {
            get { return _polnesta; }
            set
            {
                _polnesta = value;
                switch (value)
                {
                    case 1:
                        this._lineStatus = "New";
                        break;
                    case 2:
                        this._lineStatus = "Released";
                        break;
                    case 3:
                        this._lineStatus = "Change Order";
                        break;
                    case 4:
                        this._lineStatus = "Received";
                        break;
                    case 5:
                        this._lineStatus = "Closed";
                        break;
                    case 6:
                        this._lineStatus = "Cancelled";
                        break;
                }

            }
        }

        [Order((int)ValEnum.lineStatus)]
        public string LineStatus
        {
            get
            {
                return _lineStatus;
            }

            set
            {
                _lineStatus = value;
            }
        }

        [Order((int)ValEnum.itemNumber)]
        [mp.Column(DbType = "char(31)", Name = "ITEMNMBR")]
        public string ItemNumber                //11
        {
            get { return _itemNumber; }
            set { _itemNumber = value; }
        }

        [Order((int)ValEnum.itemDescription)]
        [mp.Column(DbType = "char(101)", Name = "ITEMDESC")]
        public string ItemDescription           //12
        {
            get { return _itemDescription; }
            set { _itemDescription = value; }
        }

        [Order((int)ValEnum.nonInventory)]
        public bool NonInventory
        {
            get { return _nonInventory; }
            set { _nonInventory = value; }
        }

        [Order((int)ValEnum.quantityOrdered)]
        [mp.Column(DbType = "numeric(19,5)", Name = "QTYORDER")]
        public int QuantityOrdered              //13
        {
            get { return _quantityOrdered; }
            set { _quantityOrdered = value; }
        }

        [Order((int)ValEnum.quantityReceived)]
        [mp.Column(DbType = "int", Name = "QTYREC")]
        public int QuantityReceived             //14
        {
            get { return _quantityReceived; }
            set { _quantityReceived = value; }
        }

        [Order((int)ValEnum.quantityMatched)]                   //-NOT USED IN STORED FUNCTION
        public int QuantityMatched
        {
            get { return _quantityMatched; }
            set { _quantityMatched = value; }
        }

        [Order((int)ValEnum.quantityInvoiced)]
        [mp.Column(DbType = "numeric(19,5)", Name = "QTYINVCD")]
        public int QuantityInvoiced             //15
        {
            get { return _quantityInvoiced; }
            set { _quantityInvoiced = value; }
        }

        [Order((int)ValEnum.backOrder)]                         //-NOT USED IN STORED FUNCTION
        [mp.Column(DbType = "int", Name = "BACKORDER")]
        public int BackOrder
        {
            get { return _backOrder; }
            set { _backOrder = value; }
        }

        [Order((int)ValEnum.quantityShipped)]
        [mp.Column(DbType = "int", Name = "QTYSHIP")]
        public int QuantityShipped              //16
        {
            get { return _quantityShipped; }
            set { _quantityShipped = value; }
        }

        [Order((int)ValEnum.poCreationDate)]
        [mp.Column(DbType = "datetime", Name = "DOCDATE")]
        public DateTime? PoCreationDate
        {
            get
            {
                return _poCreationDate;
            }

            set
            {
                _poCreationDate = value;
            }
        }


        //FSTRCPTDT and LSTRCPTDT are GP columns and they aren't actually updated until the batch is processed. If a receipt is created but not batched until 3 days later, it'll be dateless for that long.
        [Order((int)ValEnum.firstReceiveDate)]
        [mp.Column(DbType = "datetime", Name = "DateReceived")]
        public DateTime? FirstReceiveDate       //17
        {
            get { return _firstReceiveDate; }
            set { _firstReceiveDate = value; }
        }

        [Order((int)ValEnum.lastReceiveDate)]
        [mp.Column(DbType = "datetime", Name = "LSTRCPTDT")]
        public DateTime? LastReceiveDate       //18 
        {
            get { return _lastReceiveDate; }
            set { _lastReceiveDate = value; }
        }

        [Order((int)ValEnum.locationCode)]
        [mp.Column(DbType = "char(11)", Name = "LOCNCODE")]
        public string LocationCode              //19
        {
            get { return _locationCode; }
            set { _locationCode = value; }
        }

        [Order((int)ValEnum.costCode)]
        [mp.Column(DbType = "char(27)", Name = "COSTCODE")]
        public string CostCode                  //20
        {
            get { return _costCode; }
            set { _costCode = value; }
        }

        [Order((int)ValEnum.requiredDate)]
        [mp.Column(DbType = "datetime", Name = "REQDATE")]
        public DateTime? RequiredDate           //21
        {
            get { return _requiredDate; }
            set { _requiredDate = value; }
        }

        [Order((int)ValEnum.promisedShipDate)]
        [mp.Column(DbType = "datetime", Name = "PRMSHPDTE")]
        public DateTime? PromisedShipDate       //22
        {
            get { return _promisedShipDate; }
            set { _promisedShipDate = value; }
        }

        [Order((int)ValEnum.lineCmmtText)]
        [mp.Column(Name = "LINECMMTTEXT")]
        public string LineCommentText
        {
            get { return _lineCmmtText; }
            set
            {
                if (value != null)
                    _lineCmmtText = value.Trim();
            }
        }

        [Order((int)ValEnum.headerCmmtText)]
        [mp.Column(Name = "HEADERCMMTTEXT")]
        public string HeaderCommentText
        {
            get { return _headerCmmtText; }
            set
            {
                if (value != null)
                    _headerCmmtText = value.Trim();
            }

        }

        [Order((int)ValEnum.customerName)]
        public string CustomerName
        {
            get { return _customerName; }
            set { _customerName = value; }
        }

        [Order((int)ValEnum.ucLineComment)]
        [mp.Column(Name = "UcLineCommentsConcat")]
        public string UcLineComment
        {
            get { return _ucLineComment; }
            set 
            { 
                if (value != null)
                {
                    this.UcLineHasComments = true;
                    _ucLineComment = value.Trim();
                }
                OnPropertyChanged("UcLineComment");
            }
        }

        [Order((int)ValEnum.ucHeaderComment)]
        [mp.Column(Name = "UcHeaderCommentsConcat")]
        public string UcHeaderComment
        {
            get { return _ucHeaderComment; }
            set 
            {
                if (value != null)
                {
                    this.UcHeaderHasComments = true;
                    _ucHeaderComment = value.Trim();
                }
                OnPropertyChanged("UcHeaderComment");
            }
        }

        public bool UcHeaderHasComments
        {
            get { return _ucHeaderHasComments; }
            set 
            { 
                _ucHeaderHasComments = value;
                OnPropertyChanged("UcHeaderHasComments");
            }
        }


        public bool UcLineHasComments
        {
            get { return _ucLineHasComments; }
            set 
            { 
                _ucLineHasComments = value;
                OnPropertyChanged("UcLineHasComments");
            }
        }

        public ObservableCollection<PoUcshHeaderComment> UcHeaderCommentCol
        {
            get { return _ucHeaderCommentCol; }
            set
            {
                _ucHeaderCommentCol = value;
                foreach (PoUcshHeaderComment item in _ucHeaderCommentCol)
                    item.PropertyChanged += OnCommentTextPropertyChanged;

                this._ucHeaderCommentCol.CollectionChanged += this.OnCollectionChanged;
                this.UcHeaderComment = string.Join(" \n", (_ucHeaderCommentCol).Select(x => x.CommentText).ToList());
            }
        }

        public ObservableCollection<PoUcshLineComment> UcLineCommentCol
        {
            get { return _ucLineCommentCol; }
            set
            {
                _ucLineCommentCol = value;
                foreach (PoUcshLineComment item in _ucLineCommentCol)
                    item.PropertyChanged += OnCommentTextPropertyChanged;

                this._ucLineCommentCol.CollectionChanged += this.OnCollectionChanged;
                this.UcLineComment = string.Join(" \n", (_ucLineCommentCol).Select(x => x.CommentText).ToList());
            }
        }


        //internal static void FillUcCommentCollections(List<PurchaseOrderLineItem> poList)
        //{
        //    lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
        //    lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
        //    List<PoUcshHeaderComment> headerComs = null;
        //    List<PoUcshLineComment> lineComs = null;

        //    headerComs = dtCtx.GetTable<PoUcshHeaderComment>().ToList();
        //    lineComs = dtCtx.GetTable<PoUcshLineComment>().ToList();

        //    IEnumerable<string> headerUniques = headerComs.Select(x => x.PoNumber.Trim()).Distinct();
        //    var lineUniques = lineComs.GroupBy(x => new { PoNumber = x.PoNumber.Trim(), Order = x.Order });

        //    foreach (string s in headerUniques)
        //    {
        //        List<PoUcshHeaderComment> narrowedHeaders = headerComs.Where(x => x.PoNumber.Trim() == s.Trim() ).ToList();
        //        foreach (PurchaseOrderLineItem poLine in poList)
        //        {
        //            if (poLine.PoNumber == s)
        //                poLine.UcHeaderCommentCol = new ObservableCollection<PoUcshHeaderComment>(narrowedHeaders);

        //        }
        //    }

        //    foreach (var line in lineUniques)
        //    {
        //        List<PoUcshLineComment> narrowLines = lineComs.Where(x => x.PoNumber.Trim() == line.Key.PoNumber.Trim() && x.Order == line.Key.Order).ToList();
        //        foreach (PurchaseOrderLineItem poLine in poList)
        //        {
        //            if (line.Key.PoNumber == poLine.PoNumber && line.Key.Order == poLine.Order)
        //                poLine.UcLineCommentCol = new ObservableCollection<PoUcshLineComment>(narrowLines);
        //        }
        //    }
        //}

        public PurchaseOrderLineItem()
        {

        }

        public PurchaseOrderLineItem(string poNumber, int order, string jobNumber, string jobName,  string sopNumber, 
            string buyerId, string changeId, string vendorId, string vendorName, short lineNumber, short polnesta,
            string itemNumber, string itemDescription, int quantityOrdered, int quantityReceived, int quantityMatched,
            int quantityActualShip,
            /* int quantityInvoiced, */ DateTime? firstReceiveDate, DateTime? lastReceiveDate, string locationCode, string costCode,
            DateTime? requiredDate, DateTime? promisedShipDate, string lineCmmtText, string headerCommentText, string customerName
            , List<PoUcshHeaderComment> ucHdrComments, List<PoUcshLineComment> ucLineComments
            , bool ucHeadersHasComments, bool ucLinesHasComments
            )
        {
            this._poNumber = poNumber;
            this._order = order;
            this._jobNumber = jobNumber;
            this._jobName = (string.IsNullOrEmpty(jobName) ? "" : jobName);
            this._sopNumber = sopNumber;
            this._buyerId = buyerId;
            this._changeId = changeId;
            this._vendorId = vendorId;
            this._vendorName = vendorName;
            this._lineNumber = lineNumber;
            this._polnesta = polnesta;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._quantityOrdered = quantityOrdered;
            this._quantityReceived = quantityReceived;
            this._quantityMatched = quantityMatched;
            this._backOrder = (quantityOrdered - quantityReceived);  //derivative field not directly loaded from constructor parameters
            this._quantityShipped = quantityActualShip;
            //this._quantityInvoiced = quantityInvoiced;
            this._firstReceiveDate = firstReceiveDate;
            this._lastReceiveDate = lastReceiveDate;
            this._locationCode = locationCode;
            this._costCode = costCode;
            this._requiredDate = requiredDate;
            this._promisedShipDate = promisedShipDate;
            this._lineCmmtText = lineCmmtText;
            this._headerCmmtText = headerCommentText;
            this._customerName = customerName;

            this._ucHeaderHasComments = ucHeadersHasComments;
            this._ucLineHasComments = ucLinesHasComments;

        }

        //private void ConcatPoComment(ObservableCollection<IPoUcshComment> _genCol)
        //{
        //    if (_genCol.GetType() == typeof(ObservableCollection<PoUcshHeaderComment>))
        //        this.UcHeaderComment = string.Join(", ", _genCol.Select(x => x.CommentText).ToList());
        //    else
        //        this.UcLineComment = string.Join(", ", _genCol.Select(x => x.CommentText).ToList());
        //}

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

        void OnCollectionChanged(object sender, NotifyCollectionChangedEventArgs e)
        {
            //if (sender.GetType() == typeof(ObservableCollection<PoUcshHeaderComment>))
            //    this.UcHeaderComment = string.Join(", ", ((ObservableCollection<PoUcshHeaderComment>)sender).Select(x => x.CommentText).ToList());
            //else
            //    this.UcLineComment = string.Join(", ", ((ObservableCollection<PoUcshLineComment>)sender).Select(x => x.CommentText).ToList());


            if (sender.GetType() == typeof(ObservableCollection<PoUcshHeaderComment>))
            {
                if (e != null && e.NewItems != null)
                    foreach (PoUcshHeaderComment item in e.NewItems)
                        item.PropertyChanged += OnCommentTextPropertyChanged;

                if (e != null && e.OldItems != null)
                    foreach (PoUcshHeaderComment item in e.OldItems)
                        item.PropertyChanged -= OnCommentTextPropertyChanged;
            }
            else
            {
                if (e != null && e.NewItems != null)
                    foreach (PoUcshLineComment item in e.NewItems)
                        item.PropertyChanged += OnCommentTextPropertyChanged;

                if (e != null && e.OldItems != null)
                    foreach (PoUcshLineComment item in e.OldItems)
                        item.PropertyChanged -= OnCommentTextPropertyChanged;
            }
        }

        void OnCommentTextPropertyChanged(object sender, PropertyChangedEventArgs e)
        {
            if (e.PropertyName == "CommentText")
            {
                if (sender.GetType() == typeof(PoUcshHeaderComment))
                    this.UcHeaderComment = string.Join(" \n", (this._ucHeaderCommentCol).Select(x => x.CommentText).ToList());
                else
                    this.UcLineComment = string.Join(" \n", (this._ucLineCommentCol).Select(x => x.CommentText).ToList());
            }
        }
    }

    public class PoListFunctionV1 : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\UDF-PrimaryHardwarePKQuery_19Mar2018.sql
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\SQL Table Creation Queries\Purchase Order Line Stored Function - 07 Jan 2019
        [mp.Function(Name = "[UCSH].[dbo].[ConnectsPoLineAllJobs_Oct_30_2019]", IsComposable = true)]       //In SQL Server: UCSH/Programmability/Functions/Table-vaued Functions
        public IQueryable<PurchaseOrderLineItem> ConnectsPoLineTestAllJobs()
        {
            return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())));
        }

        public PoListFunctionV1(string connStr)
            : base(connStr)
        {
        }
    }

    public class PoListFunctionLimitYear : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\UDF-PrimaryHardwarePKQuery_19Mar2018.sql
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\SQL Table Creation Queries\Purchase Order Line Stored Function - 07 Jan 2019
        [mp.Function(Name = "[UCSH].[dbo].[ConnectsPoLineAllJobs_Aug_16_2020_1Year]", IsComposable = true)]       //In SQL Server: UCSH/Programmability/Functions/Table-vaued Functions
        public IQueryable<PurchaseOrderLineItem> ConnectsPoLineTestAllJobs()
        {
            return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())));
        }

        public PoListFunctionLimitYear(string connStr)
            : base(connStr)
        {
        }
    }


    public class PoListFunctionByJob : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\UDF-PrimaryHardwarePKQuery_19Mar2018.sql
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\SQL Table Creation Queries\Purchase Order Line Stored Function - 07 Jan 2019
        [mp.Function(Name = "[UCSH].[dbo].[ConnectsPoLineByJob_Oct_17_2019]", IsComposable = true)]       //In SQL Server: UCSH/Programmability/Functions/Table-vaued Functions
        public IQueryable<PurchaseOrderLineItem> ConnectsPoLineTestAllJobs(string jobNumber)
        {
            //return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())));
            return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())), jobNumber);
        }

        public PoListFunctionByJob(string connStr)
            : base(connStr)
        {
        }
    }

    public class PoListFunctionV1UBC : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\UDF-PrimaryHardwarePKQuery_19Mar2018.sql
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\SQL Table Creation Queries\Purchase Order Line Stored Function - 07 Jan 2019
        [mp.Function(Name = "[UBC].[dbo].[ConnectsPoLineAllJobs_Oct_30_2019]", IsComposable = true)]       //In SQL Server: UCSH/Programmability/Functions/Table-vaued Functions
        public IQueryable<PurchaseOrderLineItem> ConnectsPoLineTestAllJobs()
        {
            return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())));
        }

        public PoListFunctionV1UBC(string connStr)
            : base(connStr)
        {
        }
    }

    public class PoListFunctionLimitYearUBC : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\UDF-PrimaryHardwarePKQuery_19Mar2018.sql
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\SQL Table Creation Queries\Purchase Order Line Stored Function - 07 Jan 2019
        [mp.Function(Name = "[UBC].[dbo].[ConnectsPoLineAllJobs_Aug_16_2020_1Year]", IsComposable = true)]       //In SQL Server: UCSH/Programmability/Functions/Table-vaued Functions
        public IQueryable<PurchaseOrderLineItem> ConnectsPoLineTestAllJobs()
        {
            return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())));
        }

        public PoListFunctionLimitYearUBC(string connStr)
            : base(connStr)
        {
        }
    }


    public class PoListFunctionByJobUBC : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\UDF-PrimaryHardwarePKQuery_19Mar2018.sql
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\SQL Table Creation Queries\Purchase Order Line Stored Function - 07 Jan 2019
        [mp.Function(Name = "[UBC].[dbo].[ConnectsPoLineByJob_Oct_17_2019]", IsComposable = true)]       //In SQL Server: UCSH/Programmability/Functions/Table-vaued Functions
        public IQueryable<PurchaseOrderLineItem> ConnectsPoLineTestAllJobs(string jobNumber)
        {
            //return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())));
            return this.CreateMethodCallQuery<PurchaseOrderLineItem>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())), jobNumber);
        }

        public PoListFunctionByJobUBC(string connStr)
            : base(connStr)
        {
        }
    }

    //NOT USED
    [AttributeUsage(AttributeTargets.Property | AttributeTargets.Field, Inherited = true, AllowMultiple = false)]
    [ImmutableObject(true)]
    public sealed class OrderAttribute : Attribute
    {
        private readonly int order;
        public int Order { get { return order; } }
        public OrderAttribute(int order) { this.order = order; }
    }

    //NOT USED
    [AttributeUsage(AttributeTargets.Property | AttributeTargets.Field, Inherited = true, AllowMultiple = true)]
    [ImmutableObject(true)]
    public sealed class CustTypeAtt : Attribute
    {
        private readonly Type propType;
        public Type PropType { get { return propType; } }
        public CustTypeAtt(Type propType) { this.propType = propType; }
    }

    //NOT USED
    public enum ValEnum
    {
        poNumber = 1,
        order,
        jobNumber,
        jobName,
        sopNumber,
        buyerId,
        changeId,
        vendorId,
        vendorName,
        lineNumber,
        polnesta,
        lineStatus,
        itemNumber,
        itemDescription,
        nonInventory,
        quantityOrdered,
        quantityReceived,
        quantityMatched,
        quantityInvoiced,
        backOrder,
        quantityShipped,
        poCreationDate,
        firstReceiveDate,
        lastReceiveDate,
        locationCode,
        costCode,
        requiredDate,
        promisedShipDate,
        lineCmmtText,
        headerCmmtText,
        customerName,
        ucLineComment,
        ucHeaderComment,
        ucHeaderHasComments,
        ucLineHasComments,
    }
}
