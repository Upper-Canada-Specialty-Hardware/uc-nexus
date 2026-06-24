using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.ComponentModel;
using System.Collections.ObjectModel;
using System.Data.SqlClient;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using pm = PM_Project_Tracking.ProjectManagementClasses;

namespace PM_Project_Tracking.DataClasses
{
    public static class MainProjects
    {
        public static ObservableCollection<CombinedProject> GetCombinedProject()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<CombinedProject> combinedProjList = null;

            //var lskdjf = dtCtx.GetTable<gp.Jc00102>().ToList();

            try
            {
                var mainProjQuery = from proj in dtCtx.GetTable<MainProject>()
                                    join ac in dtCtx.GetTable<AwardedContract>() on proj.JobNumber equals ac.JobNumber
                                    join jc in dtCtx.GetTable<gp.Jc00102>() on proj.JobNumber equals jc.JobNumber
                                    join rm in dtCtx.GetTable<gp.Rm00101>() on jc.CustomerNumber equals rm.CustomerNumber
                                    join js in dtCtx.GetTable<gp.Jc00901>() on proj.JobNumber equals js.JobNumber
                                    //join ch in dtCtx.GetTable<pm.ChangeHeader>() on proj.JobNumber equals ch.JobNumber
                                    //join costs in dtCtx.GetTable<gp.Jc20001>() on proj.JobNumber equals
                                    //where js.Inactive == 0 //&& proj.JobNumber == "21369"
                                    //where proj.JobNumber == "22179"
                                    //where proj.JobNumber == "22404"
                                    orderby proj.JobNumber descending
                                    select new
                                    {
                                        JobNumber = proj.JobNumber,
                                        JobName = jc.JobName.Trim(),
                                        Division = jc.Division.Trim(),
                                        Consultant = jc.Consultant.Trim(),
                                        ProjectManager = jc.ProjectManager.Trim(),
                                        ProjectCoordinator = proj.ProjectCoordinator == null ? "" : proj.ProjectCoordinator,
                                        HardwareCoordinator = proj.HardwareCoordinator == null ? "" : proj.HardwareCoordinator,
                                        IsUca = proj.IsUca,
                                        OffsiteStorageAgreement = proj.OffsiteStorageAgreement,
                                        SubstantialCompletionDate = proj.SubstantialCompletionDate,
                                        //CustomerNumber = jc.CustomerNumber.Trim(),
                                        CustomerName = rm.CustomerName.Trim(),
                                        ProjectStatus = proj.ProjectStatus,
                                        DateModified = proj.DateModified,
                                        EstStartDate = proj.EstStartDate,
                                        EstEndDate = proj.EstEndDate,
                                        TotalProjectValue = jc.ProjectValue,
                                        BilledToDate = jc.BilledToDate,
                                        TotalActualCost = jc.TotalActualCost,
                                        TotalCostToDate = dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD) == null ? 0 :
                                                            dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD),

