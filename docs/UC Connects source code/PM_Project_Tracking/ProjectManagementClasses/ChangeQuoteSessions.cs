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
    class ChangeQuoteSessions
    {
        internal static ChangeQuoteSession CheckSession(string jobNumber, string quoteNumber)
        {
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            ChangeQuoteSession quoteSession = null;

            try
            {
                var sessionQuery = from session in dtCtx.GetTable<ChangeQuoteSession>()
                                   where session.JobNumber == jobNumber && session.QuoteNumber == quoteNumber
                                   select new
                                   {
                                       SessionId = session.SessionId,
                                       JobNumber = session.JobNumber,
                                       QuoteNumber = session.QuoteNumber,
                                       DomainUserName = session.DomainUserName,
                                       SessionDate = session.SessionDate,
                                       SessionTime = session.SessionTime
                                   };

                quoteSession = sessionQuery.AsEnumerable().Select(x => new ChangeQuoteSession(x.SessionId, x.JobNumber, x.QuoteNumber,
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

            return quoteSession;
        }

        internal static ObservableCollection<ChangeQuoteSession> GetAllSessions()
        {
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            List<ChangeQuoteSession> quoteSessions = null;

            try
            {
                var sessionQuery = from session in dtCtx.GetTable<ChangeQuoteSession>()
                                   select new
                                   {
                                       SessionId = session.SessionId,
                                       JobNumber = session.JobNumber,
                                       QuoteNumber = session.QuoteNumber,
                                       DomainUserName = session.DomainUserName,
                                       SessionDate = session.SessionDate,
                                       SessionTime = session.SessionTime
                                   };

                quoteSessions = sessionQuery.AsEnumerable().Select(x => new ChangeQuoteSession(x.SessionId, x.JobNumber, x.QuoteNumber,
                                                                                              x.DomainUserName, x.SessionDate, x.SessionTime)).ToList();


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

            return new ObservableCollection<ChangeQuoteSession>(quoteSessions);
        }

        internal static void CreateSession(string jobNumber, string quoteNumber)
        {
            bool _contBool = false;
            int _sessionId = GetNextSessionId(out _contBool);

            if (_contBool)
            {
                try
                {
                    ChangeQuoteSession session = new ChangeQuoteSession(_sessionId, jobNumber, quoteNumber, Environment.UserName
                                                                   , DateTime.Today, DateTime.Now);

                    using (ChangeQuoteSessionDataContext dtCtx = new ChangeQuoteSessionDataContext(GlobalVars.UcshConnectionString))
                    {
                        dtCtx.ChangeQuoteSession.InsertOnSubmit(session);
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

        internal static void DeleteSession(string jobNumber, string quoteNumber)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "DELETE FROM PMCHANGELINESESSION WHERE JobNumber='" + jobNumber + "' AND QuoteNumber='" + quoteNumber + "'";

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
                strQuery = "select MAX(SessionId) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMCHANGELINESESSION]";
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

    [mp.Table(Name = "PMCHANGELINESESSION")]
    public class ChangeQuoteSession
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;  //Doesn't need this but good to have just in case.

        private int _sessionId;
        private string _jobNumber;
        private string _quoteNumber;
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

        [mp.Column(Name = "QuoteNumber", IsPrimaryKey = true)]
        public string QuoteNumber
        {
            get { return _quoteNumber; }
            set { _quoteNumber = value; }
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

        public ChangeQuoteSession()
        {
        }

        public ChangeQuoteSession(string jobNumber, string quoteNumber)
        {
            this._jobNumber = jobNumber;
            this._quoteNumber = quoteNumber;
        }

        public ChangeQuoteSession(int sessionId, string jobNumber, string quoteNumber, string domainUserName, DateTime? sessionDate, DateTime? sessionTime)
        {
            this._sessionId = sessionId;
            this._jobNumber = jobNumber;
            this._quoteNumber = quoteNumber;
            this._domainUserName = domainUserName;
            this._sessionDate = sessionDate;
            this._sessionTime = sessionTime;
        }
    }

    public class ChangeQuoteSessionDataContext : lq.DataContext
    {
        public ChangeQuoteSessionDataContext(string cs)
            : base(cs)
        {
        }

        public ChangeQuoteSessionDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ChangeQuoteSession> ChangeQuoteSession;
    }
}
