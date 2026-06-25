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
    public static class RequestForInfos
    {
        internal static ObservableCollection<RequestForInfo> GetRfisByJobNumber(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<RequestForInfo> rfiList = null;

            try
            {
                var rfiQuery = from rfiLine in dtCtx.GetTable<RequestForInfo>()
                               where rfiLine.JobNumber == jobNumber
                               select new
                               {
                                   Id = rfiLine.Id,
                                   JobNumber = rfiLine.JobNumber,
                                   RfiDriNumber = rfiLine.RfiDriNumber,
                                   ContractorNumber = rfiLine.ContractorNumber,
                                   Zone = rfiLine.Zone,
                                   Reference = rfiLine.Reference,
                                   Status = rfiLine.Reference,
                                   Remarks = rfiLine.Remarks,
                                   DateCreated = rfiLine.DateCreated,
                                   TimeCreated = rfiLine.TimeCreated,
                                   UpdatingUser = rfiLine.UpdatingUser,
                                   UpdatingMachine = rfiLine.UpdatingMachine
                               };

                rfiList = rfiQuery.AsEnumerable().Select(x => new RequestForInfo(x.Id, x.JobNumber, x.RfiDriNumber, x.ContractorNumber, x.Zone
                                                                                ,x.Reference, x.Status, x.Remarks, x.DateCreated, x.TimeCreated
                                                                                ,x.UpdatingUser, x.UpdatingMachine)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<RequestForInfo>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<RequestForInfo>(rfiList);
        }

        public static void UpdateRfis(ObservableCollection<RequestForInfo> _submittalCol)
        {
            using (RequestForInfoDataContext dtCtx = new RequestForInfoDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime? _dateCreated = DateTime.Today;
                DateTime? _timeCreated = DateTime.Now;
                string _creatingUser = Environment.UserName;
                string _creatingMachine = Environment.MachineName;
                int _id = GetNextRfiId(_submittalCol[0].JobNumber);
                //_id = _id == 0 ? _id = 0 : _id--;
                foreach (RequestForInfo rfi in _submittalCol)
                {
                    try
                    {
                        if (rfi.Id == 0 && rfi.IsDeleted != true)
                        {
                            rfi.DateCreated = _dateCreated;
                            rfi.TimeCreated = _timeCreated;
                            rfi.UpdatingUser = _creatingUser;
                            rfi.UpdatingMachine = _creatingMachine;
                            rfi.Id = _id++;
                            dtCtx.RequestForInfo.InsertOnSubmit(rfi);
                        }
                        else if (rfi.Id != 0 && rfi.IsModified == true)
                        {
                            dtCtx.RequestForInfo.Attach(rfi, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, rfi);
                        }
                        else if (rfi.Id != 0 && rfi.IsDeleted == true)
                        {
                            dtCtx.RequestForInfo.Attach(rfi, rfi);
                            dtCtx.RequestForInfo.DeleteOnSubmit(rfi);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static int GetNextRfiId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMREQUESTFORINFOS] where JobNumber='" + jobNumber + "'";
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

    [mp.Table(Name = "[PMREQUESTFORINFOS]")]
    public class RequestForInfo : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _rfiDriNumber;
        private string _contractorNumber;
        private string _zone;
        private string _reference;
        private string _status;
        private string _remarks;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;

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

        [mp.Column(Name = "RfiDriNumber")]
        public string RfiDriNumber
        {
            get { return _rfiDriNumber; }
            set 
            { 
                _rfiDriNumber = value;
                this.IsModified = true;
                OnPropertyChanged("RfiDriNumber");               
            }
        }

        [mp.Column(Name = "ContractorNumber")]
        public string ContractorNumber
        {
            get { return _contractorNumber; }
            set 
            { 
                _contractorNumber = value;
                this.IsModified = true;
                OnPropertyChanged("ContractorNumber");    
            }
        }

        [mp.Column(Name = "Zone")]
        public string Zone
        {
            get { return _zone; }
            set 
            { 
                _zone = value;
                this.IsModified = true;
                OnPropertyChanged("Zone");
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

        public RequestForInfo()
        {
            this._isModified = false;
        }

        public RequestForInfo(int id, string jobNumber, string rfiDriNumber, string contractorNumber, string zone
                              ,string reference, string status, string remarks, DateTime? dateCreated, DateTime? timeCreated
                              ,string updatingUser, string updatingMachine)
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._rfiDriNumber = rfiDriNumber;
            this._contractorNumber = contractorNumber;
            this._zone = zone;
            this._reference = reference;
            this._status = status;
            this._remarks = remarks;
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

    public class RequestForInfoDataContext : lq.DataContext
    {
        public RequestForInfoDataContext(string cs)
            : base(cs)
        {
        }

        public RequestForInfoDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<RequestForInfo> RequestForInfo;
    }
}
