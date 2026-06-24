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
using pm = PM_Project_Tracking.ProjectManagementClasses;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;


namespace PM_Project_Tracking.ProjectManagementClasses
{
    class SubmittalHeaders
    {
        internal static SubmittalHeader GetSingleSubmittalHeaderByJob(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            SubmittalHeader _subHeader = null;

            try
            {
            var headerQuery = from sh in dtCtx.GetTable<SubmittalHeader>()
                              where sh.JobNumber == jobNumber
                              select new
                              {
                                  Id = sh.Id,
                                  JobNumber = sh.JobNumber,
                                  JobName = sh.JobName,
                                  JobAddress = sh.JobAddress,
                                  ContractorName = sh.ContractorName,
                                  ContractorAddress = sh.ContractorAddress,
                                  ContactName = sh.ContactName,
                                  ContactTitle = sh.ContactTitle,
                                  ContactPhoneNumber = sh.ContactPhoneNumber,
                                  UcshContactName = sh.UcshContactName,
                                  UcshContactTitle = sh.UcshContactTitle,
                                  DateCreated = sh.DateCreated,
                                  TimeCreated = sh.TimeCreated,
                                  UpdatingUser = sh.UpdatingUser,
                                  UpdatingMachine = sh.UpdatingMachine
                              };

            _subHeader = headerQuery.AsEnumerable().Select(x => new SubmittalHeader(x.Id, x.JobNumber, x.JobName, x.JobAddress, x.ContractorName
                                                                                   , x.ContractorAddress, x.ContactName, x.ContactTitle, x.ContactPhoneNumber, x.UcshContactName
                                                                                   , x.UcshContactTitle, x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine)).FirstOrDefault();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new SubmittalHeader();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return _subHeader;
        }

        internal static SubmittalHeader GetNewSingleSubmittalHeaderByJob(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            SubmittalHeader _subHeader = null;

            try
            {

                var headerQuery = from jc in dtCtx.GetTable<gp.Jc00102>()
                                  join rm1 in dtCtx.GetTable<gp.Rm00101>() on jc.CustomerNumber equals rm1.CustomerNumber into fullA
                                  from rm1 in fullA.DefaultIfEmpty()
                                  join rm2 in dtCtx.GetTable<gp.Rm00102>() on new { jc.AddressCode, jc.CustomerNumber } equals new { rm2.AddressCode, rm2.CustomerNumber } into fullB
                                  from rm2 in fullB.DefaultIfEmpty()
                                  where jc.JobNumber == jobNumber
                                  select new
                                  {
                                      Id = 0,
                                      JobNumber = jc.JobNumber,
                                      JobName = jc.JobName, //JC00102
                                      JobAddress = rm2.Address, //RM00102 on custnmbr and adrscode
                                      ContractorName = rm1.CustomerName, //JC00102
                                      ContractorAddress = rm1.Address, //RM00101
                                  };

                _subHeader = headerQuery.AsEnumerable().Select(x => new SubmittalHeader(x.Id, x.JobNumber, x.JobName, x.JobAddress, x.ContractorName
                                                                                       , x.ContractorAddress)).FirstOrDefault();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new SubmittalHeader();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return _subHeader;
        }


        public static void InsertUpdateSubmittalHeader(SubmittalHeader sm)
        {
            using (SubmittalHeaderDataContext dtCtx = new SubmittalHeaderDataContext(GlobalVars.UcshConnectionString))
            {

                    try
                    {
                        if (sm.Id == 0)
                        {
                            sm.DateCreated = DateTime.Today;
                            sm.TimeCreated = DateTime.Now;
                            sm.UpdatingUser = Environment.UserName;
                            sm.UpdatingMachine = Environment.MachineName;
                            sm.Id = GetNextSubmittalHeaderId(sm.JobNumber);
                            dtCtx.SubmittalHeader.InsertOnSubmit(sm);
                        }
                        else if (sm.Id != 0 && sm.IsModified == true)
                        {
                            sm.LastUpdateDate = DateTime.Today;
                            sm.LastUpdateTime = DateTime.Now;
                            dtCtx.SubmittalHeader.Attach(sm, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, sm);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                
                dtCtx.SubmitChanges();
            }
        }

        public static int GetNextSubmittalHeaderId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMSUBMITTALSHEADERS101]";
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

    [mp.Table(Name = "[PMSUBMITTALSHEADERS101]")]
    public class SubmittalHeader : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _jobName;
        private string _jobAddress;
        private string _contractorName;
        private string _contractorAddress;
        private string _contactName;
        private string _contactTitle;
        private string _contactPhoneNumber;
        private string _ucshContactName;
        private string _ucshContactTitle;
        private DateTime? _lastUpdateDate;
        private DateTime? _lastUpdateTime;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;

        [mp.Column(Name = "ID", IsPrimaryKey=true)]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set 
            { 
                _jobNumber = value;
                this._isModified = true;
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
            }
        }

        [mp.Column(Name = "JobAddress")]
        public string JobAddress
        {
            get { return _jobAddress; }
            set 
            { 
                _jobAddress = value; 
                this._isModified = true; 
            }
        }

        [mp.Column(Name = "ContractorName")]
        public string ContractorName
        {
            get { return _contractorName; }
            set 
            { 
                _contractorName = value;
                this._isModified = true;
            }
        }

        [mp.Column(Name = "ContractorAddress")]
        public string ContractorAddress
        {
            get { return _contractorAddress; }
            set 
            { 
                _contractorAddress = value;
                this._isModified = true;
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
            }
        }

        [mp.Column(Name = "ContactTitle")]
        public string ContactTitle
        {
            get { return _contactTitle; }
            set 
            { 
                _contactTitle = value;
                this._isModified = true;
            }
        }

        [mp.Column(Name = "ContactPhoneNumber")]
        public string ContactPhoneNumber
        {
            get { return _contactPhoneNumber; }
            set 
            { 
                _contactPhoneNumber = value;
                this._isModified = true;
            }
        }

        [mp.Column(Name = "UcshContactName")]
        public string UcshContactName
        {
            get { return _ucshContactName; }
            set 
            { 
                _ucshContactName = value;
                this._isModified = true;
            }
        }

        [mp.Column(Name = "UcshContactTitle")]
        public string UcshContactTitle
        {
            get { return _ucshContactTitle; }
            set 
            { 
                _ucshContactTitle = value;
                this._isModified = true;
            }
        }

        [mp.Column(Name = "LastUpdateDate")]
        public DateTime? LastUpdateDate
        {
            get { return _lastUpdateDate; }
            set { _lastUpdateDate = value; }
        }

        [mp.Column(Name = "LastUpdateTime", DbType = "Time", CanBeNull = true)]
        public DateTime? LastUpdateTime
        {
            get { return _lastUpdateTime; }
            set { _lastUpdateTime = value; }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set { _dateCreated = value;}
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
            set { _isModified = value; }
        }


        public SubmittalHeader()
        {

        }

        //Constructor when no headers exist
        public SubmittalHeader(int id, string jobNumber, string jobName, string jobAddress, string contractorName
                       , string contractorAddress)
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._jobAddress = jobAddress;
            this._contractorName = contractorName;
            this._contractorAddress = contractorAddress;
        }

        public SubmittalHeader(int id, string jobNumber, string jobName, string jobAddress, string contractorName
                               , string contractorAddress, string contactName, string contactTitle, string contactPhoneNumber, string ucshContactName
                               , string ucshContactTitle, DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine)
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._jobAddress = jobAddress;
            this._contractorName = contractorName;
            this._contractorAddress = contractorAddress;
            this._contactName = contactName;
            this._contactTitle = contactTitle;
            this._contactPhoneNumber = contactPhoneNumber;
            this._ucshContactName = ucshContactName;
            this._ucshContactTitle = ucshContactTitle;
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

    public class SubmittalHeaderDataContext : lq.DataContext
    {
        public SubmittalHeaderDataContext(string cs)
            : base(cs)
        {
        }

        public SubmittalHeaderDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<SubmittalHeader> SubmittalHeader;
    }
}
