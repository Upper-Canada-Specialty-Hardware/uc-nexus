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
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using PM_Project_Tracking.DataClasses.Interfaces;
using dc = PM_Project_Tracking.DataClasses;

namespace PM_Project_Tracking.ProjectManagementClasses
{
    class TaskSchedulers
    {
        internal static ObservableCollection<TaskSchedulerItem> GetTaskScheduleItemsByJobNum(string jobNum)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<TaskSchedulerItem> taskSchedulerList = null;
            Dictionary<string, int> userIdPairs = null;

            try
            {
                var taskSchedulerQuery = from taskLine in dtCtx.GetTable<TaskSchedulerItem>()
                                      where taskLine.JobNumber == jobNum
                                      select new
                                      {
                                          Id = taskLine.Id,
                                          Completed = taskLine.Completed,
                                          JobNumber = taskLine.JobNumber,
                                          JobName = taskLine.JobName,
                                          AssignedById = taskLine.AssignedById,
                                          AssignedBy = taskLine.AssignedByName,
                                          AssignedToId = taskLine.AssignedToId,
                                          AssignedTo = taskLine.AssignedToName,
                                          TaskTypeInt = taskLine.TaskTypeInt,
                                          TaskTypeName = taskLine.TaskTypeName, 
                                          Area = taskLine.Area,
                                          Duration = taskLine.Duration,
                                          Division = taskLine.Division == null ? "" : taskLine.Division,
                                          StartDate = taskLine.StartDate,
                                          EndDate = taskLine.EndDate,
                                          TimeRemaining = taskLine.TimeRemaining,
                                          BaselineStartDate = taskLine.BaselineStartDate,
                                          BaselineEndDate = taskLine.BaselineEndDate,
                                          VarianceDuration = taskLine.VarianceDuration,
                                          TotalQuantity = taskLine.TotalQuantity,
                                          CompletedQuantity = taskLine.CompletedQuantity,
                                          Comment = taskLine.Comment,
                                          DateCreated = taskLine.DateCreated,
                                          TimeCreated = taskLine.TimeCreated,
                                          UpdatingUser = taskLine.UpdatingUser,
                                          UpdatingMachine = taskLine.UpdatingMachine,
                                          EditingUser = taskLine.EditingUser,
                                          EditedDate = taskLine.DateEdited,
                                          EditedTime = taskLine.TimeEdited

                                      };

                var userIdPairQuery = from userPair in dtCtx.GetTable<dc.User>()
                                      select new
                                      {
                                          Id = userPair.Id,
                                          DomainUserName = userPair.DomainUserName
                                      };

                userIdPairQuery = userIdPairQuery.Take(153);

                userIdPairs = userIdPairQuery.AsEnumerable().Select(x => new { x.DomainUserName, x.Id }).ToDictionary(x => x.DomainUserName, x => x.Id);

                taskSchedulerList = taskSchedulerQuery.AsEnumerable().Select(x => new TaskSchedulerItem(userIdPairs, 
                                                                                x.Id,
                                                                                x.Completed,
                                                                                x.JobNumber,
                                                                                x.JobName,
                                                                                x.AssignedById,
                                                                                x.AssignedBy,
                                                                                x.AssignedToId,
                                                                                x.AssignedTo,
                                                                                x.TaskTypeInt,
                                                                                x.TaskTypeName,
                                                                                x.Area,
                                                                                x.Duration,
                                                                                x.Division,
                                                                                x.StartDate,
                                                                                x.EndDate,
                                                                                x.TimeRemaining,
                                                                                x.BaselineStartDate,
                                                                                x.BaselineEndDate,
                                                                                x.VarianceDuration,
                                                                                x.TotalQuantity,
                                                                                x.CompletedQuantity,
                                                                                x.Comment,
                                                                                x.DateCreated,
                                                                                x.TimeCreated,
                                                                                x.UpdatingUser,
                                                                                x.UpdatingMachine,
                                                                                x.EditingUser,
                                                                                x.EditedDate,
                                                                                x.EditedTime
                                                                                )).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                    return new ObservableCollection<TaskSchedulerItem>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<TaskSchedulerItem>(taskSchedulerList);
        }



