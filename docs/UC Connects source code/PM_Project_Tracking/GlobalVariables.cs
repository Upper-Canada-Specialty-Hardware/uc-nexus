using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using dc = PM_Project_Tracking.DataClasses;

namespace PM_Project_Tracking
{
    public static class GlobalVars
    {
        private static string _server = Properties.Settings.Default.Server;
        private static string _currentPmDatabaseName = Properties.Settings.Default.UcshInitCatalog;
        private static string _currentGpDatabaseName = Properties.Settings.Default.GpInitCatalog;
        private static string _ucUserDatabaseName = "UCUsers";
        private static string _ucbcDatabaseName = "PMUBC";
        private static string _gpbcDatabaseName = "UBC";
        private static string _ucUsersConnectionString = @"Data Source=" + Properties.Settings.Default.Server + ";Initial Catalog=" + Properties.Settings.Default.UCUsersInitCatalog + ";Integrated Security=SSPI;";
        private static string _ucshConnectionString = @"Data Source=" + Properties.Settings.Default.Server + ";Initial Catalog=" + Properties.Settings.Default.UcshInitCatalog + ";Integrated Security=SSPI;";
        private static string _gpConnectionString = @"Data Source=" + Properties.Settings.Default.Server + ";Initial Catalog=" + Properties.Settings.Default.GpInitCatalog + ";Integrated Security=SSPI;";
        private static string _defaultExcelSavePath = Properties.Settings.Default.DefaultExcelSaveFolder;
         
        private static GlobalsInstanceContainer _inst;

        public static GlobalsInstanceContainer Inst
        {
            get { return _inst; }
            set { _inst = value; }
        }

        public static string Server
        {
            get { return GlobalVars._server; }
            set
            {
                GlobalVars._server = value;
                GlobalVars._ucshConnectionString = @"Data Source=" + value + ";Initial Catalog=" + GlobalVars._currentPmDatabaseName + ";Integrated Security=SSPI;";
            }
        }

        public static string UcUserDatabaseName
        {
            get { return GlobalVars._ucUserDatabaseName; }
            set
            {
                GlobalVars._ucUserDatabaseName = value;
                //Will probably never need to modify this because we use the same users source (the new UCUsers database) whether or not we're in test or live going forward
                GlobalVars._ucUsersConnectionString = @"Data Source=" + GlobalVars._server + ";Initial Catalog=" + value + ";Integrated Security=SSPI;";
            }
        }

        public static string CurrentPmDatabaseName
        {
            get { return GlobalVars._currentPmDatabaseName; }
            set
            {
                GlobalVars._currentPmDatabaseName = value;
                GlobalVars._ucshConnectionString = @"Data Source=" + GlobalVars._server + ";Initial Catalog=" + value + ";Integrated Security=SSPI;";
            }
        }

        public static string CurrentGpDatabaseName
        {
            get { return GlobalVars._currentGpDatabaseName; }
            set 
            { 
                GlobalVars._currentGpDatabaseName = value;
                GlobalVars._gpConnectionString = @"Data Source=" + GlobalVars._server + ";Initial Catalog=" + value + ";Integrated Security=SSPI;";
            }
        }

        public static string UcUsersConnectionString
        {
            get { return GlobalVars._ucUsersConnectionString; }
            //set { _ucUsersConnectionString = value; }
        }

        public static string UcshConnectionString
        {
            get { return GlobalVars._ucshConnectionString; }
        }

        public static string GpConnectionString
        {
            get { return GlobalVars._gpConnectionString; }
            set { GlobalVars._gpConnectionString = value; }
        }

        public static string DefaultExcelSavePath
        {
            get { return GlobalVars._defaultExcelSavePath; }
        }

        //Refactor this so that the user can select which company they use, not being railroaded by the company ID they default to
        public static void SwitchToLive(dc.User user)   //these automatically change the connection strings when the database name property is changed
        {
            if (user.CompanyId == 1)
            {
                CurrentPmDatabaseName = "PMUCSH";
                CurrentGpDatabaseName = "UCSH";
            }
            else if(user.CompanyId == 2)
            {
                CurrentPmDatabaseName = "PMUBC";
                CurrentGpDatabaseName = "UBC";
            }
        }

        public static void SwitchToUcsh()
        {
            CurrentPmDatabaseName = "PMUCSH";
            CurrentGpDatabaseName = "UCSH";
        }

        public static void SwitchToBc()
        {
            CurrentPmDatabaseName = "PMUBC";
            CurrentGpDatabaseName = "UBC";
        }

        public static void SwitchToTest()   //these automatically change the connection strings when the database name property is changed
        {
            CurrentPmDatabaseName = "TESTPMUCSH";
            CurrentGpDatabaseName = "TUCSH";
        }
    }

    //NOT USED
    public class GlobalsInstanceContainer
    {
        private string _server;
        private string _database;
        private string _gpDatabase;

        public GlobalsInstanceContainer()
        {
            _server = Properties.Settings.Default.Server;
            _database = Properties.Settings.Default.UcshInitCatalog;
            _gpDatabase = Properties.Settings.Default.GpInitCatalog;
        }
    }
}
