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
    public class EligibleTenderRetrieval
    {
        internal static ObservableCollection<OfferToTender> GetEligibleTenders()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, DatabaseSwitcher.Convert(ref tempdtCtx));
            List<OfferToTender> projList = null;

            try
            {
                var offerQuery = from offerProj in dtCtx.GetTable<OfferToTender>()
                                 where offerProj.ProjectStatus != "NOT BIDDING" && offerProj.ProjectStatus != "BIDDING"
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
            return new ObservableCollection<OfferToTender>(projList);
        }
    }
}
