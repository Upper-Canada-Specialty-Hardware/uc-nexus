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
    [mp.Table(Name = "[POP10100]")]
    class Pop10100
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _poNumber;
        private short _poStatus;
        private string _addressThree;

        private string _buyerId;
        private DateTime? _docDate;

        [mp.Column(Name = "PONUMBER")]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "POSTATUS")]
        public short PoStatus
        {
            get { return _poStatus; }
            set { _poStatus = value; }
        }

        [mp.Column(Name = "ADDRESS3")]
        public string AddressThree
        {
            get { return _addressThree; }
            set { _addressThree = value; }
        }

        [mp.Column(Name = "BUYERID")]
        public string BuyerId
        {
            get { return _buyerId; }
            set { _buyerId = value; }
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
    }
}
