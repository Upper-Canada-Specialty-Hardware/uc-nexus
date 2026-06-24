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
    [mp.Table(Name = "[JC00901]")]
    class Jc00901
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _jobNumber;
        private short _inactive;

        [mp.Column(Name = "WS_Job_Number")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "WS_Inactive")]
        public short Inactive
        {
            get { return _inactive; }
            set { _inactive = value; }
        }
    }
}
