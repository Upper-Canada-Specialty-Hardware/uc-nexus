using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using dc = PM_Project_Tracking.DataClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using System.IO;
using System.Collections.ObjectModel;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    public static class CheckLinksJobFolders
    {
        public static void GetFolders()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));

            DrivePath _selDp = dc.PathSchemas.GetDrivePathByKey(2);
            string[] _direcs = Directory.GetDirectories(_selDp.DrivePathString);
            List<MainProject> _jobList = dtCtx.GetTable<MainProject>().ToList();
            List<MainProjWithFilePath> _jobListWithPath = new List<MainProjWithFilePath>();
            _jobList.ForEach(delegate (dc.MainProject x)
            {
                _jobListWithPath.Add(new MainProjWithFilePath(x, _direcs.Where(r => r.Contains(x.JobNumber)).FirstOrDefault() ));
            }
            );
            _jobListWithPath = _jobListWithPath.Where(x => x.JobFolderPath != null).ToList();
            PathSchemas.TruncateJobPathTable();
            PathSchemas.AddJobPathRoot(_jobListWithPath, 2);
        }
    }

    class MainProjWithFilePath : DataClasses.MainProject
    {
        private string _jobFolderPath;

        public string JobFolderPath
        {
            get
            {
                return _jobFolderPath;
            }

            set
            {
                _jobFolderPath = value;
            }
        }

        public MainProjWithFilePath(MainProject mp, string jobFolderPath)
        {
            if (jobFolderPath != null)
                this._jobFolderPath = jobFolderPath.ToString().Remove(0, 3);
            var properties = mp.GetType().GetProperties();

            properties.ToList().ForEach(property =>
            {
                //Check whether that property is present in derived class
                var isPresent = this.GetType().GetProperty(property.Name);
                if (isPresent != null)
                {
                    //If present get the value and map it
                    var value = mp.GetType().GetProperty(property.Name).GetValue(mp, null);
                    this.GetType().GetProperty(property.Name).SetValue(this, value, null);
                }
            });
        }
    }

}
