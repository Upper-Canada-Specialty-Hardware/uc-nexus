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
    [mp.Table(Name = "[SOP10100]")]
    public class Sop10100
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private short _sopType;
        private string _sopNumber;
        private string _originNumber;
        private string _customerNumber;
        private string _customerName;
        private string _slprsnid;
        private DateTime? _docDate;
        private DateTime? _fulfillDate;
        private DateTime? _invoiceDate;
        private DateTime? _sopLineDate;

        [mp.Column(Name = "SOPTYPE", IsPrimaryKey=true)]
        public short SopType
        {
            get { return _sopType; }
            set { _sopType = value; }
        }

        [mp.Column(Name = "SOPNUMBE", IsPrimaryKey = true)]
        public string SopNumber
        {
            get { return _sopNumber; }
            set { _sopNumber = value; }
        }

        [mp.Column(Name = "ORIGNUMB")]
        public string OriginNumber
        {
            get { return _originNumber; }
            set { _originNumber = value; }
        }

        [mp.Column(Name = "CUSTNMBR")]
        public string CustomerNumber
        {
            get { return _customerNumber; }
            set { _customerNumber = value; }
        }

        [mp.Column(Name = "CUSTNAME")]
        public string CustomerName
        {
            get { return _customerName; }
            set { _customerName = value; }
        }

        [mp.Column(Name = "SLPRSNID")]
        public string Slprsnid
        {
            get { return _slprsnid; }
            set { _slprsnid = value; }
        }

        [mp.Column(Name = "DOCDATE")]
        public DateTime? DocDate
        {
            get
            {
                return _docDate;
            }

            set
            {
                _docDate = value;
            }
        }

        [mp.Column(Name = "FUFILDAT")]
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

        [mp.Column(Name = "INVODATE")]
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

        [mp.Column(Name = "DEX_ROW_TS")]
        public DateTime? SopLineDate
        {
            get
            {
                return _sopLineDate;
            }

            set
            {
                _sopLineDate = value;
            }
        }


        public Sop10100()
        {
        }

        public Sop10100(short sType, string sNum, string sOrg)
        {
            this._sopType = sType;
            this._sopNumber = sNum;
            this._originNumber = sOrg;
        }
    }
}
