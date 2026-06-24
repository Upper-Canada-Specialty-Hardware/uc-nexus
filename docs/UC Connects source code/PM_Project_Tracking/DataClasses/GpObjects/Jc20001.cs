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
    [mp.Table(Name = "[JC20001]")]
    class Jc20001
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _jobNumber;
        private decimal _cost_Code_Act_Cost_TTD;

        [mp.Column(Name = "WS_Job_Number")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "Cost_Code_Act_Cost_TTD")]
        public decimal Cost_Code_Act_Cost_TTD
        {
            get
            {
                return _cost_Code_Act_Cost_TTD;
            }

            set
            {
                _cost_Code_Act_Cost_TTD = value;
            }
        }
    }
}
