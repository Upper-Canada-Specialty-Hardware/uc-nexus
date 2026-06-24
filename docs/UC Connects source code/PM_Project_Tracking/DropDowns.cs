using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using dc = PM_Project_Tracking.DataClasses;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using System.Windows;
using System.Collections.ObjectModel;
using System.Windows.Markup;

namespace PM_Project_Tracking
{
    #region Quote Summary drop downs
    public class QuoteSummaryJobList : List<KeyValuePair<string, string>>
    {
        public QuoteSummaryJobList()
        {
           this.AddRange(dc.QuoteSummaries.GetUniqueJobList());
        }
    }

    //public class QuoteSummaryJobQuoteList : List<dc.QuoteSummary>
    //{
    //    public QuoteSummaryJobQuoteList()
    //    {
    //        this.AddRange(dc.QuoteSummaries.GetQuotesByJob("33333"));
    //    }
    //    public QuoteSummaryJobQuoteList(string jobNumber)
    //    {
    //        this.AddRange(dc.QuoteSummaries.GetQuotesByJob(jobNumber));
    //    }
    //}

    public class QuoteSummaryInstDrop :  Dictionary<dc.QsInstaller, string>
    {
        public QuoteSummaryInstDrop()
        {
            this.Add(dc.QsInstaller.None, "None");
            this.Add(dc.QsInstaller.UCI, "UCI");
            this.Add(dc.QsInstaller.UCA, "UCA");
            this.Add(dc.QsInstaller.ThirdParty, "Third Party");
        }
    }



#endregion

#region pursuits drop downs


public class PursuitStatusActPend : List<string>
    {
        public PursuitStatusActPend()
        {
            this.Add("PENDING");
            this.Add("ACTIVE");
        }
    }


    public class PursuitTenderPhase : List<string>
    {
        public PursuitTenderPhase()
        {
            this.Add("BIDDING");
            this.Add("CONSULTING");
        }
    }

    public class PursuitBranch : List<string>
    {
        public PursuitBranch()
        {
            this.Add("BARRIE");
            this.Add("BRENTCLIFF");
            this.Add("MARKHAM");
            this.Add("OTTAWA");
            this.Add("VANCOUVER");
            this.Add("VICTORIA PARK");
        }
    }


    public class PursuitFacilityType : List<string>
    {
        public PursuitFacilityType()
        {
            this.Add("ALLOWANCE");
            this.Add("AFFORDABLE HOUSING");
            this.Add("AIRPORT");
            this.Add("CASINO");
            this.Add("CHURCH");
            this.Add("CEMETERY");
            this.Add("CONDO");
            this.Add("COURTHOUSE");
            this.Add("DETENTION");
            this.Add("FUNERAL HOME");
            this.Add("GOVERNMENT");
            this.Add("HOSPITAL");
            this.Add("HOTEL");
            this.Add("MIXED");
            this.Add("OFFICE BUILDING");
            this.Add("OTHER");
            this.Add("POT HOUSE");
            this.Add("RESIDENTIAL");
            this.Add("RETAIL");
            this.Add("SCHOOL");
            this.Add("WAREHOUSE");
            this.Add("WATER TREATMENT");
        }
    }

    public class PursuitNewOrReno : List<string>
    {
        public PursuitNewOrReno()
        {
            this.Add("NEW");
            this.Add("RENO");
        }
    }

    public class PursuitFundingType : List<string>  
    {
        public PursuitFundingType()
        {
            this.Add("CONSTRUCTION MANAGEMENT");
            this.Add("GENERAL TENDER");
            this.Add("P3");
        }
    }

    public class PursuitPriority : List<string>
    {
        public PursuitPriority()
        {
            this.Add("1");
            this.Add("2");
            this.Add("3");
        }
    }

    #endregion
    public class OfferToTenderStatusList : List<string>
    {
        public OfferToTenderStatusList()
        {
            this.Add("NOT BIDDING");
            this.Add("PENDING");
        }
    }

    public class BidProjectStatusList : List<string>
    {
        public BidProjectStatusList()
        {
            //this.Add("OFFER TO TENDER");
            this.Add("CONSULTING");
            this.Add("PIPELINE");
            this.Add("BIDDING");
            this.Add("AWARDED");
            this.Add("RTLORD");
            //this.Add("NOT BIDDING");
            this.Add("LOST");
            this.Add("NOT SUBMITTED");
        }
    }

    public class BidProjectDivisionList : List<string>
    {
        public BidProjectDivisionList()
        {
            this.Add("MARKHAM");
            this.Add("OTTAWA");
            this.Add("VANCOUVER");
        }
    }

    public class BidProjectTypeList : List<string>
    {
        public BidProjectTypeList()
        {
            this.Add("HEALTHCARE");
            this.Add("EDUCATION");
            this.Add("GOVERNMENT");
            this.Add("MULTI-FAMILY");
            this.Add("OFFICE");
            this.Add("INFRASTRUCTURE");
            this.Add("SPECIALTY");
        }
    }

    public class ContractStatusList : List<string>
    {
        public ContractStatusList()
        {
            //this.Add("");
            this.Add("SIGNED TO CONTRACTOR");
            this.Add("COMPLETED AND FILED");
        }
    }

