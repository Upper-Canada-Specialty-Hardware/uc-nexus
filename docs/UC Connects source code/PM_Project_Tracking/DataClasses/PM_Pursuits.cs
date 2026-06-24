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
    class Pursuits
    {
        internal static ObservableCollection<Pursuit> GetPursuits(bool ignoreBidConsult)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<Pursuit> pursuitList = null;

            try
            {
                var pursuitQuery = from pursuitLine in dtCtx.GetTable<Pursuit>()
                                   select new
                                   {
                                       Id = pursuitLine.Id,
                                       PursuitType = pursuitLine.PursuitType == null ? "" : pursuitLine.PursuitType,
                                       PursuitStatus = pursuitLine.PursuitStatus,
                                       JobNumber = pursuitLine.JobNumber,
                                       JobName = pursuitLine.JobName == null ? "" : pursuitLine.JobName,
                                       PrimeLead = pursuitLine.PrimeLead,
                                       HardwareSchedWriter = pursuitLine.HardwareSchedWriter,
                                       HardwareSchedAssistant = pursuitLine.HardwareSchedAssistant,
                                       Architect = pursuitLine.Architect,
                                       Contractor = pursuitLine.Contractor == null ? "" : pursuitLine.Contractor,
                                       ContactName = pursuitLine.ContactName,
                                       ContactEmail = pursuitLine.ContactEmail,
                                       TenderPhase = pursuitLine.TenderPhase,
                                       Branch = pursuitLine.Branch,
                                       FacilityType = pursuitLine.FacilityType,
                                       NewOrReno = pursuitLine.NewOrReno,
                                       DoorCount = pursuitLine.DoorCount,
                                       ComplexityLevel = pursuitLine.ComplexityLevel,
                                       FundingType = pursuitLine.FundingType,
                                       BidClosingDate = pursuitLine.BidClosingDate,
                                       BidClosingTime = pursuitLine.BidClosingTime,
                                       TimeLine = pursuitLine.TimeLine,
                                       JobPriority = pursuitLine.JobPriority,
                                       AvaWareTeam = pursuitLine.AvaWareTeam,
                                       KeyingScheduling = pursuitLine.KeyingScheduling,
                                       IsConulting = pursuitLine.IsConulting,
                                       ConsultingFee = pursuitLine.ConsultingFee,
                                       PerHourOrCompleteFee = pursuitLine.PerHourOrCompleteFee,
                                       ConstructionValue = pursuitLine.ConstructionValue,
                                       EstimatedProjectValue = pursuitLine.EstimatedProjectValue,
                                       UnderReviewCompletionPercentage = pursuitLine.UnderReviewCompletionPercentage,
                                       SuccessRate = pursuitLine.SuccessRate,
                                       Specifications = pursuitLine.Specifications,
                                       DateCreated = pursuitLine.DateCreated,
                                       TimeCreated = pursuitLine.TimeCreated,
                                       UpdatingUser = pursuitLine.UpdatingUser,
                                       UpdatingMachine = pursuitLine.UpdatingMachine
                                   };

                //if (ignoreBidConsult)
                //    pursuitQuery = pursuitQuery.Where(x => x.TenderPhase != "BIDDING" || x.TenderPhase != "CONSULTING");

                if (ignoreBidConsult)
                    pursuitQuery = pursuitQuery.Where(x => x.TenderPhase == "" || x.TenderPhase == null);

                pursuitList = pursuitQuery.AsEnumerable().Select(x => new Pursuit(x.Id
                                                                                , x.PursuitType
                                                                                , x.PursuitStatus
                                                                                , x.JobNumber
                                                                                , x.JobName
                                                                                , x.PrimeLead
                                                                                , x.HardwareSchedWriter
                                                                                , x.HardwareSchedAssistant
                                                                                , x.Architect
                                                                                , x.Contractor
                                                                                , x.ContactName
                                                                                , x.ContactEmail
                                                                                , x.TenderPhase
                                                                                , x.Branch
                                                                                , x.FacilityType
                                                                                , x.NewOrReno
                                                                                , x.DoorCount
                                                                                , x.ComplexityLevel
                                                                                , x.FundingType
                                                                                , x.BidClosingDate
                                                                                , x.BidClosingTime
                                                                                , x.TimeLine
                                                                                , x.JobPriority
                                                                                , x.AvaWareTeam
                                                                                , x.KeyingScheduling
                                                                                , x.IsConulting
                                                                                , x.ConsultingFee
                                                                                , x.PerHourOrCompleteFee
                                                                                , x.ConstructionValue
                                                                                , x.EstimatedProjectValue
                                                                                , x.UnderReviewCompletionPercentage
                                                                                , x.SuccessRate
                                                                                , x.Specifications
                                                                                , x.DateCreated
                                                                                , x.TimeCreated
                                                                                , x.UpdatingUser
                                                                                , x.UpdatingMachine
                                                                                )).ToList();



            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<Pursuit>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<Pursuit>(pursuitList);
        }

        public static bool UpdatePursuitProjects(ObservableCollection<Pursuit> _pursuitCol)
        {
            bool _cont = true;
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (PursuitDataContext dtCtx = new PursuitDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (Pursuit pt in _pursuitCol)
                {
                    try
                    {
                        if (pt.Id == 0 && pt.IsDeleted != true)
                        {
                            int _id = GetNextPursuitId();
                            pt.Id = _id;
                            dtCtx.Pursuit.InsertOnSubmit(pt);
                        }
                        else if (pt.Id != 0 && pt.IsModified == true)
                        {
                            //is modified?
                            dtCtx.Pursuit.Attach(pt, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, pt);
                        }
                        else if (pt.Id != 0 && pt.IsDeleted == true)
                        {
                            dtCtx.Pursuit.Attach(pt, pt);
                            dtCtx.Pursuit.DeleteOnSubmit(pt);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; }
                }
                dtCtx.SubmitChanges();
            }

            return _cont;
        }

        public static void AddPursuit(Pursuit pt)
        {
            using (PursuitDataContext dtCtx = new PursuitDataContext(GlobalVars.UcshConnectionString))
            {
                int _id = GetNextPursuitId();
                pt.Id = _id;
                pt.UpdatingUser = Environment.UserName;
                pt.UpdatingMachine = Environment.MachineName;
                pt.DateCreated = DateTime.Today;
                pt.TimeCreated = DateTime.Now;
                try
                {
                    dtCtx.Pursuit.InsertOnSubmit(pt);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void DeleteOfferToTender(Pursuit pt)
        {
            using (PursuitDataContext dtCtx = new PursuitDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.Pursuit.Attach(pt, pt);
                    dtCtx.Pursuit.DeleteOnSubmit(pt);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void UpdateSinglePursuit(Pursuit pt)
        {
            //CHECK HERE - P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Updating and insert using LINQ
            using (PursuitDataContext dtCtx = new PursuitDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    var updquery = from pursProj in dtCtx.Pursuit
                                   where pursProj.Id == pt.Id
                                   select pursProj;

                    var updPur = updquery.FirstOrDefault();
                    if (updPur != null)
                    {
                        updPur.PursuitStatus = "ACTIVE";
                        dtCtx.SubmitChanges();
                    }
                    else { MessageBox.Show("Oddly, " + pt.JobName + " was not found in the bid project table.  No 'AWARDED' status could be applied."); }
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }

                //bp.DateModified = DateTime.Now;
                //dtCtx.OfferToTender.Attach(ot, false);
                //dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, ot);
                //dtCtx.SubmitChanges();
            }
        }

        private static int GetNextPursuitId()
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[UTPMPURSUIT101]";
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

    [mp.Table(Name = "[UTPMPURSUIT101]")]
    public class Pursuit : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _pursuitType;        //REDUNDANT!!! - SEE FUNDING TYPE PROPERTY      P3, General Tender, Construction Management
        private string _pursuitStatus;      //Pending vs active status
        private string _jobNumber;
        private string _jobName;
        private string _primeLead;
        private string _hardwareSchedWriter;
        private string _hardwareSchedAssistant;
        private string _architect;
        private string _contractor;
        private string _contactName;
        private string _contactEmail;
        private string _tenderPhase;
        private string _branch;
        private string _facilityType;
        private string _newOrReno;
        private int _doorCount;
        private int _complexityLevel;
        private string _fundingType;
        private DateTime? _bidClosingDate;
        private DateTime? _bidClosingTime;
        private DateTime? _timeLine;
        private string _jobPriority;
        private string _avaWareTeam;
        private string _keyingScheduling;
        private decimal _constructionValue;
        private bool _isConsulting;
        private decimal _consultingFee;
        private string _perHourOrCompleteFee;
        private decimal _estimatedProjectValue;
        private decimal _underReviewCompletionPercentage;
        private decimal _successRate;
        private string _specifications;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;

        [mp.Column(Name = "ID", IsPrimaryKey = true, DbType="int", CanBeNull=false)]
        public int Id
        {
            get
            {
                return _id;
            }

            set
            {
                _id = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "PursuitType", CanBeNull=true, UpdateCheck = mp.UpdateCheck.Never)]
        public string PursuitType
        {
            get
            {
                return _pursuitType;
            }

            set
            {
                _pursuitType = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "PursuitStatus", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string PursuitStatus
        {
            get
            {
                return _pursuitStatus;
            }

            set
            {
                _pursuitStatus = value;
                this.IsModified = true;
                //OnPropertyChanged("PursuitStatus");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "JobNumber", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string JobNumber
        {
            get
            {
                return _jobNumber;
            }

            set
            {
                _jobNumber = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "JobName", CanBeNull = false, UpdateCheck = mp.UpdateCheck.Never)]
        public string JobName
        {
            get
            {
                return _jobName;
            }

            set
            {
                _jobName = value.ToString().ToUpper();
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "PrimeLead", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string PrimeLead
        {
            get
            {
                return _primeLead;
            }

            set
            {
                _primeLead = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "HardwareSchedWriter", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string HardwareSchedWriter
        {
            get
            {
                return _hardwareSchedWriter;
            }

            set
            {
                _hardwareSchedWriter = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "HardwareSchedAssistant", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string HardwareSchedAssistant
        {
            get
            {
                return _hardwareSchedAssistant;
            }

            set
            {
                _hardwareSchedAssistant = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Architect", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Architect
        {
            get
            {
                return _architect;
            }

            set
            {
                _architect = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Contractor", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Contractor
        {
            get
            {
                return _contractor;
            }

            set
            {
                _contractor = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "ContactName", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string ContactName
        {
            get
            {
                return _contactName;
            }

            set
            {
                _contactName = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "ContactEmail", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string ContactEmail
        {
            get
            {
                return _contactEmail;
            }

            set
            {
                _contactEmail = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "TenderPhase", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string TenderPhase
        {
            get
            {
                return _tenderPhase;
            }

            set
            {
                _tenderPhase = value;
                this.IsModified = true;
                OnPropertyChanged("TenderPhase");
                OnPropertyChanged("IsModified");

                if (value == "CONSULTING")
                {
                    this._isConsulting = true;
                    OnPropertyChanged("IsConsulting");
                }
                    

            }
        }

        [mp.Column(Name = "Branch", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Branch
        {
            get
            {
                return _branch;
            }

            set
            {
                _branch = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "FacilityType", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string FacilityType
        {
            get
            {
                return _facilityType;
            }

            set
            {
                _facilityType = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "NewOrReno", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string NewOrReno
        {
            get
            {
                return _newOrReno;
            }

            set
            {
                _newOrReno = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "DoorCount", DbType = "int", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public int DoorCount
        {
            get
            {
                return _doorCount;
            }

            set
            {
                _doorCount = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "ComplexityLevel", DbType = "int", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public int ComplexityLevel
        {
            get
            {
                return _complexityLevel;
            }

            set
            {
                _complexityLevel = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "FundingType", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string FundingType
        {
            get
            {
                return _fundingType;
            }

            set
            {
                _fundingType = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "BidClosingDate", DbType = "date", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? BidClosingDate
        {
            get
            {
                return _bidClosingDate;
            }

            set
            {
                _bidClosingDate = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "BidClosingTime", DbType = "Time", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? BidClosingTime
        {
            get
            {
                return _bidClosingTime;
            }

            set
            {
                _bidClosingTime = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "TimeLine", DbType = "date", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? TimeLine
        {
            get
            {
                return _timeLine;
            }

            set
            {
                _timeLine = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "JobPriority", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string JobPriority
        {
            get
            {
                return _jobPriority;
            }

            set
            {
                _jobPriority = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "AVAWareTeam", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string AvaWareTeam
        {
            get
            {
                return _avaWareTeam;
            }

            set
            {
                _avaWareTeam = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "KeyingSchedule", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string KeyingScheduling
        {
            get
            {
                return _keyingScheduling;
            }

            set
            {
                _keyingScheduling = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "ConstructionValue", DbType = "numeric", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public decimal ConstructionValue
        {
            get
            {
                return _constructionValue;
            }

            set
            {
                _constructionValue = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }



        [mp.Column(Name = "IsConsulting", DbType = "bit", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public bool IsConulting
        {
            get
            {
                return _isConsulting;
            }

            set
            {
                _isConsulting = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "ConsultingFee", DbType = "decimal", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public decimal ConsultingFee
        {
            get
            {
                return _consultingFee;
            }

            set
            {
                _consultingFee = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }


        [mp.Column(Name = "PerHourOrCompleteFee", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string PerHourOrCompleteFee
        {
            get
            {
                return _perHourOrCompleteFee;
            }

            set
            {
                _perHourOrCompleteFee = value;
            }
        }


        [mp.Column(Name = "EstimatedProjectValue", DbType = "numeric", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public decimal EstimatedProjectValue
        {
            get
            {
                return _estimatedProjectValue;
            }

            set
            {
                _estimatedProjectValue = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "UnderReviewCompletionPercentage", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public decimal UnderReviewCompletionPercentage
        {
            get
            {
                return _underReviewCompletionPercentage;
            }

            set
            {
                _underReviewCompletionPercentage = value;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "SuccessRate", DbType = "decimal", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public decimal SuccessRate
        {
            get
            {
                return _successRate;
            }

            set
            {
                _successRate = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Specifications", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Specifications
        {
            get
            {
                return _specifications;
            }

            set
            {
                _specifications = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "DateCreated", DbType = "date", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? DateCreated
        {
            get
            {
                return _dateCreated;
            }

            set
            {
                _dateCreated = value;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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

        [mp.Column(Name = "UpdatingUser", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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

        [mp.Column(Name = "UpdatingMachine", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
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

        public bool IsModified
        {
            get { return _isModified; }
            set
            {
                _isModified = value;
                //OnPropertyChanged("IsModified");
            }
        }

        public bool IsDeleted
        {
            get { return _isDeleted; }
            set { _isDeleted = value; }
        }



        public Pursuit()
        {
            this._jobName = "";
            this._contractor = "";
        }

        public Pursuit(
            int id, 
            string pursuitType, 
            string pursuitStatus,
            string jobNumber,
            string jobName,
            string primeLead,
            string hardwareSchedWriter,
            string hardwareSchedAssistant,
            string architect,
            string contractor,
            string contactName,
            string contactEmail,
            string tenderPhase,
            string branch, string facilityType,
            string newOrReno,
            int doorCount,
            int complexityLevel,
            string fundingType,
            DateTime? bidClosingDate,
            DateTime? bidClosingTime,
            DateTime? timeLine,
            string jobPriority,
            string avaWareTeam,
            string keyingScheduling,
            bool isConsulting,
            decimal consultingFee,
            string perHourOrCompleteFee,
            decimal constructionValue,
            decimal estimatedProjectValue,
            decimal underReviewCompletionPercentage,
            decimal successRate,
            string specifications,
            DateTime? dateCreated,
            DateTime? timeCreated,
            string updatingUser,
            string updatingMachine
            )
        {
            this._id = id;
            this._pursuitType = pursuitType;
            this._pursuitStatus = pursuitStatus;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._primeLead = primeLead;
            this._hardwareSchedWriter = hardwareSchedWriter;
            this._hardwareSchedAssistant = hardwareSchedAssistant;
            this._architect = architect;
            this._contractor = contractor;
            this._contactName = contactName;
            this._contactEmail = contactEmail;
            this._tenderPhase = tenderPhase;
            this._branch = branch;
            this._facilityType = facilityType;
            this._newOrReno = newOrReno;
            this._doorCount = doorCount;
            this._complexityLevel = complexityLevel;
            this._fundingType = fundingType;
            this._bidClosingDate = bidClosingDate;
            this._bidClosingTime = bidClosingTime;
            this._timeLine = timeLine;
            this._jobPriority = jobPriority;
            this._avaWareTeam = avaWareTeam;
            this._keyingScheduling = keyingScheduling;
            this._isConsulting = isConsulting;
            this._consultingFee = consultingFee;
            this._perHourOrCompleteFee = perHourOrCompleteFee;
            this._constructionValue = constructionValue;
            this._estimatedProjectValue = estimatedProjectValue;
            this._underReviewCompletionPercentage = underReviewCompletionPercentage;
            this._successRate = successRate;
            this._specifications = specifications;
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

    public class PursuitDataContext : lq.DataContext
    {
        public PursuitDataContext(string cs) 
            : base(cs)
        {

        }

        public PursuitDataContext(SqlConnection conn) 
            : base(conn)
        {

        }

        public lq.Table<Pursuit> Pursuit;
    }


}
