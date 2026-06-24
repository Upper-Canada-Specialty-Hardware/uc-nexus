using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using dc = PM_Project_Tracking.DataClasses;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using System.Data.SqlClient;
using System.Windows;
using System.Collections.ObjectModel;
using System.ComponentModel;

namespace PM_Project_Tracking.ProjectManagementClasses
{
    class ChangeIndexes
    {
        public static ChangeIndex GetChangeIndexByJob(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            ChangeIndex changeIndex = null;

            try
            {
                var indexQuery = from indx in dtCtx.GetTable<ChangeIndex>()
                                 join jc in dtCtx.GetTable<gp.Jc00102>() on jobNumber equals jc.JobNumber into full
                                 from jc in full.DefaultIfEmpty()
                                 where indx.JobNumber == jobNumber
                                 select new
                                 {
                                     Id = indx.Id,
                                     JobNumber = indx.JobNumber,
                                     JobName = indx.JobName,
                                     ProjectManager = indx.ProjectManager,
                                     Coordinator = indx.Coordinator,
                                     HardwareLead = indx.HardwareLead,
                                     Contact = indx.ContactName,
                                     ContactEmail = indx.ContactEmail,
                                     ContractNumber = indx.ContractNumber,
                                     LastUpdated = indx.LastUpdated,

                                     OriginalContractAmount = jc.OriginalContractAmount,
                                     //ChangesToDate = dtCtx.GetTable<ChangeLine>().GroupJoin(dtCtx.GetTable<ChangeHeader>(), cl => cl.QuoteNumber, ch => ch.QuoteNumber, (cl, g) => new { cl = cl, g = g })
                                     //       .SelectMany(temp => temp.g.DefaultIfEmpty(), (temp, ch) => new { cl = temp.cl, ch = ch })
                                     //       .Where(x => x.cl.JobNumber == jobNumber && x.ch.JobNumber == jobNumber && x.ch.Cancelled == false)
                                     //       .Select(r => r.cl.ExtendedSellPrice + (r.cl.ExtendedSellPrice * r.ch.OverheadPercentage / 100) + (r.cl.ExtendedSellPrice * r.ch.ProfitPercentage / 100)).Sum()
                                     //       == null ? 0 :
                                     //       dtCtx.GetTable<ChangeLine>().GroupJoin(dtCtx.GetTable<ChangeHeader>(), cl => cl.QuoteNumber, ch => ch.QuoteNumber, (cl, g) => new { cl = cl, g = g })
                                     //       .SelectMany(temp => temp.g.DefaultIfEmpty(), (temp, ch) => new { cl = temp.cl, ch = ch })
                                     //       .Where(x => x.cl.JobNumber == jobNumber && x.ch.JobNumber == jobNumber && x.ch.Cancelled == false)
                                     //       .Select(r => r.cl.ExtendedSellPrice + (r.cl.ExtendedSellPrice * r.ch.OverheadPercentage / 100) + (r.cl.ExtendedSellPrice * r.ch.ProfitPercentage / 100)).Sum(),

                                     ChangesToDate = dtCtx.GetTable<ChangeLine>().GroupJoin(dtCtx.GetTable<ChangeHeader>(), cl => cl.QuoteNumber, ch => ch.QuoteNumber, (cl, g) => new { cl = cl, g = g })
                                            .SelectMany(temp => temp.g.DefaultIfEmpty(), (temp, ch) => new { cl = temp.cl, ch = ch })
                                            .Where(x => x.cl.JobNumber == jobNumber && x.ch.JobNumber == jobNumber && x.ch.Approved == true && x.ch.Cancelled == false)
                                            .Select(r => r.cl.ExtendedSellPrice + (r.cl.ExtendedSellPrice * r.ch.OverheadPercentage / 100) + (r.cl.ExtendedSellPrice * r.ch.ProfitPercentage / 100)).Sum()
                                            == null ? 0 :
                                            dtCtx.GetTable<ChangeLine>().GroupJoin(dtCtx.GetTable<ChangeHeader>(), cl => cl.QuoteNumber, ch => ch.QuoteNumber, (cl, g) => new { cl = cl, g = g })
                                            .SelectMany(temp => temp.g.DefaultIfEmpty(), (temp, ch) => new { cl = temp.cl, ch = ch })
                                            .Where(x => x.cl.JobNumber == jobNumber && x.ch.JobNumber == jobNumber && x.ch.Approved == true && x.ch.Cancelled == false)
                                            .Select(r => r.cl.ExtendedSellPrice + (r.cl.ExtendedSellPrice * r.ch.OverheadPercentage / 100) + (r.cl.ExtendedSellPrice * r.ch.ProfitPercentage / 100)).Sum(),

                                     DateCreated = indx.DateCreated,
                                    TimeCreated = indx.TimeCreated,
                                    UpdatingUser = indx.UpdatingUser,
                                    UpdatingMachine = indx.UpdatingMachine
                                };

                changeIndex = indexQuery.AsEnumerable().Select(x => new ChangeIndex(x.Id, x.JobNumber, x.JobName, x.ProjectManager, x.Coordinator
                                                                                    , x.HardwareLead, x.Contact, x.ContactEmail, x.ContractNumber, x.LastUpdated
                                                                                    , x.OriginalContractAmount
                                                                                    , x.ChangesToDate
                                                                                    , x.DateCreated
                                                                                    , x.TimeCreated
                                                                                    , x.UpdatingUser
                                                                                    , x.UpdatingMachine)).FirstOrDefault();
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
                dtCtx.Dispose();
            }

            return changeIndex;
        }

