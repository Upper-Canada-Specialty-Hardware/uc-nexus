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
    [mp.Table(Name = "[POP10550]")]
    class Pop10550      //PO line comments
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _poNumber;
        private int _order;
        private string _cmmtText;

        [mp.Column(Name = "POPNUMBE")]
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

        [mp.Column(Name = "CMMTTEXT")]
        public string CmmtText
        {
            get { return _cmmtText; }
            set { _cmmtText = value; }
        }
    }
}
