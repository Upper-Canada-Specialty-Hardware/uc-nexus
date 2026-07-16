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
    [mp.Table(Name = "[JC00701]")]
    class Jc00701
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _jobNumber;
        private decimal _totalCost;

        private string _costCodeNumber1;
        private string _costCodeNumber2;
        private string _costCodeNumber3;
        private string _costCodeNumber4;

        private int _costCodeElement;

        [mp.Column(Name = "WS_Job_Number", IsPrimaryKey = true)]
        public string JobNumber
        {
            get
            {
                return _jobNumber;
            }

            set
            {
                _jobNumber = value;
            }
        }

        [mp.Column(Name = "Cost_Code_Act_Cost_TTD")]
        public decimal TotalCost
        {
            get
            {
                return _totalCost;
            }

            set
            {
                _totalCost = value;
            }
        }

        [mp.Column(Name = "Cost_Code_Number_1", IsPrimaryKey = true)]
        public string CostCodeNumber1
        {
            get
            {
                return _costCodeNumber1;
            }

            set
            {
                _costCodeNumber1 = value;
            }
        }

        [mp.Column(Name = "Cost_Code_Number_2", IsPrimaryKey = true)]
        public string CostCodeNumber2
        {
            get
            {
                return _costCodeNumber2;
            }

            set
            {
                _costCodeNumber2 = value;
            }
        }

        [mp.Column(Name = "Cost_Code_Number_3", IsPrimaryKey = true)]
        public string CostCodeNumber3
        {
            get
            {
                return _costCodeNumber3;
            }

            set
            {
                _costCodeNumber3 = value;
            }
        }

        [mp.Column(Name = "Cost_Code_Number_4", IsPrimaryKey = true)]
        public string CostCodeNumber4
        {
            get
            {
                return _costCodeNumber4;
            }

            set
            {
                _costCodeNumber4 = value;
            }
        }

        [mp.Column(Name = "Cost_Element", DbType = "bit", IsPrimaryKey = true)]
        public int CostCodeElement
        {
            get
            {
                return _costCodeElement;
            }

            set
            {
                _costCodeElement = value;
            }
        }
    }
}
