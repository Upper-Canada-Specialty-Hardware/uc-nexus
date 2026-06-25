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
    [mp.Table(Name = "[POP10500]")]
    public class Pop10500
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _poNumber;
        private int _polnenum;
        private string _popRctNum;
        private int _rcptLnNm;
        private decimal? _quantityShipped;
        private decimal? _quantityMatched;
        private decimal? _quantityInvoiced;

        private decimal? _quantityTotalShipped;

        [mp.Column(Name = "PONUMBER", IsPrimaryKey = true)]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "POLNENUM", IsPrimaryKey = true)]
        public int Polnenum
        {
            get { return _polnenum; }
            set { _polnenum = value; }
        }

        [mp.Column(Name = "POPRCTNM", IsPrimaryKey = true)]
        public string PopRctNum
        {
            get { return _popRctNum; }
            set { _popRctNum = value; }
        }

        [mp.Column(Name = "RCPTLNNM", IsPrimaryKey = true)]
        public int RcptLnNm
        {
            get { return _rcptLnNm; }
            set { _rcptLnNm = value; }
        }

        [mp.Column(Name = "QTYSHPPD")]
        public decimal? QuantityShipped
        {
            get { return _quantityShipped; }
            set { _quantityShipped = value; }
        }

        [mp.Column(Name = "QTYMATCH")]
        public decimal? QuantityMatched
        {
            get { return _quantityMatched; }
            set { _quantityMatched = value; }
        }

        [mp.Column(Name = "QTYINVCD")]
        public decimal? QuantityInvoiced
        {
            get { return _quantityInvoiced; }
            set { _quantityInvoiced = value; }
        }

        public decimal? QuantityTotalShipped
        {
            get { return _quantityTotalShipped; }
            set { _quantityTotalShipped = value; }
        }

        public Pop10500()
        {
        }

        public Pop10500(string ponumber, int polnenum, decimal? quantityTotalShipped)
        {
            this._poNumber = ponumber;
            this._polnenum = polnenum;
            this._quantityTotalShipped = quantityTotalShipped;
        }

    }
}
