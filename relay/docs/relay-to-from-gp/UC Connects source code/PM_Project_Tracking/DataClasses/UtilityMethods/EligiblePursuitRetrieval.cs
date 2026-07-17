using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Windows;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    class EligiblePursuitRetrieval
    {
        internal static ObservableCollection<Pursuit> GetEligiblePursuits()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, DatabaseSwitcher.Convert(ref tempdtCtx));
            List<Pursuit> projList = null;

            try
            {
                var offerQuery = from pursuit in dtCtx.GetTable<Pursuit>()
                                 where pursuit.TenderPhase == "BIDDING"  && pursuit.PursuitStatus != "ACTIVE"
                                 select new 
                                 {
                                     Id = pursuit.Id,
                                     JobName = pursuit.JobName, 
                                     JobNumber = pursuit.JobNumber,
                                     TenderPhase = pursuit.TenderPhase,
                                     HardwareSchedWriter = pursuit.HardwareSchedWriter,
                                     Contractor = pursuit.Contractor,
                                     BidClosingDate = pursuit.BidClosingDate,
                                     EstimatedProjectValue = pursuit.EstimatedProjectValue

                                     //DateCreated = pursuit.DateCreated,
                                     //BidDueDate = pursuit.BidDueDate,
                                     //ProjectStatus = pursuit.ProjectStatus,
                                     ////Comments = pursuit.Comments,
                                     ////Consultant = pursuit.Consultant
                                 };

                projList = offerQuery.AsEnumerable().Select(x => new Pursuit() { Id = x.Id, JobName = x.JobName, JobNumber = x.JobNumber,
                                                                                TenderPhase = x.TenderPhase, HardwareSchedWriter = x.HardwareSchedWriter, Contractor = x.Contractor,
                                                                                BidClosingDate = x.BidClosingDate, EstimatedProjectValue = x.EstimatedProjectValue}).ToList();

                if (projList.Count == 0) { MessageBox.Show(" returned no results."); return null; }

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return new ObservableCollection<Pursuit>(projList);
        }
    }
}
