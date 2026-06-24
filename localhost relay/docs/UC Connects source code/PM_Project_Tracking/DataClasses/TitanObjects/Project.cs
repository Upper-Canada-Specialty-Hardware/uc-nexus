using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using System.Text.Json;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    public class Project
    {
        int _projectId;
        string _name;
        string _description;
        string _costOptionCode;
        string _titanCo;
        string _accountingCo;
        string _contractCo;
        string _acceptedTime;   //DATE
        string _approvedTime;   //DATE
        int? _adminMinutes;
        bool? _hidden;
        string _statusCode;
        string _companyName;
        string _companyAddress1;
        string _companyAddress2;
        string _companyAddress3;
        string _dssRepEmail;
        string _projectManagerName;
        string _projectManagerEmail;
        string _assistantProjectManager1Name;
        string _assistantProjectManager1Email;
        string _assistantProjectManager2Name;
        string _assistantProjectManager2Email;
        string _contractorName;
        string _contractorPhone;
        string _contractorEmail;
        string _contractorAddress1;
        string _contractorAddress2;
        string _contractorAddress3;
        string _contractorCity;
        string _contractorState;
        string _contractorZip;
        string _contractorCountry;
        string _architectName;
        string _facilityOwnerName;
        string _engineerName;
        string _engineerEmail;
        string _teamLeaderName;
        string _teamLeaderEmail;
        int? _teamLeader2Id;
        string _teamLeader2Name;
        string _teamLeader3Name;
        string _teamLeader3Email;
        string _approverName;
        string _followUpPersonName;
        string _detailReviewerName;
        string _detailReviewerEmail;
        string _designer;
        string _jobsiteName;
        string _jobsiteAddress1;
        string _jobsiteAddress2;
        string _jobsiteAddress3;
        string _jobsiteCity;
        string _jobsiteState;
        string _jobsiteZip;
        string _jobsiteCountry;
        string _jobsitePhone;
        string _jobsiteFax;
        string _jobsiteCell;
        string _jobsiteEmail;
        string _jobsiteContact;
        string _jobsiteNotes;
        string _shopName;
        string _shopAddress1;
        string _shopAddress2;
        string _shopAddress3;
        string _shopCity;
        string _shopState;
        string _shopZip;
        string _shopCountry;
        string _salePersonName;
        string _startDate;      //DATE
        string _completeDate;   //DATE
        string _dueDate;        //DATE
        string _contractDate;   //DATE
        string _contractNumber;
        string _measurementSystemCode;
        string _jobSiteSuper;
        string _jobSiteForeman;
        string _projectNotes;
        string _jobNumber;
        string _finishHdwBy;    //DATE
        string _estimateNumber;
        string _scheduleNotes;
        string _materialScheduleNotes;
        string _keyingNotes;
        decimal? _laborRate;
        decimal? _installationRate;
        string _dodgeNum;
        string _architectsProjectNumber;
        string _notes;
        string _bidDate;        //DATE
        string _bidRequestSource;
        string _planLocation;
        string _uoc;
        string _quoteNum;
        decimal? _taxRate;
        string _verticalMarketSegmentCode;
        string _openingHeightPlus;
        string _cerpJobNumber;
        string _changeOrderDetailLevel;
        bool? _fsc;
        string _certCode;
        string _proposalType;
        string _specDivisionIncluded;
        string _architectDesignerRef;//
        string _firstInviteReceived;    //DATE
        string _allEstimatesCompleted;  //DATE
        string _lastEstimateSubmitted;  //DATE
        string _followup;               //DATE
        decimal? _bond;
        bool? _labor;
        int? _numberOfDeliveries;
        string _dateSold;                //DATE
        string _anticipatedDateToEng;    //DATE
        string _submittalReqDate;        //DATE
        bool? _expeditedMaterial;
        bool? _hollowMetalFrames;
        string _dateRequiredHmf;        //DATE
        bool? _hollowMetalDoors;
        string _dateRequiredHmd;        //DATE
        bool? _woodDoors;
        string _dateRequiredWdd;        //DATE
        string _leedRequirements;
        string _tempConstructionCores;
        decimal? _surcharge;
        int? _proposalContact;
        string _plansDated;             //DATE
        string _specificationsDated;    //DATE
        string _addendumIncluded;
        string _createdByName;
        string _createdTime;            //DATE
        int? _changeOrderCount;
        //int? _estimateCount;
        //bool? _finalEstimate;
        //bool? _finalEstimateCommitted;


        public int ProjectId
        {
            get
            {
                return _projectId;
            }

            set
            {
                _projectId = value;
            }
        }
 
        public string Name
        {
            get
            {
                return _name;
            }

            set
            {
                _name = value;
            }
        }

        public string Description
        {
            get
            {
                return _description;
            }

            set
            {
                _description = value;
            }
        }

        //public string CostOptionCode
        //{
        //    get
        //    {
        //        return _costOptionCode;
        //    }

        //    set
        //    {
        //        _costOptionCode = value;
        //    }
        //}

        //public string TitanCo
        //{
        //    get
        //    {
        //        return _titanCo;
        //    }

        //    set
        //    {
        //        _titanCo = value;
        //    }
        //}

        //public string AccountingCo
        //{
        //    get
        //    {
        //        return _accountingCo;
        //    }

        //    set
        //    {
        //        _accountingCo = value;
        //    }
        //}

        //public string ContractCo
        //{
        //    get
        //    {
        //        return _contractCo;
        //    }

        //    set
        //    {
        //        _contractCo = value;
        //    }
        //}

        //public string AcceptedTime
        //{
        //    get
        //    {
        //        return _acceptedTime;
        //    }

        //    set
        //    {
        //        _acceptedTime = value;
        //    }
        //}

        //public string ApprovedTime
        //{
        //    get
        //    {
        //        return _approvedTime;
        //    }

        //    set
        //    {
        //        _approvedTime = value;
        //    }
        //}

        //public int? AdminMinutes
        //{
        //    get
        //    {
        //        return _adminMinutes;
        //    }

        //    set
        //    {
        //        _adminMinutes = value;
        //    }
        //}

        //public bool? Hidden
        //{
        //    get
        //    {
        //        return _hidden;
        //    }

        //    set
        //    {
        //        _hidden = value;
        //    }
        //}

        //public string StatusCode
        //{
        //    get
        //    {
        //        return _statusCode;
        //    }

        //    set
        //    {
        //        _statusCode = value;
        //    }
        //}

        //public string CompanyName
        //{
        //    get
        //    {
        //        return _companyName;
        //    }

        //    set
        //    {
        //        _companyName = value;
        //    }
        //}

        //public string CompanyAddress1
        //{
        //    get
        //    {
        //        return _companyAddress1;
        //    }

        //    set
        //    {
        //        _companyAddress1 = value;
        //    }
        //}
        //public string CompanyAddress2
        //{
        //    get
        //    {
        //        return _companyAddress2;
        //    }

        //    set
        //    {
        //        _companyAddress2 = value;
        //    }
        //}

        //public string CompanyAddress3
        //{
        //    get
        //    {
        //        return _companyAddress3;
        //    }

        //    set
        //    {
        //        _companyAddress3 = value;
        //    }
        //}

        //public string DssRepEmail
        //{
        //    get
        //    {
        //        return _dssRepEmail;
        //    }

        //    set
        //    {
        //        _dssRepEmail = value;
        //    }
        //}

        //public string ProjectManagerName
        //{
        //    get
        //    {
        //        return _projectManagerName;
        //    }

        //    set
        //    {
        //        _projectManagerName = value;
        //    }
        //}

        //public string ProjectManagerEmail
        //{
        //    get
        //    {
        //        return _projectManagerEmail;
        //    }

        //    set
        //    {
        //        _projectManagerEmail = value;
        //    }
        //}

        //public string AssistantProjectManager1Name
        //{
        //    get
        //    {
        //        return _assistantProjectManager1Name;
        //    }

        //    set
        //    {
        //        _assistantProjectManager1Name = value;
        //    }
        //}

        //public string AssistantProjectManager1Email
        //{
        //    get
        //    {
        //        return _assistantProjectManager1Email;
        //    }

        //    set
        //    {
        //        _assistantProjectManager1Email = value;
        //    }
        //}

        //public string AssistantProjectManager2Name
        //{
        //    get
        //    {
        //        return _assistantProjectManager2Name;
        //    }

        //    set
        //    {
        //        _assistantProjectManager2Name = value;
        //    }
        //}

        //public string AssistantProjectManager2Email
        //{
        //    get
        //    {
        //        return _assistantProjectManager2Email;
        //    }

        //    set
        //    {
        //        _assistantProjectManager2Email = value;
        //    }
        //}

        //public string ContractorName
        //{
        //    get
        //    {
        //        return _contractorName;
        //    }

        //    set
        //    {
        //        _contractorName = value;
        //    }
        //}

        //public string ContractorPhone
        //{
        //    get
        //    {
        //        return _contractorPhone;
        //    }

        //    set
        //    {
        //        _contractorPhone = value;
        //    }
        //}

        //public string ContractorEmail
        //{
        //    get
        //    {
        //        return _contractorEmail;
        //    }

        //    set
        //    {
        //        _contractorEmail = value;
        //    }
        //}

        //public string ContractorAddress1
        //{
        //    get
        //    {
        //        return _contractorAddress1;
        //    }

        //    set
        //    {
        //        _contractorAddress1 = value;
        //    }
        //}

        //public string ContractorAddress2
        //{
        //    get
        //    {
        //        return _contractorAddress2;
        //    }

        //    set
        //    {
        //        _contractorAddress2 = value;
        //    }
        //}

        //public string ContractorAddress3
        //{
        //    get
        //    {
        //        return _contractorAddress3;
        //    }

        //    set
        //    {
        //        _contractorAddress3 = value;
        //    }
        //}

        //public string ContractorCity
        //{
        //    get
        //    {
        //        return _contractorCity;
        //    }

        //    set
        //    {
        //        _contractorCity = value;
        //    }
        //}

        //public string ContractorState
        //{
        //    get
        //    {
        //        return _contractorState;
        //    }

        //    set
        //    {
        //        _contractorState = value;
        //    }
        //}

        //public string ContractorZip
        //{
        //    get
        //    {
        //        return _contractorZip;
        //    }

        //    set
        //    {
        //        _contractorZip = value;
        //    }
        //}

        //public string ContractorCountry
        //{
        //    get
        //    {
        //        return _contractorCountry;
        //    }

        //    set
        //    {
        //        _contractorCountry = value;
        //    }
        //}

        //public string ArchitectName
        //{
        //    get
        //    {
        //        return _architectName;
        //    }

        //    set
        //    {
        //        _architectName = value;
        //    }
        //}

        //public string FacilityOwnerName
        //{
        //    get
        //    {
        //        return _facilityOwnerName;
        //    }

        //    set
        //    {
        //        _facilityOwnerName = value;
        //    }
        //}

        //public string EngineerName
        //{
        //    get
        //    {
        //        return _engineerName;
        //    }

        //    set
        //    {
        //        _engineerName = value;
        //    }
        //}

        //public string EngineerEmail
        //{
        //    get
        //    {
        //        return _engineerEmail;
        //    }

        //    set
        //    {
        //        _engineerEmail = value;
        //    }
        //}

        //public string TeamLeaderName
        //{
        //    get
        //    {
        //        return _teamLeaderName;
        //    }

        //    set
        //    {
        //        _teamLeaderName = value;
        //    }
        //}

        //public string TeamLeaderEmail
        //{
        //    get
        //    {
        //        return _teamLeaderEmail;
        //    }

        //    set
        //    {
        //        _teamLeaderEmail = value;
        //    }
        //}

        //public int? TeamLeader2Id
        //{
        //    get
        //    {
        //        return _teamLeader2Id;
        //    }

        //    set
        //    {
        //        _teamLeader2Id = value;
        //    }
        //}

        //public string TeamLeader2Name
        //{
        //    get
        //    {
        //        return _teamLeader2Name;
        //    }

        //    set
        //    {
        //        _teamLeader2Name = value;
        //    }
        //}

        //public string TeamLeader3Name
        //{
        //    get
        //    {
        //        return _teamLeader3Name;
        //    }

        //    set
        //    {
        //        _teamLeader3Name = value;
        //    }
        //}

        //public string TeamLeader3Email
        //{
        //    get
        //    {
        //        return _teamLeader3Email;
        //    }

        //    set
        //    {
        //        _teamLeader3Email = value;
        //    }
        //}

        //public string ApproverName
        //{
        //    get
        //    {
        //        return _approverName;
        //    }

        //    set
        //    {
        //        _approverName = value;
        //    }
        //}

        //public string FollowUpPersonName
        //{
        //    get
        //    {
        //        return _followUpPersonName;
        //    }

        //    set
        //    {
        //        _followUpPersonName = value;
        //    }
        //}

        //public string DetailReviewerName
        //{
        //    get
        //    {
        //        return _detailReviewerName;
        //    }

        //    set
        //    {
        //        _detailReviewerName = value;
        //    }
        //}

        //public string DetailReviewerEmail
        //{
        //    get
        //    {
        //        return _detailReviewerEmail;
        //    }

        //    set
        //    {
        //        _detailReviewerEmail = value;
        //    }
        //}

        //public string Designer
        //{
        //    get
        //    {
        //        return _designer;
        //    }

        //    set
        //    {
        //        _designer = value;
        //    }
        //}

        //public string JobsiteName
        //{
        //    get
        //    {
        //        return _jobsiteName;
        //    }

        //    set
        //    {
        //        _jobsiteName = value;
        //    }
        //}

        //public string JobsiteAddress1
        //{
        //    get
        //    {
        //        return _jobsiteAddress1;
        //    }

        //    set
        //    {
        //        _jobsiteAddress1 = value;
        //    }
        //}

        //public string JobsiteAddress2
        //{
        //    get
        //    {
        //        return _jobsiteAddress2;
        //    }

        //    set
        //    {
        //        _jobsiteAddress2 = value;
        //    }
        //}

        //public string JobsiteAddress3
        //{
        //    get
        //    {
        //        return _jobsiteAddress3;
        //    }

        //    set
        //    {
        //        _jobsiteAddress3 = value;
        //    }
        //}

        //public string JobsiteCity
        //{
        //    get
        //    {
        //        return _jobsiteCity;
        //    }

        //    set
        //    {
        //        _jobsiteCity = value;
        //    }
        //}

        //public string JobsiteState
        //{
        //    get
        //    {
        //        return _jobsiteState;
        //    }

        //    set
        //    {
        //        _jobsiteState = value;
        //    }
        //}

        //public string JobsiteZip
        //{
        //    get
        //    {
        //        return _jobsiteZip;
        //    }

        //    set
        //    {
        //        _jobsiteZip = value;
        //    }
        //}

        //public string JobsiteCountry
        //{
        //    get
        //    {
        //        return _jobsiteCountry;
        //    }

        //    set
        //    {
        //        _jobsiteCountry = value;
        //    }
        //}

        //public string JobsitePhone
        //{
        //    get
        //    {
        //        return _jobsitePhone;
        //    }

        //    set
        //    {
        //        _jobsitePhone = value;
        //    }
        //}

        //public string JobsiteFax
        //{
        //    get
        //    {
        //        return _jobsiteFax;
        //    }

        //    set
        //    {
        //        _jobsiteFax = value;
        //    }
        //}

        //public string JobsiteCell
        //{
        //    get
        //    {
        //        return _jobsiteCell;
        //    }

        //    set
        //    {
        //        _jobsiteCell = value;
        //    }
        //}

        //public string JobsiteEmail
        //{
        //    get
        //    {
        //        return _jobsiteEmail;
        //    }

        //    set
        //    {
        //        _jobsiteEmail = value;
        //    }
        //}

        //public string JobsiteContact
        //{
        //    get
        //    {
        //        return _jobsiteContact;
        //    }

        //    set
        //    {
        //        _jobsiteContact = value;
        //    }
        //}

        //public string JobsiteNotes
        //{
        //    get
        //    {
        //        return _jobsiteNotes;
        //    }

        //    set
        //    {
        //        _jobsiteNotes = value;
        //    }
        //}

        //public string ShopName
        //{
        //    get
        //    {
        //        return _shopName;
        //    }

        //    set
        //    {
        //        _shopName = value;
        //    }
        //}

        //public string ShopAddress1
        //{
        //    get
        //    {
        //        return _shopAddress1;
        //    }

        //    set
        //    {
        //        _shopAddress1 = value;
        //    }
        //}

        //public string ShopAddress2
        //{
        //    get
        //    {
        //        return _shopAddress2;
        //    }

        //    set
        //    {
        //        _shopAddress2 = value;
        //    }
        //}

        //public string ShopAddress3
        //{
        //    get
        //    {
        //        return _shopAddress3;
        //    }

        //    set
        //    {
        //        _shopAddress3 = value;
        //    }
        //}

        //public string ShopCity
        //{
        //    get
        //    {
        //        return _shopCity;
        //    }

        //    set
        //    {
        //        _shopCity = value;
        //    }
        //}

        //public string ShopState
        //{
        //    get
        //    {
        //        return _shopState;
        //    }

        //    set
        //    {
        //        _shopState = value;
        //    }
        //}

        //public string ShopZip
        //{
        //    get
        //    {
        //        return _shopZip;
        //    }

        //    set
        //    {
        //        _shopZip = value;
        //    }
        //}

        //public string ShopCountry
        //{
        //    get
        //    {
        //        return _shopCountry;
        //    }

        //    set
        //    {
        //        _shopCountry = value;
        //    }
        //}

        //public string SalePersonName
        //{
        //    get
        //    {
        //        return _salePersonName;
        //    }

        //    set
        //    {
        //        _salePersonName = value;
        //    }
        //}

        //public string StartDate
        //{
        //    get
        //    {
        //        return _startDate;
        //    }

        //    set
        //    {
        //        _startDate = value;
        //    }
        //}

        //public string CompleteDate
        //{
        //    get
        //    {
        //        return _completeDate;
        //    }

        //    set
        //    {
        //        _completeDate = value;
        //    }
        //}

        //public string DueDate
        //{
        //    get
        //    {
        //        return _dueDate;
        //    }

        //    set
        //    {
        //        _dueDate = value;
        //    }
        //}

        //public string ContractDate
        //{
        //    get
        //    {
        //        return _contractDate;
        //    }

        //    set
        //    {
        //        _contractDate = value;
        //    }
        //}

        //public string ContractNumber
        //{
        //    get
        //    {
        //        return _contractNumber;
        //    }

        //    set
        //    {
        //        _contractNumber = value;
        //    }
        //}

        //public string MeasurementSystemCode
        //{
        //    get
        //    {
        //        return _measurementSystemCode;
        //    }

        //    set
        //    {
        //        _measurementSystemCode = value;
        //    }
        //}

        //public string JobSiteSuper
        //{
        //    get
        //    {
        //        return _jobSiteSuper;
        //    }

        //    set
        //    {
        //        _jobSiteSuper = value;
        //    }
        //}

        //public string JobSiteForeman
        //{
        //    get
        //    {
        //        return _jobSiteForeman;
        //    }

        //    set
        //    {
        //        _jobSiteForeman = value;
        //    }
        //}

        //public string ProjectNotes
        //{
        //    get
        //    {
        //        return _projectNotes;
        //    }

        //    set
        //    {
        //        _projectNotes = value;
        //    }
        //}

        //public string JobNumber
        //{
        //    get
        //    {
        //        return _jobNumber;
        //    }

        //    set
        //    {
        //        _jobNumber = value;
        //    }
        //}

        //public string FinishHdwBy
        //{
        //    get
        //    {
        //        return _finishHdwBy;
        //    }

        //    set
        //    {
        //        _finishHdwBy = value;
        //    }
        //}

        //public string EstimateNumber
        //{
        //    get
        //    {
        //        return _estimateNumber;
        //    }

        //    set
        //    {
        //        _estimateNumber = value;
        //    }
        //}

        //public string ScheduleNotes
        //{
        //    get
        //    {
        //        return _scheduleNotes;
        //    }

        //    set
        //    {
        //        _scheduleNotes = value;
        //    }
        //}

        //public string MaterialScheduleNotes
        //{
        //    get
        //    {
        //        return _materialScheduleNotes;
        //    }

        //    set
        //    {
        //        _materialScheduleNotes = value;
        //    }
        //}

        //public string KeyingNotes
        //{
        //    get
        //    {
        //        return _keyingNotes;
        //    }

        //    set
        //    {
        //        _keyingNotes = value;
        //    }
        //}

        //public decimal? LaborRate
        //{
        //    get
        //    {
        //        return _laborRate;
        //    }

        //    set
        //    {
        //        _laborRate = value;
        //    }
        //}

        //public decimal? InstallationRate
        //{
        //    get
        //    {
        //        return _installationRate;
        //    }

        //    set
        //    {
        //        _installationRate = value;
        //    }
        //}

        //public string DodgeNum
        //{
        //    get
        //    {
        //        return _dodgeNum;
        //    }

        //    set
        //    {
        //        _dodgeNum = value;
        //    }
        //}

        //public string ArchitectsProjectNumber
        //{
        //    get
        //    {
        //        return _architectsProjectNumber;
        //    }

        //    set
        //    {
        //        _architectsProjectNumber = value;
        //    }
        //}

        //public string Notes
        //{
        //    get
        //    {
        //        return _notes;
        //    }

        //    set
        //    {
        //        _notes = value;
        //    }
        //}

        //public string BidDate
        //{
        //    get
        //    {
        //        return _bidDate;
        //    }

        //    set
        //    {
        //        _bidDate = value;
        //    }
        //}

        //public string BidRequestSource
        //{
        //    get
        //    {
        //        return _bidRequestSource;
        //    }

        //    set
        //    {
        //        _bidRequestSource = value;
        //    }
        //}

        //public string PlanLocation
        //{
        //    get
        //    {
        //        return _planLocation;
        //    }

        //    set
        //    {
        //        _planLocation = value;
        //    }
        //}

        //public string Uoc
        //{
        //    get
        //    {
        //        return _uoc;
        //    }

        //    set
        //    {
        //        _uoc = value;
        //    }
        //}

        //public string QuoteNum
        //{
        //    get
        //    {
        //        return _quoteNum;
        //    }

        //    set
        //    {
        //        _quoteNum = value;
        //    }
        //}

        //public decimal? TaxRate
        //{
        //    get
        //    {
        //        return _taxRate;
        //    }

        //    set
        //    {
        //        _taxRate = value;
        //    }
        //}

        //public string VerticalMarketSegmentCode
        //{
        //    get
        //    {
        //        return _verticalMarketSegmentCode;
        //    }

        //    set
        //    {
        //        _verticalMarketSegmentCode = value;
        //    }
        //}

        //public string OpeningHeightPlus
        //{
        //    get
        //    {
        //        return _openingHeightPlus;
        //    }

        //    set
        //    {
        //        _openingHeightPlus = value;
        //    }
        //}

        //public string CerpJobNumber
        //{
        //    get
        //    {
        //        return _cerpJobNumber;
        //    }

        //    set
        //    {
        //        _cerpJobNumber = value;
        //    }
        //}

        //public string ChangeOrderDetailLevel
        //{
        //    get
        //    {
        //        return _changeOrderDetailLevel;
        //    }

        //    set
        //    {
        //        _changeOrderDetailLevel = value;
        //    }
        //}

        //public bool? Fsc
        //{
        //    get
        //    {
        //        return _fsc;
        //    }

        //    set
        //    {
        //        _fsc = value;
        //    }
        //}

        //public string CertCode
        //{
        //    get
        //    {
        //        return _certCode;
        //    }

        //    set
        //    {
        //        _certCode = value;
        //    }
        //}

        //public string ProposalType
        //{
        //    get
        //    {
        //        return _proposalType;
        //    }

        //    set
        //    {
        //        _proposalType = value;
        //    }
        //}

        //public string SpecDivisionIncluded
        //{
        //    get
        //    {
        //        return _specDivisionIncluded;
        //    }

        //    set
        //    {
        //        _specDivisionIncluded = value;
        //    }
        //}

        //public string ArchitectDesignerRef
        //{
        //    get
        //    {
        //        return _architectDesignerRef;
        //    }

        //    set
        //    {
        //        _architectDesignerRef = value;
        //    }
        //}

        //public string FirstInviteReceived
        //{
        //    get
        //    {
        //        return _firstInviteReceived;
        //    }

        //    set
        //    {
        //        _firstInviteReceived = value;
        //    }
        //}

        //public string AllEstimatesCompleted
        //{
        //    get
        //    {
        //        return _allEstimatesCompleted;
        //    }

        //    set
        //    {
        //        _allEstimatesCompleted = value;
        //    }
        //}

        //public string LastEstimateSubmitted
        //{
        //    get
        //    {
        //        return _lastEstimateSubmitted;
        //    }

        //    set
        //    {
        //        _lastEstimateSubmitted = value;
        //    }
        //}

        //public string Followup
        //{
        //    get
        //    {
        //        return _followup;
        //    }

        //    set
        //    {
        //        _followup = value;
        //    }
        //}

        //public decimal? Bond
        //{
        //    get
        //    {
        //        return _bond;
        //    }

        //    set
        //    {
        //        _bond = value;
        //    }
        //}

        //public bool? Labor
        //{
        //    get
        //    {
        //        return _labor;
        //    }

        //    set
        //    {
        //        _labor = value;
        //    }
        //}

        //public int? NumberOfDeliveries
        //{
        //    get
        //    {
        //        return _numberOfDeliveries;
        //    }

        //    set
        //    {
        //        _numberOfDeliveries = value;
        //    }
        //}

        //public string DateSold
        //{
        //    get
        //    {
        //        return _dateSold;
        //    }

        //    set
        //    {
        //        _dateSold = value;
        //    }
        //}

        //public string AnticipatedDateToEng
        //{
        //    get
        //    {
        //        return _anticipatedDateToEng;
        //    }

        //    set
        //    {
        //        _anticipatedDateToEng = value;
        //    }
        //}

        //public string SubmittalReqDate
        //{
        //    get
        //    {
        //        return _submittalReqDate;
        //    }

        //    set
        //    {
        //        _submittalReqDate = value;
        //    }
        //}

        //public bool? ExpeditedMaterial
        //{
        //    get
        //    {
        //        return _expeditedMaterial;
        //    }

        //    set
        //    {
        //        _expeditedMaterial = value;
        //    }
        //}

        //public bool? HollowMetalFrames
        //{
        //    get
        //    {
        //        return _hollowMetalFrames;
        //    }

        //    set
        //    {
        //        _hollowMetalFrames = value;
        //    }
        //}

        //public string DateRequiredHmf
        //{
        //    get
        //    {
        //        return _dateRequiredHmf;
        //    }

        //    set
        //    {
        //        _dateRequiredHmf = value;
        //    }
        //}

        //public bool? HollowMetalDoors
        //{
        //    get
        //    {
        //        return _hollowMetalDoors;
        //    }

        //    set
        //    {
        //        _hollowMetalDoors = value;
        //    }
        //}

        //public string DateRequiredHmd
        //{
        //    get
        //    {
        //        return _dateRequiredHmd;
        //    }

        //    set
        //    {
        //        _dateRequiredHmd = value;
        //    }
        //}

        //public bool? WoodDoors
        //{
        //    get
        //    {
        //        return _woodDoors;
        //    }

        //    set
        //    {
        //        _woodDoors = value;
        //    }
        //}

        //public string DateRequiredWdd
        //{
        //    get
        //    {
        //        return _dateRequiredWdd;
        //    }

        //    set
        //    {
        //        _dateRequiredWdd = value;
        //    }
        //}

        //public string LeedRequirements
        //{
        //    get
        //    {
        //        return _leedRequirements;
        //    }

        //    set
        //    {
        //        _leedRequirements = value;
        //    }
        //}

        //public string TempConstructionCores
        //{
        //    get
        //    {
        //        return _tempConstructionCores;
        //    }

        //    set
        //    {
        //        _tempConstructionCores = value;
        //    }
        //}

        //public decimal? Surcharge
        //{
        //    get
        //    {
        //        return _surcharge;
        //    }

        //    set
        //    {
        //        _surcharge = value;
        //    }
        //}

        //public int? ProposalContact
        //{
        //    get
        //    {
        //        return _proposalContact;
        //    }

        //    set
        //    {
        //        _proposalContact = value;
        //    }
        //}

        //public string PlansDated
        //{
        //    get
        //    {
        //        return _plansDated;
        //    }

        //    set
        //    {
        //        _plansDated = value;
        //    }
        //}

        //public string SpecificationsDated
        //{
        //    get
        //    {
        //        return _specificationsDated;
        //    }

        //    set
        //    {
        //        _specificationsDated = value;
        //    }
        //}

        //public string AddendumIncluded
        //{
        //    get
        //    {
        //        return _addendumIncluded;
        //    }

        //    set
        //    {
        //        _addendumIncluded = value;
        //    }
        //}

        //public string CreatedByName
        //{
        //    get
        //    {
        //        return _createdByName;
        //    }

        //    set
        //    {
        //        _createdByName = value;
        //    }
        //}

        //public string CreatedTime
        //{
        //    get
        //    {
        //        return _createdTime;
        //    }

        //    set
        //    {
        //        _createdTime = value;
        //    }
        //}

        //public int? ChangeOrderCount
        //{
        //    get
        //    {
        //        return _changeOrderCount;
        //    }

        //    set
        //    {
        //        _changeOrderCount = value;
        //    }
        //}

        //public int? EstimateCount
        //{
        //    get
        //    {
        //        return _estimateCount;
        //    }

        //    set
        //    {
        //        _estimateCount = value;
        //    }
        //}

        //public bool? FinalEstimate
        //{
        //    get
        //    {
        //        return _finalEstimate;
        //    }

        //    set
        //    {
        //        _finalEstimate = value;
        //    }
        //}

        //public bool? FinalEstimateCommitted
        //{
        //    get
        //    {
        //        return _finalEstimateCommitted;
        //    }

        //    set
        //    {
        //        _finalEstimateCommitted = value;
        //    }
        //}
    }


}