    public class NoYesPendingList : List<string> //Pre-Mob Status - WSIB Clearance - Cert of Insurance
    {
        public NoYesPendingList()
        {
            this.Add("NO");
            this.Add("YES");
            this.Add("PENDING");
        }
    }

    public class OneTwoThreeNa : List<string> //MainProject - Hardware, DoorsAndFrames, UCA
    {
        public OneTwoThreeNa()
        {
            this.Add("1");
            this.Add("2");
            this.Add("3");
            this.Add("N/A");
        }
    }

    public class TrueFalse : List<string>
    {
        public TrueFalse()
        {
            this.Add("YES");
            this.Add("NO");
        }
    }

    public class PermissionTier : List<string>
    {
        public PermissionTier()
        {
            this.Add("Administrator");
            this.Add("Curator");
            this.Add("Project Manager");
            this.Add("Project Coordinator");
            this.Add("Hardware Coordinator");
            this.Add("Undefined");
        }
    }

    public class CompanyId : List<int>
    {
        public CompanyId()
        {
            this.Add(1);
            this.Add(2);
        }
    }

    public class CurrentDb : List<string>
    {
        public CurrentDb()
        {
            this.Add("PMUCSH");
            this.Add("UBC");
            this.Add("TESTPMUCSH");
        }
    }

    internal class SopLineStatus : List<string>
    {
        public SopLineStatus()
        {
            this.Add("SHIPPED OUT - CARRIER");
            this.Add("RETURNED");
            this.Add("HOLD");
            this.Add("READY FOR PICKUP");
            this.Add("TAKEN - PICKED UP");
            this.Add("CUSTOMER CALLED");
        }
    }

    public class UserCompleteList : ObservableCollection<dc.User>
    {
        public UserCompleteList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<dc.User> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<dc.User>().Select(x => x).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                System.Diagnostics.Debug.Print(this.Items.Count.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            //Obvervablecollection doesn't support .AddRange method but I fanatically wanted to keep this to one line.  Voila: (see below)
            viewsList.ForEach(delegate (dc.User x) { this.Add(x); });
        }
    }

    public class HardwareSchedWriterList : ObservableCollection<dc.User>
    {
        public HardwareSchedWriterList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<dc.User> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<dc.UserRole>().AsEnumerable().Where(r => r.RoleId == 2)
                    .Select(x => new dc.User() { Id = x.UserId, DomainUserName = x.DomainUserName, Email = x.Email } ).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                System.Diagnostics.Debug.Print(this.Items.Count.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            //Obvervablecollection doesn't support .AddRange method but I fanatically wanted to keep this to one line.  Voila: (see below)
            viewsList.ForEach(delegate (dc.User x) { this.Add(x); });
        }
    }

    public class AvawareTeamList : ObservableCollection<dc.User>
    {
        public AvawareTeamList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<dc.User> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<dc.UserRole>().AsEnumerable().Where(r => r.RoleId == 1)
                    .Select(x => new dc.User() { DomainUserName = x.DomainUserName, Id = x.UserId, Email = x.Email }).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                System.Diagnostics.Debug.Print(this.Items.Count.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            //Obvervablecollection doesn't support .AddRange method but I fanatically wanted to keep this to one line.  Voila: (see below)
            viewsList.ForEach(delegate (dc.User x) { this.Add(x); });
        }
    }

    public class ProjectCoordinatorList : List<string>
    {
        public ProjectCoordinatorList()
        {
            
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<string> viewsList = null;

            try
            {
                if (GlobalVars.CurrentPmDatabaseName == "PMUCSH")
                {
                    viewsList = dtCtx.GetTable<dc.User>().Where(r => (r.PermissionTier == 5 || r.PermissionTier == 4 || r.PermissionTier == 3) && r.IsActive == true && r.CompanyId == 1)
                                                        .Select(x => x.DomainUserName).Distinct().ToList();
                }
                else if (GlobalVars.CurrentPmDatabaseName == "PMUBC")
                {
                    viewsList = dtCtx.GetTable<dc.User>().Where(r => (r.PermissionTier == 5 || r.PermissionTier == 4 || r.PermissionTier == 3) && r.IsActive == true && r.CompanyId == 2)
                                                        .Select(x => x.DomainUserName).Distinct().ToList();
                }

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                this.AddRange(new List<string>());
            }
            finally
            {
                dtCtx.Dispose();
            }

            this.AddRange(viewsList);
        }
    }
    public class HardwareCoordinatorList : List<string>
    {
        public HardwareCoordinatorList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<string> viewsList = null;

            try
            {
                //viewsList = dtCtx.GetTable<dc.User>().Where(r => r.PermissionTier == 6).Select(x => x.DomainUserName).Distinct().ToList();
                viewsList = dtCtx.GetTable<dc.User>().Where(r => (r.PermissionTier == 6 || r.PermissionTier == 3) && r.IsActive == true).Select(x => x.DomainUserName).Union(
                            dtCtx.GetTable<dc.UserRole>().Where(k => k.RoleId == 3).Select(n => n.DomainUserName)).Distinct().ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                this.AddRange(new List<string>());
            }
            finally
            {
                dtCtx.Dispose();
            }

            this.AddRange(viewsList);
        }
    }

    public enum WarehouseReceiptType
    {
        PurchaseOrder = 1,
        RetailOrder,
        Unusual,
        Showroom
    }
}
