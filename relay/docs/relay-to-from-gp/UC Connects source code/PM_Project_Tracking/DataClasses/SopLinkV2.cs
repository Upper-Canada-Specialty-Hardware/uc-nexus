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
using System.Data.SqlClient;

namespace PM_Project_Tracking.DataClasses
{

    class SopLinksV2s
    {
        internal static ObservableCollection<SopLinkV2> GetAllSopLinkV2Lines()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<SopLinkV2> sopPopList = null;

            try
            {
                var sopLinkQuery = from sLines in (from c in dtCtx.GetTable<gp.Sop10200>() select new { c.SopType, c.SopNumber, c.Lnitmseq, c.Cmpntseq, c.ItemNumber, c.ItemDescription, c.Quantity, c.LocationCode }).Union(
                                   (from d in dtCtx.GetTable<gp.Sop30300>() select new { d.SopType, d.SopNumber, d.Lnitmseq, d.Cmpntseq, d.ItemNumber, d.ItemDescription, d.Quantity, d.LocationCode }))
                                   join sHeads in (from c in dtCtx.GetTable<gp.Sop10100>() select new { c.SopNumber, c.SopType, c.OriginNumber, c.CustomerNumber, c.CustomerName, c.Slprsnid, c.DocDate, c.FulfillDate, c.InvoiceDate }).Union(
                                   (from d in dtCtx.GetTable<gp.Sop30200>() select new { d.SopNumber, d.SopType, d.OriginNumber, d.CustomerNumber, d.CustomerName, d.Slprsnid, d.DocDate, d.FulfillDate, d.InvoiceDate }))
                                   on sLines.SopNumber equals sHeads.SopNumber into fullHeaders
                                   from sHeads in fullHeaders
                                   join sop60100 in dtCtx.GetTable<gp.Sop60100>().Distinct() on new { sLines.SopType, sLines.SopNumber, sLines.Lnitmseq, sLines.Cmpntseq }
                                   equals new { sop60100.SopType, sop60100.SopNumber, sop60100.Lnitmseq, sop60100.Cmpntseq } into fulltwo
                                   from sop60100 in fulltwo.DefaultIfEmpty()
                                   join sopLk in dtCtx.GetTable<SopLinkV2>() on new { sLines.SopType, sLines.SopNumber, sLines.Lnitmseq, sLines.Cmpntseq } equals new { sopLk.SopType, sopLk.SopNumber, sopLk.Lnitmseq, sopLk.Cmpntseq } into fullfour
                                   from sopLk in fullfour.DefaultIfEmpty()
                                   join poLine in dtCtx.GetTable<gp.Pop10110>() on new { sop60100.PoNumber, sop60100.Order } equals new { poLine.PoNumber, poLine.Order } into fullfive
                                   from poLine in fullfive.DefaultIfEmpty()
                                   join poHeader in dtCtx.GetTable<gp.Pop10100>() on sop60100.PoNumber equals poHeader.PoNumber into fullseven
                                   from poHeader in fullseven.DefaultIfEmpty()
                                   join rm in dtCtx.GetTable<gp.Rm00101>() on sHeads.CustomerNumber equals rm.CustomerNumber into fullsix
                                   from rm in fullsix.DefaultIfEmpty()
                                   select new
                                   {
                                       SopType = sLines.SopType,
                                       SopNumber = sLines.SopNumber,
                                       Lnitmseq = sLines.Lnitmseq,
                                       Cmpntseq = sLines.Cmpntseq,
                                       PoNumber = poLine.PoNumber == null ? "" : poLine.PoNumber,
                                       Order = poLine.Order == null ? 0 : poLine.Order,
                                       ItemNumber = sLines.ItemNumber,
                                       ItemDescription = sLines.ItemDescription == null ? "" : sLines.ItemDescription,
                                       PoCreationDate = poHeader.DocDate,
                                       OrderDate = sHeads.DocDate, //Doc date is in fact invoice date
                                       FulfillDate = sHeads.FulfillDate, //Order fulfillment date
                                       InvoiceDate = sHeads.InvoiceDate, //Invoice date
                                       BuyerId = sHeads.Slprsnid == null ? "" : sHeads.Slprsnid,
                                       CustomerName = sHeads.CustomerName == null ? "" : sHeads.CustomerName,
                                       CustomerNumber = sHeads.CustomerNumber,
                                       PhoneNumber = rm.PhoneNumber == null ? "" : rm.PhoneNumber,
                                       Polnesta = poLine.Polnesta == null ? (short)0 : poLine.Polnesta,
                                       VendorId = poLine.VendorId,
                                       OrderQuantity = poLine.QtyOrder == null ? 0 : poLine.QtyOrder,
                                       LineNumber = poLine.LineNumber == null ? 0 : poLine.LineNumber,
                                       PoLineCreationDate = poLine.PoLineCreationDate,

                                       HasLinkTableLine = sopLk.PoNumber == null ? false : true,
                                       RackLocation = sopLk.RackLocation == null ? "" : sopLk.RackLocation,
                                       ItemStatus = sopLk.LineStatus == null ? "" : sopLk.LineStatus,
                                       Notes = sopLk.Notes == null ? "" : sopLk.Notes,

                                       DateCreated = sopLk.DateCreated,
                                       TimeCreated = sopLk.TimeCreated,
                                       UpdatingUser = sopLk.UpdatingUser,
                                       UpdatingMachine = sopLk.UpdatingMachine
                                   };

                sopPopList = sopLinkQuery.AsEnumerable().Select(x => new SopLinkV2(x.SopType
                                                                                , x.SopNumber
                                                                                , x.Lnitmseq
                                                                                , x.Cmpntseq
                                                                                , x.PoNumber
                                                                                , x.Order
                                                                                , x.ItemNumber
                                                                                , x.ItemDescription
                                                                                , x.PoCreationDate
                                                                                , x.OrderDate
                                                                                , x.FulfillDate
                                                                                , x.InvoiceDate
                                                                                , x.BuyerId
                                                                                , x.CustomerName
                                                                                , x.CustomerNumber
                                                                                , x.PhoneNumber
                                                                                , x.Polnesta
                                                                                , x.VendorId
                                                                                , x.OrderQuantity
                                                                                , x.LineNumber
                                                                                , x.PoLineCreationDate
                                                                                , x.HasLinkTableLine
                                                                                , x.RackLocation
                                                                                , x.ItemStatus
                                                                                , x.Notes
                                                                                , x.DateCreated
                                                                                , x.TimeCreated
                                                                                , x.UpdatingUser
                                                                                , x.UpdatingMachine
                                                                                )).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<SopLinkV2>(sopPopList);
        }

