using System;
using System.Collections.Generic;
using System.Linq;
using System.Data;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Data.SqlClient;
using System.Text;
using System.Threading.Tasks;
using System.Collections.ObjectModel;
using System.ComponentModel;
using PM_Project_Tracking.ProjectManagementClasses.ProjectManagementUtililtyClasses.CostCodeAggregateModel;
using System.Windows;

namespace PM_Project_Tracking.ProjectManagementClasses.ProjectManagementUtililtyClasses.CostCodeAggregateViewModel
{
    //http://blogs.msmvps.com/deborahk/populating-a-datagrid-with-dynamic-columns-in-a-silverlight-application-using-mvvm/
    //public class CostCodeViewModel : INotifyPropertyChanged
    //{
    //    private string _jobNumber;
    //    private List<string> _costCodeColumnList;
    //    private ObservableCollection<ChangeQuoteAggregate> _sellQuoteList;
    //    private ObservableCollection<ChangeQuoteAggregate> _costQuoteList;

    //    public List<string> CostCodeColumnList
    //    {
    //        get
    //        {
    //            return _costCodeColumnList;
    //        }
    //        set
    //        {
    //            if (_costCodeColumnList != value)
    //            {
    //                _costCodeColumnList = value;
    //                OnPropertyChanged("CostCodeColumnList");
    //            }
    //        }
    //    }

    //    public ObservableCollection<ChangeQuoteAggregate> SellQuoteList
    //    {
    //        get
    //        {
    //            return _sellQuoteList;
    //        }
    //        set
    //        {
    //            if (_sellQuoteList != value)
    //            {
    //                _sellQuoteList = value;
    //                OnPropertyChanged("SellQuoteList");
    //            }
    //        }
    //    }

    //    public ObservableCollection<ChangeQuoteAggregate> CostQuoteList
    //    {
    //        get
    //        {
    //            return _costQuoteList;
    //        }
    //        set
    //        {
    //            if (_costQuoteList != value)
    //            {
    //                _costQuoteList = value;
    //                OnPropertyChanged("CostQuoteList");
    //            }
    //        }
    //    }

    //    public CostCodeViewModel()
    //    {
    //        //GetCostCodes();
    //        //GetSellValues();
    //        //GetCostValues();
    //    }

    //    public CostCodeViewModel(string jobNumber)
    //    {
    //        _jobNumber = jobNumber;
    //        GetCostCodes();
    //        GetSellValues();
    //        GetCostValues();
    //    }

    //    public void GetCostCodes()
    //    {
    //        SqlConnection conn = null;
    //        SqlDataReader rdr = null;
    //        var itemNameList = new List<string>();

    //        try
    //        {
    //            conn = new SqlConnection(GlobalVars.UcshConnectionString);
    //            string strQuery = "SELECT DISTINCT CostCode FROM [" + GlobalVars.UcshDatabaseName + "].[dbo].[PMCHANGELINE101] WHERE JobNumber='" + this._jobNumber + "'";
    //            SqlCommand cmd = new SqlCommand(strQuery, conn);
    //            conn.Open();
    //            rdr = cmd.ExecuteReader();

    //            if (rdr.HasRows)
    //            {
    //                while (rdr.Read())
    //                {
    //                    itemNameList.Add(rdr[0].ToString());
    //                }
    //            }

    //        }
    //        catch (SqlException sqlEx)
    //        {
    //            MessageBox.Show(sqlEx.ToString());
    //        }
    //        catch (Exception ex)
    //        {
    //            MessageBox.Show(ex.ToString());
    //        }
    //        finally
    //        {
    //            rdr.Close();
    //            conn.Close();
    //        }

    //        CostCodeColumnList = itemNameList;
    //    }

    //    public void GetSellValues()
    //    {
    //        SqlConnection conn = null;
    //        SqlDataReader rdr = null;
    //        var itemList = new ObservableCollection<ChangeQuoteAggregate>();

    //        try
    //        {
    //            conn = new SqlConnection(GlobalVars.UcshConnectionString);
    //            SqlCommand cmd = new SqlCommand("dbo.GetChangeLineSellSumsByJob", conn);
    //            cmd.CommandType = CommandType.StoredProcedure;
    //            cmd.Parameters.Add(new SqlParameter("jobNum", this._jobNumber));
    //            conn.Open();
    //            rdr = cmd.ExecuteReader();

    //            while (rdr.Read())
    //            {
    //                ChangeQuoteAggregate tempCq = new ChangeQuoteAggregate();
    //                tempCq.QuoteNumber = rdr.GetValue(0).ToString();
    //                for (int x = 1; x < rdr.FieldCount; x++)    //starting at 1 because we're ignoring the QuoteName field
    //                {
    //                    decimal sum = (rdr.GetValue(x) is DBNull) ? 0 : (decimal)rdr.GetValue(x);
    //                    tempCq.SellSums.Add(sum);
    //                }
    //                itemList.Add(tempCq);
    //            }

    //        }
    //        catch (SqlException sqlEx)
    //        {
    //            MessageBox.Show(sqlEx.ToString());
    //        }
    //        catch (Exception ex)
    //        {
    //            MessageBox.Show(ex.ToString());
    //        }
    //        finally
    //        {
    //            rdr.Close();
    //            conn.Close();
    //            this.SellQuoteList = itemList;
    //        }
    //    }

    //    public void GetCostValues()
    //    {
    //        SqlConnection conn = null;
    //        SqlDataReader rdr = null;
    //        var itemList = new ObservableCollection<ChangeQuoteAggregate>();

    //        try
    //        {
    //            conn = new SqlConnection(GlobalVars.UcshConnectionString);
    //            SqlCommand cmd = new SqlCommand("dbo.GetChangeLineCostSumsByJob", conn);
    //            cmd.CommandType = CommandType.StoredProcedure;
    //            cmd.Parameters.Add(new SqlParameter("jobNum", this._jobNumber));
    //            conn.Open();
    //            rdr = cmd.ExecuteReader();

    //            while (rdr.Read())
    //            {
    //                ChangeQuoteAggregate tempCq = new ChangeQuoteAggregate();
    //                tempCq.QuoteNumber = rdr.GetValue(0).ToString();
    //                for (int x = 1; x < rdr.FieldCount; x++)    //starting at 1 because we're ignoring the QuoteName field
    //                {
    //                    decimal sum = (rdr.GetValue(x) is DBNull) ? 0 : (decimal)rdr.GetValue(x);
    //                    tempCq.SellSums.Add(sum);
    //                }
    //                itemList.Add(tempCq);
    //            }

    //        }
    //        catch (SqlException sqlEx)
    //        {
    //            MessageBox.Show(sqlEx.ToString());
    //        }
    //        catch (Exception ex)
    //        {
    //            MessageBox.Show(ex.ToString());
    //        }
    //        finally
    //        {
    //            rdr.Close();
    //            conn.Close();
    //            this.CostQuoteList = itemList;
    //        }

    //    }

    //    public event PropertyChangedEventHandler PropertyChanged;
    //    private void OnPropertyChanged(string propertyName)
    //    {
    //        if (PropertyChanged != null)
    //            PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
    //    }
    //} 
}
