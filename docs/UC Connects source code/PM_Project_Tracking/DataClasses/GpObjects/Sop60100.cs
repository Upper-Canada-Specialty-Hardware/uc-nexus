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
    [mp.Table(Name = "[SOP60100]")]
    class Sop60100
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _sopNumber;
        private short _sopType;
        private int _sopLnitmseq;
        private int _sopCmpntseq;
        private string _poNumber;
        private int _order;
        private string _locncode;
        private string _buyerId;

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
            get { return _sopLnitmseq; }
            set { _sopLnitmseq = value; }
        }

        [mp.Column(Name = "CMPNTSEQ")]
        public int Cmpntseq
        {
            get
            {
                return _sopCmpntseq;
            }

            set
            {
                _sopCmpntseq = value;
            }
        }

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

        [mp.Column(Name = "LOCNCODE")]
        public string Locncode
        {
            get { return _locncode; }
            set { _locncode = value; }
        }

        public string BuyerId           //Deriving from POP10100, not a property that is actually part of SOP60100
        {
            get { return _buyerId; }
            set { _buyerId = value; }
        }


        public Sop60100()
        {
        }

        public Sop60100(string ponumber, string locncode, string sopnumber)
        {
            this._poNumber = ponumber;
            this._locncode = locncode;
            this._sopNumber = sopnumber;
        }

        public Sop60100(string ponumber, string locncode, string sopnumber, string buyerId)
        {
            this._poNumber = ponumber;
            this._locncode = locncode;
            this._sopNumber = sopnumber;
            this._buyerId = buyerId;
        }
    }
}
