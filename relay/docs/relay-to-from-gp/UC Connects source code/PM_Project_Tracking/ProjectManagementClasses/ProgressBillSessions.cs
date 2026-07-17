using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.ComponentModel;
using System.Collections.ObjectModel;
using System.Windows;
using System.Data.SqlClient;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.ProjectManagementClasses
{
    class ProgressBillSessions
    {
        internal static ProgressBillSession CheckSession(string jobNumber, int iteration, int revision)
        {
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            ProgressBillSession progBillSession = null;

            try
            {
                var sessionQuery = from session in dtCtx.GetTable<ProgressBillSession>()
                                   where session.JobNumber == jobNumber && session.Iteration == iteration && session.Revision == revision
                                   select new
                                   {
                                       SessionId = session.SessionId,
                                       JobNumber = session.JobNumber,
                                       Iteration = session.Iteration,
                                       Revision = session.Revision,
                                       DomainUserName = session.DomainUserName,
                                       SessionDate = session.SessionDate,
                                       SessionTime = session.SessionTime
                                   };

                progBillSession = sessionQuery.AsEnumerable().Select(x => new ProgressBillSession(x.SessionId, x.JobNumber, x.Iteration, x.Revision,
                                                                                              x.DomainUserName, x.SessionDate, x.SessionTime)).SingleOrDefault();


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
                dtCtx.Dispose();
            }

            return progBillSession;
        }

        internal static void CreateSession(string jobNumber, int iteration, int revision)
        {
            bool _contBool = false;
            int _sessionId = GetNextSessionId(out _contBool);

            if (_contBool)
            {
                try
                {
                    ProgressBillSession session = new ProgressBillSession(_sessionId, jobNumber, iteration, revision, Environment.UserName
                                                                   , DateTime.Today, DateTime.Now);

                    using (ProgressBillSessionDataContext dtCtx = new ProgressBillSessionDataContext(GlobalVars.UcshConnectionString))
                    {
                        dtCtx.ProgressBillSession.InsertOnSubmit(session);
                        dtCtx.SubmitChanges();
                    }
                }
                catch (SqlException sqlEx)
                {
                    MessageBox.Show(sqlEx.ToString());
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
            }
        }

        internal static void DeleteSession(string jobNumber, int iteration, int revision)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "DELETE FROM PMPROGRESSBILLSESSION WHERE JobNumber='" + jobNumber + "' AND Iteration='" + iteration + "' AND Revision='" + revision + "'";

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

        private static int GetNextSessionId(out bool contBool)
        {
            contBool = true;
            int _sessionIdVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(SessionId) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMPROGRESSBILLSESSION]";
                comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var _maxVal = comm.ExecuteScalar();
                if (_maxVal.GetType() == typeof(System.DBNull))
                    return 1;
                else
                    _sessionIdVal = (int)_maxVal + 1;
            }
            catch (SqlException sqlEx)
            {
                contBool = false;
                MessageBox.Show(sqlEx.ToString());
            }
            catch (Exception ex)
            {
                contBool = false;
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                if (conn != null)
                    conn.Close();
            }

            return _sessionIdVal;
        }
    }

    [mp.Table(Name = "PMPROGRESSBILLSESSION")]
    public class ProgressBillSession
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;  //Doesn't need this but good to have just in case.

        private int _sessionId;
        private string _jobNumber;
        private int _iteration;
        private int _revision;

        private string _domainUserName;
        private DateTime? _sessionDate;
        private DateTime? _sessionTime;

        [mp.Column(Name = "SessionId")]
        public int SessionId
        {
            get { return _sessionId; }
            set { _sessionId = value; }
        }

        [mp.Column(Name = "JobNumber", IsPrimaryKey = true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "Iteration", IsPrimaryKey = true)]
        public int Iteration
        {
            get { return _iteration; }
            set { _iteration = value; }
        }

        [mp.Column(Name = "Revision", IsPrimaryKey = true)]
        public int Revision
        {
            get { return _revision; }
            set { _revision = value; }
        }

        [mp.Column(Name = "DomainUserName")]
        public string DomainUserName
        {
            get { return _domainUserName; }
            set { _domainUserName = value; }
        }

        [mp.Column(Name = "SessionDate")]
        public DateTime? SessionDate
        {
            get { return _sessionDate; }
            set { _sessionDate = value; }
        }

        [mp.Column(Name = "SessionTime", DbType = "Time", CanBeNull = true)]
        public DateTime? SessionTime
        {
            get { return _sessionTime; }
            set { _sessionTime = value; }
        }

        public ProgressBillSession()
        {
        }

        public ProgressBillSession(string jobNumber, int iteration, int revision)
        {
            this._jobNumber = jobNumber;
            this._iteration = iteration;
            this._revision = revision;
        }

        public ProgressBillSession(int sessionId, string jobNumber, int iteration, int revision, string domainUserName, DateTime? sessionDate, DateTime? sessionTime)
        {
            this._sessionId = sessionId;
            this._jobNumber = jobNumber;
            this._iteration = iteration;
            this._revision = revision;
            this._domainUserName = domainUserName;
            this._sessionDate = sessionDate;
            this._sessionTime = sessionTime;
        }
    }

    public class ProgressBillSessionDataContext : lq.DataContext
    {
        public ProgressBillSessionDataContext(string cs)
            : base(cs)
        {
        }

        public ProgressBillSessionDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ProgressBillSession> ProgressBillSession;
    }
}