        internal static ObservableCollection<SopLinkV2> GetOpenSopLinkV2Lines()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<SopLinkV2> sopPopList = null;

            try
            {
                var sopLinkQuery = from sLines in dtCtx.GetTable<gp.Sop10200>() 
                                   join sHeads in (from c in dtCtx.GetTable<gp.Sop10100>() select new { c.SopNumber, c.SopType, c.OriginNumber, c.CustomerNumber, c.CustomerName, c.Slprsnid, c.DocDate, c.FulfillDate, c.InvoiceDate }).Union(
                                   (from d in dtCtx.GetTable<gp.Sop30200>() select new { d.SopNumber, d.SopType, d.OriginNumber, d.CustomerNumber, d.CustomerName, d.Slprsnid, d.DocDate, d.FulfillDate, d.InvoiceDate }))
                                   on sLines.SopNumber equals sHeads.SopNumber into fullHeaders
                                   from sHeads in fullHeaders
                                   join sop60100 in dtCtx.GetTable<gp.Sop60100>().Distinct() on new { sLines.SopType, sLines.SopNumber, sLines.Lnitmseq, sLines.Cmpntseq }
                                   equals new { sop60100.SopType, sop60100.SopNumber, sop60100.Lnitmseq, sop60100.Cmpntseq } into fulltwo
                                   from sop60100 in fulltwo.DefaultIfEmpty()
                                   join sopLk in dtCtx.GetTable<SopLinkV2>() on new { sLines.SopType, sLines.SopNumber, sLines.Lnitmseq, sLines.Cmpntseq } equals new { sopLk.SopType, sopLk.SopNumber, sopLk.Lnitmseq, sopLk.Cmpntseq } into fullfour
                                   from sopLk in fullfour.DefaultIfEmpty()
                                   join poLine in dtCtx.GetTable<gp.Pop10110>() on new { sop60100.PoNumber, sop60100.Order } equals new { poLine.PoNumber, poLine.Order } into fullfive
                                   from poLine in fullfive.DefaultIfEmpty()
                                   join poHeader in dtCtx.GetTable<gp.Pop10100>() on sop60100.PoNumber equals poHeader.PoNumber into fullseven
                                   from poHeader in fullseven.DefaultIfEmpty()
                                   join rm in dtCtx.GetTable<gp.Rm00101>() on sHeads.CustomerNumber equals rm.CustomerNumber into fullsix
                                   from rm in fullsix.DefaultIfEmpty()
                                   select new
                                   {
                                       SopType = sLines.SopType,
                                       SopNumber = sLines.SopNumber,
                                       Lnitmseq = sLines.Lnitmseq,
                                       Cmpntseq = sLines.Cmpntseq,
                                       PoNumber = poLine.PoNumber == null ? "" : poLine.PoNumber,
                                       Order = poLine.Order == null ? 0 : poLine.Order,
                                       ItemNumber = sLines.ItemNumber,
                                       ItemDescription = sLines.ItemDescription == null ? "" : sLines.ItemDescription,
                                       PoCreationDate = poHeader.DocDate,
                                       OrderDate = sHeads.DocDate, //Doc date is in fact invoice date
                                       FulfillDate = sHeads.FulfillDate, //Order fulfillment date
                                       InvoiceDate = sHeads.InvoiceDate, //Invoice date
                                       BuyerId = sHeads.Slprsnid == null ? "" : sHeads.Slprsnid,
                                       CustomerName = sHeads.CustomerName == null ? "" : sHeads.CustomerName,
                                       CustomerNumber = sHeads.CustomerNumber,
                                       PhoneNumber = rm.PhoneNumber == null ? "" : rm.PhoneNumber,
                                       Polnesta = poLine.Polnesta == null ? (short)0 : poLine.Polnesta,
                                       VendorId = poLine.VendorId,
                                       OrderQuantity = poLine.QtyOrder == null ? 0 : poLine.QtyOrder,
                                       LineNumber = poLine.LineNumber == null ? 0 : poLine.LineNumber,
                                       PoLineCreationDate = poLine.PoLineCreationDate,

                                       HasLinkTableLine = sopLk.PoNumber == null ? false : true,
                                       RackLocation = sopLk.RackLocation == null ? "" : sopLk.RackLocation,
                                       ItemStatus = sopLk.LineStatus == null ? "" : sopLk.LineStatus,
                                       Notes = sopLk.Notes == null ? "" : sopLk.Notes,

                                       DateCreated = sopLk.DateCreated,
                                       TimeCreated = sopLk.TimeCreated,
                                       UpdatingUser = sopLk.UpdatingUser,
                                       UpdatingMachine = sopLk.UpdatingMachine
                                   };

                sopPopList = sopLinkQuery.AsEnumerable().Select(x => new SopLinkV2(x.SopType
                                                                                , x.SopNumber
                                                                                , x.Lnitmseq
                                                                                , x.Cmpntseq
                                                                                , x.PoNumber
                                                                                , x.Order
                                                                                , x.ItemNumber
                                                                                , x.ItemDescription
                                                                                , x.PoCreationDate
                                                                                , x.OrderDate
                                                                                , x.FulfillDate
                                                                                , x.InvoiceDate
                                                                                , x.BuyerId
                                                                                , x.CustomerName
                                                                                , x.CustomerNumber
                                                                                , x.PhoneNumber
                                                                                , x.Polnesta
                                                                                , x.VendorId
                                                                                , x.OrderQuantity
                                                                                , x.LineNumber
                                                                                , x.PoLineCreationDate
                                                                                , x.HasLinkTableLine
                                                                                , x.RackLocation
                                                                                , x.ItemStatus
                                                                                , x.Notes
                                                                                , x.DateCreated
                                                                                , x.TimeCreated
                                                                                , x.UpdatingUser
                                                                                , x.UpdatingMachine
                                                                                )).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<SopLinkV2>(sopPopList);
        }
        public static bool UpdateSopLink(SopLinkV2 spLink)
        {
            bool _cont = true;
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (SopLinkDataContextV2 dtCtx = new SopLinkDataContextV2(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.SopLinkV2.Attach(spLink, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, spLink);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                    _cont = false;
                }

            }

            return _cont;
        }

