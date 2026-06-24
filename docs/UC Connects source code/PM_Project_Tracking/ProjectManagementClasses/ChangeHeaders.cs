using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Data.SqlClient;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using dc = PM_Project_Tracking.DataClasses;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.ProjectManagementClasses
{
    public class ChangeHeaders
    {
        public static ModObservableCollection<ChangeHeader> GetChangeHeaders(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ChangeHeader> headerList = null;

            try
            {
                var headerQuery = from ch in dtCtx.GetTable<ChangeHeader>()
                                 where ch.JobNumber == jobNumber
                                 orderby ch.QuoteNumber ascending
                                 select new
                                 {
                                     Id = ch.Id,
                                     JobNumber = ch.JobNumber,
                                     QuoteNumber = ch.QuoteNumber,
                                     Iteration = ch.Iteration,
                                     ContractorProjectNumber = ch.ContractorProjectNumber,
                                     Contractor = ch.Contractor,
                                     ContractNumber = ch.ContractNumber,
                                     ContractorChangeId = ch.ContractorChangeId,
                                     HeaderDescription = ch.HeaderDescription,
                                     Manager = ch.Manager,
                                     //TotalQuoteValue = dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber).Select(x => x.ExtendedSellPrice).Sum() == null ?
                                     //0 : dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber).Select(x => x.ExtendedSellPrice).Sum(),

                                     TotalQuoteValue = dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber)
                                                                                    .Select(x => x.ExtendedSellPrice).Sum()
                                                                                    +
                                                                                    dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber)
                                                                                    .Where(i => i.IsLabour == false)
                                                                                    .Select(x => x.ExtendedSellPrice).Sum() * (ch.OverheadPercentage / 100)
                                                                                    +
                                                                                    dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber)
                                                                                    .Where(i => i.IsLabour == false)
                                                                                    .Select(x => x.ExtendedSellPrice).Sum() * (ch.ProfitPercentage / 100)
                                                                                    == null ? 0 :
                                                                                    dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber)
                                                                                    .Select(x => x.ExtendedSellPrice).Sum()
                                                                                    +
                                                                                    dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber)
                                                                                    .Where(i => i.IsLabour == false)
                                                                                    .Select(x => x.ExtendedSellPrice).Sum() * (ch.OverheadPercentage / 100)
                                                                                    +
                                                                                    dtCtx.GetTable<ChangeLine>().Where(n => n.JobNumber == jobNumber && n.QuoteNumber == ch.QuoteNumber)
                                                                                    .Where(i => i.IsLabour == false)
                                                                                    .Select(x => x.ExtendedSellPrice).Sum() * (ch.ProfitPercentage / 100),

                                     Cancelled = ch.Cancelled,
                                     Approved = ch.Approved,
                                     ApprovalDate = ch.ApprovalDate,
                                     AuthorizationNumber = ch.AuthorizationNumber,
                                     TentativeApproval = ch.TentativeApproval,
                                     TentativeApprovalDate = ch.TentativeApprovalDate,
                                     OverheadPercentage = ch.OverheadPercentage,
                                     ProfitPercentage = ch.ProfitPercentage,
                                     DateSubmitted = ch.DateSubmitted,
                                     Billed = ch.Billed,
                                     BillingDate = ch.BillingDate,
                                     BillingUser = ch.BillingUser,
                                     Revision = ch.Revision,
                                     //OriginatingDocumentNumber = ch.OriginatingDocumentNumber,
                                     RevisionIteration = ch.RevisionIteration,
                                     DateCreated = ch.DateCreated,
                                     TimeCreated = ch.TimeCreated,
                                     UpdatingUser = ch.UpdatingUser,
                                     UpdatingMachine = ch.UpdatingMachine
                                 };

                headerList = headerQuery.AsEnumerable().Select(x => new ChangeHeader(x.Id, x.JobNumber, x.QuoteNumber, x.Iteration,
                                                                                    x.ContractorProjectNumber, x.Contractor, 
                                                                                    x.ContractNumber, x.ContractorChangeId, x.HeaderDescription, x.Manager, 
                                                                                    x.TotalQuoteValue,
                                                                                    x.Cancelled, x.Approved, 
                                                                                    x.ApprovalDate, x.AuthorizationNumber,
                                                                                    x.TentativeApproval, x.TentativeApprovalDate,
                                                                                    x.OverheadPercentage, x.ProfitPercentage,
                                                                                    x.DateSubmitted,
                                                                                    x.Billed, x.BillingDate, x.BillingUser, x.Revision, 
                                                                                    //x.OriginatingDocumentNumber, 
                                                                                    x.RevisionIteration, x.DateCreated, x.TimeCreated, x.UpdatingUser, 
                                                                                    x.UpdatingMachine)).ToList();


                if (headerList.Count == 0) 
                {
                    headerList = new List<ChangeHeader>();
                    return new ModObservableCollection<ChangeHeader>(headerList); 
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ModObservableCollection<ChangeHeader>();
            }
            finally
            {
                dtCtx.Dispose();
                //if (headerList.Count == 0)
                //    MessageBox.Show("There are currently no change orders created for this project.");
            }
            return new ModObservableCollection<ChangeHeader>(headerList);
        }
        //adfersafds
        public static List<ChangeHeader> GetChangeQuotesForProgressBillDropDown(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ChangeHeader> headerList = null;

            try
            {
                var headerQuery = from ch in dtCtx.GetTable<ChangeHeader>()
                                  where ch.JobNumber == jobNumber
                                  orderby ch.QuoteNumber ascending
                                  select new
                                  {
                                      QuoteNumber = ch.QuoteNumber,
                                      HeaderDescription = ch.HeaderDescription,
                                  };

                headerList = headerQuery.AsEnumerable().Select(x => new ChangeHeader(x.QuoteNumber, x.HeaderDescription)).ToList();

                if (headerList.Count == 0)
                {
                    headerList = new List<ChangeHeader>();
                    return new List<ChangeHeader>(headerList);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new List<ChangeHeader>();
            }
            finally
            {
                dtCtx.Dispose();
                //if (headerList.Count == 0)
                //    MessageBox.Show("There are currently no change orders created for this project.");
            }
            return new List<ChangeHeader>(headerList);
        }

        public static bool CreateHeader(ChangeHeader ch)
        {
            bool _cont = false;

            using (ChangeHeaderDataContext dtCtx = new ChangeHeaderDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    int _headerId = GetNextChangeHeaderId(ch.JobNumber);
                    ch.Id = _headerId;
                    ch.DateCreated = DateTime.Today;
                    ch.TimeCreated = DateTime.Now;
                    ch.UpdatingUser = Environment.UserName;
                    ch.UpdatingMachine = Environment.MachineName;
                    dtCtx.ChangeHeader.InsertOnSubmit(ch);
                    dtCtx.SubmitChanges();
                    _cont = true;  //Only reached if .SubmitChanges() does not throw an exception

                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                return _cont;
            }
        }

        public static bool UpdateHeader(ChangeHeader ch)
        {
            bool _retBool = true;
            using (ChangeHeaderDataContext dtCtx = new ChangeHeaderDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.ChangeHeader.Attach(ch, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, ch);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) 
                { 
                    MessageBox.Show(ex.ToString()); 
                    _retBool = false;
                }

                return _retBool;
            }
        }

        private static int GetNextChangeHeaderId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMCHANGEHEADER101]";
                comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var _maxVal = comm.ExecuteScalar();
                if (_maxVal.GetType() == typeof(System.DBNull))
                    return 1;
                else
                    _idVal = (int)_maxVal + 1;
            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                if (conn != null)
                    conn.Close();
            }

            return _idVal;
        }
    }

    [mp.Table(Name = "PMCHANGEHEADER101")]
    public class ChangeHeader : INotifyPropertyChanged
    {
        //Remember to add these to the database switcher
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _quoteNumber;
        private int _iteration;                         //Used to iterate the quote number without playing string games with the QuoteNumber property itself.
        private string _contractorProjectNumber;        //probably not used
        private string _contractor;
        private string _contractNumber;
        private string _contractorChangeId;
        private string _headerDescription;
        private string _manager;

        private decimal? _totalQuoteValue;               //SYNTHETIC COLUMN

        private bool _cancelled;        //This is for change orders that have been cancelled because there's a revision of it.  Basically to help with summing for projects to exclude COs with the cancelled bool set to true.
        private bool _approved;
        private string _changeReference;                // - SI/FWO/EDGE BUILDER NUMBER
        private string _authorizationNumber;            // - CO/CD/CPOC
        private DateTime? _approvalDate;
        private bool _tentativeApproval;
        private DateTime? _tentativeApprovalDate;
        private string _pricedBy;
        private decimal _overheadPercentage;
        private decimal _profitPercentage;
        private decimal _marginUi;
        private decimal _overheadAmountUI;
        private decimal _profitAmountUI;
        private decimal _totalCostUI;
        private decimal _subtotalUI;
        private decimal _totalUI;

        private DateTime? _dateSubmitted;
        private bool _billed;
        private DateTime? _billingDate;
        private string _billingUser;
        private bool _revision;
        private string _originatingDocumentNumber;  //For tracking revision changes, this way we know how to iterate
        private string _originatingRevisionNumber;
        private int _revisionIteration;             //A straight number for which revision it is instead of playing string games with the full quote number like trying to get the next quote name from Q003r2
        // Might have to change all these public string properties to actual encapsulations later instead of autos

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private ObservableCollection<CostCodeAggregate> _costCodeSums = new ObservableCollection<CostCodeAggregate>();
        private ObservableCollection<ChangeLine> _changeLineItems = new ObservableCollection<ChangeLine>();

        [mp.Column(Name = "ID")]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "JobNumber", IsPrimaryKey=true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set 
            { 
                _jobNumber = value;
                OnPropertyChanged("JobNumber");
            }
        }

        [mp.Column(Name = "QuoteNumber", IsPrimaryKey = true)]
        public string QuoteNumber
        {
            get { return _quoteNumber; }
            set 
            { 
                _quoteNumber = value;
                OnPropertyChanged("QuoteNumber");
            }
        }

        [mp.Column(Name = "Iteration")]
        public int Iteration
        {
            get { return _iteration; }
            set 
            { 
                _iteration = value;
                OnPropertyChanged("Iteration");
            }
        }

        [mp.Column(Name = "ContractorProjectNumber")]
        public string ContractorProjectNumber
        {
            get { return _contractorProjectNumber; }
            set 
            {
                _contractorProjectNumber = value;
                OnPropertyChanged("ContractorProjectNumber");
            }
        }

        [mp.Column(Name = "Contractor")]
        public string Contractor
        {
            get { return _contractor; }
            set 
            { 
                _contractor = value;
                OnPropertyChanged("Contractor");
            }
        }

        [mp.Column(Name = "ContractNumber")]
        public string ContractNumber
        {
            get { return _contractNumber; }
            set 
            { 
                _contractNumber = value;
                OnPropertyChanged("ContractNumber");
            }
        }

        [mp.Column(Name = "ContractorChangeId")]
        public string ContractorChangeId
        {
            get { return _contractorChangeId; }
            set 
            { 
                _contractorChangeId = value;
                OnPropertyChanged("ContractorChangeId");
            }
        }

        [mp.Column(Name = "HeaderDescription")]
        public string HeaderDescription
        {
            get { return _headerDescription; }
            set 
            { 
                _headerDescription = value;
                OnPropertyChanged("HeaderDescription");
            }
        }

        [mp.Column(Name = "Revision")]
        public bool Revision
        {
            get { return _revision; }
            set 
            { 
                _revision = value;
                OnPropertyChanged("Revision");
            }
        }

        [mp.Column(Name = "Manager")]
        public string Manager
        {
            get { return _manager; }
            set 
            { 
                _manager = value;
                OnPropertyChanged("Manager");
            }
        }

        public decimal? TotalQuoteValue                  //Synthetic column derived from sum of quote lines from quote lines table, retrieved at data access time
        {
            get { return _totalQuoteValue; }
            set 
            { 
                _totalQuoteValue = value;
                OnPropertyChanged("TotalQuoteValue");
            }
        }

        [mp.Column(Name = "Cancelled")]
        public bool Cancelled
        {
            get { return _cancelled; }
            set 
            { 
                _cancelled = value;
                OnPropertyChanged("Cancelled");
            }
        }

        [mp.Column(Name = "Approved")]
        public bool Approved
        {
            get { return _approved; }
            set 
            { 
                _approved = value;
                OnPropertyChanged("Approved");
            }
        }

        [mp.Column(Name = "ChangeReference")]        //New column for - SI/FWO/EDGE BUILDER NUMBER
        public string ChangeReference
        {
            get { return _changeReference; }
            set { _changeReference = value; }
        }

        [mp.Column(Name = "AuthorizationNumber")]        //Formerly "ApprovalConfirmationNumber" - CO/CD/CPOC
        public string AuthorizationNumber
        {
            get { return _authorizationNumber; }
            set 
            { 
                _authorizationNumber = value;
                OnPropertyChanged("AuthorizationNumber");
            }
        } 

        [mp.Column(Name = "ApprovalDate")]
        public DateTime? ApprovalDate
        {
            get { return _approvalDate; }
            set 
            { 
                _approvalDate = value;
                OnPropertyChanged("ApprovalDate");
            }
        }

        [mp.Column(Name = "TentativeApproval")]
        public bool TentativeApproval
        {
            get { return _tentativeApproval; }
            set 
            { 
                _tentativeApproval = value;
                OnPropertyChanged("TentativeApproval");
            }
        }

        [mp.Column(Name = "TentativeApprovalDate")]
        public DateTime? TentativeApprovalDate
        {
            get { return _tentativeApprovalDate; }
            set 
            { 
                _tentativeApprovalDate = value;
                OnPropertyChanged("TentativeApprovalDate");
            }
        }

        //[mp.Column(Name = "PricedBy")]        //Miscommunication happened, 'pricedby' can't be done at the header level because a change has many different change lines with different cost codes priced by different people in different departments
        //public string PricedBy
        //{
        //    get
        //    {
        //        return _pricedBy;
        //    }
        //    set
        //    {
        //        _pricedBy = value;
        //        OnPropertyChanged("PricedBy");
        //    }
        //}

        [mp.Column(Name = "OverheadPercentage")]
        public decimal OverheadPercentage
        {
            get { return _overheadPercentage; }
            set 
            { 
                _overheadPercentage = value;
                OnPropertyChanged("OverheadPercentage");
                UpdateHeaderSums();
            }
        }

        [mp.Column(Name = "ProfitPercentage")]
        public decimal ProfitPercentage
        {
            get { return _profitPercentage; }
            set 
            { 
                _profitPercentage = value;
                OnPropertyChanged("ProfitPercentage");
                UpdateHeaderSums();
            }
        }

        [mp.Column(Name = "DateSubmitted")]
        public DateTime? DateSubmitted
        {
            get
            {
                return _dateSubmitted;
            }

            set
            {
                _dateSubmitted = value;
            }
        }

        [mp.Column(Name = "Billed")]
        public bool Billed
        {
            get { return _billed; }
            set 
            { 
                _billed = value;
                OnPropertyChanged("Billed");
            }
        }

        [mp.Column(Name = "BillingDate")]
        public DateTime? BillingDate
        {
            get { return _billingDate; }
            set 
            { 
                _billingDate = value;
                OnPropertyChanged("BillingDate");
            }
        }

        [mp.Column(Name = "BillingUser")]
        public string BillingUser
        {
            get { return _billingUser; }
            set 
            { 
                _billingUser = value;
                OnPropertyChanged("BillingUser");
            }
        }

        [mp.Column(Name = "OriginatingDocumentNumber")]
        public string OriginatingDocumentNumber
        {
            get { return _originatingDocumentNumber; }
            set 
            { 
                _originatingDocumentNumber = value;
                OnPropertyChanged("OriginatingDocumentNumber");
            }
        }

        [mp.Column(Name = "OriginatingRevisionNumber")]
        public string OriginatingRevisionNumber
        {
            get { return _originatingRevisionNumber; }
            set 
            { 
                _originatingRevisionNumber = value;
                OnPropertyChanged("OriginatingRevisionNumber");
            }
        }

        [mp.Column(Name = "RevisionIteration")]
        public int RevisionIteration
        {
            get { return _revisionIteration; }
            set 
            { 
                _revisionIteration = value;
                OnPropertyChanged("RevisionIteration");
            }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set 
            { 
                _dateCreated = value;
                OnPropertyChanged("DateCreated");
            }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set 
            { 
                _timeCreated = value;
                OnPropertyChanged("TimeCreated");
            }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set 
            { 
                _updatingUser = value;
                OnPropertyChanged("UpdatingUser");
            }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set 
            { 
                _updatingMachine = value;
                OnPropertyChanged("UpdatingMachine");
            }
        }

        //private decimal _totalSell;
        //private decimal _totalCost;

        internal ObservableCollection<CostCodeAggregate> CostCodeSums
        {
            get { return _costCodeSums; }
            set { _costCodeSums = value; }
        }

        public ObservableCollection<ChangeLine> ChangeLineItems
        {
            get { return _changeLineItems; }
            set
            {
                _changeLineItems = value;
                value.CollectionChanged += OnUpdateHeaderSums;
                UpdateHeaderSums();
            }
        }
        
        //Only set by the event, no need for public assignment
        public decimal MarginUi
        {
            get
            {
                return _marginUi;
            }

            set
            {
                _marginUi = value;
            }
        }

        public decimal OverheadAmountUI
        {
            get
            {
                return _overheadAmountUI;
            }

            set
            {
                _overheadAmountUI = value;
            }
        }

        public decimal ProfitAmountUI
        {
            get
            {
                return _profitAmountUI;
            }

            set
            {
                _profitAmountUI = value;
            }
        }

        public decimal TotalCostUI
        {
            get
            {
                return _totalCostUI;
            }

            set
            {
                _totalCostUI = value;
            }
        }

        public decimal SubtotalUI
        {
            get
            {
                return _subtotalUI;
            }

            set
            {
                _subtotalUI = value;
            }
        }

        public decimal TotalUI
        {
            get
            {
                return _totalUI;
            }

            set
            {
                _totalUI = value;
            }
        }



        public ChangeHeader()
        {

        }

        //UI Constructor
        public ChangeHeader(dc.CombinedProject cp, ObservableCollection<ChangeHeader> chList, ChangeHeader ch, int quoteAheadNumber)
        {
            GenerateNewQuoteNumber(chList, quoteAheadNumber); //Doesn't need a return value because it directly modifies the _quoteNumber field

            this._jobNumber = cp.MainProject.JobNumber;
            this._contractor = cp.Rm00101.CustomerName;
            this._manager = cp.MainProject.ProjectManager;
            this._contractorChangeId = "";
            this._headerDescription = "";
            this._authorizationNumber = "";

            if (ch != null)
            {
                this._contractorProjectNumber = ch.ContractorProjectNumber;
                this._contractNumber = ch.ContractNumber;
            }
            
        }

        //Combobox Constructor
        public ChangeHeader(string quoteNumber, string headerDescription)
        {
            this._quoteNumber = quoteNumber;
            this._contractor = "";
            this._manager = "";
            this._contractorChangeId = "";
            this._headerDescription = "";
            this._authorizationNumber = "";
        }

        //UI Revision Constructor
        public ChangeHeader(ChangeHeader ch)
        {
            this._id = 0;
            this._jobNumber = ch.JobNumber;
            this._iteration = ch.Iteration;
            this._revision = true;
            this._revisionIteration = ch.RevisionIteration + 1;
            //This is where the "r1r1" error is. Clearly, the Original Document Number isn't being recorded. Unless this was already fixed
            //with the fact that there's two if statements
//if (string.IsNullOrEmpty(ch.OriginatingDocumentNumber))
            if (this._revisionIteration == 1)
                this._quoteNumber = ch.QuoteNumber + "r1";
            else
                this._quoteNumber = ch.QuoteNumber.Substring(0, 4) + "r" + this._revisionIteration;


            //if (ch.Revision == false)
            //    this._originatingDocumentNumber = ch.QuoteNumber;
            //else
            //    this._originatingDocumentNumber = ch.OriginatingDocumentNumber;

            this._contractorProjectNumber = ch.ContractorProjectNumber;
            this._contractor = ch.Contractor;
            this._contractNumber = ch.ContractNumber;
            this._contractorChangeId = ch.ContractorChangeId;
            this._headerDescription = ch.HeaderDescription;
            this._manager = ch.Manager;
            this._totalQuoteValue = ch.TotalQuoteValue;
            this._cancelled = false;
            this._approved = false;
            //this._approvalDate = approvalDate;
            this._authorizationNumber = "";
            //this._tentativeApproval = tentativeApproval;
            //this._tentativeApprovalDate = tentativeApprovalDate;
            this._overheadPercentage = ch.OverheadPercentage;
            this._profitPercentage = ch.ProfitPercentage;
            //this._billed = ch.Billed;
            //this._billingDate = billingDate;
            //this._billingUser = billingUser;
            //this._revision = revision;
            //this._originatingDocumentNumber = ch.OriginatingDocumentNumber;

        }

        public ChangeHeader(int id, string jobNumber, string quoteNumber, int iteration,
                            string contractorProjectNumber, string contractor,
                            string contractNumber, string contractorChangeId, string headerDescription, string manager, 
                            decimal totalQuoteValue,
                            bool cancelled, bool approved, 
                            DateTime? approvalDate, string authorizationNumber,
                            bool tentativeApproval, DateTime? tentativeApprovalDate,
                            decimal overheadPercentage, decimal profitPercentage,
                            DateTime? dateSubmitted,
                            bool billed, DateTime? billingDate, string billingUser, bool revision, 
                            //string originatingDocumentNumber, 
                            int revisionIteration, DateTime? dateCreated, DateTime? timeCreated, string updatingUser, 
                            string updatingMachine)
        {
            //Debug.Print(totalQuoteValue.ToString());

            this._id = id;
            this._jobNumber = jobNumber;
            this._quoteNumber = quoteNumber;
            this._iteration = iteration;
            this._contractorProjectNumber = contractorProjectNumber;
            this._contractor = contractor;
            this._contractNumber = contractNumber;
            this._contractorChangeId = contractorChangeId;
            this._headerDescription = headerDescription;
            this._manager = manager;
            this._totalQuoteValue = totalQuoteValue;
            this._cancelled = cancelled;
            this._approved = approved;
            this._approvalDate = approvalDate;
            this._authorizationNumber = authorizationNumber;
            this._tentativeApproval = tentativeApproval;
            this._tentativeApprovalDate = tentativeApprovalDate;
            this._overheadPercentage = overheadPercentage;
            this._profitPercentage = profitPercentage;
            this._dateSubmitted = dateSubmitted;
            this._billed = billed;
            this._billingDate = billingDate;
            this._billingUser = billingUser;
            this._revision = revision;
            //this._originatingDocumentNumber = originatingDocumentNumber;
            this._revisionIteration = revisionIteration;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;
        }

        //private void GenerateNewQuoteNumber(ObservableCollection<ChangeHeader> chList)
        //{
        //    int iter = 1;
        //    foreach (ChangeHeader ch in chList)
        //    {
        //        if (ch.Iteration >= iter)
        //            iter = ch.Iteration + 1;
        //    }

        //    this._iteration = iter;

        //    if (iter < 10)
        //    {
        //        this._quoteNumber = "Q00" + iter; 
        //        return;
        //    }

        //    if (iter < 100)
        //    {
        //        this._quoteNumber = "Q0" + iter;
        //        return;
        //    }

        //    if (iter < 999)
        //    {
        //        this._quoteNumber = "Q" + iter; 
        //        return;

        //    }

        //    if (iter > 999)
        //    {
        //        this._quoteNumber = "Q" + iter; 
        //        return;
        //    }
        //}


        private void GenerateNewQuoteNumber(ObservableCollection<ChangeHeader> chList, int aheadQuoteNumber)
        {
            //If the user opted not to use the 'skip ahead' feature for quotes, aheadQuoteNumber will equal to -1 and this will proceed normally
            if (aheadQuoteNumber > -1)
                _iteration = aheadQuoteNumber;
            else if (chList.Count == 0)
                _iteration = 1;
            else
                _iteration = chList.Select(x => x.Iteration).Max() + 1;

            if (_iteration < 10)
            {
                this._quoteNumber = "Q00" + _iteration;
                return;
            }

            if (_iteration < 100)
            {
                this._quoteNumber = "Q0" + _iteration;
                return;
            }

            if (_iteration < 999)
            {
                this._quoteNumber = "Q" + _iteration;
                return;
            }

            if (_iteration > 999)
            {
                this._quoteNumber = "Q" + _iteration;
                return;
            }
        }
        internal void OnUpdateHeaderSums(object sender, System.Collections.Specialized.NotifyCollectionChangedEventArgs e)
        {
            UpdateHeaderSums();
        }

        private void UpdateHeaderSums()
        {
            decimal _totalRev = _changeLineItems.Sum(x => x.ExtendedSellPrice);
            this._overheadAmountUI = _changeLineItems.Where(x => x.IsLabour == false).Sum(i => i.ExtendedSellPrice) * (_overheadPercentage / 100);
            this._profitAmountUI = _changeLineItems.Where(x => x.IsLabour == false).Sum(i => i.ExtendedSellPrice) * (_profitPercentage / 100);

            //_totalRev may need to be changed since it doesn't include overhead or profit amounts.

            this._subtotalUI = _changeLineItems.Sum(x => x.ExtendedSellPrice);
            this._totalCostUI = _changeLineItems.Sum(x => x.TotalLineCostUcsh);
            //Running the _changeLines.Clear() method in the window closing event causes this to run again, where we have no items, so there's a divide by zero error if this isn't placed here
            if (_totalRev != 0)
            {
                this._marginUi = ((_totalRev - _totalCostUI) / _totalRev) * 100;
            }
            this._totalUI = _subtotalUI + _overheadAmountUI + _profitAmountUI;

            OnPropertyChanged("SubtotalUI");
            OnPropertyChanged("ProfitAmountUI");
            OnPropertyChanged("OverheadAmountUI");
            OnPropertyChanged("TotalCostUI");
            OnPropertyChanged("MarginUi");
            OnPropertyChanged("TotalUI");
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class ChangeHeaderDataContext : lq.DataContext
    {
        public ChangeHeaderDataContext(string cs)
            : base(cs)
        {
        }

        public ChangeHeaderDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ChangeHeader> ChangeHeader;
    }

    internal class CostCodeAggregate
    {
        private string _costCode;
        private string _costCodeName;
        private decimal _sellTotal;
        private decimal _costTotal;

        public string CostCode
        {
            get { return _costCode; }
            set { _costCode = value; }
        }

        public string CostCodeName
        {
            get { return _costCodeName; }
            set { _costCodeName = value; }
        }

        public decimal SellTotal
        {
            get { return _sellTotal; }
            set { _sellTotal = value; }
        }

        public decimal CostTotal
        {
            get { return _costTotal; }
            set { _costTotal = value; }
        }
        
    }
}
