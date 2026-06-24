using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using System.Windows;
using System.Collections.ObjectModel;
using System.Data.SqlClient;

namespace PM_Project_Tracking.DataClasses
{
    class PathSchemas
    {
        public static DrivePath GetDrivePathByKey(int driveKey)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));

            DrivePath _selDrivePath = dtCtx.GetTable<DrivePath>().Where(x => x.DriveKey == driveKey).FirstOrDefault();

            return _selDrivePath;
        }

        public static void TruncateJobPathTable()
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "TRUNCATE TABLE PSJOBPATHROOT";

            try
            {
                SqlCommand comm = new SqlCommand(strQuery, conn);
                conn.Open();
                comm.ExecuteNonQuery();
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
        }

        public static bool AddJobPathRoot(List<um.MainProjWithFilePath> _mpWfpCol, int driveKey)
        {
            bool _cont = true;
            using (JobPathRootDataContext dtCtx = new JobPathRootDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (um.MainProjWithFilePath mpfp in _mpWfpCol)
                {
                    try
                    {
                        JobPathRoot jpr = new JobPathRoot();
                        jpr.ID = GetNextIdNumber();
                        jpr.Version = 1;
                        jpr.DriveKey = driveKey;
                        jpr.JobNumber = mpfp.JobNumber;
                        jpr.JobRootPath = mpfp.JobFolderPath;
                        jpr.DateCreated = DateTime.Today;
                        jpr.TimeCreated = DateTime.Now;
                        jpr.CreatingUser = Environment.UserName;
                        jpr.CreatingMachine = Environment.MachineName;
                        dtCtx.JobPathRoot.InsertOnSubmit(jpr);
                    }
                    catch (SqlException sqlEx)
                    {
                        MessageBox.Show(sqlEx.ToString());
                        _cont = false;
                        break;
                    }
                    catch (Exception ex)
                    {
                        MessageBox.Show(ex.ToString());
                        _cont = false;
                        break;
                    }
                }
                dtCtx.SubmitChanges();
            }
            if (!_cont)
            {
                //DeleteShippingLines(slCol);
            }
            return _cont;
        }


        public static int GetNextIdNumber()
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "SELECT MAX(ID) FROM PSJOBPATHROOT";
            int _idNum = 0;

            try
            {
                SqlCommand comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var dbVal = comm.ExecuteScalar();
                if (dbVal.GetType() == typeof(DBNull))
                    _idNum = 1;
                else
                    _idNum = (int)dbVal + 1;
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

            return _idNum;
        }
    }
    
    //A simple combined class for path schema sub classes that represent database objects like JobPathRoot and DrivePath
    public class PathSchema
    {

    }

    [mp.Table(Name = "[PSJOBPATHROOT]")]
    public class JobPathRoot
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _iD;
        private string _jobNumber;
        private int _driveKey;
        private string _jobRootPath;
        private int _version;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _creatingUser;
        private string _creatingMachine;

        [mp.Column(Name = "ID")]
        public int ID
        {
            get
            {
                return _iD;
            }

            set
            {
                _iD = value;
            }
        }

        [mp.Column(Name = "JobNumber", IsPrimaryKey =true)]
        public string JobNumber
        {
            get
            {
                return _jobNumber;
            }

            set
            {
                _jobNumber = value;
            }
        }

        [mp.Column(Name = "DriveKey", IsPrimaryKey = true)]
        public int DriveKey
        {
            get
            {
                return _driveKey;
            }

            set
            {
                _driveKey = value;
            }
        }

        [mp.Column(Name = "JobRootPath")]
        public string JobRootPath
        {
            get
            {
                return _jobRootPath;
            }

            set
            {
                _jobRootPath = value;
            }
        }

        [mp.Column(Name = "Vers", IsPrimaryKey = true)]
        public int Version
        {
            get
            {
                return _version;
            }

            set
            {
                _version = value;
            }
        }


        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set
            {
                _dateCreated = value;
            }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set
            {
                _timeCreated = value;
            }
        }

        [mp.Column(Name = "CreatingUser")]
        public string CreatingUser
        {
            get
            {
                return _creatingUser;
            }

            set
            {
                _creatingUser = value;
            }
        }

        [mp.Column(Name = "CreatingMachine")]
        public string CreatingMachine
        {
            get
            {
                return _creatingMachine;
            }

            set
            {
                _creatingMachine = value;
            }
        }

    }

    [mp.Table(Name = "[PSDRIVEPATH]")]
    public class DrivePath
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _driveKey;
        private string _driveName;
        private string _drivePathString;
        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _creatingUser;
        private string _creatingMachine;

        [mp.Column(Name = "DriveKey")]
        public int DriveKey
        {
            get
            {
                return _driveKey;
            }

            set
            {
                _driveKey = value;
            }
        }

        [mp.Column(Name = "DriveName")]
        public string DriveName
        {
            get
            {
                return _driveName;
            }

            set
            {
                _driveName = value;
            }
        }

        [mp.Column(Name = "DrivePathString")]
        public string DrivePathString
        {
            get
            {
                return _drivePathString;
            }

            set
            {
                _drivePathString = value;
            }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set
            {
                _dateCreated = value;
            }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set
            {
                _timeCreated = value;
            }
        }

        [mp.Column(Name = "CreatingUser")]
        public string CreatingUser
        {
            get
            {
                return _creatingUser;
            }

            set
            {
                _creatingUser = value;
            }
        }

        [mp.Column(Name = "CreatingMachine")]
        public string CreatingMachine
        {
            get
            {
                return _creatingMachine;
            }

            set
            {
                _creatingMachine = value;
            }
        }
    }

    public class JobPathRootDataContext : lq.DataContext
    {
        public JobPathRootDataContext(string cs)
            : base(cs)
        {

        }

        public JobPathRootDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<JobPathRoot> JobPathRoot;
    }

}
