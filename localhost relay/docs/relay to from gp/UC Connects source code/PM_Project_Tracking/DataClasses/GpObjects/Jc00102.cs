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
    public static class Jc00102Load
    {
        internal static void GetJc00102()
        {

        }
    }

    [mp.Table(Name = "[JC00102]")]
    public class Jc00102
    {
        //No need for INotifyPropertyChanged since users will not be able to edit any of the values given that they're from GP.

        //JobNumber
        //JobName
        //Division 
        //Consultant        --Estimator_ID   or   WS_Manager_ID
        //CustomerNumber    --This will be needed in order to join customer data from RM00101
        //CustomerName
        //ProjectValue      --Orig_Contract_Amount  or   Contract_to_Date   or   Expected_Contract
        //CurrentBacklog
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _jobNumber;
        private string _jobName;
        private string _addressCode;
        private string _division;
        private string _consultant;
        private string _projectManager;
        private string _customerNumber;
        private string _customerName;        //Not actually on this table
        private decimal _projectValue;
        private decimal _originalContractAmount;

        private decimal _billedToDate;
        private decimal _totalActualCost;
        private DateTime? _creationDate;

        //Not actually on this table
        public string CustomerName
        {
            get { return _customerName; }
            set { _customerName = value; }
        }

        [mp.Column(Name = "WS_Job_Number", IsPrimaryKey = true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "WS_Job_Name")]
        public string JobName
        {
            get { return _jobName; }
            set { _jobName = value; }
        }

        [mp.Column(Name = "Job_Address_Code")]
        public string AddressCode
        {
            get { return _addressCode; }
            set { _addressCode = value; }
        }

        [mp.Column(Name = "Divisions")]
        public string Division
        {
            get { return _division; }
            set { _division = value; }
        }

        [mp.Column(Name = "WS_Manager_ID")]
        public string Consultant
        {
            get { return _consultant; }
            set { _consultant = value; }
        }

        [mp.Column(Name = "Estimator_ID")]
        public string ProjectManager
        {
            get { return _projectManager; }
            set { _projectManager = value; }
        }

        [mp.Column(Name = "CUSTNMBR")]
        public string CustomerNumber
        {
            get { return _customerNumber; }
            set { _customerNumber = value; }
        }

        [mp.Column(Name = "Contract_to_Date")]
        public decimal ProjectValue
        {
            get { return _projectValue; }
            set { _projectValue = value; }
        }

        [mp.Column(Name = "Orig_Contract_Amount")]
        public decimal OriginalContractAmount
        {
            get { return _originalContractAmount; }
            set { _originalContractAmount = value; }
        }

        [mp.Column(Name = "Total_Actual_Cost")]
        public decimal TotalActualCost
        {
            get
            {
                return _totalActualCost;
            }

            set
            {
                _totalActualCost = value;
            }
        }

        [mp.Column(Name = "Billed_Amount_TTD")]
        public decimal BilledToDate
        {
            get { return _billedToDate; }
            set { _billedToDate = value; }
        }

        [mp.Column(Name = "CREATDDT")]
        public DateTime? CreationDate
        {
            get { return _creationDate; }
            set { _creationDate = value; }
        }


        public Jc00102()
        {
        }

        public Jc00102(string projNum, string custNum)
        {
            this._jobNumber = projNum;
            this._customerNumber = custNum;
        }
    }
}
