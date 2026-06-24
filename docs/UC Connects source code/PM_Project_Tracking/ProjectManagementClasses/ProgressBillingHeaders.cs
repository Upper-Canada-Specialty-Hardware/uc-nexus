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
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.ProjectManagementClasses
{
    class ProgressBillingHeaders
    {
        public static ObservableCollection<ProgressBillingHeader> GetProgressBillingHeaders(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ProgressBillingHeader> headerList = null;

            try
            {
                var headerQuery = from pb in dtCtx.GetTable<ProgressBillingHeader>()
                                  where pb.JobNumber == jobNumber
                                  select new
                                  {
                                      Id = pb.Id,
                                      JobNumber = pb.JobNumber,
                                      ContractNumber = pb.ContractNumber,
                                      HstNumber = pb.HstNumber,
                                      CompanyAddress = pb.Address,
                                      TelephoneNumber = pb.TelephoneNumber,
                                      FaxNumber = pb.FaxNumber,
                                      Iteration = pb.Iteration,
                                      BillingName = pb.BillingName,
                                      OriginalContractAmount = pb.OriginalContractAmount,
                                      Cancelled = pb.Cancelled,
                                      Revision = pb.Revision,
                                      Billed = pb.Billed,
                                      BillingDate = pb.BillingDate,
                                      BillingUser = pb.BillingUser,
                                      InvoiceNumber = pb.InvoiceNumber,
                                      InvoiceDate = pb.InvoiceDate,
                                      InvoicingUser = pb.InvoicingUser,
                                      DateCreated = pb.DateCreated,
                                      TimeCreated = pb.TimeCreated,
                                      UpdatingUser = pb.UpdatingUser,
                                      UpdatingMachine = pb.UpdatingMachine,

                                      GrossInvoiceCurrent = dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == false)
                                      .Select(x => x.CurrentAmount).Sum() == null ?
                                      0 : dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == false)
                                      .Select(x => x.CurrentAmount).Sum(),

                                      GrossInvoicePrevious = dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == false)  //if more than 1 revision of same iteration, all should be cancelled except most current, so it shouldn't over-sum
                                      .Select(x => x.PreviousAmount).Sum() == null ?
                                      0 : dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == false)
                                      .Select(x => x.PreviousAmount).Sum(),

                                      ApprovedChangeOrdersCurrent = dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == true)
                                      .Select(x => x.CurrentAmount).Sum() == null ?
                                      0 : dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == true)
                                      .Select(x => x.CurrentAmount).Sum(),

                                      ApprovedChangeOrdersPrevious = dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == true)
                                      .Select(x => x.PreviousAmount).Sum() == null ?
                                      0 : dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == true)
                                      .Select(x => x.PreviousAmount).Sum(),

                                      InvoicedHoldbackCurrent = dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == false)
                                      .Select(x => (x.CurrentAmount * x.HoldbackPercentage)).Sum()  == null ?
                                      0 : dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision)
                                      .Select(x => (x.CurrentAmount * x.HoldbackPercentage)).Sum(),

                                      InvoicedHoldbackPrevious = dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision && n.ChangeOrder == false)
                                      .Select(x => (x.PreviousAmount * x.HoldbackPercentage)).Sum()  == null ?
                                      0 : dtCtx.GetTable<ProgressBillingLine>().Where(n => n.JobNumber == jobNumber && n.BillingHeaderIteration == pb.Iteration && n.BillingHeaderRevision == pb.Revision)
                                      .Select(x => (x.PreviousAmount * x.HoldbackPercentage)).Sum(),

                                      CurrentHoldbackReleased = pb.CurrentHoldbackReleased,
                                      PreviousHoldbackReleased = pb.PreviousHoldbackReleased
                                  };

                headerList = headerQuery.AsEnumerable().Select(x => new ProgressBillingHeader(x.Id, x.JobNumber, x.ContractNumber, x.HstNumber, x.CompanyAddress
                                                                                            ,x.TelephoneNumber, x.FaxNumber ,x.Iteration, x.BillingName, x.OriginalContractAmount
                                                                                            ,x.Cancelled ,x.Revision, x.Billed, x.BillingDate, x.BillingUser
                                                                                            ,x.InvoiceNumber, x.InvoiceDate, x.InvoicingUser
                                                                                            ,x.DateCreated ,x.TimeCreated, x.UpdatingUser, x.UpdatingMachine
                                                                                            ,x.GrossInvoiceCurrent, x.GrossInvoicePrevious, x.ApprovedChangeOrdersCurrent, x.ApprovedChangeOrdersPrevious
                                                                                            ,x.InvoicedHoldbackCurrent, x.InvoicedHoldbackPrevious, x.CurrentHoldbackReleased, x.PreviousHoldbackReleased)).ToList();

                if (headerList.Count == 0)
                {
                    headerList = new List<ProgressBillingHeader>();
                    return new ObservableCollection<ProgressBillingHeader>(headerList);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return new ObservableCollection<ProgressBillingHeader>(headerList);
        }

        public static void CreateNewProgressBilling(ProgressBillingHeader pbHeader)
        {
            using (ProgressBillHeaderDataContext dtCtx = new ProgressBillHeaderDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime _today = DateTime.Today;
                DateTime _now = DateTime.Now;

                    try
                    {
                        pbHeader.DateCreated = _today;
                        pbHeader.TimeCreated = _now;
                        pbHeader.UpdatingUser = Environment.UserName;
                        pbHeader.UpdatingMachine = Environment.MachineName;
                        pbHeader.Id = GetNextProgressBillHeaderId(pbHeader.JobNumber);
                        dtCtx.ProgressBillingHeader.InsertOnSubmit(pbHeader);
                        dtCtx.SubmitChanges();
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }


        public static int GetNextProgressBillHeaderId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMPROGRESSBILLINGHEADER101]";
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

    [mp.Table(Name = "PMPROGRESSBILLINGHEADER101")]
    public class ProgressBillingHeader : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _contractNumber;
        private string _hstNumber;
        private string _address;
        private string _telephoneNumber;
        private string _faxNumber;
        private int _iteration;
        private string _billingName;
        private decimal _originalContractAmount;
        private decimal _currentHoldbackReleased;
        private decimal _previousHoldbackReleased;

        private bool _cancelled;
        private int _revision;
        private bool _billed;
        private DateTime? _billingDate;
        private string _billingUser;
        private string _invoiceNumber;
        private DateTime? _invoiceDate;
        private string _invoicingUser;

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private HeaderSubtotals _headerSubs;

        [mp.Column(Name = "ID")]
        public int Id
        {
            get { return _id; }
            set 
            { 
                _id = value;
                OnPropertyChanged("Id");
            }
        }

        [mp.Column(Name = "JobNumber", IsPrimaryKey = true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set 
            { 
                _jobNumber = value;
                OnPropertyChanged("JobNumber");
            }
        }

        [mp.Column(Name = "Iteration", IsPrimaryKey = true)]
        public int Iteration
        {
            get { return _iteration; }
            set 
            { 
                _iteration = value;
                OnPropertyChanged("Iteration");
            }
        }

        [mp.Column(Name = "ContractNumber")]
        public string ContractNumber
        {
            get { return _contractNumber; }
            set { _contractNumber = value; }
        }

        [mp.Column(Name = "HstNumber")]
        public string HstNumber
        {
            get { return _hstNumber; }
            set { _hstNumber = value; }
        }

        [mp.Column(Name = "CompanyAddress")]
        public string Address
        {
            get { return _address; }
            set { _address = value; }
        }

        [mp.Column(Name = "TelephoneNumber")]
        public string TelephoneNumber
        {
            get { return _telephoneNumber; }
            set { _telephoneNumber = value; }
        }

        [mp.Column(Name = "FaxNumber")]
        public string FaxNumber
        {
            get { return _faxNumber; }
            set { _faxNumber = value; }
        }

        [mp.Column(Name = "BillingName")]
        public string BillingName
        {
            get { return _billingName; }
            set 
            { 
                _billingName = value;
                OnPropertyChanged("BillingName");
            }
        }

        [mp.Column(Name = "OriginalContractAmount")]
        public decimal OriginalContractAmount
        {
            get { return _originalContractAmount; }
            set { _originalContractAmount = value; }
        }

        [mp.Column(Name = "CurrentHoldbackReleased")]
        public decimal CurrentHoldbackReleased
        {
            get { return _currentHoldbackReleased; }
            set { _currentHoldbackReleased = value; }
        }

        [mp.Column(Name = "PreviousHoldbackReleased")]
        public decimal PreviousHoldbackReleased
        {
            get { return _previousHoldbackReleased; }
            set { _previousHoldbackReleased = value; }
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

        [mp.Column(Name = "Revision", IsPrimaryKey = true)]
        public int Revision
        {
            get { return _revision; }
            set 
            { 
                _revision = value;
                OnPropertyChanged("Revision");
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

        [mp.Column(Name = "InvoiceNumber")]
        public string InvoiceNumber
        {
            get { return _invoiceNumber; }
            set { _invoiceNumber = value; }
        }

        [mp.Column(Name = "InvoiceDate")]
        public DateTime? InvoiceDate
        {
            get { return _invoiceDate; }
            set { _invoiceDate = value; }
        }

        [mp.Column(Name = "InvoicingUser")]
        public string InvoicingUser
        {
            get { return _invoicingUser; }
            set { _invoicingUser = value; }
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

        internal HeaderSubtotals HeaderSubs
        {
            get { return _headerSubs; }
            set { _headerSubs = value; }
        }

        public ProgressBillingHeader()
        {
            this.HeaderSubs = new HeaderSubtotals();
        }

        //Constructor for first progress billing of the project
        public ProgressBillingHeader(dc.CombinedProject combProj, string billingName, string contractNumber, string hstNumber)
        {
            this._jobNumber = combProj.MainProject.JobNumber;
            this._iteration = 0;
            this._revision = 0;
            this._billingName = billingName;
            this._contractNumber = contractNumber;
            this._hstNumber = hstNumber;
        }

        //Constructor for creating new progress billings off of previous ones
        public ProgressBillingHeader(int id, string jobNumber, int iteration, string billingName, bool cancelled
                                    , int revision, bool billed, DateTime? billingDate, string billingUser, DateTime? dateCreated
                                    , DateTime? timeCreated, string updatingUser, string updatingMachine
                                    //, decimal grossInvoiceCurrent, decimal grossInvoicePrevious, decimal approvedChangeOrdersCurrent, decimal approvedChangeOrdersPrevious
                                    //, decimal invoicedHoldbackCurrent
                                    )
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._iteration = iteration;
            this._billingName = billingName;
            this._cancelled = cancelled;
            this._revision = revision;
            this._billed = billed;
            this._billingDate = billingDate;
            this._billingUser = billingUser;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this.HeaderSubs = new HeaderSubtotals();

            //this.HeaderSubs.GrossInvoiceCurrent = grossInvoiceCurrent;
            //this.HeaderSubs.GrossInvoicePrevious = grossInvoicePrevious;
            //this.HeaderSubs.ApprovedChangeOrdersCurrent = approvedChangeOrdersCurrent;
            //this.HeaderSubs.ApprovedChangeOrdersPrevious = approvedChangeOrdersPrevious;
            //this.HeaderSubs.InvoicedHoldbackCurrent = invoicedHoldbackCurrent;
        }

        //Constructor for creating new revision progress billings in the main progress billing maindow
        public ProgressBillingHeader(ProgressBillingHeader pb)
        {
            this._id = pb.Id;
            this._jobNumber = pb.JobNumber;
            this._iteration = pb.Iteration;
            this._billingName = pb.BillingName;
            this._cancelled = pb.Cancelled;
            this._revision = pb.Revision;
            this._billed = pb.Billed;
            this._billingDate = pb.BillingDate;
            this._billingUser = pb.BillingUser;
            //this._dateCreated = pb.DateCreated;
            //this._timeCreated = pb.TimeCreated;
            //this._updatingUser = pb.UpdatingUser;
            //this._updatingMachine = pb.UpdatingMachine;

            this.HeaderSubs = new HeaderSubtotals();

            //this.HeaderSubs.GrossInvoiceCurrent = grossInvoiceCurrent;
            //this.HeaderSubs.GrossInvoicePrevious = grossInvoicePrevious;
            //this.HeaderSubs.ApprovedChangeOrdersCurrent = approvedChangeOrdersCurrent;
            //this.HeaderSubs.ApprovedChangeOrdersPrevious = approvedChangeOrdersPrevious;
            //this.HeaderSubs.InvoicedHoldbackCurrent = invoicedHoldbackCurrent;
        }

        public ProgressBillingHeader(int id, string jobNumber, string contractNumber, string hstNumber, string companyAddress
                                    , string phoneNumber, string faxNumber, int iteration, string billingName, decimal originalContractAmount
                                    , bool cancelled
                                    , int revision, bool billed, DateTime? billingDate, string billingUser 
                                    , string invoiceNumber, DateTime? invoiceDate, string invoicingUser
                                    , DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine
                                    , decimal grossInvoiceCurrent, decimal grossInvoicePrevious, decimal approvedChangeOrdersCurrent, decimal approvedChangeOrdersPrevious
                                    , decimal invoicedHoldbackCurrent, decimal invoicedHoldbackPrevious, decimal currentHoldbackReleased, decimal previousHoldbackReleased)
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._contractNumber = contractNumber;
            this._hstNumber = hstNumber;
            this._address = companyAddress;
            this._telephoneNumber = phoneNumber;
            this._faxNumber = faxNumber;
            this._iteration = iteration;
            this._billingName = billingName;
            this._originalContractAmount = originalContractAmount;
            this._cancelled = cancelled;
            this._revision = revision;
            this._billed = billed;
            this._billingDate = billingDate;
            this._billingUser = billingUser;
            this._invoiceNumber = invoiceNumber;
            this._invoiceDate = invoiceDate;
            this._invoicingUser = invoicingUser;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this.HeaderSubs = new HeaderSubtotals();

            this.HeaderSubs.GrossInvoiceCurrent = grossInvoiceCurrent;
            this.HeaderSubs.GrossInvoicePrevious = grossInvoicePrevious;
            this.HeaderSubs.ApprovedChangeOrdersCurrent = approvedChangeOrdersCurrent;
            this.HeaderSubs.ApprovedChangeOrdersPrevious = approvedChangeOrdersPrevious;
            this.HeaderSubs.InvoicedHoldbackCurrent = invoicedHoldbackCurrent;
            this.HeaderSubs.InvoicedHoldbackPrevious = invoicedHoldbackPrevious;
            this.HeaderSubs.HoldbackReleasedCurrent = currentHoldbackReleased;
            this.HeaderSubs.HoldbackReleasedPrevious = previousHoldbackReleased;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

    }

    internal class HeaderSubtotals
    {
        private decimal _grossInvoiceCurrent;
        private decimal _grossInvoicePrevious;
        private decimal _grossInvoiceToDate;
        private decimal _approvedChangeOrdersCurrent;
        private decimal _approvedChangeOrdersPrevious;
        private decimal _approvedChangeOrdersToDate;
        private decimal _subtotalGrossInvoiceCurrent;
        private decimal _subtotalGrossInvoicePrevious;
        private decimal _subtotalGrossInvoiceToDate;
        private decimal _invoicedHoldbackCurrent; //_
        private decimal _invoicedHoldbackPrevious;
        private decimal _invoicedHoldbackToDate;
        private decimal _holdbackReleasedCurrent;
        private decimal _holdbackReleasedPrevious;
        private decimal _holdbackReleasedToDate;
        private decimal _netInvoiceCurrent;
        private decimal _netInvoicePrevious;
        private decimal _netInvoiceToDate;
        private decimal _addHstCurrent;
        private decimal _addHstPrevious;
        private decimal _addHstToDate;
        private decimal _totalCurrent;
        private decimal _totalPrevious;
        private decimal _totalToDate;


        public decimal GrossInvoiceCurrent
        {
            get { return _grossInvoiceCurrent; }
            set 
            { 
                _grossInvoiceCurrent = value;
                _grossInvoiceToDate = _grossInvoicePrevious + _grossInvoiceCurrent;

                _subtotalGrossInvoiceCurrent = _approvedChangeOrdersCurrent + _grossInvoiceCurrent;
                _subtotalGrossInvoiceToDate = _subtotalGrossInvoiceCurrent + _subtotalGrossInvoicePrevious;

                _netInvoiceCurrent = Math.Abs(_subtotalGrossInvoiceCurrent) - _invoicedHoldbackCurrent + _holdbackReleasedCurrent;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstCurrent = Math.Abs(_netInvoiceCurrent) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalCurrent = _netInvoiceCurrent + Math.Abs(_addHstCurrent);
                _totalToDate = _totalCurrent + _totalPrevious;
            }
        }


        public decimal GrossInvoicePrevious
        {
            get { return _grossInvoicePrevious; }
            set 
            { 
                _grossInvoicePrevious = value;
                _grossInvoiceToDate = _grossInvoiceCurrent + _grossInvoicePrevious;

                _subtotalGrossInvoicePrevious = _approvedChangeOrdersPrevious + _grossInvoicePrevious;
                _subtotalGrossInvoiceToDate = _subtotalGrossInvoiceCurrent + _subtotalGrossInvoicePrevious;

                _netInvoicePrevious = Math.Abs(_subtotalGrossInvoicePrevious) - _invoicedHoldbackPrevious + _holdbackReleasedPrevious;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstPrevious = Math.Abs(_netInvoicePrevious) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalPrevious = _netInvoicePrevious + Math.Abs(_addHstPrevious);
                _totalToDate = _totalCurrent + _totalPrevious;
            }
        }


        public decimal GrossInvoiceToDate
        {
            get { return _grossInvoiceToDate; }
            //set { _grossInvoiceToDate = value; }
        }


        public decimal ApprovedChangeOrdersCurrent
        {
            get { return _approvedChangeOrdersCurrent; }
            set 
            { 
                _approvedChangeOrdersCurrent = value;
                _approvedChangeOrdersToDate = _approvedChangeOrdersPrevious + _approvedChangeOrdersCurrent;

                _subtotalGrossInvoiceCurrent = _grossInvoiceCurrent + _approvedChangeOrdersCurrent;
                _subtotalGrossInvoiceToDate = _subtotalGrossInvoiceCurrent + _subtotalGrossInvoicePrevious;

                _netInvoiceCurrent = Math.Abs(_subtotalGrossInvoiceCurrent) - _invoicedHoldbackCurrent + _holdbackReleasedCurrent;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstCurrent = Math.Abs(_netInvoiceCurrent) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalCurrent = _netInvoiceCurrent + Math.Abs(_addHstCurrent);
                _totalToDate = _totalCurrent + _totalPrevious;
            }
        }


        public decimal ApprovedChangeOrdersPrevious
        {
            get { return _approvedChangeOrdersPrevious; }
            set 
            { 
                _approvedChangeOrdersPrevious = value;
                _approvedChangeOrdersToDate = _approvedChangeOrdersCurrent + _approvedChangeOrdersPrevious;

                _subtotalGrossInvoicePrevious = _grossInvoicePrevious + _approvedChangeOrdersPrevious;
                _subtotalGrossInvoiceToDate = _subtotalGrossInvoiceCurrent + _subtotalGrossInvoicePrevious;

                _netInvoicePrevious = Math.Abs(_subtotalGrossInvoicePrevious) - _invoicedHoldbackPrevious + _holdbackReleasedPrevious;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstPrevious = Math.Abs(_netInvoicePrevious) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalPrevious = _netInvoicePrevious + Math.Abs(_addHstPrevious);
                _totalToDate = _totalCurrent + _totalPrevious;
            }
        }


        public decimal ApprovedChangeOrdersToDate
        {
            get { return _approvedChangeOrdersToDate; }
            //set { _approvedChangeOrdersToDate = value; }
        }


        public decimal SubtotalGrossInvoiceCurrent  //Derivative value only, value is not directly set by the constructor ever, so no need to add up the values again
        {
            get { return _subtotalGrossInvoiceCurrent; }
            //set 
            //{ 
            //    _subtotalGrossInvoiceCurrent = value;
            //}
        }


        public decimal SubtotalGrossInvoicePrevious  //Derivative value only, value is not directly set by the constructor ever, so no need to add up the values again
        {
            get { return _subtotalGrossInvoicePrevious; }
            //set 
            //{ 
            //    _subtotalGrossInvoicePrevious = value;
            //}
        }


        public decimal SubtotalGrossInvoiceToDate
        {
            get { return _subtotalGrossInvoiceToDate; }
            //set { _subtotalGrossInvoiceToDate = value; }
        }


        public decimal InvoicedHoldbackCurrent
        {
            get { return _invoicedHoldbackCurrent; }
            set 
            { 
                _invoicedHoldbackCurrent = value;
                _invoicedHoldbackToDate = _invoicedHoldbackPrevious + _invoicedHoldbackCurrent;

                _netInvoiceCurrent = Math.Abs(_subtotalGrossInvoiceCurrent) - _invoicedHoldbackCurrent + _holdbackReleasedCurrent;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstCurrent = Math.Abs(_netInvoiceCurrent) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalCurrent = _netInvoiceCurrent + Math.Abs(_addHstCurrent);
                _totalToDate = _totalCurrent + _totalPrevious;
            }
        }


        public decimal InvoicedHoldbackPrevious
        {
            get { return _invoicedHoldbackPrevious; }
            set 
            { 
                _invoicedHoldbackPrevious = value;
                _invoicedHoldbackToDate = _invoicedHoldbackCurrent + _invoicedHoldbackPrevious;

                _netInvoicePrevious = Math.Abs(_subtotalGrossInvoicePrevious) - _invoicedHoldbackPrevious + _holdbackReleasedPrevious;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstPrevious = Math.Abs(_netInvoicePrevious) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalPrevious = _netInvoicePrevious + Math.Abs(_addHstPrevious);
                _totalToDate = _totalCurrent + _totalPrevious;
            }
        }


        public decimal InvoicedHoldbackToDate
        {
            get { return _invoicedHoldbackToDate; }
            //set { _invoicedHoldbackToDate = value; }
        }


        public decimal HoldbackReleasedCurrent
        {
            get { return _holdbackReleasedCurrent; }
            set 
            { 
                _holdbackReleasedCurrent = value;
                _holdbackReleasedToDate = _holdbackReleasedPrevious + _holdbackReleasedCurrent;

                _netInvoiceCurrent = Math.Abs(_subtotalGrossInvoiceCurrent) - _invoicedHoldbackCurrent + _holdbackReleasedCurrent;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstCurrent = Math.Abs(_netInvoiceCurrent) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalCurrent = _netInvoiceCurrent + Math.Abs(_addHstCurrent);
                _totalToDate = _totalCurrent + _totalPrevious;

            }
        }


        public decimal HoldbackReleasedPrevious
        {
            get { return _holdbackReleasedPrevious; }
            set 
            { 
                _holdbackReleasedPrevious = value;
                _holdbackReleasedToDate = _holdbackReleasedCurrent + _holdbackReleasedPrevious;

                _netInvoicePrevious = Math.Abs(_subtotalGrossInvoicePrevious) - _invoicedHoldbackPrevious + _holdbackReleasedPrevious;
                _netInvoiceToDate = Math.Abs(_subtotalGrossInvoiceToDate) - _invoicedHoldbackToDate + _holdbackReleasedToDate;

                _addHstPrevious = Math.Abs(_netInvoicePrevious) * 0.13m;
                _addHstToDate = _addHstCurrent + _addHstPrevious;

                _totalPrevious = _netInvoicePrevious + Math.Abs(_addHstPrevious);
                _totalToDate = _totalCurrent + _totalPrevious;

            }
        }


        public decimal HoldbackReleasedToDate
        {
            get { return _holdbackReleasedToDate; }
            //set { _holdbackReleasedToDate = value; }
        }


        public decimal NetInvoiceCurrent
        {
            get { return _netInvoiceCurrent; }
            set { _netInvoiceCurrent = value; }
        }


        public decimal NetInvoicePrevious
        {
            get { return _netInvoicePrevious; }
            set { _netInvoicePrevious = value; }
        }


        public decimal NetInvoiceToDate
        {
            get { return _netInvoiceToDate; }
            set { _netInvoiceToDate = value; }
        }


        public decimal AddHstCurrent
        {
            get { return _addHstCurrent; }
            set { _addHstCurrent = value; }
        }


        public decimal AddHstPrevious
        {
            get { return _addHstPrevious; }
            set { _addHstPrevious = value; }
        }


        public decimal AddHstToDate
        {
            get { return _addHstToDate; }
            set { _addHstToDate = value; }
        }


        public decimal TotalCurrent
        {
            get { return _totalCurrent; }
            set { _totalCurrent = value; }
        }


        public decimal TotalPrevious
        {
            get { return _totalPrevious; }
            set { _totalPrevious = value; }
        }


        public decimal TotalToDate
        {
            get { return _totalToDate; }
            set { _totalToDate = value; }
        }

        public HeaderSubtotals()
        {
        }

    }

    public class ProgressBillHeaderDataContext : lq.DataContext
    {
        public ProgressBillHeaderDataContext(string cs)
            : base(cs)
        {
        }

        public ProgressBillHeaderDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ProgressBillingHeader> ProgressBillingHeader;
    }
}
