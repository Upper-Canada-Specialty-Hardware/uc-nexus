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


namespace PM_Project_Tracking.ProjectManagementClasses
{
    class ProgressBillingLines
    {
        public static ObservableCollection<ProgressBillingLine> GetProgressBillingStandardLines(ProgressBillingHeader pbHeader)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ProgressBillingLine> lineList = null;

            try
            {
                var headerQuery = from pb in dtCtx.GetTable<ProgressBillingLine>()
                                  where pb.JobNumber == pbHeader.JobNumber && pb.BillingHeaderIteration == pbHeader.Iteration
                                  && pb.BillingHeaderRevision == pbHeader.Revision && pb.ChangeOrder == false
                                  select new
                                  {
                                      Id = pb.Id,
                                      JobNumber = pb.JobNumber,
                                      BillingHeaderIteration = pb.BillingHeaderIteration,
                                      BillingHeaderRevision = pb.BillingHeaderRevision,
                                      Serial = pb.Serial,
                                      CostCode = pb.CostCode,
                                      BaseDescription = pb.BaseDescription,
                                      BaseContract = pb.BaseContract,
                                      CurrentAmount = pb.CurrentAmount,
                                      PreviousAmount = pb.PreviousAmount,
                                      ChangeOrder = pb.ChangeOrder,
                                      QuoteNumber = pb.QuoteNumber,
                                      Cpoc = pb.Cpoc,
                                      DateCreated = pb.DateCreated,
                                      TimeCreated = pb.TimeCreated,
                                      UpdatingUser = pb.UpdatingUser,
                                      UpdatingMachine = pb.UpdatingMachine
                                  };

                lineList = headerQuery.AsEnumerable().Select(x => new ProgressBillingLine(x.Id, x.JobNumber, x.BillingHeaderIteration, x.BillingHeaderRevision, x.Serial
                                                                                          , x.CostCode, x.BaseDescription, x.BaseContract 
                                                                                          , x.CurrentAmount, x.PreviousAmount, x.ChangeOrder
                                                                                          , x.QuoteNumber, x.Cpoc
                                                                                          , x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine)).ToList();

                if (lineList.Count == 0)
                {
                    lineList = new List<ProgressBillingLine>();
                    return new ObservableCollection<ProgressBillingLine>(lineList);
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
            return new ObservableCollection<ProgressBillingLine>(lineList);
        }

        public static ObservableCollection<ProgressBillingLine> GetProgressBillingChangeLines(ProgressBillingHeader pbHeader)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ProgressBillingLine> lineList = null;

            try
            {
                var headerQuery = from pb in dtCtx.GetTable<ProgressBillingLine>()
                                  where pb.JobNumber == pbHeader.JobNumber && pb.BillingHeaderIteration == pbHeader.Iteration
                                  && pb.BillingHeaderRevision == pbHeader.Revision && pb.ChangeOrder == true
                                  select new
                                  {
                                      Id = pb.Id,
                                      JobNumber = pb.JobNumber,
                                      BillingHeaderIteration = pb.BillingHeaderIteration,
                                      BillingHeaderRevision = pb.BillingHeaderRevision,
                                      Serial = pb.Serial,
                                      CostCode = pb.CostCode,
                                      BaseDescription = pb.BaseDescription,
                                      BaseContract = pb.BaseContract,
                                      CurrentAmount = pb.CurrentAmount,
                                      PreviousAmount = pb.PreviousAmount,
                                      ChangeOrder = pb.ChangeOrder,
                                      QuoteNumber = pb.QuoteNumber,
                                      Cpoc = pb.Cpoc,
                                      DateCreated = pb.DateCreated,
                                      TimeCreated = pb.TimeCreated,
                                      UpdatingUser = pb.UpdatingUser,
                                      UpdatingMachine = pb.UpdatingMachine,

                                      DrawDownList = ChangeLineDrawDowns.GetChangeLineDrawDownsViaBillingLine(pb.JobNumber, pb.BillingHeaderIteration, pb.BillingHeaderRevision, pb.Serial, pb)
                                  };

                lineList = headerQuery.AsEnumerable().Select(x => new ProgressBillingLine(x.Id, x.JobNumber, x.BillingHeaderIteration, x.BillingHeaderRevision, x.Serial
                                                                                          , x.CostCode, x.BaseDescription, x.BaseContract 
                                                                                          , x.CurrentAmount, x.PreviousAmount, x.ChangeOrder
                                                                                          , x.QuoteNumber, x.Cpoc
                                                                                          , x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine
                                                                                          , x.DrawDownList)).ToList();

                if (lineList.Count == 0)
                {
                    lineList = new List<ProgressBillingLine>();
                    return new ObservableCollection<ProgressBillingLine>(lineList);
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
            return new ObservableCollection<ProgressBillingLine>(lineList);
        }

        public static void UpdateProgBillLines(ObservableCollection<ProgressBillingLine> _progBillLineCol)
        {
            using (ProgressBillLineDataContext dtCtx = new ProgressBillLineDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime _today = DateTime.Today;
                DateTime _now = DateTime.Now;
                foreach (ProgressBillingLine cl in _progBillLineCol)
                {
                    try
                    {
                        if (cl.Id == 0 && cl.IsDeleted != true)
                        {
                            cl.DateCreated = _today;
                            cl.TimeCreated = _now;
                            cl.UpdatingUser = Environment.UserName;
                            cl.UpdatingMachine = Environment.MachineName;
                            cl.Id = GetNextProgressBillLineId(cl.JobNumber);
                            dtCtx.ProgressBillingLine.InsertOnSubmit(cl);
                        }
                        else if (cl.Id != 0 && cl.IsModified == true)
                        {
                            dtCtx.ProgressBillingLine.Attach(cl, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, cl);
                        }
                        else if (cl.Id != 0 && cl.IsDeleted == true)
                        {
                            dtCtx.ProgressBillingLine.Attach(cl, cl);
                            dtCtx.Refresh(lq.RefreshMode.KeepChanges, cl);
                            dtCtx.ProgressBillingLine.DeleteOnSubmit(cl);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static void DeleteProgressBillChangeLines(ObservableCollection<ProgressBillingLine> _progBillLineCol)
        {
            using (ProgressBillLineDataContext dtCtx = new ProgressBillLineDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ProgressBillingLine cl in _progBillLineCol)
                {
                    try
                    {
                        if (cl.IsNew)
                        {
                            dtCtx.ProgressBillingLine.Attach(cl, cl);
                            dtCtx.Refresh(lq.RefreshMode.KeepChanges, cl);
                            dtCtx.ProgressBillingLine.DeleteOnSubmit(cl);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static int GetNextProgressBillLineId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMPROGRESSBILLINGLINE101]";
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

    [mp.Table(Name = "PMPROGRESSBILLINGLINE101")]
    public class ProgressBillingLine : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private int _billingHeaderIteration;
        private int _billingHeaderRevision;
        private int _serial;
        private string _costCode;
        private string _baseDescription;        
        private decimal _baseContract;          //ORIGIN one-time value
        private decimal _previousAmount;        //ORIGIN for the purpose of the class, but derivative cumulative of previous billings
        private decimal _currentAmount;         //ORIGIN, decided by the user at the time of billing
        private decimal _completedAmount;       //DERIVATIVE of prevrious and current amount
        private decimal _balance;               //DERIVATIVE of base contract minus completed
        private decimal _holdbackPercentage;
        private bool _changeOrder;              //1 = regular progress billing, 2 = approved extras, 3 = unapproved extras  //Unapproved will be totally derivative, only need two types
        private string _quoteNumber;            //Only for billing type 2
        private string _cpoc;                   //Only for billing type 2

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        //No need for _isNew because an _id value of 0 implies new

        private bool _isModified;
        private bool _isDeleted;
        private bool _isNew;

        private ChangeLineDrawDownCollection _drawDownsList;

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

        [mp.Column(Name = "BillingHeaderIteration", IsPrimaryKey = true)]
        public int BillingHeaderIteration
        {
            get { return _billingHeaderIteration; }
            set 
            { 
                _billingHeaderIteration = value;
                OnPropertyChanged("BillingHeaderIteration");
            }
        }

        [mp.Column(Name = "BillingHeaderRevision", IsPrimaryKey = true)]
        public int BillingHeaderRevision
        {
            get { return _billingHeaderRevision; }
            set 
            { 
                _billingHeaderRevision = value;
                OnPropertyChanged("BillingHeaderRevision");
            }
        }

        [mp.Column(Name = "Serial", IsPrimaryKey = true)]
        public int Serial
        {
            get { return _serial; }
            set 
            { 
                _serial = value;
                OnPropertyChanged("Serial");
            }
        }

        [mp.Column(Name = "CostCode")]
        public string CostCode
        {
            get { return _costCode; }
            set 
            { 
                _costCode = value;
                OnPropertyChanged("CostCode");
            }
        }

        [mp.Column(Name = "BaseDescription")]
        public string BaseDescription
        {
            get { return _baseDescription; }
            set 
            { 
                _baseDescription = value;
                _isModified = true;
                OnPropertyChanged("BaseDescription");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "BaseContract")]
        public decimal BaseContract
        {
            get { return _baseContract; }
            set 
            { 
                _baseContract = value;
                _balance = _baseContract - _completedAmount;
                _isModified = true;
                OnPropertyChanged("BaseContract");
                OnPropertyChanged("Balance");
                OnPropertyChanged("IsModified");
            }
        }

        //come back to this
        public decimal CompletedAmount
        {
            get { return _completedAmount; }
            set 
            { 
                _completedAmount = value;
                _isModified = true;
                OnPropertyChanged("CompletedAmount");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "PreviousAmount")]
        public decimal PreviousAmount
        {
            get { return _previousAmount; }
            set 
            { 
                _previousAmount = value;
                _completedAmount = _currentAmount + value;
                _balance = _baseContract - _completedAmount;
                _isModified = true;
                OnPropertyChanged("PreviousAmount");
                OnPropertyChanged("CompletedAmount");
                OnPropertyChanged("Balance");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "CurrentAmount")]
        public decimal CurrentAmount
        {
            get { return _currentAmount; }
            set 
            { 
                _currentAmount = value;
                _completedAmount = _previousAmount + value;
                _isModified = true;
                _balance = _baseContract - _completedAmount;
                OnPropertyChanged("CurrentAmount");
                OnPropertyChanged("CompletedAmount");
                OnPropertyChanged("Balance");
                OnPropertyChanged("IsModified");
            }
        }


        public decimal Balance
        {
            get { return _balance; }
            set 
            { 
                _balance = value;
                _isModified = true;
                OnPropertyChanged("Balance");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "HoldbackPercentage")]
        public decimal HoldbackPercentage
        {
            get { return _holdbackPercentage; }
            set 
            { 
                _holdbackPercentage = value;
                _isModified = true;
                OnPropertyChanged("HoldbackPercentage");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "ChangeOrder", IsPrimaryKey = true, DbType="bit", CanBeNull=false)]
        public bool ChangeOrder
        {
            get { return _changeOrder; }
            set 
            { 
                _changeOrder = value;
                OnPropertyChanged("ChangeOrder");
            }
        }

        [mp.Column(Name = "QuoteNumber")]
        public string QuoteNumber
        {
            get { return _quoteNumber; }
            set 
            { 
                _quoteNumber = value;
                OnPropertyChanged("QuoteNumber");
            }
        }

        [mp.Column(Name = "CPOC")]
        public string Cpoc
        {
            get { return _cpoc; }
            set 
            { 
                _cpoc = value;
                OnPropertyChanged("Cpoc");
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

        public bool IsNew
        {
            get { return _isNew; }
            set { _isNew = value; }
        }

        public ChangeLineDrawDownCollection DrawDownsList
        {
            get { return _drawDownsList; }
            set { _drawDownsList = value; }
        }

        public ProgressBillingLine()
        {
            this._drawDownsList = new ChangeLineDrawDownCollection(this);
        }

        //
        public ProgressBillingLine(ProgressBillingHeader header,string costCode, int serial, bool isChangeOrder, string quoteNumber)
        {
            this._isNew = true;
            this._jobNumber = header.JobNumber;
            this._billingHeaderIteration = header.Iteration;
            this._billingHeaderRevision = header.Revision;
            this._costCode = costCode;
            this._serial = serial;
            this._changeOrder = isChangeOrder;
            if (this._changeOrder)
                this._quoteNumber = quoteNumber;

            this._holdbackPercentage = 0.1m;

            this._drawDownsList = new ChangeLineDrawDownCollection(this);
        }

        public ProgressBillingLine(int id, string jobNumber, int billingHeaderIteration, int billingHeaderRevision, int serial
                                    ,string costCode, string baseDescription, decimal baseContract
                                    ,decimal currentAmount, decimal previousAmount, bool changeOrder
                                    ,string quoteNumber, string cpoc, DateTime? dateCreated, DateTime? timeCreated, string updatingUser
                                    ,string updatingMachine)
        {
            this._isNew = false;
            this._id = id;
            this._jobNumber = jobNumber;
            this._billingHeaderIteration = billingHeaderIteration;
            this._billingHeaderRevision = billingHeaderRevision;
            this._serial = serial;
            this._costCode = costCode;
            this._baseDescription = baseDescription;
            this._baseContract = baseContract;
            this._currentAmount = currentAmount;
            this._previousAmount = previousAmount;
            this._completedAmount = _currentAmount + _previousAmount;
            this._balance = _baseContract - _completedAmount;
            this._changeOrder = changeOrder;
            this._quoteNumber = quoteNumber;
            this._cpoc = cpoc;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this._drawDownsList = new ChangeLineDrawDownCollection(this);
        }

        public ProgressBillingLine(int id, string jobNumber, int billingHeaderIteration, int billingHeaderRevision, int serial
                            , string costCode, string baseDescription, decimal baseContract
                            , decimal currentAmount, decimal previousAmount, bool changeOrder
                            , string quoteNumber, string cpoc, DateTime? dateCreated, DateTime? timeCreated, string updatingUser
                            , string updatingMachine, List<ChangeLineDrawDown> drawDownCol)
        {
            this._isNew = false;
            this._id = id;
            this._jobNumber = jobNumber;
            this._billingHeaderIteration = billingHeaderIteration;
            this._billingHeaderRevision = billingHeaderRevision;
            this._serial = serial;
            this._costCode = costCode;
            this._baseDescription = baseDescription;
            this._baseContract = baseContract;
            this._currentAmount = currentAmount;
            this._previousAmount = previousAmount;
            this._completedAmount = _currentAmount + _previousAmount;
            this._balance = _baseContract - _completedAmount;
            this._changeOrder = changeOrder;
            this._quoteNumber = quoteNumber;
            this._cpoc = cpoc;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this._drawDownsList = new ChangeLineDrawDownCollection(drawDownCol);
            _drawDownsList.PbChangeLine = this;
        }

        private void GetCostCodeSerial(string costCode, ObservableCollection<ProgressBillingLine> blList)
        {
            int iter = 1;
            foreach (ProgressBillingLine bl in blList)
            {
                if (bl._serial >= iter)
                    iter = bl._serial + 1;
            }
            this._serial = iter;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

    }

    public class ProgressBillLineDataContext : lq.DataContext
    {
        public ProgressBillLineDataContext(string cs)
            : base(cs)
        {
        }

        public ProgressBillLineDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ProgressBillingLine> ProgressBillingLine;
    }
}
