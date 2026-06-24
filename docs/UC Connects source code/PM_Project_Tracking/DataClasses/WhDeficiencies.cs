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
using PM_Project_Tracking.DataClasses.Interfaces;

namespace PM_Project_Tracking.DataClasses
{
    class WhDeficiencies
    {
        internal static ObservableCollection<WhDeficiency> GetDeficienciesByPo(string poNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<WhDeficiency> purchOrderList = null;


            try
            {
                var deflist = from dl in dtCtx.GetTable<WhDeficiency>()
                              where dl.PoNumber == poNumber
                              select new
                              {
                                  Id = dl.Id,
                                  PoNumber = dl.PoNumber,
                                  JobNumber = dl.JobNumber,
                                  Completed = dl.Completed,
                                  CompletingUser = dl.CompletingUser,
                                  DateCompleted = dl.DateCompleted,
                                  TimeCompleted = dl.TimeCompleted,
                                  Remarks = dl.Remarks,
                                  UpdatingUser = dl.UpdatingUser,
                                  UpdatingMachine = dl.UpdatingMachine,
                                  DateCreated = dl.DateCreated,
                                  TimeCreated = dl.TimeCreated,
                              };

                purchOrderList = deflist.AsEnumerable().Select(x => new WhDeficiency(x.Id
                                                                                    ,x.PoNumber
                                                                                    ,x.JobNumber
                                                                                    ,x.Completed
                                                                                    ,x.CompletingUser
                                                                                    ,x.DateCompleted
                                                                                    ,x.TimeCompleted
                                                                                    ,x.Remarks
                                                                                    ,x.UpdatingUser
                                                                                    ,x.UpdatingMachine
                                                                                    ,x.DateCreated
                                                                                    ,x.TimeCreated
                                                                                    )).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<WhDeficiency>(purchOrderList);
        }

        public static void AddWhDeficiency(WhDeficiency whDef)
        {
            using (WhDeficiencyDataContext dtCtx = new WhDeficiencyDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    whDef.Id = GetNextWhDeficiencyItemId();
                    dtCtx.WhDeficiency.InsertOnSubmit(whDef);
                    dtCtx.SubmitChanges();
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void UpdateWhDeficiency(WhDeficiency whDef)
        {
            using (WhDeficiencyDataContext dtCtx = new WhDeficiencyDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.WhDeficiency.Attach(whDef, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, whDef);
                    dtCtx.SubmitChanges();
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        private static int GetNextWhDeficiencyItemId()
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[WHRECEIPTDEFICIENCY101]";
                comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var _maxVal = comm.ExecuteScalar();
                if (_maxVal.GetType() == typeof(System.DBNull))
                    _idVal = 1;
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

    [mp.Table(Name = "[WHRECEIPTDEFICIENCY101]")]
    public class WhDeficiency : IJobNumberHaver, INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _poNumber;
        private string _jobNumber;
        bool _completed;
        private string _completingUser;
        private DateTime? _dateCompleted;
        private DateTime? _timeCompleted;
        private string _remarks;

        private string _updatingUser;
        private string _updatingMachine;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;

        private bool _isModified;
        private bool _isDeleted;
        private bool _isNew;


        [mp.Column(Name = "ID", IsPrimaryKey = true)]
        public int Id
        {
            get
            {
                return _id;
            }

            set
            {
                _id = value;
            }
        }

        [mp.Column(Name = "PONUMBER")]
        public string PoNumber
        {
            get
            {
                return _poNumber;
            }

            set
            {
                _poNumber = value;
            }
        }

        [mp.Column(Name = "JobNumber")]
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

        [mp.Column(Name = "Completed")]
        public bool Completed
        {
            get
            {
                return _completed;
            }

            set
            {
                _completed = value;
                OnPropertyChanged("Completed");
                this._isModified = true;
                OnPropertyChanged("IsModified");
                if (value)
                {
                    this._completingUser = Environment.UserName == null ? "NULL USER" : Environment.UserName;
                    this._dateCompleted = DateTime.Today;
                    this._timeCompleted = DateTime.Now;
                }
                else
                {
                    this._completingUser = null;
                    this._dateCompleted = null;
                    this._timeCompleted = null;
                }
            }
        }

        [mp.Column(Name = "CompletingUser")]
        public string CompletingUser
        {
            get
            {
                return _completingUser;
            }

            set
            {
                _completingUser = value;
            }
        }

        [mp.Column(Name = "DateCompleted")]
        public DateTime? DateCompleted
        {
            get
            {
                return _dateCompleted;
            }

            set
            {
                _dateCompleted = value;
            }
        }

        [mp.Column(Name = "TimeCompleted", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCompleted
        {
            get
            {
                return _timeCompleted;
            }

            set
            {
                _timeCompleted = value;
            }
        }

        [mp.Column(Name = "Remarks")]
        public string Remarks
        {
            get
            {
                return _remarks;
            }

            set
            {
                _remarks = value;
                OnPropertyChanged("Remarks");
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get
            {
                return _updatingUser;
            }

            set
            {
                _updatingUser = value;
            }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get
            {
                return _updatingMachine;
            }

            set
            {
                _updatingMachine = value;
            }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get
            {
                return _dateCreated;
            }

            set
            {
                _dateCreated = value;
            }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get
            {
                return _timeCreated;
            }

            set
            {
                _timeCreated = value;
            }
        }


        public bool IsModified
        {
            get
            {
                return _isModified;
            }

            set
            {
                _isModified = value;
            }
        }

        public bool IsDeleted
        {
            get
            {
                return _isDeleted;
            }

            set
            {
                _isDeleted = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        public bool IsNew
        {
            get
            {
                return _isNew;
            }

            set
            {
                _isNew = value;
            }
        }

        public WhDeficiency()
        {

        }

        public WhDeficiency(int id, string poNumber, string jobNumber, bool outstanding, string completingUser,
                            DateTime? dateCompleted, DateTime? timeCompleted, string remarks, string updatingUser, string updatingMachine,
                            DateTime? dateCreated, DateTime? timeCreated)
        {
            this._id = id;
            this._poNumber = poNumber;
            this._jobNumber = jobNumber;
            this._completed = outstanding;
            this._completingUser = completingUser;
            this._dateCompleted = dateCompleted;
            this._timeCompleted = timeCompleted;
            this._remarks = remarks;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
        }

        public WhDeficiency(PurchaseOrderHeader poHeader)
        {
            this.Id = 0;
            this.IsNew = true;
            this.PoNumber = poHeader.PoNumber;
            this.JobNumber = poHeader.JobNumber;

            this._updatingUser = Environment.UserName == null ? "NULL USER" : Environment.UserName;
            this._updatingMachine = Environment.MachineName;
            this._dateCreated = DateTime.Today;
            this._timeCreated = DateTime.Now;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class WhDeficiencyDataContext : lq.DataContext
    {
        public WhDeficiencyDataContext(string cs)
            : base(cs)
        {

        }

        public WhDeficiencyDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public WhDeficiencyDataContext(string cs, lq.Mapping.MappingSource ms)
            : base(cs, ms)
        {
        }

        public lq.Table<WhDeficiency> WhDeficiency;
    }
}
