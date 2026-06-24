using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using gp = PM_Project_Tracking.DataClasses.GpObjects;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    public static class TransferBidToAwContrMainProj
    {
        internal static BidProject GetDetailedBidProject(BidProject preBidProj)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, DatabaseSwitcher.Convert(ref tempdtCtx));
            BidProject _outBidProj = null;

            try
            {
                var preQuery = from bidProj in dtCtx.GetTable<BidProject>()
                               join jc in dtCtx.GetTable<gp.Jc00102>() on bidProj.JobNumber equals jc.JobNumber.Trim()
                               join rm in dtCtx.GetTable<gp.Rm00101>() on jc.CustomerNumber equals rm.CustomerNumber
                               where bidProj.JobNumber == preBidProj.JobNumber
                               select new
                               {
                                   Id = bidProj.Id,
                                   JobNumber = bidProj.JobNumber,
                                   JobName = bidProj.JobName,
                                   CustomerNumber = jc.CustomerNumber.Trim(),
                                   CustomerName = rm.CustomerName.Trim(),
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

                _outBidProj = preQuery.AsEnumerable().Select(x => new BidProject(x.Id, x.JobNumber, x.JobName, x.CustomerNumber, x.CustomerName,
                                                                               x.Consultant, x.ProjectStatus, 
                                                                               x.Division,
                                                                               x.ProjectType,
                                                                               x.Comments, x.DateTenderOffer,
                                                                               x.DateModified, x.BidClosingDate, x.BidClosingTime, x.EstStartDate, x.EstStartDate,
                                                                               x.EstProjValue)).ToList().FirstOrDefault();

                //if (projList.Count == 0) { return new ObservableCollection<BidProject>(); }

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return _outBidProj;
        }
    }
}
