using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Data;
using System.Data.SqlClient;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using dc = PM_Project_Tracking.DataClasses;

namespace PM_Project_Tracking.EConnect.SupportProcedures
{
    public static class taPopRcptLandedCostNew
    {
        public static void CreateLandedCosts(ObservableCollection<dc.ReceivingLine> recLines)
        {
            //http://csharp-station.com/Tutorial/AdoDotNet/Lesson07
            string connStr = @"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=UCSH;Integrated Security=SSPI;";
            SqlConnection conn = new SqlConnection(connStr);
            SqlCommand cmd = new SqlCommand("dbo.taPopRcptLandedCost", conn);
            cmd.CommandType = System.Data.CommandType.StoredProcedure;


            try
            {
                conn.Open();
                AddParameters(cmd, recLines);

                cmd.ExecuteNonQuery();
                if (cmd.Parameters["@O_iErrorState"] != null)
                {
                    MessageBox.Show(cmd.Parameters["@O_iErrorState"].Value.ToString());
                }

            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (Exception Ex)
            {
                MessageBox.Show(Ex.ToString());
            }
            finally
            {
                conn.Close();
            }
        }

        private static void AddParameters(SqlCommand cmd, ObservableCollection<dc.ReceivingLine> recLines)
        {
            cmd.Parameters.AddWithValue("@I_vPOPRCTNM", "RCT062522");         //required
            cmd.Parameters.AddWithValue("@I_vLanded_Cost_ID", "MISC");        //required

            cmd.Parameters.AddWithValue("@I_vRCPTLNNM", (int)0);               //Receipt Line Number - 0 = Landed Cost will be calculated for all lines, anything else is a specific entry
            cmd.Parameters.AddWithValue("@I_vLCLINENUMBER", (int)16384);               //Landed Cost Line Number 
            cmd.Parameters.AddWithValue("@I_vLCHDRNUMBER", (int)0);                //Landed Cost Header Number

            cmd.Parameters.AddWithValue("@I_vVENDORID", "");               //
            cmd.Parameters.AddWithValue("@I_vApportion_By", (short)1);
            //cmd.Parameters.AddWithValue("@I_vreceiptdate", DateTime.Today.ToString("yyyy/MM/dd"));

            SqlParameter errIntOutput = new SqlParameter("@O_iErrorState", SqlDbType.SmallInt);
            cmd.Parameters.Add(errIntOutput);
            cmd.Parameters["@O_iErrorState"].Direction = ParameterDirection.Output;
            SqlParameter errStrOutput = new SqlParameter("@oErrString", SqlDbType.VarChar);
            cmd.Parameters.Add(errStrOutput);
            cmd.Parameters["@oErrString"].Direction = ParameterDirection.Output;

        }
    }



    //working version
    public static class taPopRcptLandedCostOld
    {
        public static void CreateLandedCosts(ObservableCollection<dc.ReceivingLine> recLines)
        {
            //http://csharp-station.com/Tutorial/AdoDotNet/Lesson07
            string connStr = @"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=UCSH;Integrated Security=SSPI;";
            SqlConnection conn = new SqlConnection(connStr);
            SqlCommand cmd = new SqlCommand("dbo.taPopRcptLandedCost", conn);
            cmd.CommandType = System.Data.CommandType.StoredProcedure;


            try
            {
                conn.Open();
                AddParameters(cmd, recLines);

                SqlParameter errIntOutput = new SqlParameter("@O_iErrorState", (short)0);
                cmd.Parameters.Add(errIntOutput);
                cmd.Parameters["@O_iErrorState"].Direction = ParameterDirection.Output;

                cmd.Parameters.AddWithValue("@oErrString", "");
                //int i = 
                cmd.ExecuteNonQuery();
                if (errIntOutput != null)
                {
                    int idFromString = int.Parse(errIntOutput.Value.ToString());
                }

            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (Exception Ex)
            {
                MessageBox.Show(Ex.ToString());
            }
            finally
            {
                conn.Close();
            }
        }

        private static void AddParameters(SqlCommand cmd, ObservableCollection<dc.ReceivingLine> recLines)
        {
            cmd.Parameters.AddWithValue("@I_vPOPRCTNM", "RCT062522");         //required
            cmd.Parameters.AddWithValue("@I_vLanded_Cost_ID", "MISC");        //required

            cmd.Parameters.AddWithValue("@I_vRCPTLNNM", (int)0);      //16384         //Receipt Line Number - 0 = Landed Cost will be calculated for all lines, anything else is a specific entry
            cmd.Parameters.AddWithValue("@I_vLCLINENUMBER", (int)16384);               //Landed Cost Line Number 
            cmd.Parameters.AddWithValue("@I_vLCHDRNUMBER", (int)0);   //16384            //Landed Cost Header Number

            cmd.Parameters.AddWithValue("@I_vVENDORID", "SHE101");               //
            cmd.Parameters.AddWithValue("@I_vApportion_By", (short)1);
            //cmd.Parameters.AddWithValue("@I_vreceiptdate", DateTime.Today.ToString("yyyy/MM/dd"));

        }
    }
}
