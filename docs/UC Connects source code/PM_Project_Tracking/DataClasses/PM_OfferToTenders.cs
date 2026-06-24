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
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.DataClasses
{
    public static class OfferToTenders
    {
        internal static ObservableCollection<OfferToTender> GetOfferToTenderProjects()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));        
            List<OfferToTender> projList = null;
            
            try
            {
                var offerQuery = from offerProj in dtCtx.GetTable<OfferToTender>()
                                 orderby offerProj.ProjectStatus descending, offerProj.Id
                                 where offerProj.ProjectStatus != "BIDDING" || offerProj.ProjectStatus == null
                                 //where offerProj.Id == 24536343
                                 select new
                                 {
                                     Id = offerProj.Id,
                                     JobName = offerProj.JobName,
                                     CustomerName = offerProj.CustomerName,
                                     RequestDate = offerProj.RequestDate,
                                     BidDueDate = offerProj.BidDueDate,
                                     ProjectStatus = offerProj.ProjectStatus,
                                     Comments = offerProj.Comments,
                                     Consultant = offerProj.Consultant
                                 };

                projList = offerQuery.AsEnumerable().Select(x => new OfferToTender(x.Id, x.JobName, x.CustomerName, x.RequestDate,
                                                                                   x.BidDueDate, x.ProjectStatus, x.Comments, x.Consultant)).ToList();

                if (projList.Count == 0) { return new ObservableCollection<OfferToTender>(); }

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
                if (projList.Count == 0)
                    MessageBox.Show("Offer to tenders returned no entries from the database."); 
            }
            return new ObservableCollection<OfferToTender>(projList);
        }

        public static void UpdateOfferToTenderProjects(ObservableCollection<OfferToTender> _offTendCol)
        {
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (OfferToTenderDataContext dtCtx = new OfferToTenderDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (OfferToTender ot in _offTendCol)
                {
                    try
                    {
                        if (ot.Id == 0 && ot.IsDeleted != true)
                        {
                            dtCtx.OfferToTender.InsertOnSubmit(ot);
                        }
                        else if (ot.Id != 0 && ot.IsModified == true)
                        {
                            //is modified?
                            dtCtx.OfferToTender.Attach(ot, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, ot);
                        }
                        else if (ot.Id != 0 && ot.IsDeleted == true)
                        {
                            dtCtx.OfferToTender.Attach(ot, ot);
                            dtCtx.OfferToTender.DeleteOnSubmit(ot);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static void AddOfferToTender(OfferToTender ot)
        {   
            using (OfferToTenderDataContext dtCtx = new OfferToTenderDataContext(GlobalVars.UcshConnectionString))
            {
                ot.UpdatingUser = Environment.UserName;
                ot.UpdatingMachine = Environment.MachineName;
                ot.DateCreated = DateTime.Today;
                ot.TimeCreated = DateTime.Now;
                try
                {
                    dtCtx.OfferToTender.InsertOnSubmit(ot);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void DeleteOfferToTender(OfferToTender ot)
        {
            using (OfferToTenderDataContext dtCtx = new OfferToTenderDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.OfferToTender.Attach(ot, ot);
                    dtCtx.OfferToTender.DeleteOnSubmit(ot);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void UpdateSingleOfferToTender(OfferToTender ot)
        {
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (OfferToTenderDataContext dtCtx = new OfferToTenderDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    var updquery = from ottProj in dtCtx.OfferToTender
                                   where ottProj.Id == ot.Id
                                   select ottProj;

                    var updBid = updquery.FirstOrDefault();
                    if (updBid != null)
                    {
                        updBid.ProjectStatus = "BIDDING";
                        dtCtx.SubmitChanges();
                    }
                    else { MessageBox.Show("Oddly, " + ot.JobName + " was not found in the bid project table.  No 'AWARDED' status could be applied.");}
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }

                //bp.DateModified = DateTime.Now;
                //dtCtx.OfferToTender.Attach(ot, false);
                //dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, ot);
                //dtCtx.SubmitChanges();
            }
        }
    }

    [mp.Table(Name = "[UTPMOFFERTOTENDER101]")]
    public class OfferToTender : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobName;
        private string _customerName;
        private DateTime? _requestDate;
        private DateTime? _bidDueDate;
        private string _projectStatus;
        private string _comments;
        private string _consultant;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;

        [mp.Column(Name = "ID", IsPrimaryKey = true, AutoSync = System.Data.Linq.Mapping.AutoSync.OnInsert, IsDbGenerated = true)]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "JobName")]
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

        [mp.Column(Name = "CustomerName")]
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

        [mp.Column(Name = "RequestDate")]
        public DateTime? RequestDate
        {
            get { return _requestDate; }
            set 
            { 
                _requestDate = value;
                this.IsModified = true;
                OnPropertyChanged("RequestDate");
            }
        }

        [mp.Column(Name = "BidDueDate")]
        public DateTime? BidDueDate
        {
            get { return _bidDueDate; }
            set 
            { 
                _bidDueDate = value;
                this.IsModified = true;
                OnPropertyChanged("BidDueDate");
            }
        }

        [mp.Column(Name = "ProjectStatus")]
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

        [mp.Column(Name = "Comments")]
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

        [mp.Column(Name = "Consultant")]
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

        public OfferToTender()
        {
        }

        public OfferToTender(int id, string jobName, string custName, DateTime? reqDate, DateTime? bidDue, string projStat, string comments, string consultant)
        {
            this._id = id;
            this._jobName = jobName;
            this._customerName = custName;
            this._requestDate = reqDate;
            this._bidDueDate = bidDue;
            this._projectStatus = projStat;
            this._comments = comments;
            this._consultant = consultant;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class OfferToTenderDataContext : lq.DataContext
    {
        public OfferToTenderDataContext(string cs)
            : base(cs)
        {
        }

        public OfferToTenderDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<OfferToTender> OfferToTender;
    }
}
