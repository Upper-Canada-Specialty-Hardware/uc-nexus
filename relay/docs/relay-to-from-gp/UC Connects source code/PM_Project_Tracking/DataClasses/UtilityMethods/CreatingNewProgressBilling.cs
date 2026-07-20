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
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using System.Data;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    class CreatingNewProgressBilling
    {
        //get latest prog bill iteration, then revision num.  In case of revisions being made, cancel previous.

        //private int iter
        //private int revision

        public static void CreateNewProgressBilling(dc.CombinedProject combProj, bool isRevision, string billingName, string hstNumber, string contractNumber)
        {
            int _maxIter;
            pm.ProgressBillingHeader _latestProgBill;
            pm.ProgressBillingHeader _newPbHeader;
            _maxIter = GetMaxHeaderIteration(combProj.MainProject.JobNumber);
            //_maxIter = 0;
            _latestProgBill = GetLatestProgressBilling(combProj.MainProject.JobNumber, _maxIter);

            if (_latestProgBill != null && _latestProgBill.Billed == false)
            {
                MessageBox.Show("Cannot create new progress billing when previous (" + _latestProgBill.BillingName + ") has not been posted or billed.");
                return;
            }

            if (_latestProgBill == null)  //First progress billing, not need for the other procedures since there would not be any pb lines or draw downs created prior to the first billing header
            {
                _newPbHeader = new pm.ProgressBillingHeader(combProj, billingName, hstNumber, contractNumber);
                pm.ProgressBillingHeaders.CreateNewProgressBilling(_newPbHeader);
            }
            else if (isRevision)
                CreateNewProgressBill(_latestProgBill, billingName, false);
            else                                                                    //Create Next Month's progress billing from last pb (rev or otherwise)
                CreateNewProgressBill(_latestProgBill, billingName, true);
        }

        internal static int GetMaxHeaderIteration(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(Iteration) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMPROGRESSBILLINGHEADER101] where JobNumber='" + jobNumber + "'";
                comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var _maxVal = comm.ExecuteScalar();
                if (_maxVal.GetType() == typeof(System.DBNull))
                    return 1;
                else
                    return (int)_maxVal;
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

            return _idVal;
        }

        internal static pm.ProgressBillingHeader GetLatestProgressBilling(string jobNumber, int maxIter)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<pm.ProgressBillingHeader> headerList = null;

            try
            {
                var pbHeaderQuery = from pb in dtCtx.GetTable<pm.ProgressBillingHeader>()
                                    where pb.JobNumber == jobNumber && pb.Iteration == maxIter
                                    select new
                                    {
                                        Id = pb.Id,
                                        JobNumber = pb.JobNumber,
                                        Iteration = pb.Iteration,
                                        BillingName = pb.BillingName,
                                        Cancelled = pb.Cancelled,
                                        Revision = pb.Revision,
                                        Billed = pb.Billed,
                                        BillingDate = pb.BillingDate,
                                        BillingUser = pb.BillingUser,
                                        DateCreated = pb.DateCreated,
                                        TimeCreated = pb.TimeCreated,
                                        UpdatingUser = pb.UpdatingUser,
                                        UpdatingMachine = pb.UpdatingMachine
                                    };

                headerList = pbHeaderQuery.AsEnumerable().Select(x => new pm.ProgressBillingHeader(x.Id, x.JobNumber, x.Iteration, x.BillingName, x.Cancelled
                                                                                         , x.Revision, x.Billed, x.BillingDate, x.BillingUser, x.DateCreated
                                                                                         , x.TimeCreated, x.UpdatingUser, x.UpdatingMachine)).ToList();
            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }

            if (headerList == null || headerList.Count == 0)
                return null;
            else
                return headerList.Where(x => x.Revision == headerList.Max(r => r.Revision)).FirstOrDefault(); //This should grab the highest no matter what

        }

        private static void CreateNewProgressBill(pm.ProgressBillingHeader pbHeader, string billName, bool isNewBilling)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);

            try
            {

                SqlCommand cmd = new SqlCommand("dbo.CreateNewProgressBillingData", conn);
                cmd.CommandType = CommandType.StoredProcedure;
                cmd.Parameters.Add(new SqlParameter("jobNumber", pbHeader.JobNumber));
                cmd.Parameters.Add(new SqlParameter("iteration", pbHeader.Iteration));
                cmd.Parameters.Add(new SqlParameter("revision", pbHeader.Revision));
                cmd.Parameters.Add(new SqlParameter("billName", billName));
                cmd.Parameters.Add(new SqlParameter("isNewBilling", isNewBilling));
                cmd.Parameters.Add(new SqlParameter("updatingUser", Environment.UserName));
                cmd.Parameters.Add(new SqlParameter("updatingMachine", Environment.MachineName));
                cmd.Parameters.Add(new SqlParameter("dateCreated", DateTime.Today));
                cmd.Parameters.Add(new SqlParameter("timeCreated", DateTime.Now));
                conn.Open();
                cmd.ExecuteNonQuery();
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
                conn.Close();
                conn.Dispose();
            }
        }
    }
}