        public static void CreateIndex(ChangeIndex ch)
        {
            using (ChangeIndexDataContext dtCtx = new ChangeIndexDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    int _headerId = GetNextChangeIndexId(ch.JobNumber);
                    ch.Id = _headerId;
                    ch.DateCreated = DateTime.Today;
                    ch.TimeCreated = DateTime.Now;
                    ch.UpdatingUser = Environment.UserName;
                    ch.UpdatingMachine = Environment.MachineName;
                    dtCtx.ChangeIndex.InsertOnSubmit(ch);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void UpdateIndex(ChangeIndex ch)
        {
            using (ChangeIndexDataContext dtCtx = new ChangeIndexDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    ch.LastUpdated = DateTime.Today;
                    dtCtx.ChangeIndex.Attach(ch, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, ch);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        private static int GetNextChangeIndexId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMCHANGEINDEX101]";
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

    [mp.Table(Name = "[PMCHANGEINDEX101]")]
    public class ChangeIndex : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _jobName;
        private string _projectManager;
        private string _coordinator;
        private string _hardwareLead;
        private string _contactName;
        private string _contactEmail;
        private string _contractNumber;

        private decimal _originalContractAmount;
        private decimal _changesToDate;
        private decimal _revisedContractAmount;

        private DateTime? _lastUpdated;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;

        [mp.Column(Name = "ID", IsPrimaryKey = true)]
        public int Id
        {
            get { return _id; }
            set 
            { 
                _id = value;
                this._isModified = true;
            }
        }

        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set 
            { 
                _jobNumber = value;
                this._isModified = true;
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
                this._isModified = true;
                OnPropertyChanged("JobName");
            }
        }

        [mp.Column(Name = "ProjectManager")]
        public string ProjectManager
        {
            get { return _projectManager; }
            set 
            { 
                _projectManager = value;
                this._isModified = true;
                OnPropertyChanged("ProjectManager");
            }
        }

        [mp.Column(Name = "Coordinator")]
        public string Coordinator
        {
            get { return _coordinator; }
            set 
            { 
                _coordinator = value;
                this._isModified = true;
                OnPropertyChanged("Coordinator");
            }
        }

        [mp.Column(Name = "HardwareLead")]
        public string HardwareLead
        {
            get { return _hardwareLead; }
            set 
            { 
                _hardwareLead = value;
                this._isModified = true;
                OnPropertyChanged("HardwareLead");
            }
        }

        [mp.Column(Name = "ContactName")]
        public string ContactName
        {
            get { return _contactName; }
            set
            {
                _contactName = value;
                this._isModified = true;
                OnPropertyChanged("Contact");
            }
        }

        [mp.Column(Name = "ContactEmail")]
        public string ContactEmail
        {
            get { return _contactEmail; }
            set
            {
                _contactEmail = value;
                this._isModified = true;
                OnPropertyChanged("ContactEmail");
            }
        }

        [mp.Column(Name = "ContractNumber")]
        public string ContractNumber
        {
            get { return _contractNumber; }
            set
            {
                _contractNumber = value;
                this._isModified = true;
                OnPropertyChanged("ContractNumber");
            }
        }

        //Derived from a WennSoft table
        public decimal OriginalContractAmount
        {
            get { return _originalContractAmount; }
            set 
            { 
                _originalContractAmount = value;
                //_revisedContractAmount = _changesToDate + _originalContractAmount;
                //OnPropertyChanged("OriginalContractAmount");
                //OnPropertyChanged("RevisedContractAmount");
            }
        }

        //Summed from quote line tables
        public decimal ChangesToDate
        {
            get { return _changesToDate; }
            set 
            { 
                _changesToDate = value;
                _revisedContractAmount = _changesToDate + _originalContractAmount;
                OnPropertyChanged("ChangesToDate");
                OnPropertyChanged("RevisedContractAmount");
            }
        }

        //Summed from quote line tables
        public decimal RevisedContractAmount
        {
            get { return _revisedContractAmount; }
            set 
            { 
                _revisedContractAmount = value;
                OnPropertyChanged("RevisedContractAmount");
            }
        }

        [mp.Column(Name = "LastUpdated")]
        public DateTime? LastUpdated
        {
            get { return _lastUpdated; }
            set 
            { 
                _lastUpdated = value;
                OnPropertyChanged("LastUdpated");
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


        public ChangeIndex()
        {

        }

        public ChangeIndex(dc.CombinedProject cp)
        {
            this._id = 0;
            this._jobNumber = cp.MainProject.JobNumber;
            this._jobName = cp.Jc00102.JobName;
            this._projectManager = cp.MainProject.ProjectManager;
            //this._consultant = cp.Jc00102.Consultant;
            this._originalContractAmount = cp.Jc00102.ProjectValue;
            this._contractNumber = cp.AwardedContract.ContractNumber;
            //last updated
            //contact
            //contact email
            //GetChangeSums += ChangeLineItems.CollectionChanged;
            
        }

        public ChangeIndex(int id, string jobNumber, string jobName, string projectManager, string coordinator
                           , string hardwareLead, string contactName, string contactEmail, string contractNumber, DateTime? lastUpdated
                           , decimal originalContractAmount
                           , decimal changesToDate
                           , DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine)
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._projectManager = projectManager;
            this._coordinator = coordinator;
            this._hardwareLead = hardwareLead;
            this._contactName = contactName;
            this._contactEmail = contactEmail;
            this._contractNumber = contractNumber;
            this._lastUpdated = lastUpdated;

            this._originalContractAmount = originalContractAmount;
            this.ChangesToDate = changesToDate; //Aimed at the property instead of field in order to trigger the setter that updates the revised contract value.

            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class ChangeIndexDataContext : lq.DataContext
    {
        public ChangeIndexDataContext(string cs)
            : base(cs)
        {
        }

        public ChangeIndexDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ChangeIndex> ChangeIndex;
    }

}
