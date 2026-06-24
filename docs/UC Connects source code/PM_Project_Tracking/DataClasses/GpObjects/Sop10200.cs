using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.ComponentModel;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking.DataClasses.GpObjects
{
    [mp.Table(Name = "[SOP10200]")]
    public class Sop10200 : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _sopNumber;
        private short _sopType;
        private int _lnitmseq;
        private int _cmpntseq;
        private decimal _quantity;
        private string _itemNumber;
        private string _itemDescription;
        private string _locationCode;
        private decimal _unitCost;
        private decimal _unitPrice;
        private decimal _extendedPrice;
        private short _backOrderType;
        private bool _isNonInventory;
        private bool _noteBool;
        private decimal? _noteIndex;
        private string _lineComment;

        private bool _isExistingLock;

        [mp.Column(Name = "SOPNUMBE")]
        public string SopNumber
        {
            get { return _sopNumber; }
            set { _sopNumber = value; }
        }

        [mp.Column(Name = "SOPTYPE")]
        public short SopType
        {
            get { return _sopType; }
            set { _sopType = value; }
        }

        [mp.Column(Name = "LNITMSEQ")]
        public int Lnitmseq
        {
            get { return _lnitmseq; }
            set { _lnitmseq = value; }
        }

        [mp.Column(Name = "CMPNTSEQ")]
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

        [mp.Column(Name = "QUANTITY")]      //Column in SQL is decimal but this is stored as int.  Will have to see about conversion so it doesn't break.
        public decimal Quantity
        {
            get { return _quantity; }
            set
            {
                _quantity = value;
                _extendedPrice = _quantity * _unitPrice;
                OnPropertyChanged("ExtendedPrice");
            }
        }

        [mp.Column(Name = "ITEMNMBR")]
        public string ItemNumber
        {
            get { return _itemNumber; }
            set
            {
                _itemNumber = value;
                OnPropertyChanged("ItemNumber");
            }
        }

        [mp.Column(Name = "ITEMDESC")]
        public string ItemDescription
        {
            get { return _itemDescription; }
            set
            {
                _itemDescription = value;
                OnPropertyChanged("Description");
            }
        }

        [mp.Column(Name = "LOCNCODE")]
        public string LocationCode
        {
            get { return _locationCode; }
            set
            {
                _locationCode = value;
                OnPropertyChanged("LocationCode");
            }
        }

        [mp.Column(Name = "UNITCOST")]
        public decimal UnitCost
        {
            get { return _unitCost; }
            set
            {
                _unitCost = value;
                OnPropertyChanged("UnitCost");
            }

        }

        [mp.Column(Name = "UNITPRCE")]
        public decimal UnitPrice
        {
            get { return _unitPrice; }
            set
            {
                _unitPrice = value;
                _extendedPrice = _quantity * _unitPrice;
                OnPropertyChanged("UnitPrice");
                OnPropertyChanged("ExtendedPrice");
            }
        }

        [mp.Column(Name = "XTNDPRCE")]
        public decimal ExtendedPrice
        {
            get { return _extendedPrice; }
            set
            {
                _extendedPrice = value;
            }
        }

        //Only exposed to UI in inventory item menu
        public short BackOrderType
        {
            get { return _backOrderType; }
            set
            {
                _backOrderType = value;
                OnPropertyChanged("BackOrderType");
            }
        }

        [mp.Column(Name = "NONINVEN", DbType = "SmallInt", CanBeNull = true)]
        public bool IsNonInventory
        {
            get { return _isNonInventory; }
            set
            {
                _isNonInventory = value;
                if (value)
                    _locationCode = "MARKHAM";
                OnPropertyChanged("IsNonInventory");
            }
        }

        //Derived from SOP10202
        public decimal? NoteIndex
        {
            get { return _noteIndex; }
            set { _noteIndex = value; }
        }

        public bool NoteBool
        {
            get { return _noteBool; }
            set
            {
                _noteBool = value;
                OnPropertyChanged("NoteBool");
            }
        }
        //Derived from SOP10202
        public string LineComment
        {
            get { return _lineComment; }
            set
            {
                _lineComment = value;
                if (!string.IsNullOrEmpty(value))
                    this.NoteBool = true;
                else
                    this.NoteBool = false;
            }
        }

        public bool IsExistingLock  //Bind this property to IsReadOnly property on datagrid so that the item number can't be edited
        {
            get { return _isExistingLock; }
            set { _isExistingLock = value; }
        }


        public Sop10200()
        {
            _isNonInventory = true;
            _backOrderType = 3;
            _locationCode = "MARKHAM";
        }

        public Sop10200(string sopNumber, int lineSeq, string itemNumber, string itemDescription, decimal quantityOrdered)
        {
            this._sopNumber = sopNumber;
            this._lnitmseq = lineSeq;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._quantity = quantityOrdered;
        }

        public Sop10200(string _docNum, int _lineSeq, int _quant, string _itemNum, string _desc, string locCode, decimal _unitCost, decimal _unitPrice, decimal _extPrice, bool _isNonInv, string lineCom)
        {
            this._sopNumber = _docNum;
            this._lnitmseq = _lineSeq;
            this._quantity = _quant;
            this._itemNumber = _itemNum;
            this._itemDescription = _desc;      //was previously this.Description = _desc;
            this._locationCode = locCode;
            this._unitCost = _unitCost;
            this._unitPrice = _unitPrice;
            this._extendedPrice = _extPrice;
            this._isNonInventory = _isNonInv;
            this._backOrderType = 3;
            this._lineComment = lineCom;
            if (!string.IsNullOrEmpty(lineCom))
                this._noteBool = true;

            this._isExistingLock = true;
        }

        public void Clear()
        {
            var props = this.GetType().GetProperties();
            for (int i = 0; i < props.Count(); i++)
            {
                props[i].SetValue(this, null);
                //this might be a problem when we bound properties to the object - this won't fire the on property changed event
                //http://stackoverflow.com/questions/11210440/raise-an-event-when-property-changed-using-reflection
            }
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
