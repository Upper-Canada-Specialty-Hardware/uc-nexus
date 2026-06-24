using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using dc = PM_Project_Tracking.DataClasses;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using System.Windows;
using System.Collections.ObjectModel;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    public static class EligibleProjectRetrieval
    {
        public static ObservableCollection<BidProject> GetEligibleProjects()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, DatabaseSwitcher.Convert(ref tempdtCtx));
            List<BidProject> projList = null;

            try
            {
                var preProjQuery = from allProj in dtCtx.GetTable<BidProject>()
                                    join jc in dtCtx.GetTable<gp.Jc00102>() on allProj.JobNumber equals jc.JobNumber.Trim()
                                    select new
                                    {
                                        Id = allProj.Id,
                                        JobNumber = allProj.JobNumber,
                                        JobName = jc.JobName,
                                    };

                var mainProjQuery = from mp in dtCtx.GetTable<MainProject>()
                                    join jc in dtCtx.GetTable<gp.Jc00102>() on mp.JobNumber equals jc.JobNumber
                                    select new
                                    {
                                        Id = "",
                                        JobNumber = mp.JobNumber,
                                        JobName = jc.JobName,
                                    };

                //var eligList = preProjQuery.Except(mainProjQuery);
                //projList = eliList.AsEnumerable().Select(x => new BidProject(x.Id, x.JobNumber, x.JobName)).ToList();

                var eliList = preProjQuery.Where(x => !mainProjQuery.Any(y => y.JobNumber == x.JobNumber)).ToList();
                projList = eliList.AsEnumerable().Select(x => new BidProject(x.Id, x.JobNumber, x.JobName)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return new ObservableCollection<BidProject>(projList);
        }
    }
}
