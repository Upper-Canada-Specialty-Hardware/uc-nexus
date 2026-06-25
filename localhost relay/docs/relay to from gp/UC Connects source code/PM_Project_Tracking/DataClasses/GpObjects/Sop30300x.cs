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
    [mp.Table(Name = "[SOP30300]")]
    public class Sop30300x
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
            }
        }

        [mp.Column(Name = "ITEMNMBR")]
        public string ItemNumber
        {
            get { return _itemNumber; }
            set
            {
                _itemNumber = value;

            }
        }

        [mp.Column(Name = "ITEMDESC")]
        public string ItemDescription
        {
            get { return _itemDescription; }
            set
            {
                _itemDescription = value;

            }
        }

        [mp.Column(Name = "LOCNCODE")]
        public string LocationCode
        {
            get { return _locationCode; }
            set
            {
                _locationCode = value;

            }
        }



        public Sop30300x()
        {

        }

        public Sop30300x(string sopNumber, int lineSeq, string itemNumber, string itemDescription, decimal quantityOrdered)
        {
            this._sopNumber = sopNumber;
            this._lnitmseq = lineSeq;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._quantity = quantityOrdered;
        }

        public Sop30300x(string _docNum, int _lineSeq, int _quant, string _itemNum, string _desc, string locCode, decimal _unitCost, decimal _unitPrice, decimal _extPrice, bool _isNonInv, string lineCom)
        {
            this._sopNumber = _docNum;
            this._lnitmseq = _lineSeq;
            this._quantity = _quant;
            this._itemNumber = _itemNum;
            this._itemDescription = _desc;      //was previously this.Description = _desc;
            this._locationCode = locCode;
        }

    }
}
