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

    class SopLinks
    {
        internal static ObservableCollection<SopLink> GetAllSopPopLinkLines()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<SopLink> sopPopList = null;

            var sopUnion = (from c in dtCtx.GetTable<gp.Sop10100>() select new { c.SopNumber, c.SopType, c.OriginNumber, c.CustomerNumber, c.CustomerName, c.Slprsnid, c.DocDate, c.FulfillDate }).Union(
                            (from d in dtCtx.GetTable<gp.Sop30200>() select new { d.SopNumber, d.SopType, d.OriginNumber, d.CustomerNumber, d.CustomerName, d.Slprsnid, d.DocDate, d.FulfillDate }));

            try
            {
                var sopLinkQuery = from poLine in dtCtx.GetTable<gp.Pop10110>()
                                   join sop in dtCtx.GetTable<gp.Sop60100>().Distinct() on new { poLine.PoNumber, poLine.Order } equals new { sop.PoNumber, sop.Order } into fulltwo
                                   from sop in fulltwo.DefaultIfEmpty()
                                   join sopAll in sopUnion on sop.SopNumber equals sopAll.SopNumber into fullthree
                                   from sopAll in fullthree.DefaultIfEmpty()
                                   join sopLk in dtCtx.GetTable<SopLink>() on new { poLine.PoNumber, poLine.Order } equals new { sopLk.PoNumber, sopLk.Order } into fullfour
                                   from sopLk in fullfour.DefaultIfEmpty()
                                   join rm in dtCtx.GetTable<gp.Rm00101>() on sopAll.CustomerNumber equals rm.CustomerNumber into fullfive
                                   from rm in fullfive.DefaultIfEmpty()
                                   where poLine.LocationCode == "SHOWROOM"
                                   select new
                                   {
                                       PoNumber = poLine.PoNumber,
                                       Order = poLine.Order,
                                       SopNumber = sop.SopNumber == null ? "" : sop.SopNumber,
                                       PoDate = poLine.ReleaseDate, //PO Date
                                       OrderDate = sopAll.DocDate, //Doc date is in fact invoice date
                                       FulfillDate = sopAll.FulfillDate, //Order fulfillment date
                                       //Invoice date
                                       BuyerId = sopAll.Slprsnid == null ? "" : sopAll.Slprsnid,
                                       CustomerName = sopAll.CustomerName == null ? "" : sopAll.CustomerName,
                                       CustomerNumber = sopAll.CustomerNumber,
                                       PhoneNumber = rm.PhoneNumber == null ? "" : rm.PhoneNumber,
                                       Polnesta = poLine.Polnesta,
                                       ItemNumber = poLine.ItemNumber,
                                       ItemDescription = poLine.ItemDescription == null ? "" : poLine.ItemDescription,
                                       VendorId = poLine.VendorId,
                                       OrderQuantity = poLine.QtyOrder,
                                       LineNumber = poLine.LineNumber,
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

                sopPopList = sopLinkQuery.AsEnumerable().Select(x => new SopLink(x.PoNumber, x.Order, x.SopNumber, x.PoDate, x.OrderDate,
                                                                x.FulfillDate, x.BuyerId, x.CustomerName, x.CustomerNumber, 
                                                                x.PhoneNumber,
                                                                x.Polnesta, x.ItemNumber,
                                                                x.ItemDescription, x.VendorId, x.OrderQuantity, x.LineNumber, x.PoLineCreationDate,
                                                                x.HasLinkTableLine, x.RackLocation, x.ItemStatus, x.Notes,
                                                                x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine)).ToList();
                                                                

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<SopLink>(sopPopList);
        }

        public static bool UpdateSopLink(SopLink spLink)
        {
            bool _cont = true;
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (SopLinkDataContext dtCtx = new SopLinkDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.SopLink.Attach(spLink, false);
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

        public static bool AddSopLink(SopLink spLink)
        {
            bool _cont = true;
            using (SopLinkDataContext dtCtx = new SopLinkDataContext(GlobalVars.UcshConnectionString))
            {
                spLink.UpdatingUser = Environment.UserName;
                spLink.UpdatingMachine = Environment.MachineName;
                spLink.DateCreated = DateTime.Today;
                spLink.TimeCreated = DateTime.Now;
                try
                {
                    dtCtx.SopLink.InsertOnSubmit(spLink);
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

    [mp.Table(Name = "[SOPPOPLINK101]")]
    public class SopLink : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private string _poNumber;
        private int _order;
        private string _sopNumber;
        private DateTime? _poDate;
        private DateTime? _orderDate;
        private DateTime? _fulfillDate;
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
        private DateTime? _poCreationDate;

        private bool _hasLinkTableLines;
        private bool _linkTableDataEdited;
        private string _rackLocation;
        private string _lineStatus;
        private string _notes;

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;



        [mp.Column(Name = "PONUMBER", IsPrimaryKey=true)]
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

        public DateTime? PoDate
        {
            get
            {
                return _poDate;
            }

            set
            {
                _poDate = value;
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

        public SopLink()
        {

        }

        public SopLink(string poNumber, int order, string sopNumber, DateTime? poDate, DateTime? orderDate,
                        DateTime? fulfillDate, string buyerId, string customerName, string customerNumber, 
                        string phoneNumber,
                        short polnesta,
                        string itemNumber, string itemDescription, string vendorId, decimal orderQuantity, int lineNumber,
                        DateTime? poLineCreationDate, bool hasLinkTableLines, string rackLocation, string itemStatus, string notes,
                        DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine)
        {
            this._poNumber = poNumber;
            this._sopNumber = sopNumber;
            this._order = order;
            this._poDate = PoDate;
            this._orderDate = orderDate;
            this._fulfillDate = fulfillDate;
            this._buyerId = buyerId;
            this._customerName = customerName;
            this._customerNumber = customerNumber;
            this._phoneNumber = phoneNumber;
            this._polnesta = polnesta;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._vendorId = vendorId;
            this._orderQuantity = orderQuantity;
            this._lineNumber = lineNumber;
            this._poCreationDate = poLineCreationDate;

            this._hasLinkTableLines = hasLinkTableLines;

            this._rackLocation = rackLocation;
            this._lineStatus = itemStatus;
            this._notes = notes;

            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

        }

    }

    public class SopLinkDataContext : lq.DataContext
    {
        public SopLinkDataContext(string cs)
            : base(cs)
        {

        }

        public SopLinkDataContext(SqlConnection conn)
            : base(conn)
        {

        }

        public lq.Table<SopLink> SopLink;
    }
}