        public static bool AddSopLink(SopLinkV2 spLink)
        {
            bool _cont = true;
            using (SopLinkDataContextV2 dtCtx = new SopLinkDataContextV2(GlobalVars.UcshConnectionString))
            {
                spLink.UpdatingUser = Environment.UserName;
                spLink.UpdatingMachine = Environment.MachineName;
                spLink.DateCreated = DateTime.Today;
                spLink.TimeCreated = DateTime.Now;
                try
                {
                    dtCtx.SopLinkV2.InsertOnSubmit(spLink);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                    _cont = false;
                }

                return _cont;
            }
        }

    }


    [mp.Table(Name = "[SOPPOPLINK101NEW]")]
    public class SopLinkV2 : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private string _sopNumber;
        private short _sopType;
        private int _lnitmseq;
        private int _cmpntseq;
        private string _poNumber;
        private int _order;
        private DateTime? _poHeaderDate;
        private DateTime? _orderDate;
        private DateTime? _fulfillDate;
        private DateTime? _invoiceDate;
        private string _buyerId;
        private string _customerName;
        private string _customerNumber;
        private string _phoneNumber;
        private short _polnesta;
        private string _itemNumber;
        private string _itemDescription;
        private string _vendorId;
        private decimal _orderQuantity;
        private int _lineNumber;
        private DateTime? _poLineCreationDate;

