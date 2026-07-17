using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Collections.ObjectModel;
using System.Windows;
using System.Data.SqlClient;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.DataClasses
{
    public static class BidProjects
    {
        internal static ObservableCollection<BidProject> GetBidProjects(bool ignoreAwarded)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<BidProject> projList = null;

            try
            {
                var preQuery = from bidProj in dtCtx.GetTable<BidProject>()
                                   //where bidProj.ProjectStatus != "AWARDED" || 
                               //where bidProj.ProjectStatus != null
                               orderby bidProj.JobNumber descending
                               select new
                               {
                                   Id = bidProj.Id,
                                   JobNumber = bidProj.JobNumber == null ? "" : bidProj.JobNumber, // bidProj.JobNumber,
                                   JobName = bidProj.JobName,
                                   CustomerNumber = bidProj.CustomerNumber,
                                   CustomerName = bidProj.CustomerName,
                                   Consultant = bidProj.Consultant,
                                   ProjectStatus = bidProj.ProjectStatus,
                                   Division = bidProj.Division,
                                   ProjectType = bidProj.ProjectType,
                                   Comments = bidProj.Comments,
                                   DateTenderOffer = bidProj.DateTenderOffer,
                                   DateModified = bidProj.DateModified,
                                   BidClosingDate = bidProj.BidClosingDate,
                                   BidClosingTime = bidProj.BidClosingTime,
                                   EstStartDate = bidProj.EstStartDate,
                                   EstEndDate = bidProj.EstEndDate,
                                   EstProjValue = bidProj.EstProjValue
                               };

                if (ignoreAwarded)
                    preQuery = preQuery.Where(x => x.ProjectStatus != "AWARDED" || x.ProjectStatus == null);

                projList = preQuery.AsEnumerable().Select(x => new BidProject(x.Id, x.JobNumber, x.JobName , x.CustomerNumber, x.CustomerName,
                                                                               x.Consultant, x.ProjectStatus, 
                                                                               x.Division,
                                                                               x.ProjectType,
                                                                               x.Comments, x.DateTenderOffer,
                                                                               x.DateModified, x.BidClosingDate, x.BidClosingTime, x.EstStartDate, x.EstStartDate,
                                                                               x.EstProjValue)).ToList();

                if (projList.Count == 0) { return new ObservableCollection<BidProject>(); }
                 
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
                if (projList.Count == 0)
                    MessageBox.Show("Bid projects returned no entries from the database.");
            }
            return new ObservableCollection<BidProject>(projList);
        }

        public static bool UpdateBidProjects(ObservableCollection<BidProject> _preProjCol)
        {
            bool _cont = true;
            //foreach (BidProject bp in _preProjCol)
            //{
            //    if (bp.JobNumber == null || bp.JobNumber == "")
            //    {
            //        MessageBox.Show("Bids without job numbers are not permitted, cancelling operation");
            //        return false;
            //    }
            //}
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (BidProjectDataContext dtCtx = new BidProjectDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (BidProject bp in _preProjCol)
                {
                    try
                    {
                        if (bp.Id == 0 && bp.IsDeleted != true)
                        {
                            int _id = GetNextBidProjectId();
                            bp.Id = _id;
                            dtCtx.BidProject.InsertOnSubmit(bp);
                        }
                        else if (bp.Id != 0 && bp.IsModified == true)
                        {
                            bp.DateModified = DateTime.Now;
                            dtCtx.BidProject.Attach(bp, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, bp);
                        }
                        else if (bp.Id != 0 && bp.IsDeleted == true)
                        {
                            dtCtx.BidProject.Attach(bp, bp);
                            dtCtx.BidProject.DeleteOnSubmit(bp);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; }
                }
                dtCtx.SubmitChanges();
            }

            return _cont;
        }

        public static void AddBidProject(BidProject bp)
        {
            using (BidProjectDataContext dtCtx = new BidProjectDataContext(GlobalVars.UcshConnectionString))
            {
                bp.UpdatingUser = Environment.UserName;
                bp.UpdatingMachine = Environment.MachineName;
                bp.DateCreated = DateTime.Today;
                bp.TimeCreated = DateTime.Now;
                try
                {
                    int _id = GetNextBidProjectId();
                    bp.Id = _id;
                    dtCtx.BidProject.InsertOnSubmit(bp);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void DeleteBidProject(BidProject bp)
        {
            using (BidProjectDataContext dtCtx = new BidProjectDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.BidProject.Attach(bp, bp);
                    dtCtx.BidProject.DeleteOnSubmit(bp);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void UpdateSingleBidProject(BidProject bp)
        {
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (BidProjectDataContext dtCtx = new BidProjectDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    var updquery = from bidProj in dtCtx.BidProject
                                   where bidProj.Id == bp.Id
                                   select bidProj;

                    var updBid = updquery.FirstOrDefault();
                    if (updBid != null)
                    {
                        updBid.ProjectStatus = "AWARDED";
                        dtCtx.SubmitChanges();
                    }
                    else
                    {
                        MessageBox.Show("Oddly, " + bp.JobName + " was not found in the bid project table.  No 'AWARDED' status could be applied.");
                    }
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }

                //bp.DateModified = DateTime.Now;
                //dtCtx.BidProject.Attach(bp, false);
                //dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, bp);
                //dtCtx.SubmitChanges();
            }
        }

        public static int GetNextBidProjectId()
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[UTPMBIDPROJ101]";
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

    [mp.Table(Name = "[UTPMBIDPROJ101]")]
    public class BidProject : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _jobName;
        private string _customerNumber;
        private string _customerName;
        private string _consultant;
        private string _projectStatus;
        private string _division;
        private string _projectType;
        private string _comments;
        private DateTime? _dateTenderOffer;
        private DateTime? _dateModified;
        private DateTime? _bidClosingDate;
        private DateTime? _bidClosingTime;          //added 17 Jan 2018
        private DateTime? _estStartDate;
        private DateTime? _estEndDate;
        private decimal _estProjValue;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        //No need for _isNew because an _id value of 0 implies new
        private bool _isModified;
        private bool _isDeleted;

        [mp.Column(Name = "ID", IsPrimaryKey = true)] //, AutoSync = System.Data.Linq.Mapping.AutoSync.OnInsert, IsDbGenerated = true
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        //[mp.Column(Name = "ID", IsPrimaryKey = true)]
        //public int Id
        //{
        //    get { return _id; }
        //    set { _id = value; }
        //}

        [mp.Column(Name = "JobNumber", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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

        [mp.Column(Name = "JobName", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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

        [mp.Column(Name = "CustomerNumber", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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

        [mp.Column(Name = "CustomerName", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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

        [mp.Column(Name = "Consultant", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Consultant
        {
            get { return _consultant; }
            set 
            { 
                _consultant = value;
                this.IsModified = true;
                OnPropertyChanged("Consultant");
            }
        }

        [mp.Column(Name = "ProjectStatus", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string ProjectStatus
        {
            get { return _projectStatus; }
            set 
            { 
                _projectStatus = value;
                this.IsModified = true;
                OnPropertyChanged("ProjectStatus");
            }
        }

        [mp.Column(Name = "Division", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Division
        {
            get
            {
                return _division;
            }

            set
            {
                _division = value;
                this.IsModified = true;
                OnPropertyChanged("Division");
            }
        }

        [mp.Column(Name = "ProjectType", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string ProjectType
        {
            get
            {
                return _projectType;
            }

            set
            {
                _projectType = value;
                this.IsModified = true;
                OnPropertyChanged("ProjectType");
            }
        }

        [mp.Column(Name = "Comments", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Comments
        {
            get { return _comments; }
            set 
            { 
                _comments = value;
                this.IsModified = true;
                OnPropertyChanged("Comments");
            }
        }

        [mp.Column(Name = "DateTenderOffer", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? DateTenderOffer
        {
            get { return _dateTenderOffer; }
            set 
            { 
                _dateTenderOffer = value;
                this.IsModified = true;
                OnPropertyChanged("DateTenderOffer");
            }
        }

        [mp.Column(Name = "DateModified", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]     //IsVersion property allows for 'dtCtx.PreProject.Attach(pp, true)' to work.
        public DateTime? DateModified
        {
            get { return _dateModified; }
            set 
            { 
                _dateModified = value;
                this.IsModified = true;
                OnPropertyChanged("DateModified");
            }
        }

        [mp.Column(Name = "BidClosingDate", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? BidClosingDate
        {
            get { return _bidClosingDate; }
            set 
            { 
                _bidClosingDate = value;
                this.IsModified = true;
                OnPropertyChanged("BidClosingDate");
            }
        }

        [mp.Column(Name = "BidClosingTime", DbType = "Time", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? BidClosingTime
        {
            get { return _bidClosingTime; }
            set 
            { 
                _bidClosingTime = value;
                this.IsModified = true;
                OnPropertyChanged("BidClosingTime");
            }
        }

        [mp.Column(Name = "EstStartDate", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? EstStartDate
        {
            get { return _estStartDate; }
            set 
            { 
                _estStartDate = value;
                this.IsModified = true;
                OnPropertyChanged("EstStartDate");
            }
        }

        [mp.Column(Name = "EstEndDate", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? EstEndDate
        {
            get { return _estEndDate; }
            set 
            { 
                _estEndDate = value;
                this.IsModified = true;
                OnPropertyChanged("EstEndDate");
            }
        }

        [mp.Column(Name = "EstProjValue", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public decimal EstProjValue
        {
            get { return _estProjValue; }
            set 
            { 
                _estProjValue = value;
                this.IsModified = true;
                OnPropertyChanged("EstProjValue");
            }
        }

        [mp.Column(Name = "DateCreated", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set { _dateCreated = value; }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set { _timeCreated = value; }
        }

        [mp.Column(Name = "UpdatingUser", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set { _updatingUser = value; }
        }

        [mp.Column(Name = "UpdatingMachine", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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


        public BidProject()
        {
            this._dateModified = DateTime.Now;
        }

        public BidProject(int id, string jobNumber, string jobName)
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._isModified = false;
        }

        public BidProject(int Id, string jobNumber, string jobName, string custNumb, string custName, string consul, string projStatus, 
                            string division,
                            string projecType,
                            string comments, DateTime? dateTenderOffer,
                          DateTime? dateModified, DateTime? bidClosingDate, DateTime? bidClosingTime, DateTime? estStartingDate, DateTime? estEndDate, decimal estProjValue)
        {
            this._id = Id;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._customerNumber = custNumb;
            this._customerName = custName;
            this._consultant = consul;
            this._projectStatus = projStatus;
            this._division = division;
            this._projectType = projecType;
            this._comments = comments;
            this._dateTenderOffer = dateTenderOffer;
            this._dateModified = dateModified;
            this._bidClosingDate = bidClosingDate;
            this._bidClosingTime = bidClosingTime;
            this._estStartDate = estStartingDate;
            this._estEndDate = estEndDate;
            this._estProjValue = estProjValue;
            this._isModified = false;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class BidProjectDataContext : lq.DataContext
    {
        public BidProjectDataContext(string cs)
            : base(cs)
        {
        }

        public BidProjectDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<BidProject> BidProject;
    }
}