        internal static ObservableCollection<TaskSchedulerItem> GetTaskScheduleItemsAll(bool ignoreComp)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<TaskSchedulerItem> taskSchedulerList = null;

            try
            {
                var taskSchedulerQuery = from taskLine in dtCtx.GetTable<TaskSchedulerItem>()
                                         select new
                                         {
                                             Id = taskLine.Id,
                                             Completed = taskLine.Completed,
                                             JobNumber = taskLine.JobNumber,
                                             JobName = taskLine.JobName,
                                             AssignedById = taskLine.AssignedById,
                                             AssignedBy = taskLine.AssignedByName,
                                             AssignedToId = taskLine.AssignedToId,
                                             AssignedTo = taskLine.AssignedToName,
                                             TaskTypeInt = taskLine.TaskTypeInt,
                                             TaskTypeName = taskLine.TaskTypeName,
                                             Area = taskLine.Area,
                                             Duration = taskLine.Duration,
                                             Division = taskLine.Division == null ? "" : taskLine.Division,
                                             StartDate = taskLine.StartDate,
                                             EndDate = taskLine.EndDate,
                                             TimeRemaining = taskLine.TimeRemaining,
                                             BaselineStartDate = taskLine.BaselineStartDate,
                                             BaselineEndDate = taskLine.BaselineEndDate,
                                             VarianeDuration = taskLine.VarianceDuration,
                                             TotalQuantity = taskLine.TotalQuantity,
                                             CompletedQuantity = taskLine.CompletedQuantity,
                                             Comment = taskLine.Comment,
                                             DateCreated = taskLine.DateCreated,
                                             TimeCreated = taskLine.TimeCreated,
                                             UpdatingUser = taskLine.UpdatingUser,
                                             UpdatingMachine = taskLine.UpdatingMachine,
                                             EditingUser = taskLine.EditingUser,
                                             EditedDate = taskLine.DateEdited,
                                             EditedTime = taskLine.TimeEdited
                                         };

                if (ignoreComp)
                    taskSchedulerQuery = taskSchedulerQuery.Where(x => x.Completed == false);

                taskSchedulerList = taskSchedulerQuery.AsEnumerable().Select(x => new TaskSchedulerItem(new Dictionary<string, int>(), 
                                                                                x.Id,
                                                                                x.Completed,
                                                                                x.JobNumber,
                                                                                x.JobName,
                                                                                x.AssignedById,
                                                                                x.AssignedBy,
                                                                                x.AssignedToId,
                                                                                x.AssignedTo,
                                                                                x.TaskTypeInt,
                                                                                x.TaskTypeName,
                                                                                x.Area,
                                                                                x.Duration,
                                                                                x.Division,
                                                                                x.StartDate,
                                                                                x.EndDate,
                                                                                x.TimeRemaining,
                                                                                x.BaselineStartDate,
                                                                                x.BaselineEndDate,
                                                                                x.VarianeDuration,
                                                                                x.TotalQuantity,
                                                                                x.CompletedQuantity,
                                                                                x.Comment,
                                                                                x.DateCreated,
                                                                                x.TimeCreated,
                                                                                x.UpdatingUser,
                                                                                x.UpdatingMachine,
                                                                                x.EditingUser,
                                                                                x.EditedDate,
                                                                                x.EditedTime
                                                                                )).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<TaskSchedulerItem>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<TaskSchedulerItem>(taskSchedulerList);
        }

        internal static ObservableCollection<TaskEnum> GetTaskEnums()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<TaskEnum> taskEnumList = null;


            try
            {
                var taskSchedulerQuery = from taskLine in dtCtx.GetTable<TaskEnum>()
                                         select new
                                         {
                                             Id = taskLine.Id,
                                             TaskName = taskLine.TaskName,
                                             DerivativeOperation = taskLine.DerivateOperation,
                                             CreatingUser = taskLine.CreatingUser,
                                             DateCreated = taskLine.DateCreated,
                                             TimeCreated = taskLine.TimeCreated
                                         };

                taskEnumList = taskSchedulerQuery.AsEnumerable().Select(x => new TaskEnum(x.Id
                                                                                ,x.TaskName
                                                                                ,x.DerivativeOperation
                                                                                ,x.CreatingUser
                                                                                ,x.DateCreated
                                                                                ,x.TimeCreated
                                                                                )).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<TaskEnum>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<TaskEnum>(taskEnumList);
        }

