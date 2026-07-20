using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.ComponentModel;
using System.Data.SqlClient;
using System.Collections.ObjectModel;
using System.Windows;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;


namespace PM_Project_Tracking.ProjectManagementClasses
{
    public static class SubmittalLines
    {
        internal static ObservableCollection<SubmittalLine> GetSubmittalsByJobNumber(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<SubmittalLine> submittalList = null;

            try
            {
                var subQuery = from sub in dtCtx.GetTable<SubmittalLine>()
                               where sub.JobNumber == jobNumber
                               select new
                               {
                                   Id = sub.Id,
                                   JobNumber = sub.JobNumber,
                                   BlockNumber = sub.BlockNumber,
                                   ItemType = sub.ItemType,
                                   Reference = sub.Reference,
                                   DateReturnedFromContractor = sub.DateReturnedFromContractor,
                                   QuantityPerPage = sub.QuantityPerPage,
                                   SpecSection = sub.SpecSection,
                                   Copies = sub.Copies,
                                   Status = sub.Status,
                                   Remarks = sub.Remarks,
                                   DateSubmitted = sub.DateSubmitted,
                                   DateCreated = sub.DateCreated,
                                   TimeCreated = sub.TimeCreated,
                                   UpdatingUser = sub.UpdatingUser,
                                   UpdatingMachine = sub.UpdatingMachine
                               };

                submittalList = subQuery.AsEnumerable().Select(x => new SubmittalLine(x.Id, x.JobNumber, x.BlockNumber, x.ItemType, x.Reference
                                                                                , x.DateReturnedFromContractor, x.QuantityPerPage, x.SpecSection, x.Copies, x.Status
                                                                                , x.Remarks
                                                                                , x.DateSubmitted
                                                                                , x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<SubmittalLine>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<SubmittalLine>(submittalList);;
        }

        public static void UpdateSubmittals(ObservableCollection<SubmittalLine> _submittalCol, string jobNum)
        {
            using (SubmittalDataContext dtCtx = new SubmittalDataContext(GlobalVars.UcshConnectionString))
            {
                int _id = GetNextSubmittalId(jobNum);

                foreach (SubmittalLine sm in _submittalCol)
                {
                    try
                    {
                        if (sm.Id == 0 && sm.IsDeleted != true)
                        {
                            sm.DateCreated = DateTime.Today;
                            sm.TimeCreated = DateTime.Now;
                            sm.UpdatingUser = Environment.UserName;
                            sm.UpdatingMachine = Environment.MachineName;
                            sm.Id = _id++;
                            dtCtx.Submittal.InsertOnSubmit(sm);
                        }
                        else if (sm.Id != 0 && sm.IsModified == true)
                        {
                            dtCtx.Submittal.Attach(sm, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, sm);
                        }
                        else if (sm.Id != 0 && sm.IsDeleted == true)
                        {
                            dtCtx.Submittal.Attach(sm, sm);
                            dtCtx.Submittal.DeleteOnSubmit(sm);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }


        public static int GetNextSubmittalId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMSUBMITTALLINES101] where JobNumber='" + jobNumber + "'";
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

    [mp.Table(Name = "[PMSUBMITTALLINES101]")]
    public class SubmittalLine : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private bool _selForExport;
        private int _id;            //Id and JobNumber are primary key
        private string _jobNumber;
        private string _blockNumber;
        private string _itemType;
        private string _reference;
        private DateTime? _dateReturnedFromContractor;
        private int _quantityPerPage;
        private string _specSection;
        private int _copies;
        private string _status;
        private string _remarks;
        private DateTime? _dateSubmitted;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;


        public bool SelForExport
        {
            get
            {
                return _selForExport;
            }

            set
            {
                _selForExport = value;
                OnPropertyChanged("SelForExport");
            }
        }

        [mp.Column(Name = "ID", IsPrimaryKey = true)]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "JobNumber", IsPrimaryKey = true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set 
            {
                _jobNumber = value;                 //Only ever seen in a window that shows submittals by project anyway, so this column/property will never be shown to the UI.  At least for now.
                this.IsModified = true;           
                OnPropertyChanged("JobNumber");
            }
        }

        [mp.Column(Name = "BlockNumber")]
        public string BlockNumber
        {
            get { return _blockNumber; }
            set 
            { 
                _blockNumber = value;
                this.IsModified = true;
                OnPropertyChanged("BlockNumber");
            }
        }

        [mp.Column(Name = "ItemType")]
        public string ItemType
        {
            get { return _itemType; }
            set 
            { 
                _itemType = value;
                this.IsModified = true;
                OnPropertyChanged("ItemType");
            }
        }

        [mp.Column(Name = "Reference")]
        public string Reference
        {
            get { return _reference; }
            set 
            { 
                _reference = value;
                this.IsModified = true;
                OnPropertyChanged("Reference");
            }
        }

        [mp.Column(Name = "DateReturnedFromContractor")]
        public DateTime? DateReturnedFromContractor
        {
            get { return _dateReturnedFromContractor; }
            set 
            { 
                _dateReturnedFromContractor = value;
                this.IsModified = true;
                OnPropertyChanged("DateReturnedFromContractor");
            }
        }

        [mp.Column(Name = "QuantityPerPage")]
        public int QuantityPerPage
        {
            get { return _quantityPerPage; }
            set 
            {
                _quantityPerPage = value;
                this.IsModified = true;
                OnPropertyChanged("QuantityPerPage");
            }
        }

        [mp.Column(Name = "SpecSection")]
        public string SpecSection
        {
            get { return _specSection; }
            set 
            { 
                _specSection = value;
                this.IsModified = true;
                OnPropertyChanged("SpecSection");
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

        [mp.Column(Name = "Status")]
        public string Status
        {
            get { return _status; }
            set 
            { 
                _status = value;
                this.IsModified = true;
                OnPropertyChanged("Status");
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
                this.IsModified = true;
                OnPropertyChanged("DateSubmitted");
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


        public SubmittalLine()
        {
            this._isModified = false;
        }

        public SubmittalLine(int id, string jobNumber, string blockNumber, string itemType, string reference
                         , DateTime? dateReturnedFromContractor, int quantityPerPage, string specSection, int copies, string status
                         , string remarks
                         , DateTime? dateSubmitted
                         , DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine)
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._blockNumber = blockNumber;
            this._itemType = itemType;
            this._reference = reference;
            this._dateReturnedFromContractor = dateReturnedFromContractor;
            this._quantityPerPage = quantityPerPage;
            this._specSection = specSection;
            this._copies = copies;
            this._status = status;
            this._remarks = remarks;
            this._dateSubmitted = dateSubmitted;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;
            this._isModified = false;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class SubmittalDataContext : lq.DataContext
    {
        public SubmittalDataContext(string cs)
            : base(cs)
        {
        }

        public SubmittalDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<SubmittalLine> Submittal;
    }
}
