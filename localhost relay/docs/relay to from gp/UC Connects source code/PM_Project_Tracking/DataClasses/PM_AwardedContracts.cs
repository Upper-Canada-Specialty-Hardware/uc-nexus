using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.ComponentModel;
using System.Collections.ObjectModel;
using System.Windows;
using System.Data.SqlClient;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.DataClasses
{
    public static class AwardedContracts
    {
        public static ObservableCollection<AwardedContract> GetAwardedContracts()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<AwardedContract> contrList = null;
            
            try
            {
                var contrQuery = from awContr in dtCtx.GetTable<AwardedContract>()
                                 //join jc in dtCtx.GetTable<GpObjects.Jc00102>() on awContr.JobNumber equals jc.JobNumber.Trim()
                                 orderby awContr.JobNumber descending
                                 select new
                                 {
                                     Id = awContr.Id,
                                     JobNumber = awContr.JobNumber,
                                     JobName = awContr.JobName,
                                     CustomerNumber = awContr.CustomerNumber,
                                     CustomerName = awContr.CustomerName,
                                     CustomerContName = awContr.CustomerContName,
                                     ContractNumber = awContr.ContractNumber,
                                     DateSubToContractor = awContr.DateSubToContractor,
                                     Copies = awContr.Copies,
                                     ContractStatus = awContr.ContractStatus,
                                     DateRetFromContractor = awContr.DateRetFromContractor,
                                     PreMobStatus = awContr.PreMobStatus,
                                     WsibClearance = awContr.WsibClearance,
                                     CertOfInsurance = awContr.CertOfInsurance,
                                     Form1000 = awContr.Form1000,
                                     UciSafetyManual = awContr.UciSafetyManual,
                                     UcaSafetyManual = awContr.UcaSafetyManual,
                                     SupervisorForm = awContr.SupervisorForm,
                                     Cad7Report = awContr.Cad7Report,
                                     FallProtection = awContr.FallProtection,
                                     PrequalSubDate = awContr.PreQualSubDate,
                                     Remarks = awContr.Remarks
                                 };

                contrList = contrQuery.AsEnumerable().Select(x => new AwardedContract(x.Id, x.JobNumber, x.JobName, x.CustomerNumber, x.CustomerName,
                                                                                      x.CustomerContName, x.ContractNumber, x.DateSubToContractor, x.Copies,
                                                                                      x.ContractStatus, x.DateRetFromContractor, x.PreMobStatus, x.WsibClearance,
                                                                                      x.CertOfInsurance, x.Form1000, x.UciSafetyManual, x.UcaSafetyManual,
                                                                                      x.SupervisorForm, x.Cad7Report, x.FallProtection, x.PrequalSubDate, x.Remarks)).ToList();

                if (contrList.Count == 0) { return new ObservableCollection<AwardedContract>(); }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
                if (contrList.Count == 0)
                    MessageBox.Show("Awarded contracts returned no entries from the database.");
            }
            return new ObservableCollection<AwardedContract>(contrList);
        }

        public static void UpdateAwardedContracts(ObservableCollection<AwardedContract> _preProjCol)
        {
            using (AwardContractDataContext dtCtx = new AwardContractDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (AwardedContract aw in _preProjCol) //No insert or delete operations since the AwardContract DataGrid only allows modification
                {
                    if (aw.IsModified == true)
                    {
                        //pp.DateModified = DateTime.Now;
                        try
                        {
                            dtCtx.AwardContract.Attach(aw, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, aw);
                        }
                        catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                    }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static void AddAwardedContract(AwardedContract aw)
        {
            using (AwardContractDataContext dtCtx = new AwardContractDataContext(GlobalVars.UcshConnectionString))
            {
                aw.UpdatingUser = Environment.UserName;
                aw.UpdatingMachine = Environment.MachineName;
                aw.DateCreated = DateTime.Today;
                aw.TimeCreated = DateTime.Now;
                try
                {
                    dtCtx.AwardContract.InsertOnSubmit(aw);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }
    }

    [mp.Table(Name = "[UTPMAWCONTRACTS101]")]
    public class AwardedContract : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _jobName;
        private string _customerNumber;
        private string _customerName;
        private string _customerContName;
        private string _contractNumber;
        private DateTime? _dateSubToContractor;
        private int _copies;
        private string _contractStatus;
        private DateTime? _dateRetFromContractor;
        private string _coordinator;       //Added 10 Jan 2018
        private string _preMobStatus;      
        private string _wsibClearance;
        private string _certOfInsurance;
        private bool _form1000;
        private bool _uciSafetyManual;
        private bool _ucaSafetyManual;
        private bool _supervisorForm;
        private bool _cad7Report;
        private bool _fallProtection;
        private DateTime? _preQualSubDate;
        private string _remarks;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;


        [mp.Column(Name = "ID", AutoSync = System.Data.Linq.Mapping.AutoSync.OnInsert, IsDbGenerated = true)]
        public int Id
        {
            get { return _id; }
            set 
            { 
                _id = value;
                OnPropertyChanged("Id");
            }
        }

        [mp.Column(Name = "JobNumber", IsPrimaryKey=true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set 
            { 
                _jobNumber = value;
                this.IsModified = true;
                OnPropertyChanged("JobNumber");
            }
        }

        [mp.Column(Name = "JobName")]
        public string JobName
        {
            get { return _jobName; }
            set 
            { 
                _jobName = value;
                this.IsModified = true;
                OnPropertyChanged("JobName");
            }
        }

        [mp.Column(Name = "CustomerNumber")]
        public string CustomerNumber
        {
            get { return _customerNumber; }
            set 
            { 
                _customerNumber = value;
                this.IsModified = true;
                OnPropertyChanged("CustomerNumber");
            }
        }

        [mp.Column(Name = "CustomerName")]
        public string CustomerName
        {
            get { return _customerName; }
            set 
            { 
                _customerName = value;
                this.IsModified = true;
                OnPropertyChanged("CustomerName");
            }
        }

        [mp.Column(Name = "CustomerContName")]
        public string CustomerContName
        {
            get { return _customerContName; }
            set 
            { 
                _customerContName = value;
                this.IsModified = true;
                OnPropertyChanged("CustomerContName");
            }
        }

        [mp.Column(Name = "ContractNumber")]
        public string ContractNumber
        {
            get { return _contractNumber; }
            set 
            { 
                _contractNumber = value;
                this.IsModified = true;
                OnPropertyChanged("ContractNumber");
            }
        }

        [mp.Column(Name = "DateSubToContractor")]
        public DateTime? DateSubToContractor
        {
            get { return _dateSubToContractor; }
            set 
            { 
                _dateSubToContractor = value;
                this.IsModified = true;
                OnPropertyChanged("DateSubToContractor");
            }
        }

        [mp.Column(Name = "Copies")]
        public int Copies
        {
            get { return _copies; }
            set 
            { 
                _copies = value;
                this.IsModified = true;
                OnPropertyChanged("Copies");
            }
        }

        [mp.Column(Name = "ContractStatus")]
        public string ContractStatus
        {
            get { return _contractStatus; }
            set 
            { 
                _contractStatus = value;
                this.IsModified = true;
                OnPropertyChanged("ContractStatus");
            }
        }

        [mp.Column(Name = "DateRetFromContractor")]
        public DateTime? DateRetFromContractor
        {
            get { return _dateRetFromContractor; }
            set 
            { 
                _dateRetFromContractor = value;
                this.IsModified = true;
                OnPropertyChanged("DateRetFromContractor");
            }
        }

        [mp.Column(Name = "Coordinator")]
        internal string Coordinator
        {
            get { return _coordinator; }
            set 
            { 
                _coordinator = value;
                this.IsModified = true;
                OnPropertyChanged("Coordinator");
            }
        }

        [mp.Column(Name = "PreMobStatus")]
        public string PreMobStatus
        {
            get { return _preMobStatus; }
            set 
            { 
                _preMobStatus = value;
                this.IsModified = true;
                OnPropertyChanged("PreMobStatus");
            }
        }

        [mp.Column(Name = "WSIBClearance")]
        public string WsibClearance
        {
            get { return _wsibClearance; }
            set 
            { 
                _wsibClearance = value;
                this.IsModified = true;
                OnPropertyChanged("WsibClearance");
            }
        }

        [mp.Column(Name = "CertOfInsurance")]
        public string CertOfInsurance
        {
            get { return _certOfInsurance; }
            set 
            { 
                _certOfInsurance = value;
                this.IsModified = true;
                OnPropertyChanged("CertOfInsurance");
            }
        }

        [mp.Column(Name = "Form1000")]
        public bool Form1000
        {
            get { return _form1000; }
            set 
            { 
                _form1000 = value;
                this.IsModified = true;
                OnPropertyChanged("Form1000");
            }
        }

        [mp.Column(Name = "UCISafetyManual")]
        public bool UciSafetyManual
        {
            get { return _uciSafetyManual; }
            set 
            { 
                _uciSafetyManual = value;
                this.IsModified = true;
                OnPropertyChanged("UciSafetyManual");
            }
        }

        [mp.Column(Name = "UCASafetyManual")]
        public bool UcaSafetyManual
        {
            get { return _ucaSafetyManual; }
            set 
            { 
                _ucaSafetyManual = value;
                this.IsModified = true;
                OnPropertyChanged("UcAccessSafetyManual");
            }
        }

        [mp.Column(Name = "SupervisorForm")]
        public bool SupervisorForm
        {
            get { return _supervisorForm; }
            set 
            { 
                _supervisorForm = value;
                this.IsModified = true;
                OnPropertyChanged("SupervisionForm");
            }
        }

        [mp.Column(Name = "Cad7Report")]
        public bool Cad7Report
        {
            get { return _cad7Report; }
            set 
            { 
                _cad7Report = value;
                this.IsModified = true;
                OnPropertyChanged("Cad7Report");
            }
        }

        [mp.Column(Name = "FallProtection")]
        public bool FallProtection
        {
            get { return _fallProtection; }
            set 
            { 
                _fallProtection = value;
                this.IsModified = true;
                OnPropertyChanged("FallProtection");
            }
        }

        [mp.Column(Name = "PreQualSubDate")]
        public DateTime? PreQualSubDate
        {
            get { return _preQualSubDate; }
            set 
            { 
                _preQualSubDate = value;
                this.IsModified = true;
                OnPropertyChanged("PreQualSubDate");
            }
        }

        [mp.Column(Name = "Remarks")]
        public string Remarks
        {
            get { return _remarks; }
            set 
            { 
                _remarks = value;
                this.IsModified = true;
                OnPropertyChanged("Remarks");
            }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set { _dateCreated = value; }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set { _timeCreated = value; }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set { _updatingUser = value; }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set { _updatingMachine = value; }
        }

        public bool IsModified
        {
            get { return _isModified; }
            set 
            { 
                _isModified = value;
                OnPropertyChanged("IsModified");
            }
        }

        public bool IsDeleted
        {
            get { return _isDeleted; }
            set { _isDeleted = value; }
        }

        public AwardedContract()
        {
        }

        //public AwardedContract(string jobNum, string jobName)
        //{
        //    this._jobNumber = jobNum;
        //    this._jobName = jobName;
        //}

        public AwardedContract(int id, string jobNum, string jobName, string custNum, string custName, string custConName, string contrNum,
                               DateTime? dateSubCont, int cops, string contractStat, DateTime? dateRetCont, string preMobStat, string wsib, string certIns,
                                bool form1, bool uciSafety, bool ucaSafety, bool supervisorForm, bool cad7, bool fallProtect, DateTime? preQualSub, string remarks)
        {
            this._id = id;
            this._jobNumber = jobNum;
            this._jobName = jobName;
            this._customerNumber = custNum;
            this._customerName = custName;
            this._customerContName = custConName;
            this._contractNumber = contrNum;
            this._dateSubToContractor = dateSubCont;
            this._copies = cops;
            this._contractStatus = contractStat;
            this._dateRetFromContractor = dateRetCont;
            this._preMobStatus = preMobStat;
            this._wsibClearance = wsib;
            this._certOfInsurance = certIns;
            this._form1000 = form1;
            this._uciSafetyManual = uciSafety;
            this._ucaSafetyManual = ucaSafety;
            this._supervisorForm = supervisorForm;
            this._cad7Report = cad7;
            this._fallProtection = fallProtect;
            this._preQualSubDate = preQualSub;
            this._remarks = remarks;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class AwardContractDataContext : lq.DataContext
    {
        public AwardContractDataContext(string cs)
            : base(cs)
        {
        }

        public AwardContractDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<AwardedContract> AwardContract;
    }
}
