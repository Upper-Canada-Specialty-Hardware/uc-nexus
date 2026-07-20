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

    [mp.Table(Name = "[POP30300]")]
    class Pop30300
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _popRctNum;
        private DateTime? _glPostDate;

        [mp.Column(Name = "POPRCTNM", IsPrimaryKey = true)]
        public string PopRctNum
        {
            get { return _popRctNum; }
            set { _popRctNum = value; }
        }

        [mp.Column(Name = "GLPOSTDT")]
        public DateTime? GlPostDate
        {
            get { return _glPostDate; }
            set { _glPostDate = value; }
        }

        public Pop30300()
        {
        }
    }
}