        internal static bool UpdateAddTaskSchedulerItems(ref ObservableCollection<TaskSchedulerItem> tsiCol)
        {
            using (TaskSchedulerItemDataContext dtCtx = new TaskSchedulerItemDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime? _dateCreated = DateTime.Today;
                DateTime? _timeCreated = DateTime.Now;
                string _creatingUser = Environment.UserName;
                string _creatingMachine = Environment.MachineName;
                int _id = GetNextChangeTaskItemId();

                foreach (TaskSchedulerItem tsi in tsiCol)
                {
                    try
                    {
                        if (tsi.IsNew || tsi.IsModified)             //&& (tsi.StartDate != null && tsi.EndDate != null)
                        {
                            if (tsi.Id == 0 && tsi.IsDeleted != true)
                            {
                                tsi.DateCreated = _dateCreated;
                                tsi.TimeCreated = _timeCreated;
                                tsi.UpdatingUser = _creatingUser;
                                tsi.UpdatingMachine = _creatingMachine;
                                tsi.Id = _id++;
                                dtCtx.TaskSchedulerItem.InsertOnSubmit(tsi);
                                tsi.IsNew = false;
                                tsi.IsModified = false;
                            }
                            else if (tsi.Id != 0 && tsi.IsModified == true)
                            {
                                tsi.DateEdited = _dateCreated;
                                tsi.TimeEdited = _timeCreated;
                                tsi.EditingUser = _creatingUser;
                                dtCtx.TaskSchedulerItem.Attach(tsi, false);
                                dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, tsi);
                                tsi.IsModified = false;
                            }
                            //else if (tsi.Id != 0 && tsi.IsDeleted == true)    //Not supposed to be used in this method
                            //{
                            //    dtCtx.TaskSchedulerItem.Attach(tsi, tsi);
                            //    dtCtx.TaskSchedulerItem.DeleteOnSubmit(tsi);
                            //}
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
                return true;
            }
        }

        public static bool UpdateTaskSchedulerItem(TaskSchedulerItem tsi, ObservableCollection<dc.User> users)
        {
            bool _cont = true;
            Dictionary<string, int> _userDic = users.AsEnumerable().Select(x => new { x.DomainUserName, x.Id }).ToDictionary(x => x.DomainUserName, x => x.Id);
            using (TaskSchedulerItemDataContext dtCtx = new TaskSchedulerItemDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    tsi.DateEdited = DateTime.Today;
                    tsi.TimeEdited = DateTime.Now;
                    tsi.EditingUser = Environment.UserName;
                    dtCtx.TaskSchedulerItem.Attach(tsi, false);
                    //tsi.UserIdPairs = _userDic;
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, tsi);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex)
                { 
                    MessageBox.Show(ex.ToString()); 
                    _cont = false; 
                }
                finally
                {
                    //if (_cont)
                    //    dtCtx.SubmitChanges();
                }
            }
            return _cont;
        }

        public static bool AddTaskSchedulerItem(TaskSchedulerItem tsi)
        {
            bool _cont = true;
            using (TaskSchedulerItemDataContext dtCtx = new TaskSchedulerItemDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    int _taskId = GetNextChangeTaskItemId();
                    tsi.Id = _taskId;
                    tsi.DateCreated = DateTime.Today;
                    tsi.TimeCreated = DateTime.Now;
                    tsi.UpdatingUser = Environment.UserName;
                    tsi.UpdatingMachine = Environment.MachineName;
                    dtCtx.TaskSchedulerItem.InsertOnSubmit(tsi);
                    dtCtx.SubmitChanges();
                    tsi.InsertedToDb = true;
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                    _cont = false;
                }
            }
            return _cont;
        }

        public static bool DeleteTaskSchedulerItem(TaskSchedulerItem tsi)
        {
            bool _cont = false;
            using (TaskSchedulerItemDataContext dtCtx = new TaskSchedulerItemDataContext(GlobalVars.UcshConnectionString))
            {
                //if (!_cont) return _cont;
                try
                {
                    dtCtx.TaskSchedulerItem.Attach(tsi, tsi);
                    dtCtx.TaskSchedulerItem.DeleteOnSubmit(tsi);
                    dtCtx.SubmitChanges();
                    _cont = true;
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }

                return _cont;
            }
        }