                                        TotalQuoteValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber 
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice 
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100)) 
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()
                                                                                                                                            
                                                                                                                                            ?? 0,

                                       TotalQuotesApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                        TotalQuotesTentApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.TentativeApproval == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                        TotalQuotesNotApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                        //private decimal totalQuotesValue;
                                        //private decimal totalQuotesApprovedValue;
                                        //private decimal totalQuotesTentApprovedValue;
                                        //private decimal totalQuotesNotApprovedValue;

                                        ContractStatus = ac.ContractStatus,
                                        PreMobStatus = ac.PreMobStatus,
                                        SupplyCompletionPer = proj.SupplyCompletion,
                                        Hardware = proj.Hardware,
                                        DoorsAndFrames = proj.DoorsAndFrames,
                                        UcAccess = proj.UcAccess,
                                        PickeringInstall = proj.PickeringInstall,
                                        PickeringInstallPer = proj.PickeringInstallPer,
                                        SiteInstall = proj.SiteInstall,
                                        SiteInstallPer = proj.SiteInstallPer,
                                        ChangeOrders = proj.ChangeOrders,
                                        ChangeOrderComments = proj.ChangeOrderComments,
                                        PmComments = proj.PmComments,
                                        CreationDate = jc.CreationDate,
                                        //UnifiedAddress = proj.City.Trim() + " " + proj.Province.Trim() + " " + proj.PostalCode.Trim(),
                                    };

                combinedProjList = mainProjQuery.AsEnumerable().Select(x => new CombinedProject(x.JobNumber,
                                                                                                x.ProjectManager,
                                                                                                x.ProjectCoordinator,
                                                                                                x.HardwareCoordinator,
                                                                                                x.IsUca,
                                                                                                x.OffsiteStorageAgreement,
                                                                                                x.SubstantialCompletionDate,
                                                                                                x.ProjectStatus,
                                                                                                x.DateModified,
                                                                                                x.EstStartDate,
                                                                                                x.EstEndDate,
                                                                                                x.SupplyCompletionPer,
                                                                                                x.Hardware, x.DoorsAndFrames, x.UcAccess,
                                                                                                x.PickeringInstall,
                                                                                                x.PickeringInstallPer,
                                                                                                x.SiteInstall,
                                                                                                x.SiteInstallPer, x.PmComments,
                                                                                                x.ChangeOrders,
                                                                                                x.ChangeOrderComments,
                                                                                                x.JobName, x.Division, x.Consultant, x.TotalProjectValue, x.BilledToDate,
                                                                                                x.TotalActualCost,
                                                                                                x.TotalCostToDate,
                                                                                                x.ContractStatus, x.PreMobStatus,
                                                                                                x.CustomerName,
                                                                                                x.CreationDate,
                                                                                                x.TotalQuoteValue,
                                                                                                x.TotalQuotesApprovedValue,
                                                                                                x.TotalQuotesTentApprovedValue,
                                                                                                x.TotalQuotesNotApprovedValue)).ToList();

                if (combinedProjList.Count == 0) { return new ObservableCollection<CombinedProject>(); }

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
                if (combinedProjList.Count == 0)
                    MessageBox.Show("Main projects returned no entries from the database.");
            }
            return new ObservableCollection<CombinedProject>(combinedProjList);
        }

        public static ObservableCollection<CombinedProject> GetLimitedUsers(User user)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<CombinedProject> combinedProjList = null;

            //I know this huge set of 3 blocks for project managers, project coordinators and hardware coordinators is ugly but I'm sick of project management having no clue how
            //their own project delegation works, so this will have to do less I build yet another system that doesn't work they way they wanted to because they didn't think it
            //through when explaining what they wanted
            if (user.PermissionTier == 4)
            {
                try
                {
                    var mainProjQuery = from proj in dtCtx.GetTable<MainProject>()
                                        join ac in dtCtx.GetTable<AwardedContract>() on proj.JobNumber equals ac.JobNumber
                                        join jc in dtCtx.GetTable<gp.Jc00102>() on proj.JobNumber equals jc.JobNumber
                                        join rm in dtCtx.GetTable<gp.Rm00101>() on jc.CustomerNumber equals rm.CustomerNumber
                                        join js in dtCtx.GetTable<gp.Jc00901>() on proj.JobNumber equals js.JobNumber
                                        //where jc.JobNumber == "20037"
                                        //where js.Inactive == 0 && jc.ProjectManager == user.GpEstimatorId
                                        where user.PermissionTier > 3 ? ((user.GpEstimators.Contains(jc.Consultant) || user.WsManagers.Contains(jc.ProjectManager)) && js.Inactive == 0) : false
                                        select new
                                        {
                                            JobNumber = proj.JobNumber,
                                            JobName = jc.JobName.Trim(),
                                            Division = jc.Division.Trim(),
                                            Consultant = jc.Consultant.Trim(),
                                            ProjectManager = jc.ProjectManager.Trim(),
                                            ProjectCoordinator = proj.ProjectCoordinator == null ? "" : proj.ProjectCoordinator,
                                            HardwareCoordinator = proj.HardwareCoordinator == null ? "" : proj.HardwareCoordinator,
                                            IsUca = proj.IsUca,
                                            OffsiteStorageAgreement = proj.OffsiteStorageAgreement,
                                            SubstantialCompletionDate = proj.SubstantialCompletionDate,
                                            //CustomerNumber = jc.CustomerNumber.Trim(),
                                            CustomerName = rm.CustomerName.Trim(),
                                            ProjectStatus = proj.ProjectStatus,
                                            DateModified = proj.DateModified,
                                            EstStartDate = proj.EstStartDate,
                                            EstEndDate = proj.EstEndDate,
                                            TotalProjectValue = jc.ProjectValue,
                                            BilledToDate = jc.BilledToDate,
                                            TotalActualCost = jc.TotalActualCost,
                                            TotalCostToDate = dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD) == null ? 0 :
                                                            dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD),

                                            TotalQuoteValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesTentApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.TentativeApproval == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesNotApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,
                                            ContractStatus = ac.ContractStatus,
                                            PreMobStatus = ac.PreMobStatus,
                                            SupplyCompletionPer = proj.SupplyCompletion,
                                            Hardware = proj.Hardware,
                                            DoorsAndFrames = proj.DoorsAndFrames,
                                            UcAccess = proj.UcAccess,
                                            PickeringInstall = proj.PickeringInstall,
                                            PickeringInstallPer = proj.PickeringInstallPer,
                                            SiteInstall = proj.SiteInstall,
                                            SiteInstallPer = proj.SiteInstallPer,
                                            ChangeOrders = proj.ChangeOrders,
                                            ChangeOrderComments = proj.ChangeOrderComments,
                                            PmComments = proj.PmComments,
                                            CreationDate = jc.CreationDate
                                            //UnifiedAddress = proj.City.Trim() + " " + proj.Province.Trim() + " " + proj.PostalCode.Trim(),
                                        };

                    combinedProjList = mainProjQuery.AsEnumerable().Select(x => new CombinedProject(x.JobNumber, x.ProjectManager, x.ProjectCoordinator, x.HardwareCoordinator, 
                                                                                                    x.IsUca,
                                                                                                    x.OffsiteStorageAgreement,
                                                                                                    x.SubstantialCompletionDate,
                                                                                                    x.ProjectStatus, 
                                                                                                    x.DateModified,
                                                                                                    x.EstStartDate, x.EstEndDate,
                                                                                                    x.SupplyCompletionPer,
                                                                                                    x.Hardware, x.DoorsAndFrames, x.UcAccess,
                                                                                                    x.PickeringInstall,
                                                                                                    x.PickeringInstallPer,
                                                                                                    x.SiteInstall,
                                                                                                    x.SiteInstallPer,
                                                                                                    x.PmComments,
                                                                                                    x.ChangeOrders,
                                                                                                    x.ChangeOrderComments,
                                                                                                    x.JobName, x.Division, x.Consultant, x.TotalProjectValue, x.BilledToDate,
                                                                                                    x.TotalActualCost,
                                                                                                    x.TotalCostToDate,
                                                                                                    x.ContractStatus, x.PreMobStatus,
                                                                                                    x.CustomerName,
                                                                                                    x.CreationDate,
                                                                                                    x.TotalQuoteValue,
                                                                                                    x.TotalQuotesApprovedValue,
                                                                                                    x.TotalQuotesTentApprovedValue,
                                                                                                    x.TotalQuotesNotApprovedValue)).ToList();

                    if (combinedProjList.Count == 0) { return new ObservableCollection<CombinedProject>(); }

                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
                finally
                {
                    dtCtx.Dispose();
                    //if (combinedProjList.Count == 0)
                    //    MessageBox.Show("There were no projects associated with " + user.DomainUserName + " using the GP project manager ID '" + user.GpEstimatorId + "' found in the GP database");
                }
                return new ObservableCollection<CombinedProject>(combinedProjList);
            }
            else if (user.PermissionTier == 5)
            {
                try
                {
                    var mainProjQuery = from proj in dtCtx.GetTable<MainProject>()
                                        join ac in dtCtx.GetTable<AwardedContract>() on proj.JobNumber equals ac.JobNumber
                                        join jc in dtCtx.GetTable<gp.Jc00102>() on proj.JobNumber equals jc.JobNumber
                                        join rm in dtCtx.GetTable<gp.Rm00101>() on jc.CustomerNumber equals rm.CustomerNumber
                                        join js in dtCtx.GetTable<gp.Jc00901>() on proj.JobNumber equals js.JobNumber
                                        //where jc.JobNumber == "20037"
                                        //where js.Inactive == 0 && jc.ProjectManager == user.GpEstimatorId
                                        where user.PermissionTier > 3 ? ((proj.ProjectCoordinator == user.DomainUserName || user.WsManagers.Contains(jc.ProjectManager)) && js.Inactive == 0) : false
                                        select new
                                        {
                                            JobNumber = proj.JobNumber,
                                            JobName = jc.JobName.Trim(),
                                            Division = jc.Division.Trim(),
                                            Consultant = jc.Consultant.Trim(),
                                            ProjectManager = jc.ProjectManager.Trim(),
                                            ProjectCoordinator = proj.ProjectCoordinator == null ? "" : proj.ProjectCoordinator,
                                            HardwareCoordinator = proj.HardwareCoordinator == null ? "" : proj.HardwareCoordinator,
                                            IsUca = proj.IsUca,
                                            OffsiteStorageAgreement = proj.OffsiteStorageAgreement,
                                            SubstantialCompletionDate = proj.SubstantialCompletionDate,
                                            //CustomerNumber = jc.CustomerNumber.Trim(),
                                            CustomerName = rm.CustomerName.Trim(),
                                            ProjectStatus = proj.ProjectStatus,
                                            DateModified = proj.DateModified,
                                            EstStartDate = proj.EstStartDate,
                                            EstEndDate = proj.EstEndDate,
                                            TotalProjectValue = jc.ProjectValue,
                                            BilledToDate = jc.BilledToDate,
                                            TotalActualCost = jc.TotalActualCost,
                                            TotalCostToDate = dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD) == null ? 0 :
                                                            dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD),

                                            TotalQuoteValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesTentApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.TentativeApproval == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesNotApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,
                                            ContractStatus = ac.ContractStatus,
                                            PreMobStatus = ac.PreMobStatus,
                                            SupplyCompletionPer = proj.SupplyCompletion,
                                            Hardware = proj.Hardware,
                                            DoorsAndFrames = proj.DoorsAndFrames,
                                            UcAccess = proj.UcAccess,
                                            PickeringInstall = proj.PickeringInstall,
                                            PickeringInstallPer = proj.PickeringInstallPer,
                                            SiteInstall = proj.SiteInstall,
                                            SiteInstallPer = proj.SiteInstallPer,
                                            ChangeOrders = proj.ChangeOrders,
                                            ChangeOrderComments = proj.ChangeOrderComments,
                                            PmComments = proj.PmComments,
                                            CreationDate = jc.CreationDate
                                            //UnifiedAddress = proj.City.Trim() + " " + proj.Province.Trim() + " " + proj.PostalCode.Trim(),
                                        };

                    combinedProjList = mainProjQuery.AsEnumerable().Select(x => new CombinedProject(x.JobNumber, x.ProjectManager, x.ProjectCoordinator, x.HardwareCoordinator, 
                                                                                                    x.IsUca,
                                                                                                    x.OffsiteStorageAgreement,
                                                                                                    x.SubstantialCompletionDate,
                                                                                                    x.ProjectStatus, 
                                                                                                    x.DateModified,
                                                                                                    x.EstStartDate, x.EstEndDate,
                                                                                                    x.SupplyCompletionPer,
                                                                                                    x.Hardware, x.DoorsAndFrames, x.UcAccess,
                                                                                                    x.PickeringInstall,
                                                                                                    x.PickeringInstallPer,
                                                                                                    x.SiteInstall,
                                                                                                    x.SiteInstallPer,
                                                                                                    x.PmComments,
                                                                                                    x.ChangeOrders,
                                                                                                    x.ChangeOrderComments,
                                                                                                    x.JobName, x.Division, x.Consultant, x.TotalProjectValue, x.BilledToDate,
                                                                                                    x.TotalActualCost,
                                                                                                    x.TotalCostToDate,
                                                                                                    x.ContractStatus, x.PreMobStatus,
                                                                                                    x.CustomerName,
                                                                                                    x.CreationDate,
                                                                                                    x.TotalQuoteValue,
                                                                                                    x.TotalQuotesApprovedValue,
                                                                                                    x.TotalQuotesTentApprovedValue,
                                                                                                    x.TotalQuotesNotApprovedValue)).ToList();

                    if (combinedProjList.Count == 0) { return new ObservableCollection<CombinedProject>(); }

                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
                finally
                {
                    dtCtx.Dispose();
                    //if (combinedProjList.Count == 0)
                    //    MessageBox.Show("There were no projects associated with " + user.DomainUserName + " using the GP project manager ID '" + user.GpEstimatorId + "' found in the GP database");
                }
                return new ObservableCollection<CombinedProject>(combinedProjList);
            }
            else if (user.PermissionTier == 6)
            {
                try
                {
                    var mainProjQuery = from proj in dtCtx.GetTable<MainProject>()
                                        join ac in dtCtx.GetTable<AwardedContract>() on proj.JobNumber equals ac.JobNumber
                                        join jc in dtCtx.GetTable<gp.Jc00102>() on proj.JobNumber equals jc.JobNumber
                                        join rm in dtCtx.GetTable<gp.Rm00101>() on jc.CustomerNumber equals rm.CustomerNumber
                                        join js in dtCtx.GetTable<gp.Jc00901>() on proj.JobNumber equals js.JobNumber
                                        //where jc.JobNumber == "20037"
                                        //where js.Inactive == 0 && jc.ProjectManager == user.GpEstimatorId
                                        where user.PermissionTier > 3 ? ((proj.HardwareCoordinator == user.DomainUserName || user.WsManagers.Contains(jc.ProjectManager)) && js.Inactive == 0) : false
                                        select new
                                        {
                                            JobNumber = proj.JobNumber,
                                            JobName = jc.JobName.Trim(),
                                            Division = jc.Division.Trim(),
                                            Consultant = jc.Consultant.Trim(),
                                            ProjectManager = jc.ProjectManager.Trim(),
                                            ProjectCoordinator = proj.ProjectCoordinator == null ? "" : proj.ProjectCoordinator,
                                            HardwareCoordinator = proj.HardwareCoordinator == null ? "" : proj.HardwareCoordinator,
                                            IsUca = proj.IsUca,
                                            OffsiteStorageAgreement = proj.OffsiteStorageAgreement,
                                            SubstantialCompletionDate = proj.SubstantialCompletionDate,
                                            //CustomerNumber = jc.CustomerNumber.Trim(),
                                            CustomerName = rm.CustomerName.Trim(),
                                            ProjectStatus = proj.ProjectStatus,
                                            DateModified = proj.DateModified,
                                            EstStartDate = proj.EstStartDate,
                                            EstEndDate = proj.EstEndDate,
                                            TotalProjectValue = jc.ProjectValue,
                                            BilledToDate = jc.BilledToDate,
                                            TotalActualCost = jc.TotalActualCost,
                                            TotalCostToDate = dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD) == null ? 0 :
                                                            dtCtx.GetTable<gp.Jc20001>().Where(n => n.JobNumber == proj.JobNumber).Sum(i => i.Cost_Code_Act_Cost_TTD),

                                            TotalQuoteValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesTentApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.TentativeApproval == true)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,

                                            TotalQuotesNotApprovedValue = (decimal?)dtCtx.GetTable<pm.ChangeLine>().Join(dtCtx.GetTable<pm.ChangeHeader>(), chLine => new { chLine.JobNumber, chLine.QuoteNumber },
                                                                                                                                   cHead => new { cHead.JobNumber, cHead.QuoteNumber },
                                                                                                                                   (cLine, cHead) => new { cLine, cHead })
                                                                                                                                   .Where(i => i.cLine.JobNumber == proj.JobNumber
                                                                                                                                            && i.cLine.QuoteNumber == i.cHead.QuoteNumber
                                                                                                                                            && i.cHead.Cancelled == false
                                                                                                                                            && i.cHead.Approved == false)
                                                                                                                                   .Select(r => r.cLine.ExtendedSellPrice
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.OverheadPercentage / 100))
                                                                                                                                            + (r.cLine.ExtendedSellPrice * (r.cHead.ProfitPercentage / 100))
                                                                                                                                            ).Sum()

                                                                                                                                            ?? 0,
                                            ContractStatus = ac.ContractStatus,
                                            PreMobStatus = ac.PreMobStatus,
                                            SupplyCompletionPer = proj.SupplyCompletion,
                                            Hardware = proj.Hardware,
                                            DoorsAndFrames = proj.DoorsAndFrames,
                                            UcAccess = proj.UcAccess,
                                            PickeringInstall = proj.PickeringInstall,
                                            PickeringInstallPer = proj.PickeringInstallPer,
                                            SiteInstall = proj.SiteInstall,
                                            SiteInstallPer = proj.SiteInstallPer,
                                            ChangeOrders = proj.ChangeOrders,
                                            ChangeOrderComments = proj.ChangeOrderComments,
                                            PmComments = proj.PmComments,
                                            CreationDate = jc.CreationDate
                                            //UnifiedAddress = proj.City.Trim() + " " + proj.Province.Trim() + " " + proj.PostalCode.Trim(),
                                        };

                    combinedProjList = mainProjQuery.AsEnumerable().Select(x => new CombinedProject(x.JobNumber, x.ProjectManager, x.ProjectCoordinator, x.HardwareCoordinator, 
                                                                                                    x.IsUca,
                                                                                                    x.OffsiteStorageAgreement,
                                                                                                    x.SubstantialCompletionDate,
                                                                                                    x.ProjectStatus, 
                                                                                                    x.DateModified,
                                                                                                    x.EstStartDate, x.EstEndDate,
                                                                                                    x.SupplyCompletionPer,
                                                                                                    x.Hardware, x.DoorsAndFrames, x.UcAccess,
                                                                                                    x.PickeringInstall,
                                                                                                    x.PickeringInstallPer,
                                                                                                    x.SiteInstall,
                                                                                                    x.SiteInstallPer,
                                                                                                    x.PmComments,
                                                                                                    x.ChangeOrders,
                                                                                                    x.ChangeOrderComments,
                                                                                                    x.JobName, x.Division, x.Consultant, x.TotalProjectValue, x.BilledToDate,
                                                                                                    x.TotalActualCost,
                                                                                                    x.TotalCostToDate,
                                                                                                    x.ContractStatus, x.PreMobStatus,
                                                                                                    x.CustomerName,
                                                                                                    x.CreationDate,
                                                                                                    x.TotalQuoteValue,
                                                                                                    x.TotalQuotesApprovedValue,
                                                                                                    x.TotalQuotesTentApprovedValue,
                                                                                                    x.TotalQuotesNotApprovedValue)).ToList();

                    if (combinedProjList.Count == 0) { return new ObservableCollection<CombinedProject>(); }

                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
                finally
                {
                    dtCtx.Dispose();
                    //if (combinedProjList.Count == 0)
                    //    MessageBox.Show("There were no projects associated with " + user.DomainUserName + " using the GP project manager ID '" + user.GpEstimatorId + "' found in the GP database");
                }
                return new ObservableCollection<CombinedProject>(combinedProjList);
            }
            else
            {
                return new ObservableCollection<CombinedProject>();
            }
        }

        public static CombinedProject GetSingleProject(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            CombinedProject combinedProjList = null;

            //I know this huge set of 3 blocks for project managers, project coordinators and hardware coordinators is ugly but I'm sick of project management having no clue how
            //their own project delegation works, so this will have to do less I build yet another system that doesn't work they way they wanted to because they didn't think it
            //through when explaining what they wanted

                try
                {
                    var mainProjQuery = from proj in dtCtx.GetTable<MainProject>()
                                        join ac in dtCtx.GetTable<AwardedContract>() on proj.JobNumber equals ac.JobNumber
                                        join jc in dtCtx.GetTable<gp.Jc00102>() on proj.JobNumber equals jc.JobNumber
                                        join rm in dtCtx.GetTable<gp.Rm00101>() on jc.CustomerNumber equals rm.CustomerNumber
                                        join js in dtCtx.GetTable<gp.Jc00901>() on proj.JobNumber equals js.JobNumber
                                        where jc.JobNumber == jobNumber
                                        select new
                                        {
                                            JobNumber = proj.JobNumber,
                                            JobName = jc.JobName.Trim(),
                                            Division = jc.Division.Trim(),
                                            Consultant = jc.Consultant.Trim(),
                                            ProjectManager = jc.ProjectManager.Trim(),
                                            ProjectCoordinator = proj.ProjectCoordinator == null ? "" : proj.ProjectCoordinator,
                                            HardwareCoordinator = proj.HardwareCoordinator == null ? "" : proj.HardwareCoordinator,
                                            //CustomerNumber = jc.CustomerNumber.Trim(),
                                            CustomerName = rm.CustomerName.Trim(),
                                            City = rm.City.Trim(),
                                            Province = rm.Province.Trim(),
                                            PostalCode = rm.PostalCode.Trim(),
                                            ProjectStatus = proj.ProjectStatus,
                                            DateModified = proj.DateModified,
                                            EstStartDate = proj.EstStartDate,
                                            EstEndDate = proj.EstEndDate,
                                            TotalProjectValue = jc.ProjectValue,
                                            BilledToDate = jc.BilledToDate,
                                            TotalActualCost = jc.TotalActualCost,
                                            ContractStatus = ac.ContractStatus,
                                            PreMobStatus = ac.PreMobStatus,
                                            SupplyCompletionPer = proj.SupplyCompletion,
                                            Hardware = proj.Hardware,
                                            DoorsAndFrames = proj.DoorsAndFrames,
                                            UcAccess = proj.UcAccess,
                                            PickeringInstall = proj.PickeringInstall,
                                            PickeringInstallPer = proj.PickeringInstallPer,
                                            SiteInstall = proj.SiteInstall,
                                            SiteInstallPer = proj.SiteInstallPer,
                                            ChangeOrders = proj.ChangeOrders,
                                            ChangeOrderComments = proj.ChangeOrderComments,
                                            PmComments = proj.PmComments,
                                            CreationDate = jc.CreationDate
                                            //UnifiedAddress = proj.City.Trim() + " " + proj.Province.Trim() + " " + proj.PostalCode.Trim(),
                                        };

                    combinedProjList = mainProjQuery.AsEnumerable().Select(x => new CombinedProject(x.JobNumber, x.ProjectManager, x.ProjectCoordinator, x.HardwareCoordinator, x.ProjectStatus, x.DateModified,
                                                                                                    x.EstStartDate, x.EstEndDate,
                                                                                                    x.SupplyCompletionPer,
                                                                                                    x.Hardware, x.DoorsAndFrames, x.UcAccess,
                                                                                                    x.PickeringInstall,
                                                                                                    x.PickeringInstallPer,
                                                                                                    x.SiteInstall,
                                                                                                    x.SiteInstallPer,
                                                                                                    x.PmComments,
                                                                                                    x.ChangeOrders,
                                                                                                    x.ChangeOrderComments,
                                                                                                    x.JobName, x.Division, x.Consultant, x.TotalProjectValue, x.BilledToDate,
                                                                                                    x.ContractStatus, x.PreMobStatus,
                                                                                                    x.CustomerName,
                                                                                                    x.CreationDate,
                                                                                                    x.City,
                                                                                                    x.Province,
                                                                                                    x.PostalCode)).FirstOrDefault();

                    if (combinedProjList == null) { return new CombinedProject(); }

                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
                finally
                {
                    dtCtx.Dispose();
                    //if (combinedProjList.Count == 0)
                    //    MessageBox.Show("There were no projects associated with " + user.DomainUserName + " using the GP project manager ID '" + user.GpEstimatorId + "' found in the GP database");
                }
                return combinedProjList;
            
        }
        public static void UpdateMainProjects(List<MainProject> _mainProjCol)
        {
            using (MainProjectDataContext dtCtx = new MainProjectDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (MainProject mp in _mainProjCol) //No insert or delete operations since the AwardContract DataGrid only allows modification
                {
                    try
                    {
                        if (mp.IsModified == true)
                        {
                            mp.DateModified = DateTime.Today;
                            dtCtx.MainProject.Attach(mp, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, mp);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static void AddMainProject(MainProject mp)
        {
            using (MainProjectDataContext dtCtx = new MainProjectDataContext(GlobalVars.UcshConnectionString))
            {
                mp.UpdatingUser = Environment.UserName;
                mp.UpdatingMachine = Environment.MachineName;
                mp.DateCreated = DateTime.Today;
                mp.TimeCreated = DateTime.Now;
                try
                {
                    dtCtx.MainProject.InsertOnSubmit(mp);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }
    }

    public class CombinedProject : INotifyPropertyChanged
    {
        //Have properties for MainProject, JC00102, RM00101 and probably AwardedContract

        private MainProject _mainProject = new MainProject();
        private AwardedContract _awardedContract = new AwardedContract();
        private gp.Jc00102 _jc00102 = new gp.Jc00102();
        private gp.Rm00101 _rm00101 = new gp.Rm00101();

        public MainProject MainProject
        {
            get { return _mainProject; } 
            set { _mainProject = value; }
        }

        public AwardedContract AwardedContract
        {
            get { return _awardedContract; }
            set { _awardedContract = value; }
        }

        public gp.Jc00102 Jc00102
        {
            get { return _jc00102; }
            set { _jc00102 = value; }
        }

        public gp.Rm00101 Rm00101
        {
            get { return _rm00101; }
            set { _rm00101 = value; }
        }

        //add some derived properties that come from the objects

        public CombinedProject()
        {

        }

        public CombinedProject(string jobNum)
        {
            this._mainProject._jobNumber = jobNum;
        }

        //Constructor for MainProjects
        public CombinedProject(string jobNum, string projMan, string projectCoordinator, string hardwareCoordinator, 
                               bool isUca,
                               bool offsiteStorageAgreement,
                               DateTime? substantialCompletionDate, 
                               string projStat, DateTime? dateMod, DateTime? estStart, DateTime? estEnd,
                               decimal supplyComp,
                               string hw, string doorAndF, string uca, string pickInst,
                               decimal pickInstPer, string siteInst, decimal siteInstPer, 
                               string pmComm, 
                               bool co,
                               string coComm,
                               string jobName, string div, string consult, decimal projVal, decimal billToDate,
                               decimal totalActualCost,
                               decimal totalCostToDate,
                               string contrStat, string preMobStat,
                               string custName,
                               DateTime? creationDate,
                               decimal totalQuotesValue,
                               decimal totalQuotesApprovedValue,
                               decimal totalQuotesTentApprovedValue,
                               decimal totalQuotesNotApprovedValue)
        {
            this._mainProject._jobNumber = jobNum;
            this._mainProject._projectManager = projMan;
            this._mainProject.ProjectCoordinator = projectCoordinator;
            this._mainProject.HardwareCoordinator = hardwareCoordinator;
            this._mainProject.IsUca = isUca;
            this._mainProject.OffsiteStorageAgreement = offsiteStorageAgreement;
            this._mainProject._substantialCompletionDate = substantialCompletionDate;
            this._mainProject._projectStatus = projStat;
            this._mainProject._dateModified = dateMod;
            this._mainProject._estStartDate = estStart;
            this._mainProject._estEndDate = estEnd;
            this._mainProject._supplyCompletion = supplyComp;
            this._mainProject._hardware = hw;
            this._mainProject._doorsAndFrames = doorAndF;
            this._mainProject._ucAccess = uca;
            this._mainProject._pickeringInstall = pickInst;
            this._mainProject._pickeringInstallPer = pickInstPer;
            this._mainProject._siteInstall = siteInst;   //assign property not backing field for some reason
            this._mainProject._siteInstallPer = siteInstPer;
            this._mainProject._changeOrders = co;
            this._mainProject._changeOrderComments = coComm;
            this._mainProject._pmComments = pmComm;

            //this._mainProject._projectValue = projVal;
            //this._mainProject._billedToDate = billToDate;
            this._mainProject.ProjectValue = projVal;       //Need to target the properties not underlying fields in order to calculate derived values like backlog
            this._mainProject.BilledToDate = billToDate;    //Need to target the properties not underlying fields in order to calculate derived values like backlog
            this._mainProject.TotalActualCost = totalActualCost;
            this._mainProject.TotalCostToDate = totalCostToDate;


            this._jc00102.JobName = jobName;
            this._jc00102.Division = div;
            this._jc00102.Consultant = consult;
            this._jc00102.ProjectManager = projMan;
            this._jc00102.ProjectValue = projVal;
            this._jc00102.BilledToDate = billToDate;
            this._jc00102.CreationDate = creationDate;

            this._awardedContract.ContractStatus = contrStat;
            this._awardedContract.PreMobStatus = preMobStat;

            this._rm00101.CustomerName = custName;

            this._mainProject.IsModified = false;

            this._mainProject.TotalQuotesValue = totalQuotesValue;
            this._mainProject.TotalQuotesApprovedValue = totalQuotesApprovedValue;
            this._mainProject.TotalQuotesTentApprovedValue = totalQuotesTentApprovedValue;
            this._mainProject.TotalQuotesNotApprovedValue = totalQuotesNotApprovedValue;
        }

        //Constructor for Warehouse shipping project select with expanded customer data
        public CombinedProject(string jobNumber, string jobName, string address1, string address2, string city,
                               string province, string country, string postalCode, string phoneNumber, string faxNumber)
        {
            this._jc00102.JobNumber = jobNumber;          
            this._jc00102.JobName = jobName;
            this._rm00101.Address = address1;
            this._rm00101.Address2 = address2;
            this._rm00101.City = city;
            this._rm00101.Province = province;
            this._rm00101.Country = country;
            this._rm00101.PostalCode = postalCode;
            this._rm00101.PhoneNumber = phoneNumber;
            this._rm00101.FaxNumber = faxNumber;

            //this._jc00102.Consultant = consult;
            //this._jc00102.ProjectManager = projMan;
            //this._rm00101.CustomerName = custName;
        }


        //Constructor for Warehouse blank line shipping document with 3 additional RM table fields provided - City, Province, Postal Code
        public CombinedProject(string jobNum, string projMan, string projectCoordinator, string hardwareCoordinator, string projStat, DateTime? dateMod, DateTime? estStart, DateTime? estEnd,
                               decimal supplyComp,
                               string hw, string doorAndF, string uca, string pickInst,
                               decimal pickInstPer, string siteInst, decimal siteInstPer,
                               string pmComm,
                               bool co,
                               string coComm,
                               string jobName, string div, string consult, decimal projVal, decimal billToDate,
                               string contrStat, string preMobStat,
                               string custName,
                               DateTime? creationDate
                               , string city, string province, string postalCode)
        {
            this._mainProject._jobNumber = jobNum;
            this._mainProject._projectManager = projMan;
            this._mainProject.ProjectCoordinator = projectCoordinator;
            this._mainProject.HardwareCoordinator = hardwareCoordinator;
            this._mainProject._projectStatus = projStat;
            this._mainProject._dateModified = dateMod;
            this._mainProject._estStartDate = estStart;
            this._mainProject._estEndDate = estEnd;
            this._mainProject._supplyCompletion = supplyComp;
            this._mainProject._hardware = hw;
            this._mainProject._doorsAndFrames = doorAndF;
            this._mainProject._ucAccess = uca;
            this._mainProject._pickeringInstall = pickInst;
            this._mainProject._pickeringInstallPer = pickInstPer;
            this._mainProject._siteInstall = siteInst;   //assign property not backing field for some reason
            this._mainProject._siteInstallPer = siteInstPer;
            this._mainProject._changeOrders = co;
            this._mainProject._changeOrderComments = coComm;
            this._mainProject._pmComments = pmComm;

            //this._mainProject._projectValue = projVal;
            //this._mainProject._billedToDate = billToDate;
            this._mainProject.ProjectValue = projVal;       //Need to target the properties not underlying fields in order to calculate derived values like backlog
            this._mainProject.BilledToDate = billToDate;    //Need to target the properties not underlying fields in order to calculate derived values like backlog

            this._jc00102.JobName = jobName;
            this._jc00102.Division = div;
            this._jc00102.Consultant = consult;
            this._jc00102.ProjectManager = projMan;
            this._jc00102.ProjectValue = projVal;
            this._jc00102.BilledToDate = billToDate;
            this._jc00102.CreationDate = creationDate;

            this._awardedContract.ContractStatus = contrStat;
            this._awardedContract.PreMobStatus = preMobStat;

            this._rm00101.CustomerName = custName;

            this._rm00101.City = city;
            this._rm00101.Province = province;
            this._rm00101.PostalCode = postalCode;

            this._mainProject.IsModified = false;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    [mp.Table(Name= "[UTPMMAINAWPROJ101]")]
    public class MainProject : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;

        internal string _jobNumber;
        internal string _projectManager;
        internal string _projectStatus;
        private string _projectCoordinator;       //Added 10 Jan 2018
        private string _hardwareCoordinator; //Added 04 June 2018
        private bool _isUca;                //Added 02 Oct 2019
        private bool _offsiteStorageAgreement;  //Added 27 May 2021
        internal DateTime? _substantialCompletionDate;

        internal DateTime? _dateModified;
        internal DateTime? _estStartDate;
        internal DateTime? _estEndDate;

        internal decimal _projectValue;      //From JC00102, but assign this one at the same time when retrieving data
        internal decimal _billedToDate;      //From JC00102, but assign this one at the same time when retrieving data
        internal decimal _totalActualCost;
        internal decimal _totalCostToDate;  //Sum of "Cost_Code_Act_Cost_TTD" field in JC20001
        internal decimal _currentBacklog;    //DERIVED
        internal decimal _percentageBilled;  //DERIVED
        internal decimal _currentMargin;

        // 	Original Project Margin as setup in GP based on total cost and total sell
        //  Original Project Value as setup in GP based on total sell

        private decimal origProjMargin;
        private decimal origProjValue;
        private decimal totalQuotesValue;
        private decimal totalQuotesApprovedValue;
        private decimal totalQuotesTentApprovedValue;
        private decimal totalQuotesNotApprovedValue;


        //this._overheadAmountUI = _changeLineItems.Where(x => x.IsLabour == false).Sum(i => i.ExtendedSellPrice) * (_overheadPercentage / 100);
        //this._profitAmountUI = _changeLineItems.Where(x => x.IsLabour == false).Sum(i => i.ExtendedSellPrice) * (_profitPercentage / 100);


        internal decimal _supplyCompletion;            //to add - Supply completion (prob derived from GP)
            //to add - Install completion (prob derived from GP)
        internal string _hardware;
        internal string _doorsAndFrames;
        internal string _ucAccess;
            internal string _pickeringInstall;
            internal string _siteInstall;
        internal decimal _pickeringInstallPer;
        internal decimal _siteInstallPer;
            internal bool _changeOrders;
            internal string _changeOrderComments;
        internal string _pmComments;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        internal bool _isModified;
        internal bool _isDeleted;

        private string _dynColor;

        internal string DynColor
        {
            get { return _dynColor; }
            set 
            { 
                _dynColor = value;
                OnPropertyChanged("ProjectManager");
            }
        }

        internal int Id     //being used only for comparison in transfer eligible projects
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name="JobNumber", IsPrimaryKey=true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "ProjectManager")]
        public string ProjectManager
        {
            get { return _projectManager; }
            set 
            { 
                _projectManager = value;
                this.IsModified = true;
                OnPropertyChanged("ProjectManager");
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

        [mp.Column(Name = "ProjectCoordinator")]
        public string ProjectCoordinator
        {
            get { return _projectCoordinator; }
            set 
            { 
                _projectCoordinator = value;
                this.IsModified = true;
                OnPropertyChanged("Coordinator");
            }
        }

        [mp.Column(Name = "HardwareCoordinator")]
        public string HardwareCoordinator
        {
            get { return _hardwareCoordinator; }
            set
            {
                _hardwareCoordinator = value;
                this.IsModified = true;
                OnPropertyChanged("HardwareCoordinator");
            }
        }

        [mp.Column(Name = "IsUca", DbType="bit")]
        public bool IsUca
        {
            get
            {
                return _isUca;
            }

            set
            {
                _isUca = value;
                this.IsModified = true;
                OnPropertyChanged("IsUca");
            }
        }

        [mp.Column(Name = "OffsiteStorageAgreement", DbType = "bit")]
        public bool OffsiteStorageAgreement
        {
            get
            {
                return _offsiteStorageAgreement;
            }

            set
            {
                _offsiteStorageAgreement = value;
                this.IsModified = true;
                OnPropertyChanged("OffsiteStorageAgreement");
            }
        }

        [mp.Column(Name = "SubstantialCompletionDate")]
        public DateTime? SubstantialCompletionDate
        {
            get
            {
                return _substantialCompletionDate;
            }

            set
            {
                _substantialCompletionDate = value;
                this.IsModified = true;
                OnPropertyChanged("SubstantialCompletionDate");
            }
        }

        [mp.Column(Name = "DateModified")]
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

        [mp.Column(Name = "EstStartDate")]
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

        [mp.Column(Name = "EstEndDate")]
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

        //Property used to display derivative value, not visible to UI
        public decimal ProjectValue
        {
            get { return _projectValue; }
            set 
            { 
                _projectValue = value;
                this.IsModified = true;
                this._currentBacklog = value - this._billedToDate;
                if (value == 0)
                {
                    this._percentageBilled = 0;
                }
                else
                {
                    this._percentageBilled = this._billedToDate / value;
                }
                //this._percentageBilled = this._billedToDate / value;
                OnPropertyChanged("ProjectValue");
                OnPropertyChanged("CurrentBacklog");
                OnPropertyChanged("PercentageBilled");
            }
        }

        public decimal BilledToDate
        {
            get { return _billedToDate; }
            set 
            { 
                _billedToDate = value;
                this.IsModified = true;
                this._currentBacklog = this._projectValue - value;
                if (value == 0)
                {
                    this._percentageBilled = 0;
                }
                else
                {
                    this._percentageBilled = value / this._projectValue;
                }
                //this._percentageBilled = value / this._projectValue;
                OnPropertyChanged("BilledToDate");
                OnPropertyChanged("CurrentBacklog");
                OnPropertyChanged("PercentageBilled");
                OnPropertyChanged("CurrentMargin");
            }
        }

        public decimal TotalActualCost
        {
            get
            {
                return _totalActualCost;
            }

            set
            {
                _totalActualCost = value;
                this.IsModified = true;
                //if (value == 0 || _billedToDate == 0)
                //{
                //    this._currentMargin = 0;
                //}
                //else
                //{
                //    this._currentMargin = decimal.Round((((_billedToDate - value) / _billedToDate) * 100), 2); 
                //}
                ////
                OnPropertyChanged("TotalActualCost");
                //OnPropertyChanged("CurrentMargin");
            }

        }

        public decimal TotalCostToDate
        {
            get
            {
                return this._totalCostToDate;
            }

            set
            {
                this._totalCostToDate = value;
                this.IsModified = true;
                if (value == 0 || _billedToDate == 0)
                {
                    this._currentMargin = 0;
                }
                else
                {
                    this._currentMargin = decimal.Round((((_billedToDate - value) / _billedToDate) * 100), 2);
                }
                OnPropertyChanged("TotalCostToDate");
                OnPropertyChanged("CurrentMargin");
            }
        }

        //Derivative
        public decimal CurrentMargin
        {
            get
            {
                return _currentMargin;
            }

            set
            {
                _currentMargin = value;
            }
        }

        //Derivative
        public decimal CurrentBacklog
        {
            get { return _currentBacklog; }
            //Set method not used, but implemented for the sake of a constructor in this class - MainProjWithFilePath : DataClasses.MainProject
            set { _currentBacklog = value;}
        }

        //Derivative
        public decimal PercentageBilled
        {
            get { return _percentageBilled; }
            //Set method not used, but implemented for the sake of a constructor in this class - MainProjWithFilePath : DataClasses.MainProject
            set { _percentageBilled = value; }
        }

        [mp.Column(Name = "SupplyCompletionPer")]
        public decimal SupplyCompletion
        {
            get { return _supplyCompletion; }
            set 
            { 
                _supplyCompletion = value;
                this.IsModified = true;
                OnPropertyChanged("SupplyCompletion");
            }
        }

        [mp.Column(Name = "Hardware")]
        public string Hardware
        {
            get { return _hardware; }
            set
            {
                _hardware = value;
                this.IsModified = true;
                OnPropertyChanged("Hardware");
            }
        }

        [mp.Column(Name = "DoorsAndFrames")]
        public string DoorsAndFrames
        {
            get { return _doorsAndFrames; }
            set
            {
                _doorsAndFrames = value;
                this.IsModified = true;
                OnPropertyChanged("DoorsAndFrames");
            }
        }

        [mp.Column(Name = "UCAccess")]
        public string UcAccess
        {
            get { return _ucAccess; }
            set
            {
                _ucAccess = value;
                this.IsModified = true;
                OnPropertyChanged("UcAccess");
            }
        }


        [mp.Column(Name = "PickeringInstall")]
        public string PickeringInstall
        {
            get { return _pickeringInstall; }
            set 
            { 
                _pickeringInstall = value;
                this.IsModified = true;
                OnPropertyChanged("PickeringInstall");
            }
        }

        [mp.Column(Name = "SiteInstall")]
        public string SiteInstall
        {
            get { return _siteInstall; }
            set 
            { 
                _siteInstall = value;
                this.IsModified = true;
                OnPropertyChanged("SiteInstall");
            }
        }


        [mp.Column(Name = "PickeringInstallPer")]
        public decimal PickeringInstallPer
        {
            get { return _pickeringInstallPer; }
            set 
            { 
                _pickeringInstallPer = value;
                this.IsModified = true;
                OnPropertyChanged("PickeringInstallPer");
            }
        }

        [mp.Column(Name = "SiteInstallPer")]
        public decimal SiteInstallPer
        {
            get { return _siteInstallPer; }
            set 
            { 
                _siteInstallPer = value;
                this.IsModified = true;
                OnPropertyChanged("SiteInstallPer");
            }
        }

        [mp.Column(Name = "ChangeOrders")]
        public bool ChangeOrders
        {
            get { return _changeOrders; } 
            set 
            { 
                _changeOrders = value;
                this.IsModified = true;
                OnPropertyChanged("ChangeOrders");
            }
        }

        [mp.Column(Name = "ChangeOrderComments")]
        public string ChangeOrderComments
        {
            get { return _changeOrderComments; }
            set 
            { 
                _changeOrderComments = value;
                this.IsModified = true;
                OnPropertyChanged("ChangeOrderComments");
            }
        }


        [mp.Column(Name = "PMComments")]
        public string PmComments
        {
            get { return _pmComments; }
            set 
            { 
                _pmComments = value;
                this.IsModified = true;
                OnPropertyChanged("PmComments");
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

        internal decimal OrigProjMargin
        {
            get
            {
                return origProjMargin;
            }

            set
            {
                origProjMargin = value;
            }
        }

        internal decimal OrigProjValue
        {
            get
            {
                return origProjValue;
            }

            set
            {
                origProjValue = value;
            }
        }

        public decimal TotalQuotesValue
        {
            get
            {
                return totalQuotesValue;
            }

            set
            {
                totalQuotesValue = value;
                OnPropertyChanged("TotalQuotesValue");
            }
        }

        public decimal TotalQuotesApprovedValue
        {
            get
            {
                return totalQuotesApprovedValue;
            }

            set
            {
                totalQuotesApprovedValue = value;
                OnPropertyChanged("TotalQuotesApprovedValue");
            }
        }

        public decimal TotalQuotesTentApprovedValue
        {
            get
            {
                return totalQuotesTentApprovedValue;
            }

            set
            {
                totalQuotesTentApprovedValue = value;
                OnPropertyChanged("TotalQuotesTentApprovedValue");
            }
        }

        public decimal TotalQuotesNotApprovedValue
        {
            get
            {
                return totalQuotesNotApprovedValue;
            }

            set
            {
                totalQuotesNotApprovedValue = value;
                OnPropertyChanged("TotalQuotesNotApprovedValue");
            }
        }

        public MainProject()
        {
            this._dynColor = "Orange";
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class MainProjectDataContext : lq.DataContext
    {
        public MainProjectDataContext(string cs)
            : base(cs)
        {
        }

        public MainProjectDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<MainProject> MainProject;
    }
}
