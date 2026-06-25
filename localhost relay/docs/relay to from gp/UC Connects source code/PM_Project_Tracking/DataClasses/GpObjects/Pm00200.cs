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
    [mp.Table(Name = "[PM00200]")]
    class Pm00200
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _vendorId;
        private string _vendorName;

        [mp.Column(Name = "VENDORID")]
        public string VendorId
        {
            get { return _vendorId; }
            set { _vendorId = value; }
        }

        [mp.Column(Name = "VENDNAME")]
        public string VendorName
        {
            get { return _vendorName; }
            set { _vendorName = value; }
        }
    }
}
