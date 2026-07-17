using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking.DataClasses.GpObjects
{
    [mp.Table(Name = "[POP10110]")]
    class Pop10110
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _poNumber;
        private int _order;
        private string _jobNumber;
        private string _vendorId;
        private short _lineNumber;
        private short _polnesta;
        private string _itemNumber;
        private string _itemDescription;
        private decimal _unitCost;
        private short _nonInventory;
        private decimal _qtyOrder;
        private DateTime? _releaseDate;
        private DateTime? _firstReceiveDate;
        private DateTime? _lastReceiveDate;
        private string _locationCode;
        private string _costCode;
        private DateTime? _requiredDate;
        private DateTime? _promisedShipDate;
        private DateTime? _poLineCreationDate;

        [mp.Column(Name = "PONUMBER")]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "ORD")]
        public int Order
        {
            get { return _order; }
            set { _order = value; }
        }

        [mp.Column(Name = "JOBNUMBR")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "VENDORID")]
        public string VendorId
        {
            get { return _vendorId; }
            set { _vendorId = value; }
        }

        [mp.Column(Name = "LineNumber")]
        public short LineNumber
        {
            get { return _lineNumber; }
            set { _lineNumber = value; }
        }

        [mp.Column(Name = "POLNESTA")]
        public short Polnesta
        {
            get { return _polnesta; }
            set { _polnesta = value; }
        }

        [mp.Column(Name = "ITEMNMBR")]
        public string ItemNumber
        {
            get { return _itemNumber; }
            set { _itemNumber = value; }
        }

        [mp.Column(Name = "ITEMDESC")]
        public string ItemDescription
        {
            get { return _itemDescription; }
            set { _itemDescription = value; }
        }

        [mp.Column(Name = "UNITCOST")]
        public decimal UnitCost
        {
            get { return _unitCost; }
            set { _unitCost = value; }
        }

        [mp.Column(Name = "NONINVEN")]
        public short NonInventory
        {
            get { return _nonInventory; }
            set { _nonInventory = value; }
        }

        [mp.Column(Name = "QTYORDER")]
        public decimal QtyOrder
        {
            get { return _qtyOrder; }
            set { _qtyOrder = value; }
        }

        [mp.Column(Name = "Released_Date")]
        public DateTime? ReleaseDate
        {
            get
            {
                return _releaseDate;
            }

            set
            {
                _releaseDate = value;
            }
        }

        [mp.Column(Name = "FSTRCPTDT")]
        public DateTime? FirstReceiveDate
        {
            get { return _firstReceiveDate; }
            set { _firstReceiveDate = value; }
        }

        [mp.Column(Name = "LSTRCPTDT")]
        public DateTime? LastReceiveDate
        {
            get { return _lastReceiveDate; }
            set { _lastReceiveDate = value; }
        }

        [mp.Column(Name = "LOCNCODE")]
        public string LocationCode
        {
            get { return _locationCode; }
            set { _locationCode = value; }
        }

        [mp.Column(Name = "COSTCODE")]
        public string CostCode
        {
            get { return _costCode; }
            set { _costCode = value; }
        }

        [mp.Column(Name = "REQDATE")]
        public DateTime? RequiredDate
        {
            get { return _requiredDate; }
            set { _requiredDate = value; }
        }

        [mp.Column(Name = "PRMSHPDTE")]
        public DateTime? PromisedShipDate
        {
            get { return _promisedShipDate; }
            set { _promisedShipDate = value; }
        }

        [mp.Column(Name = "DEX_ROW_TS")]
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
    }
}