        private static int GetNextChangeTaskItemId()
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMTASKSCHEDULER101]";
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

        internal static double GetBusinessDays(DateTime startD, DateTime endD)
        {
            double calcBusinessDays =
                1 + ((endD - startD).TotalDays * 5 -
                (startD.DayOfWeek - endD.DayOfWeek) * 2) / 7;

            if (endD.DayOfWeek == DayOfWeek.Saturday) calcBusinessDays--;
            if (startD.DayOfWeek == DayOfWeek.Sunday) calcBusinessDays--;

            return calcBusinessDays;
        }

    }


    [mp.Table(Name = "PMTASKSCHEDULER101")]
    public class TaskSchedulerItem : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;
        const double _OPACITYFULL = 1;
        const double _OPACITYPARTIAL = 0.4;
        const string _COLORSELECTABLE = "Orange";
        const string _COLORPARTIAL = "#FF8DB258";

        private int _id;
        private bool _completed;
        private string _jobNumber;
        private string _jobName;
        private int _assignedById;
        private string _assignedByName;
        private int _assignedToId;
        private string _assignedToName;

        private dc.User _assignedToUser;
        private Dictionary<string, int> _userIdPairs;

        private int _taskTypeInt;
        private string _taskTypeName;
        private string _area;
        private double _duration;
        private string _division;
        private DateTime? _startDate;
        private DateTime? _endDate;
        private double _timeRemaining;
        private DateTime? _baselineStartDate;
        private DateTime? _baselineEndDate;
        private double _varianceDuration;
        private int _totalQuantity;
        private int _completedQuantity;
        private string _comment;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;
        private DateTime? _dateEdited;
        private DateTime? _timeEdited;
        private string _editingUser;

        private bool _isNew;
        private bool _isModified;
        private bool _isDeleted;
        private double _uiOpacity;
        private string _uiBorderColor;
        private bool _insertedToDb;

        private int _etsin;

        [mp.Column(Name = "ID", IsPrimaryKey=true)]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
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
                this.IsModified = true;
                OnPropertyChanged("Completed");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "JobName")]
        public string JobName
        {
            get { return _jobName; }
            set { _jobName = value; }
        }

        [mp.Column(Name = "AssignedById")]
        public int AssignedById
        {
            get { return _assignedById; }
            set { _assignedById = value; }
        }

        [mp.Column(Name = "AssignedByName")]
        public string AssignedByName
        {
            get { return _assignedByName; }
            set { _assignedByName = value; }
        }

        [mp.Column(Name = "AssignedToId")]
        public int AssignedToId
        {
            get { return _assignedToId; }
            set { _assignedToId = value; }
        }

        [mp.Column(Name = "AssignedToName")]
        public string AssignedToName
        {
            get { return _assignedToName; }
            set
            {
                //For LINQ constructor when updating database since it doesn't seem to pass the dictionary collection object
                if (value != null && UserIdPairs == null)
                {
                    _assignedToName = value;
                    //this.IsModified = true;
                }
                else if (UserIdPairs != null)
                {
                    _assignedToName = value;
                    _assignedToId = UserIdPairs[value];
                    this.IsModified = true;
                    OnPropertyChanged("AssignedToName");
                    OnPropertyChanged("AssignedToId");
                    OnPropertyChanged("IsModified");
                }
            }
        }

        public dc.User AssignedToUser
        {
            get 
            {
                return _assignedToUser;
            }

            set
            {
                _assignedToUser = value;
                this.IsModified = true;
                OnPropertyChanged("AssignedToUser");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "TaskTypeInt")]
        public int TaskTypeInt
        {
            get { return _taskTypeInt; }
            set 
            { 
                _taskTypeInt = value;
                this.IsModified = true;
                OnPropertyChanged("TaskTypeInt");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "TaskTypeName")]
        public string TaskTypeName
        {
            get { return _taskTypeName; }
            set 
            { 
                _taskTypeName = value;
                OnPropertyChanged("TaskTypeName");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Area")]
        public string Area
        {
            get { return _area; }
            set 
            { 
                _area = value;
                this.IsModified = true;
                OnPropertyChanged("Area");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Duration", UpdateCheck = mp.UpdateCheck.Never)]
        public double Duration
        {
            get { return _duration; }
            set 
            { 
                _duration = value;
                OnPropertyChanged("Duration");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Division")]
        public string Division
        {
            get { return _division; }
            set { _division = value; }
        }


        [mp.Column(Name = "StartDate", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? StartDate
        {
            get { return _startDate; }
            set 
            {
                //DateTime _asdf = DateTime.Parse("2018-05-31");
                _startDate = value;
                if (_isNew)
                    _baselineStartDate = value;
                else if (_isNew == false && _baselineStartDate == null)
                    _baselineStartDate = value;

                _duration = (DateTime.Today < _endDate) ? TaskSchedulers.GetBusinessDays(value.Value, _endDate.Value) : 0;

                if (_endDate.HasValue)
                {
                    if (DateTime.Today > _endDate)
                        _timeRemaining = 0;
                    else if (DateTime.Today < _startDate)
                        _timeRemaining = TaskSchedulers.GetBusinessDays(_startDate.Value, _endDate.Value);
                    else
                        _timeRemaining = TaskSchedulers.GetBusinessDays(DateTime.Today, _endDate.Value);
                }
                else
                    _timeRemaining = 0;

                if (_endDate.HasValue)
                    _varianceDuration = ((TimeSpan)(_endDate.Value - value.Value)).TotalDays - ((TimeSpan)(_baselineEndDate.Value - _baselineStartDate.Value)).TotalDays;

                this.IsModified = true;
                OnPropertyChanged("StartDate");
                OnPropertyChanged("BaselineStartDate");
                OnPropertyChanged("Duration");
                OnPropertyChanged("TimeRemaining");
                OnPropertyChanged("VarianceDuration");
                OnPropertyChanged("UiOpacity");
                OnPropertyChanged("UiBorderColor");
            }
        }

        [mp.Column(Name = "EndDate", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? EndDate
        {
            get { return _endDate; }
            set 
            { 
                _endDate = value;
                if (_isNew)
                    _baselineEndDate = value;
                else if (_isNew == false && _baselineEndDate == null)
                    _baselineEndDate = value;

                if (_startDate != null)
                    _duration = (DateTime.Today < _endDate) ? TaskSchedulers.GetBusinessDays(_startDate.Value, value.Value) : 0; //(double)((value - _startDate) as TimeSpan?).Value.TotalDays;
                //_timeRemaining = (DateTime.Today < _endDate) ? TaskSchedulers.GetBusinessDays(DateTime.Today, _endDate.Value) : 0;
                if (_startDate.HasValue)
                {
                    if (DateTime.Today > _endDate)
                        _timeRemaining = 0;
                    else if (DateTime.Today < _startDate)
                        _timeRemaining = TaskSchedulers.GetBusinessDays(_startDate.Value, _endDate.Value);
                    else
                        _timeRemaining = TaskSchedulers.GetBusinessDays(DateTime.Today, _endDate.Value);
                }
                else
                    _timeRemaining = 0;

                if (_startDate.HasValue)
                    _varianceDuration = ((TimeSpan)(value.Value - _startDate.Value)).TotalDays - ((TimeSpan)(_baselineEndDate.Value - _baselineStartDate.Value)).TotalDays;

                this.IsModified = true;
                OnPropertyChanged("EndDate");
                OnPropertyChanged("BaselineEndDate");
                OnPropertyChanged("Duration");
                OnPropertyChanged("TimeRemaining");
                OnPropertyChanged("VarianceDuration");
                OnPropertyChanged("UiOpacity");
                OnPropertyChanged("UiBorderColor");
            }
        }

        [mp.Column(Name = "TimeRemaining", UpdateCheck = mp.UpdateCheck.Never)]
        public double TimeRemaining
        {
            get { return _timeRemaining; }
            set 
            { 
                _timeRemaining = value;
                OnPropertyChanged("TimeRemaining");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "BaselineStartDate")]
        public DateTime? BaselineStartDate
        {
            get { return _baselineStartDate; }
            set 
            { 
                _baselineStartDate = value;
                OnPropertyChanged("BaselineStartDate");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "BaselineEndDate")]
        public DateTime? BaselineEndDate
        {
            get { return _baselineEndDate; }
            set 
            { 
                _baselineEndDate = value;
                OnPropertyChanged("BaselineEndDate");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "VarianceDuration", UpdateCheck = mp.UpdateCheck.Never)]
        public double VarianceDuration
        {
            get { return _varianceDuration; }
            set 
            { 
                _varianceDuration = value;
                OnPropertyChanged("VarianceDuration");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "TotalQuantity", UpdateCheck = mp.UpdateCheck.Never)]
        public int TotalQuantity
        {
            get { return _totalQuantity; }
            set 
            { 
                _totalQuantity = value;
                this.IsModified = true;
                OnPropertyChanged("TotalQuantity");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "CompletedQuantity", UpdateCheck = mp.UpdateCheck.Never)]
        public int CompletedQuantity
        {
            get { return _completedQuantity; }
            set 
            { 
                _completedQuantity = value;
                this.IsModified = true;
                OnPropertyChanged("CompletedQuantity");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Comment", CanBeNull=true, UpdateCheck=mp.UpdateCheck.Never)]
        public string Comment
        {
            get
            {
                return _comment;
            }

            set
            {
                _comment = value;
                this.IsModified = true;
                OnPropertyChanged("Comment");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set { _dateCreated = value; }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time")]
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

      [mp.Column(Name = "EditedDate", UpdateCheck = mp.UpdateCheck.Never, CanBeNull=true)]
        public DateTime? DateEdited
        {
            get { return _dateEdited; }
            set { _dateEdited = value; }
        }

        [mp.Column(Name = "EditedTime", DbType = "Time", UpdateCheck = mp.UpdateCheck.Never, CanBeNull = true)]
        public DateTime? TimeEdited
        {
            get { return _timeEdited; }
            set { _timeEdited = value; }
        }

        [mp.Column(Name = "EditingUser", UpdateCheck = mp.UpdateCheck.Never, CanBeNull = true)]
        public string EditingUser
        {
            get { return _editingUser; }
            set { _editingUser = value; }
        }

        internal bool IsNew
        {
            get { return _isNew; }
            set 
            { 
                _isNew = value;
                if (value)
                {
                    this._uiOpacity = _OPACITYFULL;
                    this._uiBorderColor = _COLORSELECTABLE;
                }
                else
                {
                    this._uiOpacity = _OPACITYPARTIAL;
                    this._uiBorderColor = _COLORPARTIAL;
                }
                OnPropertyChanged("IsModified");
                OnPropertyChanged("UiOpacity");
                OnPropertyChanged("UiBorderColor");
            }
        }


        internal bool IsModified
        {
            get { return _isModified; }
            set 
            { 
                _isModified = value;
                if (value)
                {
                    this._uiOpacity = _OPACITYFULL;
                    this._uiBorderColor = _COLORSELECTABLE;
                }
                else
                {
                    this._uiOpacity = _OPACITYPARTIAL;
                    this._uiBorderColor = _COLORPARTIAL;
                }
                OnPropertyChanged("IsModified");
                OnPropertyChanged("UiOpacity");
                OnPropertyChanged("UiBorderColor");
            }
        }


        public bool IsDeleted
        {
            get { return _isDeleted; }
            set 
            { 
                _isDeleted = value;
                this.IsModified = true;
                OnPropertyChanged("IsDeleted");
                OnPropertyChanged("IsModified");
                OnPropertyChanged("UiOpacity");
                OnPropertyChanged("UiBorderColor");
            }
        }


        public double UiOpacity
        {
            get { return _uiOpacity; }
            set { _uiOpacity = value; }
        }


        public string UiBorderColor
        {
            get { return _uiBorderColor; }
            set { _uiBorderColor = value; }
        }


        public bool InsertedToDb
        {
            get { return _insertedToDb; }
            set { _insertedToDb = value; }
        }

        public Dictionary<string, int> UserIdPairs
        {
            get
            {
                return _userIdPairs;
            }

            set
            {
                _userIdPairs = value;
            }
        }

        public TaskSchedulerItem()
        {
            this._isNew = true;
            //this.UserIdPairs = new Dictionary<string, int>();
            this._uiOpacity = 1;
        }

        //Constructor in the UI for a new task
        public TaskSchedulerItem(Dictionary<string, int> userList, string jobNumber, string jobName, int assignById, string assignByName,int assignToId
                                , string assignToName, int taskTypeInt, string taskTypeName, string area, string division)
        {
            this.IsNew = true;  //modifies the opacity
            this.UserIdPairs = userList;
            this._assignedToUser = new dc.User();
            this.AssignedToUser.Id = assignToId;
            this.AssignedToUser.DomainUserName = assignToName;

            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._assignedById = assignById;
            this._assignedByName = assignByName;
            this._assignedToId = assignToId;
            this._assignedToName = assignToName;
            this._taskTypeInt = taskTypeInt;
            this._taskTypeName = taskTypeName;
            this._area = area;
            this._division = division;

            //this.IsModified = false;  //testing purposes only
        }

        public TaskSchedulerItem(Dictionary<string, int> userList, int id, bool completed,
                            string jobNumber, string jobName, int assignById, string assignByName
                            ,int assignToId, string assignToName, int taskTypeInt, string taskTypeName, string area
                            ,double duration 
                            ,string division
                            ,DateTime? startDate, DateTime? endDate, double timeRemaining, DateTime? baselineStartDate
                            ,DateTime? baselineEndDate, double varianceDuration, int totalQuantity, int completedQuantity, string comment,
                            DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine, 
                            string editingUser, DateTime? dateEdited, DateTime? timeEdited)
        {
            this.IsNew = false; //modifies the opacity
            this.UserIdPairs = userList;

            //delete this later
            //this._assignedToUser = new dc.UserTwo();
            //this.AssignedToUser.Id = assignToId;
            //this.AssignedToUser.DomainUserName = assignToName;
            //

            this._id = id;
            this._completed = completed;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._assignedById = assignById;
            this._assignedByName = assignByName;
            this._assignedToId = assignToId;
            this._assignedToName = assignToName;
            this._taskTypeInt = taskTypeInt; 
            this._taskTypeName = taskTypeName;
            this._area = area;
            this._duration = duration;
            this._division = division;
            this._startDate = startDate;
            this._endDate = endDate;
            this._timeRemaining = timeRemaining;
            this._baselineStartDate = baselineStartDate;
            this._baselineEndDate = baselineEndDate;
            this._varianceDuration = varianceDuration;
            this._totalQuantity = totalQuantity;
            this._completedQuantity = completedQuantity;
            this._comment = comment;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this._editingUser = editingUser;
            this._dateEdited = dateEdited;
            this._timeEdited = timeEdited;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class TaskSchedulerItemDataContext : lq.DataContext
    {
        public TaskSchedulerItemDataContext(string cs)
            : base(cs)
        {
        }

        public TaskSchedulerItemDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public TaskSchedulerItemDataContext(string cs, lq.Mapping.MappingSource ms)
            : base(cs, ms)
        {
        }

        public lq.Table<TaskSchedulerItem> TaskSchedulerItem;
    }

    [mp.Table(Name = "PMTASKITEMLIST001")]
    class TaskEnum
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _taskName;
        private bool _derivateOperation;
        private string _creatingUser;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;

        [mp.Column(Name = "ID")]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "TaskName")]
        public string TaskName
        {
            get { return _taskName; }
            set { _taskName = value; }
        }

        [mp.Column(Name = "DerivateOperation", DbType="bit")]
        public bool DerivateOperation
        {
            get { return _derivateOperation; }
            set { _derivateOperation = value; }
        }

        [mp.Column(Name = "CreatingUser")]
        public string CreatingUser
        {
            get { return _creatingUser; }
            set { _creatingUser = value; }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set { _dateCreated = value; }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time")]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set { _timeCreated = value; }
        }

        public TaskEnum()
        {
        }

        public TaskEnum(int id, string taskName, bool derivativeOperation, string creatingUser, DateTime? dateCreated
                        ,DateTime? timeCreated)
        {
            this._id = id;
            this._taskName = taskName;
            this._derivateOperation = derivativeOperation;
            this._creatingUser = creatingUser;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
        }
    }
}
