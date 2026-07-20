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

namespace PM_Project_Tracking.DataClasses
{
    public class ShipHeaderSessions
    {
        internal static ShipHeaderSession CheckSession(string jobNumber, int memoNumber)
        {
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            ShipHeaderSession quoteSession = null;

            try
            {
                var sessionQuery = from session in dtCtx.GetTable<ShipHeaderSession>()
                                   where session.JobNumber == jobNumber && session.MemoNumber == memoNumber
                                   select new
                                   {
                                       SessionId = session.SessionId,
                                       JobNumber = session.JobNumber,
                                       MemoNumber = session.MemoNumber,
                                       DomainUserName = session.DomainUserName,
                                       SessionDate = session.SessionDate,
                                       SessionTime = session.SessionTime
                                   };

                quoteSession = sessionQuery.AsEnumerable().Select(x => new ShipHeaderSession(x.SessionId, x.JobNumber, x.MemoNumber,
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

        internal static void CreateSession(string jobNumber, int memoNumber)
        {
            bool _contBool = false;
            int _sessionId = GetNextSessionId(out _contBool);

            if (_contBool)
            {
                try
                {
                    ShipHeaderSession session = new ShipHeaderSession(_sessionId, jobNumber, memoNumber, Environment.UserName
                                                                   , DateTime.Today, DateTime.Now);

                    using (ShipHeaderSessionDataContext dtCtx = new ShipHeaderSessionDataContext(GlobalVars.UcshConnectionString))
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

        internal static void DeleteSession(string jobNumber, int memoNumber)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "DELETE FROM WHSHIPHEADERSESSION WHERE JobNumber='" + jobNumber + "' AND MemoNumber='" + memoNumber + "'";

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
                strQuery = "select MAX(SessionId) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[WHSHIPHEADERSESSION]";
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

    [mp.Table(Name = "WHSHIPHEADERSESSION")]
    public class ShipHeaderSession
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;  //Doesn't need this but good to have just in case.

        private int _sessionId;
        private string _jobNumber;
        private int _memoNumber;
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

        [mp.Column(Name = "MemoNumber", IsPrimaryKey = true)]
        public int MemoNumber
        {
            get { return _memoNumber; }
            set { _memoNumber = value; }
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

        public ShipHeaderSession()
        {
        }

        public ShipHeaderSession(string jobNumber, int memoNumber)
        {
            this._jobNumber = jobNumber;
            this._memoNumber = memoNumber;
        }

        public ShipHeaderSession(int sessionId, string jobNumber, int memoNumber, string domainUserName, DateTime? sessionDate, DateTime? sessionTime)
        {
            this._sessionId = sessionId;
            this._jobNumber = jobNumber;
            this._memoNumber = memoNumber;
            this._domainUserName = domainUserName;
            this._sessionDate = sessionDate;
            this._sessionTime = sessionTime;
        }
    }

    public class ShipHeaderSessionDataContext : lq.DataContext
    {
        public ShipHeaderSessionDataContext(string cs)
            : base(cs)
        {
        }

        public ShipHeaderSessionDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ShipHeaderSession> ChangeQuoteSession;
    }
}