        private bool _hasLinkTableLines;
        private bool _linkTableDataEdited;
        private string _rackLocation;
        private string _lineStatus;
        private string _notes;

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;



        [mp.Column(Name = "SOPNUMBE", IsPrimaryKey = true)]
        public string SopNumber
        {
            get
            {
                return _sopNumber;
            }

            set
            {
                _sopNumber = value;
            }
        }

        [mp.Column(Name = "SOPTYPE", IsPrimaryKey = true)]
        public short SopType
        {
            get
            {
                return _sopType;
            }

            set
            {
                _sopType = value;
            }
        }

        [mp.Column(Name = "LNITMSEQ", IsPrimaryKey = true)]
        public int Lnitmseq
        {
            get
            {
                return _lnitmseq;
            }

            set
            {
                _lnitmseq = value;
            }
        }

        [mp.Column(Name = "CMPNTSEQ", IsPrimaryKey = true)]
        public int Cmpntseq
        {
            get
            {
                return _cmpntseq;
            }

            set
            {
                _cmpntseq = value;
            }
        }

        [mp.Column(Name = "PONUMBER")]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "ORD", IsPrimaryKey = true)]
        public int Order
        {
            get { return _order; }
            set { _order = value; }
        }



        public DateTime? PoHeaderDate
        {
            get
            {
                return _poHeaderDate;
            }

            set
            {
                _poHeaderDate = value;
            }
        }

        public DateTime? OrderDate
        {
            get
            {
                return _orderDate;
            }

            set
            {
                _orderDate = value;
            }
        }

        public DateTime? FulfillDate
        {
            get
            {
                return _fulfillDate;
            }

            set
            {
                _fulfillDate = value;
            }
        }

        public DateTime? InvoiceDate
        {
            get
            {
                return _invoiceDate;
            }

            set
            {
                _invoiceDate = value;
            }
        }

        public string BuyerId
        {
            get
            {
                return _buyerId;
            }

            set
            {
                _buyerId = value;
            }
        }

        public string CustomerName
        {
            get
            {
                return _customerName;
            }

            set
            {
                _customerName = value;
            }
        }

        public string CustomerNumber
        {
            get
            {
                return _customerNumber;
            }

            set
            {
                _customerNumber = value;
            }
        }

        public string PhoneNumber
        {
            get
            {
                return _phoneNumber;
            }

            set
            {
                _phoneNumber = value;
            }
        }

        public short Polnesta
        {
            get
            {
                return _polnesta;
            }

            set
            {
                _polnesta = value;
            }
        }

        public string ItemNumber
        {
            get
            {
                return _itemNumber;
            }

            set
            {
                _itemNumber = value;
            }
        }

        public string ItemDescription
        {
            get
            {
                return _itemDescription;
            }

            set
            {
                _itemDescription = value;
            }
        }

        public string VendorId
        {
            get
            {
                return _vendorId;
            }

            set
            {
                _vendorId = value;
            }
        }

        public decimal OrderQuantity
        {
            get
            {
                return _orderQuantity;
            }

            set
            {
                _orderQuantity = value;
            }
        }

        public int LineNumber
        {
            get
            {
                return _lineNumber;
            }

            set
            {
                _lineNumber = value;
            }
        }

        public DateTime? PoLineCreationDate
        {
            get
            {
                return _poLineCreationDate;
            }

            set
            {
                _poLineCreationDate = value;
            }
        }


        public bool HasLinkTableLines
        {
            get
            {
                return _hasLinkTableLines;
            }

            set
            {
                _hasLinkTableLines = value;
            }
        }

        public bool LinkTableDataEdited
        {
            get
            {
                return _linkTableDataEdited;
            }

            set
            {
                _linkTableDataEdited = value;
            }
        }

        [mp.Column(Name = "RackLocation")]
        public string RackLocation
        {
            get
            {
                return _rackLocation;
            }

            set
            {
                if (_rackLocation != value)
                {
                    _rackLocation = value;
                    _linkTableDataEdited = true;
                    OnPropertyChanged("RackLocation");
                }
            }
        }

        [mp.Column(Name = "LineStatus")]
        public string LineStatus
        {
            get
            {
                return _lineStatus;
            }

            set
            {
                if (_lineStatus != value)
                {
                    _lineStatus = value;
                    _linkTableDataEdited = true;
                    OnPropertyChanged("Status");
                }
            }
        }

        [mp.Column(Name = "Notes")]
        public string Notes
        {
            get
            {
                return _notes;
            }

            set
            {
                if (_notes != value)
                {
                    _notes = value;
                    _linkTableDataEdited = true;
                    OnPropertyChanged("Notes");
                }
            }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set
            {
                _dateCreated = value;
                OnPropertyChanged("DateCreated");
            }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set
            {
                _timeCreated = value;
                OnPropertyChanged("TimeCreated");
            }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set
            {
                _updatingUser = value;
                OnPropertyChanged("UpdatingUser");
            }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set
            {
                _updatingMachine = value;
                OnPropertyChanged("UpdatingMachine");
            }
        }


        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

        public SopLinkV2()
        {

        }

        //public SopLinkV2(string poNumber, int order, string sopNumber, DateTime? poDate, DateTime? orderDate,
        //                DateTime? fulfillDate, DateTime? invoiceDate,
        //                string buyerId, string customerName, string customerNumber,
        //                string phoneNumber,
        //                short polnesta,
        //                string itemNumber, string itemDescription, string vendorId, decimal orderQuantity, int lineNumber,
        //                DateTime? poLineCreationDate, bool hasLinkTableLines, string rackLocation, string itemStatus, string notes,
        //                DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine)
        //{
        //    this._poNumber = poNumber;
        //    this._sopNumber = sopNumber;
        //    this._order = order;
        //    this._poDate = PoDate;
        //    this._orderDate = orderDate;
        //    this._fulfillDate = fulfillDate;
        //    this._invoiceDate = invoiceDate;
        //    this._buyerId = buyerId;
        //    this._customerName = customerName;
        //    this._customerNumber = customerNumber;
        //    this._phoneNumber = phoneNumber;
        //    this._polnesta = polnesta;
        //    this._itemNumber = itemNumber;
        //    this._itemDescription = itemDescription;
        //    this._vendorId = vendorId;
        //    this._orderQuantity = orderQuantity;
        //    this._lineNumber = lineNumber;
        //    this._poCreationDate = poLineCreationDate;

        //    this._hasLinkTableLines = hasLinkTableLines;

        //    this._rackLocation = rackLocation;
        //    this._lineStatus = itemStatus;
        //    this._notes = notes;

        //    this._dateCreated = dateCreated;
        //    this._timeCreated = timeCreated;
        //    this._updatingUser = updatingUser;
        //    this._updatingMachine = updatingMachine;

        //}

        public SopLinkV2(short sopType
                        ,string sopNumber
                        ,int lnitmSeq
                        ,int cmpntSeq
                        ,string poNumber
                        ,int order
                        ,string itemNumber
                        ,string itemDescription
                        ,DateTime? poHeaderCreationDate
                        ,DateTime? orderDate
                        ,DateTime? fulfillDate
                        ,DateTime? invoiceDate
                        ,string buyerId
                        ,string customerName
                        ,string customerNumber
                        ,string phoneNumber
                        ,short polnesta
                        ,string vendorId
                        ,decimal orderQty
                        ,int lineNumber
                        ,DateTime? poLineCreationDate
                        ,bool hasLinkTableLines
                        ,string rackLocation
                        ,string itemStatus 
                        ,string notes
                        ,DateTime? dateCreated
                        ,DateTime? timeCreated
                        ,string updatingUser
                        ,string updatingMachine
                        )
        {
            this._sopType = sopType;
            this._sopNumber = sopNumber;
            this._lnitmseq = lnitmSeq;
            this._cmpntseq = cmpntSeq;
            this._poNumber = poNumber;
            this._order = order;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._poHeaderDate = poHeaderCreationDate;
            this._orderDate = orderDate;
            this._fulfillDate = fulfillDate;
            this._invoiceDate = invoiceDate;
            this._buyerId = buyerId;
            this._customerName = customerName;
            this._customerNumber = customerNumber;
            this._phoneNumber = phoneNumber;
            this._polnesta = polnesta;
            this._vendorId = vendorId;
            this._orderQuantity = orderQty;
            this._lineNumber = lineNumber;
            this._poLineCreationDate = poLineCreationDate;
            this._hasLinkTableLines = hasLinkTableLines;
            this._rackLocation = rackLocation;
        }



        //debugging
        //public SopLinkV2(short sopType
        //        , string sopNumber
        //        , int lnitmSeq
        //        , int cmpntSeq
        //        , string poNumber
        //        , int order
        //        , string itemNumber
        //        , string itemDescription
        //        , DateTime? orderDate
        //        , DateTime? fulfillDate
        //        , string buyerId
        //        , string customerName
        //        , string customerNumber
        //        , string phoneNumber
        //        , short polnesta
        //        , string vendorId
        //        , decimal orderQty
        //        , int lineNumber
        //        , DateTime? poCreationDate
        //        , bool hasLinkTableLines
        //        , string rackLocation
        //        , string itemStatus
        //        , string notes
        //        , DateTime? dateCreated
        //        , DateTime? timeCreated
        //        , string updatingUser
        //        , string updatingMachine
        //        )
        //{
        //    this._sopType = sopType;
        //    this._sopNumber = sopNumber;
        //    this._lnitmseq = lnitmSeq;
        //    this._cmpntseq = cmpntSeq;
        //    this._poNumber = poNumber;
        //    this._order = order;
        //    this._itemNumber = itemNumber;
        //    this._itemDescription = itemDescription;
        //    this._orderDate = orderDate;
        //    this._fulfillDate = fulfillDate;
        //    this._buyerId = buyerId;
        //    this._customerName = customerName;
        //    this._customerNumber = customerNumber;
        //    this._phoneNumber = phoneNumber;
        //    this._polnesta = polnesta;
        //    this._vendorId = vendorId;
        //    this._orderQuantity = orderQty;
        //    this._lineNumber = lineNumber;
        //    this._poCreationDate = poCreationDate;
        //    this._hasLinkTableLines = hasLinkTableLines;
        //    this._rackLocation = rackLocation;
        //}
    }


    public class SopLinkDataContextV2 : lq.DataContext
    {
        public SopLinkDataContextV2(string cs)
            : base(cs)
        {

        }

        public SopLinkDataContextV2(SqlConnection conn)
            : base(conn)
        {

        }

        public lq.Table<SopLinkV2> SopLinkV2;
    }

}
