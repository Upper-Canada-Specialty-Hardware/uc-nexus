using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.ComponentModel;
using System.Data.SqlClient;
using System.Collections.ObjectModel;
using System.Windows;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using PM_Project_Tracking.DataClasses.Interfaces;
using System.Reflection;
using System.Windows.Markup;

namespace PM_Project_Tracking.DataClasses
{
    //[AttributeUsage(AttributeTargets.Property | AttributeTargets.Field, Inherited = true, AllowMultiple = false)]
    //[ImmutableObject(true)]
    //public sealed class CostCodeAttr : Attribute
    //{
    //    private readonly string _costCodeFamily;
    //    public string CostCodeFamily { get { return _costCodeFamily; } }
    //    public CostCodeAttr(string costCodeFamily) { this._costCodeFamily = costCodeFamily; }
    //}

    class QuoteSummaries
    {
        internal static ObservableCollection<QuoteSummary> GetQuotesByJob(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<QuoteSummary> quoteList = null;

            try
            {
                var preQuery = from qs in dtCtx.GetTable<QuoteSummary>()
                               where qs.JobNumber == jobNumber
                               orderby qs.QuoteNumber, qs.RevisionIteration
                               select new
                               {
                                   Id = qs.Id,
                                   Iteration = qs.Iteration,
                                   JobNumber = qs.JobNumber,
                                   JobName = qs.JobName,
                                   QuoteNumber = qs.QuoteNumber,
                                   IsRevision = qs.IsRevision,
                                   OriginatingDocumentNumber = qs.OriginatingDocumentNumber,
                                   RevisionIteration = qs.RevisionIteration,
                                   Contractor = qs.Contractor,
                                   ClosingDate = qs.ClosingDate,

                                   PstTax = qs.PstTax,
                                   GstTax = qs.GstTax,

                                   FieldInstall = qs.FieldInstall == null ? 0 : qs.FieldInstall,
                                   FrameInstall = qs.FrameInstall == null ? 0 : qs.FrameInstall,
                                   AutoOperatorInstall = qs.AutoOperatorInstall == null ? 0 : qs.AutoOperatorInstall,

                                   NumberOfDoorLeafs = qs.NumberOfDoorLeafs,
                                   RevenuePerDoor = qs.RevenuePerDoor,

                                   Cc2102002Cost = qs.Cc2102002Cost,
                                   Cc2200002Cost = qs.Cc2200002Cost,
                                   Cc3100003Cost = qs.Cc3100003Cost,
                                   Cc3200003Cost = qs.Cc3200003Cost,
                                   Cc3300003Cost = qs.Cc3300003Cost,
                                   Cc3400003Cost = qs.Cc3400003Cost,
                                   Cc3500003Cost = qs.Cc3500003Cost,
                                   Cc4100004Cost = qs.Cc4100004Cost,
                                   Cc4200004Cost = qs.Cc4200004Cost,
                                   Cc4300004Cost = qs.Cc4300004Cost,
                                   Cc4400004Cost = qs.Cc4400004Cost,
                                   Cc4500004Cost = qs.Cc4500004Cost,
                                   Cc4600004Cost = qs.Cc4600004Cost,
                                   Cc5100005Cost = qs.Cc5100005Cost,
                                   Cc5200005Cost = qs.Cc5200005Cost,
                                   Cc5300005Cost = qs.Cc5300005Cost,
                                   Cc5400005Cost = qs.Cc5400005Cost,
                                   Cc5500005Cost = qs.Cc5500005Cost,
                                   Cc5600005Cost = qs.Cc5600005Cost,
                                   Cc5700005Cost = qs.Cc5700005Cost,
                                   Cc5800005Cost = qs.Cc5800005Cost,
                                   Cc6100006Cost = qs.Cc6100006Cost,
                                   Cc6200006Cost = qs.Cc6200006Cost,
                                   Cc6300006Cost = qs.Cc6300006Cost,
                                   Cc6400006Cost = qs.Cc6400006Cost,
                                   Cc7100007Cost = qs.Cc7100007Cost,
                                   Cc7200007Cost = qs.Cc7200007Cost,
                                   Cc7300007Cost = qs.Cc7300007Cost,
                                   Cc8000008Cost = qs.Cc8000008Cost,
                                   Cc9000009Cost = qs.Cc9000009Cost,

                                   Cc2102002Sell = qs.Cc2102002Sell,
                                   Cc2200002Sell = qs.Cc2200002Sell,
                                   Cc3100003Sell = qs.Cc3100003Sell,
                                   Cc3200003Sell = qs.Cc3200003Sell,
                                   Cc3300003Sell = qs.Cc3300003Sell,
                                   Cc3400003Sell = qs.Cc3400003Sell,
                                   Cc3500003Sell = qs.Cc3500003Sell,
                                   Cc4100004Sell = qs.Cc4100004Sell,
                                   Cc4200004Sell = qs.Cc4200004Sell,
                                   Cc4300004Sell = qs.Cc4300004Sell,
                                   Cc4400004Sell = qs.Cc4400004Sell,
                                   Cc4500004Sell = qs.Cc4500004Sell,
                                   Cc4600004Sell = qs.Cc4600004Sell,
                                   Cc5100005Sell = qs.Cc5100005Sell,
                                   Cc5200005Sell = qs.Cc5200005Sell,
                                   Cc5300005Sell = qs.Cc5300005Sell,
                                   Cc5400005Sell = qs.Cc5400005Sell,
                                   Cc5500005Sell = qs.Cc5500005Sell,
                                   Cc5600005Sell = qs.Cc5600005Sell,
                                   Cc5700005Sell = qs.Cc5700005Sell,
                                   Cc5800005Sell = qs.Cc5800005Sell,
                                   Cc6100006Sell = qs.Cc6100006Sell,
                                   Cc6200006Sell = qs.Cc6200006Sell,
                                   Cc6300006Sell = qs.Cc6300006Sell,
                                   Cc6400006Sell = qs.Cc6400006Sell,
                                   Cc7100007Sell = qs.Cc7100007Sell,
                                   Cc7200007Sell = qs.Cc7200007Sell,
                                   Cc7300007Sell = qs.Cc7300007Sell,
                                   Cc8000008Sell = qs.Cc8000008Sell,
                                   Cc9000009Sell = qs.Cc9000009Sell,


                                   Cc2102002Mu = qs.Cc2102002Mu,
                                   Cc2200002Mu = qs.Cc2200002Mu,
                                   Cc3100003Mu = qs.Cc3100003Mu,
                                   Cc3200003Mu = qs.Cc3200003Mu,
                                   Cc3300003Mu = qs.Cc3300003Mu,
                                   Cc3400003Mu = qs.Cc3400003Mu,
                                   Cc3500003Mu = qs.Cc3500003Mu,
                                   Cc4100004Mu = qs.Cc4100004Mu,
                                   Cc4200004Mu = qs.Cc4200004Mu,
                                   Cc4300004Mu = qs.Cc4300004Mu,
                                   Cc4400004Mu = qs.Cc4400004Mu,
                                   Cc4500004Mu = qs.Cc4500004Mu,
                                   Cc4600004Mu = qs.Cc4600004Mu,
                                   Cc5100005Mu = qs.Cc5100005Mu,
                                   Cc5200005Mu = qs.Cc5200005Mu,
                                   Cc5300005Mu = qs.Cc5300005Mu,
                                   Cc5400005Mu = qs.Cc5400005Mu,
                                   Cc5500005Mu = qs.Cc5500005Mu,
                                   Cc5600005Mu = qs.Cc5600005Mu,
                                   Cc5700005Mu = qs.Cc5700005Mu,
                                   Cc5800005Mu = qs.Cc5800005Mu,
                                   Cc6100006Mu = qs.Cc6100006Mu,
                                   Cc6200006Mu = qs.Cc6200006Mu,
                                   Cc6300006Mu = qs.Cc6300006Mu,
                                   Cc6400006Mu = qs.Cc6400006Mu,
                                   Cc7100007Mu = qs.Cc7100007Mu,
                                   Cc7200007Mu = qs.Cc7200007Mu,
                                   Cc7300007Mu = qs.Cc7300007Mu,
                                   Cc8000008Mu = qs.Cc8000008Mu,
                                   Cc9000009Mu = qs.Cc9000009Mu,

                                   DateCreated = qs.DateCreated,
                                   TimeCreated =  qs.TimeCreated,
                                   UpdatingUser = qs.UpdatingUser,
                                   UpdatingMachine = qs.UpdatingMachine

                               };

                quoteList = preQuery.AsEnumerable().Select(x => new QuoteSummary(x.Id,
                                                                                x.Iteration,
                                                                                x.JobNumber,
                                                                                x.JobName,
                                                                                x.QuoteNumber,
                                                                                x.IsRevision,
                                                                                x.OriginatingDocumentNumber,
                                                                                x.RevisionIteration,
                                                                                x.Contractor,
                                                                                x.ClosingDate,

                                                                                x.PstTax,
                                                                                x.GstTax,

                                                                                x.FieldInstall,
                                                                                x.FrameInstall,
                                                                                x.AutoOperatorInstall,

                                                                                x.NumberOfDoorLeafs,
                                                                                x.RevenuePerDoor,

                                                                                x.Cc2102002Cost,
                                                                                x.Cc2200002Cost,
                                                                                x.Cc3100003Cost,
                                                                                x.Cc3200003Cost,
                                                                                x.Cc3300003Cost,
                                                                                x.Cc3400003Cost,
                                                                                x.Cc3500003Cost,
                                                                                x.Cc4100004Cost,
                                                                                x.Cc4200004Cost,
                                                                                x.Cc4300004Cost,
                                                                                x.Cc4400004Cost,
                                                                                x.Cc4500004Cost,
                                                                                x.Cc4600004Cost,
                                                                                x.Cc5100005Cost,
                                                                                x.Cc5200005Cost,
                                                                                x.Cc5300005Cost,
                                                                                x.Cc5400005Cost,
                                                                                x.Cc5500005Cost,
                                                                                x.Cc5600005Cost,
                                                                                x.Cc5700005Cost,
                                                                                x.Cc5800005Cost,
                                                                                x.Cc6100006Cost,
                                                                                x.Cc6200006Cost,
                                                                                x.Cc6300006Cost,
                                                                                x.Cc6400006Cost,
                                                                                x.Cc7100007Cost,
                                                                                x.Cc7200007Cost,
                                                                                x.Cc7300007Cost,
                                                                                x.Cc8000008Cost,
                                                                                x.Cc9000009Cost,

                                                                                x.Cc2102002Sell,
                                                                                x.Cc2200002Sell,
                                                                                x.Cc3100003Sell,
                                                                                x.Cc3200003Sell,
                                                                                x.Cc3300003Sell,
                                                                                x.Cc3400003Sell,
                                                                                x.Cc3500003Sell,
                                                                                x.Cc4100004Sell,
                                                                                x.Cc4200004Sell,
                                                                                x.Cc4300004Sell,
                                                                                x.Cc4400004Sell,
                                                                                x.Cc4500004Sell,
                                                                                x.Cc4600004Sell,
                                                                                x.Cc5100005Sell,
                                                                                x.Cc5200005Sell,
                                                                                x.Cc5300005Sell,
                                                                                x.Cc5400005Sell,
                                                                                x.Cc5500005Sell,
                                                                                x.Cc5600005Sell,
                                                                                x.Cc5700005Sell,
                                                                                x.Cc5800005Sell,
                                                                                x.Cc6100006Sell,
                                                                                x.Cc6200006Sell,
                                                                                x.Cc6300006Sell,
                                                                                x.Cc6400006Sell,
                                                                                x.Cc7100007Sell,
                                                                                x.Cc7200007Sell,
                                                                                x.Cc7300007Sell,
                                                                                x.Cc8000008Sell,
                                                                                x.Cc9000009Sell,

                                                                                x.Cc2102002Mu,
                                                                                x.Cc2200002Mu,
                                                                                x.Cc3100003Mu,
                                                                                x.Cc3200003Mu,
                                                                                x.Cc3300003Mu,
                                                                                x.Cc3400003Mu,
                                                                                x.Cc3500003Mu,
                                                                                x.Cc4100004Mu,
                                                                                x.Cc4200004Mu,
                                                                                x.Cc4300004Mu,
                                                                                x.Cc4400004Mu,
                                                                                x.Cc4500004Mu,
                                                                                x.Cc4600004Mu,
                                                                                x.Cc5100005Mu,
                                                                                x.Cc5200005Mu,
                                                                                x.Cc5300005Mu,
                                                                                x.Cc5400005Mu,
                                                                                x.Cc5500005Mu,
                                                                                x.Cc5600005Mu,
                                                                                x.Cc5700005Mu,
                                                                                x.Cc5800005Mu,
                                                                                x.Cc6100006Mu,
                                                                                x.Cc6200006Mu,
                                                                                x.Cc6300006Mu,
                                                                                x.Cc6400006Mu,
                                                                                x.Cc7100007Mu,
                                                                                x.Cc7200007Mu,
                                                                                x.Cc7300007Mu,
                                                                                x.Cc8000008Mu,
                                                                                x.Cc9000009Mu,

                                                                                x.DateCreated,
                                                                                x.TimeCreated,
                                                                                x.UpdatingUser,
                                                                                x.UpdatingMachine

                                                                                )).ToList();

            }
            catch(Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<QuoteSummary>(quoteList);
        }

        public static List<KeyValuePair<string, string>> GetUniqueJobList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<KeyValuePair<string, string>> _jobList = null;

            //Returns an IQueryable collection of KeyValue pair objects
            //var a = dtCtx.GetTable<QuoteSummary>().GroupBy(x => new { JobNumber = x.JobNumber, JobName = x.JobName }).Select(r => new KeyValuePair<string, string>(r.Key.JobNumber, r.Key.JobName) );

            //Returns a List collection of KeyValue pair objects but usees .AsEnumerable in between
            //var b = dtCtx.GetTable<QuoteSummary>().GroupBy(x => new { JobNumber = x.JobNumber, JobName = x.JobName }).Select(r => new { JobNumber = r.Key.JobNumber, JobName = r.Key.JobName })
            //                                        .AsEnumerable().Select(i => new KeyValuePair<string, string>(i.JobNumber, i.JobName)).ToList();

            try
            {
                //Returns a List collection of KeyValue pair objects
                _jobList = dtCtx.GetTable<QuoteSummary>().GroupBy(x => new { JobNumber = x.JobNumber, JobName = x.JobName }).Select(r => new KeyValuePair<string, string>(r.Key.JobNumber, r.Key.JobName)).ToList();
            }
            catch(Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return _jobList;
        }

        public static List<KeyValuePair<string, string>> GetEligibleJobList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<KeyValuePair<string, string>> _jobList = null;

            try
            {
                _jobList = dtCtx.GetTable<BidProject>().Where(x => !dtCtx.GetTable<QuoteSummary>().Any(i => i.JobNumber == x.JobNumber))
                                                        .GroupBy(x => new { JobNumber = x.JobNumber, JobName = x.JobName })
                                                        .Select(r => new KeyValuePair<string, string>(r.Key.JobNumber, r.Key.JobName)).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return _jobList;
        }

        public static void UpdateRelatedBidObject(QuoteSummary qs)
        {
            using (BidProjectDataContext dtCtx = new BidProjectDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    BidProject _bidProj = dtCtx.GetTable<BidProject>().Where(x => x.JobNumber == qs.JobNumber).FirstOrDefault();

                    if (_bidProj != null && _bidProj.EstProjValue <= 0)
                    {
                        _bidProj.EstProjValue = qs.UiSellTotalWithTax;
                        dtCtx.SubmitChanges();
                        MessageBox.Show("Projected value updated. Please refresh the bids in order to see the updated value.");
                    }
                    else if (_bidProj != null && _bidProj.EstProjValue > 0)
                    {
                        MessageBox.Show("Cannot update bid's value because its estimated project value is already above $0");
                    }
                    else if (_bidProj == null)
                    {
                        MessageBox.Show(qs.JobNumber + " is not found in the bids table.");
                    }
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
            }
        }

        public static bool CreateQuoteSummary(QuoteSummary qs)
        {
            bool _cont = false;

            using (QuoteSummaryDataContext dtCtx = new QuoteSummaryDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    int _headerId = GetNextQuoteSummaryId(qs.JobNumber);
                    qs.Id = _headerId;
                    qs.DateCreated = DateTime.Today;
                    qs.TimeCreated = DateTime.Now;
                    qs.UpdatingUser = Environment.UserName;
                    qs.UpdatingMachine = Environment.MachineName;
                    dtCtx.QuoteSummary.InsertOnSubmit(qs);
                    dtCtx.SubmitChanges();
                    _cont = true;  //Only reached if .SubmitChanges() does not throw an exception

                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                return _cont;
            }
        }

        public static bool UpdateQuoteSummary(QuoteSummary ch)
        {
            bool _retBool = true;
            using (QuoteSummaryDataContext dtCtx = new QuoteSummaryDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {

                    dtCtx.QuoteSummary.Attach(ch, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, ch);
                    //dtCtx.Refresh(lq.RefreshMode.KeepChanges, ch);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                    _retBool = false;
                }

                return _retBool;
            }
        }


        private static int GetNextQuoteSummaryId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[UTPMQUOTESUMMARY101]";
                comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var _maxVal = comm.ExecuteScalar();
                if (_maxVal.GetType() == typeof(System.DBNull))
                    return 1;
                else
                    _idVal = (int)_maxVal + 1;
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
    }

    [mp.Table(Name = "[UTPMQUOTESUMMARY101]")]
    public class QuoteSummary : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;          //primary key
        private string _jobName;
        private int _iteration;             //primary key
        private string _quoteNumber;
        private string _fullQuoteNumber;
        private string _contractor;
        private DateTime? _closingDate;

        private bool _isRevision;
        private string _originatingDocumentNumber;  //For tracking revision changes, this way we know how to iterate
        private string _originatingRevisionNumber;
        private int _revisionIteration;             //A straight number for which revision it is instead of playing string games with the full quote number like trying to get the next quote name from Q003r2
        // Might have to change all these public string properties to actual encapsulations later instead of autos

        private decimal _pstTax;
        private decimal _gstTax;

        private decimal _uiSellTotalWithTax;
        private decimal _uiSellTotal;

        private QsInstaller _fieldInstall;
        private QsInstaller _frameInstall;
        private QsInstaller _autoOperatorInstall;

        private decimal _numberOfDoorLeafs;
        private decimal _revenuePerDoor;

        private decimal _cc2102002Cost;
        private decimal _cc2200002Cost;
        private decimal _cc3100003Cost;
        private decimal _cc3200003Cost;
        private decimal _cc3300003Cost;
        private decimal _cc3400003Cost;
        private decimal _cc3500003Cost;
        private decimal _cc4100004Cost;
        private decimal _cc4200004Cost;     //not used?
        private decimal _cc4300004Cost;
        private decimal _cc4400004Cost;
        private decimal _cc4500004Cost;
        private decimal _cc4600004Cost;
        private decimal _cc5100005Cost;
        private decimal _cc5200005Cost;
        private decimal _cc5300005Cost;
        private decimal _cc5400005Cost;
        private decimal _cc5500005Cost;
        private decimal _cc5600005Cost;
        private decimal _cc5700005Cost;
        private decimal _cc5800005Cost;
        private decimal _cc6100006Cost;
        private decimal _cc6200006Cost;
        private decimal _cc6300006Cost;
        private decimal _cc6400006Cost;
        private decimal _cc7100007Cost;
        private decimal _cc7200007Cost;
        private decimal _cc7300007Cost;
        private decimal _cc8000008Cost;
        private decimal _cc9000009Cost;


        private decimal _cc2102002Sell;
        private decimal _cc2200002Sell;
        private decimal _cc3100003Sell;
        private decimal _cc3200003Sell;
        private decimal _cc3300003Sell;
        private decimal _cc3400003Sell;
        private decimal _cc3500003Sell;
        private decimal _cc4100004Sell;
        private decimal _cc4200004Sell;
        private decimal _cc4300004Sell;
        private decimal _cc4400004Sell;
        private decimal _cc4500004Sell;
        private decimal _cc4600004Sell;
        private decimal _cc5100005Sell;
        private decimal _cc5200005Sell;
        private decimal _cc5300005Sell;
        private decimal _cc5400005Sell;
        private decimal _cc5500005Sell;
        private decimal _cc5600005Sell;
        private decimal _cc5700005Sell;
        private decimal _cc5800005Sell;
        private decimal _cc6100006Sell;
        private decimal _cc6200006Sell;
        private decimal _cc6300006Sell;
        private decimal _cc6400006Sell;
        private decimal _cc7100007Sell;
        private decimal _cc7200007Sell;
        private decimal _cc7300007Sell;
        private decimal _cc8000008Sell;
        private decimal _cc9000009Sell;


        private decimal _cc2102002Mu;
        private decimal _cc2200002Mu;
        private decimal _cc3100003Mu;
        private decimal _cc3200003Mu;
        private decimal _cc3300003Mu;
        private decimal _cc3400003Mu;
        private decimal _cc3500003Mu;
        private decimal _cc4100004Mu;
        private decimal _cc4200004Mu;
        private decimal _cc4300004Mu;
        private decimal _cc4400004Mu;
        private decimal _cc4500004Mu;
        private decimal _cc4600004Mu;
        private decimal _cc5100005Mu;
        private decimal _cc5200005Mu;
        private decimal _cc5300005Mu;
        private decimal _cc5400005Mu;
        private decimal _cc5500005Mu;
        private decimal _cc5600005Mu;
        private decimal _cc5700005Mu;
        private decimal _cc5800005Mu;
        private decimal _cc6100006Mu;
        private decimal _cc6200006Mu;
        private decimal _cc6300006Mu;
        private decimal _cc6400006Mu;
        private decimal _cc7100007Mu;
        private decimal _cc7200007Mu;
        private decimal _cc7300007Mu;
        private decimal _cc8000008Mu;
        private decimal _cc9000009Mu;

        //UI only
        private decimal _cc2102002Margin;
        private decimal _cc2200002Margin;
        private decimal _cc3100003Margin;
        private decimal _cc3200003Margin;
        private decimal _cc3300003Margin;
        private decimal _cc3400003Margin;
        private decimal _cc3500003Margin;
        private decimal _cc4100004Margin;
        private decimal _cc4200004Margin;
        private decimal _cc4300004Margin;
        private decimal _cc4400004Margin;
        private decimal _cc4500004Margin;
        private decimal _cc4600004Margin;
        private decimal _cc5100005Margin;
        private decimal _cc5200005Margin;
        private decimal _cc5300005Margin;
        private decimal _cc5400005Margin;
        private decimal _cc5500005Margin;
        private decimal _cc5600005Margin;
        private decimal _cc5700005Margin;
        private decimal _cc5800005Margin;
        private decimal _cc6100006Margin;
        private decimal _cc6200006Margin;
        private decimal _cc6300006Margin;
        private decimal _cc6400006Margin;
        private decimal _cc7100007Margin;
        private decimal _cc7200007Margin;
        private decimal _cc7300007Margin;
        private decimal _cc8000008Margin;
        private decimal _cc9000009Margin;

        private decimal _cc2102002CostTax;
        private decimal _cc2200002CostTax;
        private decimal _cc3100003CostTax;
        private decimal _cc3200003CostTax;
        private decimal _cc3300003CostTax;
        private decimal _cc3400003CostTax;
        private decimal _cc3500003CostTax;
        private decimal _cc4100004CostTax;
        private decimal _cc4200004CostTax;
        private decimal _cc4300004CostTax;
        private decimal _cc4400004CostTax;
        private decimal _cc4500004CostTax;
        private decimal _cc4600004CostTax;
        private decimal _cc5100005CostTax;
        private decimal _cc5200005CostTax;
        private decimal _cc5300005CostTax;
        private decimal _cc5400005CostTax;
        private decimal _cc5500005CostTax;
        private decimal _cc5600005CostTax;
        private decimal _cc5700005CostTax;
        private decimal _cc5800005CostTax;
        private decimal _cc6100006CostTax;
        private decimal _cc6200006CostTax;
        private decimal _cc6300006CostTax;
        private decimal _cc6400006CostTax;
        private decimal _cc7100007CostTax;
        private decimal _cc7200007CostTax;
        private decimal _cc7300007CostTax;
        private decimal _cc8000008CostTax;
        private decimal _cc9000009CostTax;

        private decimal _cc2102002SellTax;
        private decimal _cc2200002SellTax;
        private decimal _cc3100003SellTax;
        private decimal _cc3200003SellTax;
        private decimal _cc3300003SellTax;
        private decimal _cc3400003SellTax;
        private decimal _cc3500003SellTax;
        private decimal _cc4100004SellTax;
        private decimal _cc4200004SellTax;
        private decimal _cc4300004SellTax;
        private decimal _cc4400004SellTax;
        private decimal _cc4500004SellTax;
        private decimal _cc4600004SellTax;
        private decimal _cc5100005SellTax;
        private decimal _cc5200005SellTax;
        private decimal _cc5300005SellTax;
        private decimal _cc5400005SellTax;
        private decimal _cc5500005SellTax;
        private decimal _cc5600005SellTax;
        private decimal _cc5700005SellTax;
        private decimal _cc5800005SellTax;
        private decimal _cc6100006SellTax;
        private decimal _cc6200006SellTax;
        private decimal _cc6300006SellTax;
        private decimal _cc6400006SellTax;
        private decimal _cc7100007SellTax;
        private decimal _cc7200007SellTax;
        private decimal _cc7300007SellTax;
        private decimal _cc8000008SellTax;
        private decimal _cc9000009SellTax;


        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;
        private bool _isNew;

        [mp.Column(Name = "ID")]
        public int Id
        {
            get
            {
                return _id;
            }

            set
            {
                _id = value;
            }
        }


        [mp.Column(Name = "JobNumber", IsPrimaryKey=true)]
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

        [mp.Column(Name = "JobName")]
        public string JobName
        {
            get
            {
                return _jobName;
            }

            set
            {
                _jobName = value;
            }
        }

        [mp.Column(Name = "Iteration", IsPrimaryKey = true)]
        public int Iteration
        {
            get
            {
                return _iteration;
            }

            set
            {
                _iteration = value;
            }
        }

        [mp.Column(Name = "QuoteNumber")]
        public string QuoteNumber
        {
            get
            {
                return _quoteNumber;
            }

            set
            {
                _quoteNumber = value;
            }
        }

        //UI only
        public string FullQuoteNumber
        {
            get
            {
                return _fullQuoteNumber;
            }

            set
            {
                _fullQuoteNumber = value;
            }
        }

        [mp.Column(Name = "Contractor")]
        public string Contractor
        {
            get
            {
                return _contractor;
            }

            set
            {
                _contractor = value;
                this.IsModified = true;
            }
        }

        [mp.Column(Name = "ClosingDate")]
        public DateTime? ClosingDate
        {
            get
            {
                return _closingDate;
            }

            set
            {
                _closingDate = value;
                this.IsModified = true;
            }
        }

        [mp.Column(Name = "IsRevision")]
        public bool IsRevision
        {
            get { return _isRevision; }
            set
            {
                _isRevision = value;
                OnPropertyChanged("Revision");
            }
        }

        [mp.Column(Name = "OriginatingDocumentNumber")]
        public string OriginatingDocumentNumber
        {
            get { return _originatingDocumentNumber; }
            set
            {
                _originatingDocumentNumber = value;
                OnPropertyChanged("OriginatingDocumentNumber");
            }
        }

        [mp.Column(Name = "OriginatingRevisionNumber")]
        public string OriginatingRevisionNumber
        {
            get { return _originatingRevisionNumber; }
            set
            {
                _originatingRevisionNumber = value;
                OnPropertyChanged("OriginatingRevisionNumber");
            }
        }

        [mp.Column(Name = "RevisionIteration", IsPrimaryKey=true)]
        public int RevisionIteration
        {
            get { return _revisionIteration; }
            set
            {
                _revisionIteration = value;
                OnPropertyChanged("RevisionIteration");
            }
        }

        [mp.Column(Name = "PstTax")]
        public decimal PstTax
        {
            get
            {
                return _pstTax;
            }

            set
            {
                _pstTax = value;
                Cc2102002CostTax = Cc2102002CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc2200002CostTax = Cc2200002CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3100003CostTax = Cc3100003CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3200003CostTax = Cc3200003CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3300003CostTax = Cc3300003CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3400003CostTax = Cc3400003CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3500003CostTax = Cc3500003CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4100004CostTax = Cc4100004CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4200004CostTax = Cc4200004CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4300004CostTax = Cc4300004CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4400004CostTax = Cc4400004CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4500004CostTax = Cc4500004CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4600004CostTax = Cc4600004CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5100005CostTax = Cc5100005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5200005CostTax = Cc5200005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5300005CostTax = Cc5300005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5400005CostTax = Cc5400005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5500005CostTax = Cc5500005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5600005CostTax = Cc5600005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5700005CostTax = Cc5700005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5800005CostTax = Cc5800005CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6100006CostTax = Cc6100006CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6200006CostTax = Cc6200006CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6300006CostTax = Cc6300006CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6400006CostTax = Cc6400006CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc7100007CostTax = Cc7100007CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc7200007CostTax = Cc7200007CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc7300007CostTax = Cc7300007CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc8000008CostTax = Cc8000008CostTax * (1 + (value / 100) + (_gstTax / 100));
                Cc9000009CostTax = Cc9000009CostTax * (1 + (value / 100) + (_gstTax / 100));

                Cc2102002SellTax = Cc2102002SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc2200002SellTax = Cc2200002SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3100003SellTax = Cc3100003SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3200003SellTax = Cc3200003SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3300003SellTax = Cc3300003SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3400003SellTax = Cc3400003SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc3500003SellTax = Cc3500003SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4100004SellTax = Cc4100004SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4200004SellTax = Cc4200004SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4300004SellTax = Cc4300004SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4400004SellTax = Cc4400004SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4500004SellTax = Cc4500004SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc4600004SellTax = Cc4600004SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5100005SellTax = Cc5100005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5200005SellTax = Cc5200005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5300005SellTax = Cc5300005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5400005SellTax = Cc5400005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5500005SellTax = Cc5500005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5600005SellTax = Cc5600005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5700005SellTax = Cc5700005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc5800005SellTax = Cc5800005SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6100006SellTax = Cc6100006SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6200006SellTax = Cc6200006SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6300006SellTax = Cc6300006SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc6400006SellTax = Cc6400006SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc7100007SellTax = Cc7100007SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc7200007SellTax = Cc7200007SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc7300007SellTax = Cc7300007SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc8000008SellTax = Cc8000008SellTax * (1 + (value / 100) + (_gstTax / 100));
                Cc9000009SellTax = Cc9000009SellTax * (1 + (value / 100) + (_gstTax / 100));

                this.IsModified = true;
            }
        }

        [mp.Column(Name = "GstTax")]
        public decimal GstTax
        {
            get
            {
                return _gstTax;
            }

            set
            {
                _gstTax = value;
                Cc2102002CostTax = Cc2102002Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc2200002CostTax = Cc2200002Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc3100003CostTax = Cc3100003Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc3200003CostTax = Cc3200003Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc3300003CostTax = Cc3300003Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc3400003CostTax = Cc3400003Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc3500003CostTax = Cc3500003Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc4100004CostTax = Cc4100004Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc4200004CostTax = Cc4200004Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc4300004CostTax = Cc4300004Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc4400004CostTax = Cc4400004Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc4500004CostTax = Cc4500004Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc4600004CostTax = Cc4600004Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5100005CostTax = Cc5100005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5200005CostTax = Cc5200005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5300005CostTax = Cc5300005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5400005CostTax = Cc5400005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5500005CostTax = Cc5500005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5600005CostTax = Cc5600005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5700005CostTax = Cc5700005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc5800005CostTax = Cc5800005Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc6100006CostTax = Cc6100006Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc6200006CostTax = Cc6200006Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc6300006CostTax = Cc6300006Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc6400006CostTax = Cc6400006Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc7100007CostTax = Cc7100007Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc7200007CostTax = Cc7200007Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc7300007CostTax = Cc7300007Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc8000008CostTax = Cc8000008Cost * (1 + (value / 100) + (_pstTax / 100));
                Cc9000009CostTax = Cc9000009Cost * (1 + (value / 100) + (_pstTax / 100));

                Cc2102002SellTax = Cc2102002Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc2200002SellTax = Cc2200002Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc3100003SellTax = Cc3100003Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc3200003SellTax = Cc3200003Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc3300003SellTax = Cc3300003Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc3400003SellTax = Cc3400003Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc3500003SellTax = Cc3500003Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc4100004SellTax = Cc4100004Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc4200004SellTax = Cc4200004Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc4300004SellTax = Cc4300004Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc4400004SellTax = Cc4400004Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc4500004SellTax = Cc4500004Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc4600004SellTax = Cc4600004Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5100005SellTax = Cc5100005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5200005SellTax = Cc5200005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5300005SellTax = Cc5300005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5400005SellTax = Cc5400005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5500005SellTax = Cc5500005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5600005SellTax = Cc5600005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5700005SellTax = Cc5700005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc5800005SellTax = Cc5800005Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc6100006SellTax = Cc6100006Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc6200006SellTax = Cc6200006Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc6300006SellTax = Cc6300006Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc6400006SellTax = Cc6400006Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc7100007SellTax = Cc7100007Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc7200007SellTax = Cc7200007Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc7300007SellTax = Cc7300007Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc8000008SellTax = Cc8000008Sell * (1 + (value / 100) + (_pstTax / 100));
                Cc9000009SellTax = Cc9000009Sell * (1 + (value / 100) + (_pstTax / 100));

                this.IsModified = true;
            }
        }

        public decimal UiSellTotalWithTax
        {
            get
            {
                return this.GetType().GetProperties().Where(x => x.CustomAttributes.Any(y => y.AttributeType == typeof(CostCodeSellWithTax)))
                    .Where(i => (decimal)i.GetValue(this) > 0)
                    .Select(x => (decimal)x.GetValue(this))
                    .Sum();
            }

            set
            {
                _uiSellTotalWithTax = value;
            }
        }

        public decimal UiSellTotal
        {
            get
            {
                return this.GetType().GetProperties().Where(x => x.CustomAttributes.Any(y => y.AttributeType == typeof(CostCodeSell)))
                    .Where(i => (decimal)i.GetValue(this) > 0)
                    .Select(x => (decimal)x.GetValue(this))
                    .Sum();
            }

            set
            {
                _uiSellTotal = value;
            }
        }

        [mp.Column(Name = "FieldInstall", DbType="int")]
        public QsInstaller FieldInstall
        {
            get
            {
                return _fieldInstall;
            }

            set
            {
                _fieldInstall = value;
                this.IsModified = true;
                OnPropertyChanged("FieldInstall");
            }
        }

        [mp.Column(Name = "FrameInstall", DbType = "int")]
        public QsInstaller FrameInstall
        {
            get
            {
                return _frameInstall;
            }

            set
            {
                _frameInstall = value;
                this.IsModified = true;
                OnPropertyChanged("FrameInstall");
            }
        }

        [mp.Column(Name = "AutoOperatorInstall", DbType = "int")]
        public QsInstaller AutoOperatorInstall
        {
            get
            {
                return _autoOperatorInstall;
            }

            set
            {
                _autoOperatorInstall = value;
                this.IsModified = true;
                OnPropertyChanged("AutoOperatorInstall");
            }
        }

        [mp.Column(Name = "NumberOfDoorLeafs")]
        public decimal NumberOfDoorLeafs
        {
            get
            {
                return _numberOfDoorLeafs;
            }

            set
            {
                _numberOfDoorLeafs = value;
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                this.IsModified = true;
            }
        }

        [mp.Column(Name = "RevenuePerDoor", DbType = "numeric(19, 5)", UpdateCheck = mp.UpdateCheck.Never)]
        public decimal RevenuePerDoor
        {
            get
            {
                return _revenuePerDoor;
            }

            set
            {
                _revenuePerDoor = value;
                this.IsModified = true;
            }
        }

        #region Cost

        //[CostCodeAttr("210-200-002")]
        [mp.Column(Name = "Cc2102002Cost")]
        public decimal Cc2102002Cost
        {
            get
            {
                return _cc2102002Cost;
            }

            set
            {
                _cc2102002Cost = value;
                _cc2102002Mu = value == 0 ? 0 : (_cc2102002Sell - value) / value * 100;
                _cc2102002Margin = _cc2102002Sell == 0 ? 0 : (_cc2102002Sell - _cc2102002Cost) / _cc2102002Sell * 100;
                _cc2102002CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc2102002CostTax");
                OnPropertyChanged("Cc2102002Margin");
                OnPropertyChanged("Cc2102002Cost");
                OnPropertyChanged("Cc2102002Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("220-000-002")]
        [mp.Column(Name = "Cc2200002Cost")]
        public decimal Cc2200002Cost
        {
            get
            {
                return _cc2200002Cost;
            }

            set
            {
                _cc2200002Cost = value;
                _cc2200002Mu = value == 0 ? 0 : (_cc2200002Sell - value) / value * 100;
                _cc2200002CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc2200002CostTax");
                OnPropertyChanged("Cc2200002Cost");
                OnPropertyChanged("Cc2200002Margin");
                OnPropertyChanged("Cc2200002Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("310-000-003")]
        [mp.Column(Name = "Cc3100003Cost")]
        public decimal Cc3100003Cost
        {
            get
            {
                return _cc3100003Cost;
            }

            set
            {
                _cc3100003Cost = value;
                _cc3100003Mu = value == 0 ? 0 : (_cc3100003Sell - value) / value * 100;
                _cc3100003CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc3100003CostTax");
                OnPropertyChanged("Cc3100003Cost");
                OnPropertyChanged("Cc3100003Margin");
                OnPropertyChanged("Cc3100003Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("320-000-003")]
        [mp.Column(Name = "Cc3200003Cost")]
        public decimal Cc3200003Cost
        {
            get
            {
                return _cc3200003Cost;
            }

            set
            {
                _cc3200003Cost = value;
                _cc3200003Mu = value == 0 ? 0 : (_cc3200003Sell - value) / value * 100;
                _cc3200003CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc3200003CostTax");
                OnPropertyChanged("Cc3200003Cost");
                OnPropertyChanged("Cc3200003Margin");
                OnPropertyChanged("Cc3200003Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("330-000-003")]
        [mp.Column(Name = "Cc3300003Cost")]
        public decimal Cc3300003Cost
        {
            get
            {
                return _cc3300003Cost;
            }

            set
            {
                _cc3300003Cost = value;
                _cc3300003Mu = value == 0 ? 0 : (_cc3300003Sell - value) / value * 100;
                _cc3300003CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc3300003CostTax");
                OnPropertyChanged("Cc3300003Cost");
                OnPropertyChanged("Cc3300003Margin");
                OnPropertyChanged("Cc3300003Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("340-000-003")]
        [mp.Column(Name = "Cc3400003Cost")]
        public decimal Cc3400003Cost
        {
            get
            {
                return _cc3400003Cost;
            }

            set
            {
                _cc3400003Cost = value;
                _cc3400003Mu = value == 0 ? 0 : (_cc3400003Sell - value) / value * 100;
                _cc3400003CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc3400003CostTax");
                OnPropertyChanged("Cc3400003Cost");
                OnPropertyChanged("Cc3400003Margin");
                OnPropertyChanged("Cc3400003Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("350-000-003")]
        [mp.Column(Name = "Cc3500003Cost")]
        public decimal Cc3500003Cost
        {
            get
            {
                return _cc3500003Cost;
            }

            set
            {
                _cc3500003Cost = value;
                _cc3500003Mu = value == 0 ? 0 : (_cc3500003Sell - value) / value * 100;
                _cc3500003CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc3500003CostTax");
                OnPropertyChanged("Cc3500003Cost");
                OnPropertyChanged("Cc3500003Margin");
                OnPropertyChanged("Cc3500003Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("410-000-004")]
        [mp.Column(Name = "Cc4100004Cost")]
        public decimal Cc4100004Cost
        {
            get
            {
                return _cc4100004Cost;
            }

            set
            {
                _cc4100004Cost = value;
                _cc4100004Mu = value == 0 ? 0 : (_cc4100004Sell - value) / value * 100;
                _cc4100004CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc4100004CostTax");
                OnPropertyChanged("Cc4100004Cost");
                OnPropertyChanged("Cc4100004Margin");
                OnPropertyChanged("Cc4100004Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("420-000-004")]
        [mp.Column(Name = "Cc4200004Cost")]
        public decimal Cc4200004Cost
        {
            get
            {
                return _cc4200004Cost;
            }

            set
            {
                _cc4200004Cost = value;
                _cc4200004Mu = value == 0 ? 0 : (_cc4200004Sell - value) / value * 100;
                _cc4200004CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc4200004CostTax");
                OnPropertyChanged("Cc4200004Cost");
                OnPropertyChanged("Cc4200004Margin");
                OnPropertyChanged("Cc4200004Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("430-000-004")]
        [mp.Column(Name = "Cc4300004Cost")]
        public decimal Cc4300004Cost
        {
            get
            {
                return _cc4300004Cost;
            }

            set
            {
                _cc4300004Cost = value;
                _cc4300004Mu = value == 0 ? 0 : (_cc4300004Sell - value) / value * 100;
                _cc4300004CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc4300004CostTax");
                OnPropertyChanged("Cc4300004Cost");
                OnPropertyChanged("Cc4300004Margin");
                OnPropertyChanged("Cc4300004Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("440-000-004")]
        [mp.Column(Name = "Cc4400004Cost")]
        public decimal Cc4400004Cost
        {
            get
            {
                return _cc4400004Cost;
            }

            set
            {
                _cc4400004Cost = value;
                _cc4400004Mu = value == 0 ? 0 : (_cc4400004Sell - value) / value * 100;
                _cc4400004CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc4400004CostTax");
                OnPropertyChanged("Cc4400004Cost");
                OnPropertyChanged("Cc4400004Margin");
                OnPropertyChanged("Cc4400004Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("450-000-004")]
        [mp.Column(Name = "Cc4500004Cost")]
        public decimal Cc4500004Cost
        {
            get
            {
                return _cc4500004Cost;
            }

            set
            {
                _cc4500004Cost = value;
                _cc4500004Mu = value == 0 ? 0 : (_cc4500004Sell - value) / value * 100;
                _cc4500004CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc4500004CostTax");
                OnPropertyChanged("Cc4500004Cost");
                OnPropertyChanged("Cc4500004Margin");
                OnPropertyChanged("Cc4500004Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("460-000-004")]
        [mp.Column(Name = "Cc4600004Cost")]
        public decimal Cc4600004Cost
        {
            get
            {
                return _cc4600004Cost;
            }

            set
            {
                _cc4600004Cost = value;
                _cc4600004Mu = value == 0 ? 0 : (_cc4600004Sell - value) / value * 100;
                _cc4600004CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc4600004CostTax");
                OnPropertyChanged("Cc4600004Cost");
                OnPropertyChanged("Cc4600004Margin");
                OnPropertyChanged("Cc4600004Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("510-000-005")]
        [mp.Column(Name = "Cc5100005Cost")]
        public decimal Cc5100005Cost
        {
            get
            {
                return _cc5100005Cost;
            }

            set
            {
                _cc5100005Cost = value;
                _cc5100005Mu = value == 0 ? 0 : (_cc5100005Sell - value) / value * 100;
                _cc5100005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5100005CostTax");
                OnPropertyChanged("Cc5100005Cost");
                OnPropertyChanged("Cc5100005Margin");
                OnPropertyChanged("Cc5100005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("520-000-005")]
        [mp.Column(Name = "Cc5200005Cost")]
        public decimal Cc5200005Cost
        {
            get
            {
                return _cc5200005Cost;
            }

            set
            {
                _cc5200005Cost = value;
                _cc5200005Mu = value == 0 ? 0 : (_cc5200005Sell - value) / value * 100;
                _cc5200005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5200005CostTax");
                OnPropertyChanged("Cc5200005Cost");
                OnPropertyChanged("Cc5200005Margin");
                OnPropertyChanged("Cc5200005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("530-000-005")]
        [mp.Column(Name = "Cc5300005Cost")]
        public decimal Cc5300005Cost
        {
            get
            {
                return _cc5300005Cost;
            }

            set
            {
                _cc5300005Cost = value;
                _cc5300005Mu = value == 0 ? 0 : (_cc5300005Sell - value) / value * 100;
                _cc5300005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5300005CostTax");
                OnPropertyChanged("Cc5300005Cost");
                OnPropertyChanged("Cc5300005Margin");
                OnPropertyChanged("Cc5300005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("540-000-005")]
        [mp.Column(Name = "Cc5400005Cost")]
        public decimal Cc5400005Cost
        {
            get
            {
                return _cc5400005Cost;
            }

            set
            {
                _cc5400005Cost = value;
                _cc5400005Mu = value == 0 ? 0 : (_cc5400005Sell - value) / value * 100;
                _cc5400005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5400005CostTax");
                OnPropertyChanged("Cc5400005Cost");
                OnPropertyChanged("Cc5400005Margin");
                OnPropertyChanged("Cc5400005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("550-000-005")]
        [mp.Column(Name = "Cc5500005Cost")]
        public decimal Cc5500005Cost
        {
            get
            {
                return _cc5500005Cost;
            }

            set
            {
                _cc5500005Cost = value;
                _cc5500005Mu = value == 0 ? 0 : (_cc5500005Sell - value) / value * 100;
                _cc5500005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5500005CostTax");
                OnPropertyChanged("Cc5500005Cost");
                OnPropertyChanged("Cc5500005Margin");
                OnPropertyChanged("Cc5500005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("560-000-005")]
        [mp.Column(Name = "Cc5600005Cost")]
        public decimal Cc5600005Cost
        {
            get
            {
                return _cc5600005Cost;
            }

            set
            {
                _cc5600005Cost = value;
                _cc5600005Mu = value == 0 ? 0 : (_cc5600005Sell - value) / value * 100;
                _cc5600005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5600005CostTax");
                OnPropertyChanged("Cc5600005Cost");
                OnPropertyChanged("Cc5600005Margin");
                OnPropertyChanged("Cc5600005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("570-000-005")]
        [mp.Column(Name = "Cc5700005Cost")]
        public decimal Cc5700005Cost
        {
            get
            {
                return _cc5700005Cost;
            }

            set
            {
                _cc5700005Cost = value;
                _cc5700005Mu = value == 0 ? 0 : (_cc5700005Sell - value) / value * 100;
                _cc5700005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5700005CostTax");
                OnPropertyChanged("Cc5700005Cost");
                OnPropertyChanged("Cc5700005Margin");
                OnPropertyChanged("Cc5700005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("580-000-005")]
        [mp.Column(Name = "Cc5800005Cost")]
        public decimal Cc5800005Cost
        {
            get
            {
                return _cc5800005Cost;
            }

            set
            {
                _cc5800005Cost = value;
                _cc5800005Mu = value == 0 ? 0 : (_cc5800005Sell - value) / value * 100;
                _cc5800005CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc5800005CostTax");
                OnPropertyChanged("Cc5800005Cost");
                OnPropertyChanged("Cc5800005Margin");
                OnPropertyChanged("Cc5800005Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("610-000-006")]
        [mp.Column(Name = "Cc6100006Cost")]
        public decimal Cc6100006Cost
        {
            get
            {
                return _cc6100006Cost;
            }

            set
            {
                _cc6100006Cost = value;
                _cc6100006Mu = value == 0 ? 0 : (_cc6100006Sell - value) / value * 100;
                _cc6100006CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc6100006CostTax");
                OnPropertyChanged("Cc6100006Cost");
                OnPropertyChanged("Cc6100006Margin");
                OnPropertyChanged("Cc6100006Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("620-000-006")]
        [mp.Column(Name = "Cc6200006Cost")]
        public decimal Cc6200006Cost
        {
            get
            {
                return _cc6200006Cost;
            }

            set
            {
                _cc6200006Cost = value;
                _cc6200006Mu = value == 0 ? 0 : (_cc6200006Sell - value) / value * 100;
                _cc6200006CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc6200006CostTax");
                OnPropertyChanged("Cc6200006Cost");
                OnPropertyChanged("Cc6200006Margin");
                OnPropertyChanged("Cc6200006Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("630-000-006")]
        [mp.Column(Name = "Cc6300006Cost")]
        public decimal Cc6300006Cost
        {
            get
            {
                return _cc6300006Cost;
            }

            set
            {
                _cc6300006Cost = value;
                _cc6300006Mu = value == 0 ? 0 : (_cc6300006Sell - value) / value * 100;
                _cc6300006CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc6300006CostTax");
                OnPropertyChanged("Cc6300006Cost");
                OnPropertyChanged("Cc6300006Margin");
                OnPropertyChanged("Cc6300006Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("640-000-006")]
        [mp.Column(Name = "Cc6400006Cost")]
        public decimal Cc6400006Cost
        {
            get
            {
                return _cc6400006Cost;
            }

            set
            {
                _cc6400006Cost = value;
                _cc6400006Mu = value == 0 ? 0 : (_cc6400006Sell - value) / value * 100;
                _cc6400006CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc6400006CostTax");
                OnPropertyChanged("Cc6400006Cost");
                OnPropertyChanged("Cc6400006Margin");
                OnPropertyChanged("Cc6400006Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("710-000-007")]
        [mp.Column(Name = "Cc7100007Cost")]
        public decimal Cc7100007Cost
        {
            get
            {
                return _cc7100007Cost;
            }

            set
            {
                _cc7100007Cost = value;
                _cc7100007Mu = value == 0 ? 0 : (_cc7100007Sell - value) / value * 100;
                _cc7100007CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc7100007CostTax");
                OnPropertyChanged("Cc7100007Cost");
                OnPropertyChanged("Cc7100007Margin");
                OnPropertyChanged("Cc7100007Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("720-000-007")]
        [mp.Column(Name = "Cc7200007Cost")]
        public decimal Cc7200007Cost
        {
            get
            {
                return _cc7200007Cost;
            }

            set
            {
                _cc7200007Cost = value;
                _cc7200007Mu = value == 0 ? 0 : (_cc7200007Sell - value) / value * 100;
                _cc7200007CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc7200007CostTax");
                OnPropertyChanged("Cc7200007Cost");
                OnPropertyChanged("Cc7200007Margin");
                OnPropertyChanged("Cc7200007Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("730-000-007")]
        [mp.Column(Name = "Cc7300007Cost")]
        public decimal Cc7300007Cost
        {
            get
            {
                return _cc7300007Cost;
            }

            set
            {
                _cc7300007Cost = value;
                _cc7300007Mu = value == 0 ? 0 : (_cc7300007Sell - value) / value * 100;
                _cc7300007CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc7300007CostTax");
                OnPropertyChanged("Cc7300007Cost");
                OnPropertyChanged("Cc7300007Margin");
                OnPropertyChanged("Cc7300007Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("800-000-008")]
        [mp.Column(Name = "Cc8000008Cost")]
        public decimal Cc8000008Cost
        {
            get
            {
                return _cc8000008Cost;
            }

            set
            {
                _cc8000008Cost = value;
                _cc8000008Mu = value == 0 ? 0 : (_cc8000008Sell - value) / value * 100;
                _cc8000008CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc8000008CostTax");
                OnPropertyChanged("Cc8000008Cost");
                OnPropertyChanged("Cc8000008Margin");
                OnPropertyChanged("Cc8000008Mu");
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("900-000-009")]
        [mp.Column(Name = "Cc9000009Cost")]
        public decimal Cc9000009Cost
        {
            get
            {
                return _cc9000009Cost;
            }

            set
            {
                _cc9000009Cost = value;
                _cc9000009Mu = value == 0 ? 0 : (_cc9000009Sell - value) / value * 100;
                _cc9000009CostTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                OnPropertyChanged("Cc9000009CostTax");
                OnPropertyChanged("Cc9000009Cost");
                OnPropertyChanged("Cc9000009Margin");
                OnPropertyChanged("Cc9000009Mu");
                this.IsModified = true;
            }
        }

        #endregion



        #region Sell

        [CostCodeSell("210-200-2", "2", "Supply Hardware")]
        [mp.Column(Name = "Cc2102002Sell")]
        public decimal Cc2102002Sell
        {
            get
            {
                return _cc2102002Sell;
            }

            set
            {
                _cc2102002Sell = value;
                _cc2102002Mu = _cc2102002Cost == 0 ? 0 : (value - _cc2102002Cost) / _cc2102002Cost * 100;
                _cc2102002Margin = _cc2102002Sell == 0 ? 0 : (_cc2102002Sell - _cc2102002Cost) / _cc2102002Sell * 100;
                _cc2102002SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc2102002SellTax");
                OnPropertyChanged("Cc2102002Margin");
                OnPropertyChanged("Cc2102002Sell");
                OnPropertyChanged("Cc2102002Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("220-000-2", "2", "Supply Washroom Accessories")]
        [mp.Column(Name = "Cc2200002Sell")]
        public decimal Cc2200002Sell
        {
            get
            {
                return _cc2200002Sell;
            }

            set
            {
                _cc2200002Sell = value;
                _cc2200002Mu = _cc2200002Mu == 0 ? 0 : (value - _cc2200002Cost) / _cc2200002Cost * 100;
                _cc2200002Margin = _cc2200002Sell == 0 ? 0 : (_cc2200002Sell - _cc2200002Cost) / _cc2200002Sell * 100;
                _cc2200002SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc2200002SellTax");
                OnPropertyChanged("Cc2200002Margin");
                OnPropertyChanged("Cc2200002Sell");
                OnPropertyChanged("Cc2200002Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("310-000-3", "3", "Supply HM Frames & Screens")]
        [mp.Column(Name = "Cc3100003Sell")]
        public decimal Cc3100003Sell
        {
            get
            {
                return _cc3100003Sell;
            }

            set
            {
                _cc3100003Sell = value;
                _cc3100003Mu = _cc3100003Mu == 0 ? 0 : (value - _cc3100003Cost) / _cc3100003Cost * 100;
                _cc3100003Margin = _cc3100003Sell == 0 ? 0 : (_cc3100003Sell - _cc3100003Cost) / _cc3100003Sell * 100;
                _cc3100003SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc3100003SellTax");
                OnPropertyChanged("Cc3100003Margin");
                OnPropertyChanged("Cc3100003Sell");
                OnPropertyChanged("Cc3100003Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("320-000-3", "3", "Supply Hollow Metal Doors")]
        [mp.Column(Name = "Cc3200003Sell")]
        public decimal Cc3200003Sell
        {
            get
            {
                return _cc3200003Sell;
            }

            set
            {
                _cc3200003Sell = value;
                _cc3200003Mu = _cc3200003Mu == 0 ? 0 : (value - _cc3200003Cost) / _cc3200003Cost * 100;
                _cc3200003Margin = _cc3200003Sell == 0 ? 0 : (_cc3200003Sell - _cc3200003Cost) / _cc3200003Sell * 100;
                _cc3200003SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc3200003SellTax");
                OnPropertyChanged("Cc3200003Margin");
                OnPropertyChanged("Cc3200003Sell");
                OnPropertyChanged("Cc3200003Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("330-000-3", "3", "Supply Wood Doors & Frames")]
        [mp.Column(Name = "Cc3300003Sell")]
        public decimal Cc3300003Sell
        {
            get
            {
                return _cc3300003Sell;
            }

            set
            {
                _cc3300003Sell = value;
                _cc3300003Mu = _cc3300003Mu == 0 ? 0 : (value - _cc3300003Cost) / _cc3300003Cost * 100;
                _cc3300003Margin = _cc3300003Sell == 0 ? 0 : (_cc3300003Sell - _cc3300003Cost) / _cc3300003Sell * 100;
                _cc3300003SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc3300003SellTax");
                OnPropertyChanged("Cc3300003Margin");
                OnPropertyChanged("Cc3300003Sell");
                OnPropertyChanged("Cc3300003Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("340-000-3", "3", "Supply Glazing")]
        [mp.Column(Name = "Cc3400003Sell")]
        public decimal Cc3400003Sell
        {
            get
            {
                return _cc3400003Sell;
            }

            set
            {
                _cc3400003Sell = value;
                _cc3400003Mu = _cc3400003Mu == 0 ? 0 : (value - _cc3400003Cost) / _cc3400003Cost * 100;
                _cc3400003Margin = _cc3400003Sell == 0 ? 0 : (_cc3400003Sell - _cc3400003Cost) / _cc3400003Sell * 100;
                _cc3400003SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc3400003SellTax");
                OnPropertyChanged("Cc3400003Margin");
                OnPropertyChanged("Cc3400003Sell");
                OnPropertyChanged("Cc3400003Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("350-000-3", "3", "Specialty Doors & Frames")]
        [mp.Column(Name = "Cc3500003Sell")]
        public decimal Cc3500003Sell
        {
            get
            {
                return _cc3500003Sell;
            }

            set
            {
                _cc3500003Sell = value;
                _cc3500003Mu = _cc3500003Mu == 0 ? 0 : (value - _cc3500003Cost) / _cc3500003Cost * 100;
                _cc3500003Margin = _cc3500003Sell == 0 ? 0 : (_cc3500003Sell - _cc3500003Cost) / _cc3500003Sell * 100;
                _cc3500003SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc3500003SellTax");
                OnPropertyChanged("Cc3500003Margin");
                OnPropertyChanged("Cc3500003Sell");
                OnPropertyChanged("Cc3500003Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("410-000-4", "4", "Supply Auto Door Operator")]
        [mp.Column(Name = "Cc4100004Sell")]
        public decimal Cc4100004Sell
        {
            get
            {
                return _cc4100004Sell;
            }

            set
            {
                _cc4100004Sell = value;
                _cc4100004Mu = _cc4100004Mu == 0 ? 0 : (value - _cc4100004Cost) / _cc4100004Cost * 100;
                _cc4100004Margin = _cc4100004Sell == 0 ? 0 : (_cc4100004Sell - _cc4100004Cost) / _cc4100004Sell * 100;
                _cc4100004SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc4100004SellTax");
                OnPropertyChanged("Cc4100004Margin");
                OnPropertyChanged("Cc4100004Sell");
                OnPropertyChanged("Cc4100004Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("420-000-4", "4", "None")]
        [mp.Column(Name = "Cc4200004Sell")]
        public decimal Cc4200004Sell
        {
            get
            {
                return _cc4200004Sell;
            }

            set
            {
                _cc4200004Sell = value;
                _cc4200004Mu = _cc4200004Mu == 0 ? 0 : (value - _cc4200004Cost) / _cc4200004Cost * 100;
                _cc4200004Margin = _cc4200004Sell == 0 ? 0 : (_cc4200004Sell - _cc4200004Cost) / _cc4200004Sell * 100;
                _cc4200004SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc4200004SellTax");
                OnPropertyChanged("Cc4200004Margin");
                OnPropertyChanged("Cc4200004Sell");
                OnPropertyChanged("Cc4200004Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("430-000-4", "4", "Install Auto Door Operators")]
        [mp.Column(Name = "Cc4300004Sell")]
        public decimal Cc4300004Sell
        {
            get
            {
                return _cc4300004Sell;
            }

            set
            {
                _cc4300004Sell = value;
                _cc4300004Mu = _cc4300004Mu == 0 ? 0 : (value - _cc4300004Cost) / _cc4300004Cost * 100;
                _cc4300004Margin = _cc4300004Sell == 0 ? 0 : (_cc4300004Sell - _cc4300004Cost) / _cc4300004Sell * 100;
                _cc4300004SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc4300004SellTax");
                OnPropertyChanged("Cc4300004Margin");
                OnPropertyChanged("Cc4300004Sell");
                OnPropertyChanged("Cc4300004Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("440-000-4", "4", "Install/Comm Electrical Integration Hardware")]
        [mp.Column(Name = "Cc4400004Sell")]
        public decimal Cc4400004Sell
        {
            get
            {
                return _cc4400004Sell;
            }

            set
            {
                _cc4400004Sell = value;
                _cc4400004Mu = _cc4400004Mu == 0 ? 0 : (value - _cc4400004Cost) / _cc4400004Cost * 100;
                _cc4400004Margin = _cc4400004Sell == 0 ? 0 : (_cc4400004Sell - _cc4400004Cost) / _cc4400004Sell * 100;
                _cc4400004SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc4400004SellTax");
                OnPropertyChanged("Cc4400004Margin");
                OnPropertyChanged("Cc4400004Sell");
                OnPropertyChanged("Cc4400004Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("450-000-4", "4", "Shop Installation Hardware")]
        [mp.Column(Name = "Cc4500004Sell")]
        public decimal Cc4500004Sell
        {
            get
            {
                return _cc4500004Sell;
            }

            set
            {
                _cc4500004Sell = value;
                _cc4500004Mu = _cc4500004Mu == 0 ? 0 : (value - _cc4500004Cost) / _cc4500004Cost * 100;
                _cc4500004Margin = _cc4500004Sell == 0 ? 0 : (_cc4500004Sell - _cc4500004Cost) / _cc4500004Sell * 100;
                _cc4500004SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc4500004SellTax");
                OnPropertyChanged("Cc4500004Margin");
                OnPropertyChanged("Cc4500004Sell");
                OnPropertyChanged("Cc4500004Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("460-000-4", "4", "Shop Installation Glazing")]
        [mp.Column(Name = "Cc4600004Sell")]
        public decimal Cc4600004Sell
        {
            get
            {
                return _cc4600004Sell;
            }

            set
            {
                _cc4600004Sell = value;
                _cc4600004Mu = _cc4600004Mu == 0 ? 0 : (value - _cc4600004Cost) / _cc4600004Cost * 100;
                _cc4600004Margin = _cc4600004Sell == 0 ? 0 : (_cc4600004Sell - _cc4600004Cost) / _cc4600004Sell * 100;
                _cc4600004SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc4600004SellTax");
                OnPropertyChanged("Cc4600004Margin");
                OnPropertyChanged("Cc4600004Sell");
                OnPropertyChanged("Cc4600004Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("510-000-5", "5", "Field Install Doors & Hardware")]
        [mp.Column(Name = "Cc5100005Sell")]
        public decimal Cc5100005Sell
        {
            get
            {
                return _cc5100005Sell;
            }

            set
            {
                _cc5100005Sell = value;
                _cc5100005Mu = _cc5100005Mu == 0 ? 0 : (value - _cc5100005Cost) / _cc5100005Cost * 100;
                _cc5100005Margin = _cc5100005Sell == 0 ? 0 : (_cc5100005Sell - _cc5100005Cost) / _cc5100005Sell * 100;
                _cc5100005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5100005SellTax");
                OnPropertyChanged("Cc5100005Margin");
                OnPropertyChanged("Cc5100005Sell");
                OnPropertyChanged("Cc5100005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("520-000-5", "5", "Field Install Frames")]
        [mp.Column(Name = "Cc5200005Sell")]
        public decimal Cc5200005Sell
        {
            get
            {
                return _cc5200005Sell;
            }

            set
            {
                _cc5200005Sell = value;
                _cc5200005Mu = _cc5200005Mu == 0 ? 0 : (value - _cc5200005Cost) / _cc5200005Cost * 100;
                _cc5200005Margin = _cc5200005Sell == 0 ? 0 : (_cc5200005Sell - _cc5200005Cost) / _cc5200005Sell * 100;
                _cc5200005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5200005SellTax");
                OnPropertyChanged("Cc5200005Margin");
                OnPropertyChanged("Cc5200005Sell");
                OnPropertyChanged("Cc5200005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("530-000-5", "5", "Warranty Work")]
        [mp.Column(Name = "Cc5300005Sell")]
        public decimal Cc5300005Sell
        {
            get
            {
                return _cc5300005Sell;
            }

            set
            {
                _cc5300005Sell = value;
                _cc5300005Mu = _cc5300005Mu == 0 ? 0 : (value - _cc5300005Cost) / _cc5300005Cost * 100;
                _cc5300005Margin = _cc5300005Sell == 0 ? 0 : (_cc5300005Sell - _cc5300005Cost) / _cc5300005Sell * 100;
                _cc5300005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5300005SellTax");
                OnPropertyChanged("Cc5300005Margin");
                OnPropertyChanged("Cc5300005Sell");
                OnPropertyChanged("Cc5300005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("540-000-5", "5", "Service Work")]
        [mp.Column(Name = "Cc5400005Sell")]
        public decimal Cc5400005Sell
        {
            get
            {
                return _cc5400005Sell;
            }

            set
            {
                _cc5400005Sell = value;
                _cc5400005Mu = _cc5400005Mu == 0 ? 0 : (value - _cc5400005Cost) / _cc5400005Cost * 100;
                _cc5400005Margin = _cc5400005Sell == 0 ? 0 : (_cc5400005Sell - _cc5400005Cost) / _cc5400005Sell * 100;
                _cc5400005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5400005SellTax");
                OnPropertyChanged("Cc5400005Margin");
                OnPropertyChanged("Cc5400005Sell");
                OnPropertyChanged("Cc5400005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("550-000-5", "5", "Shop Installation of Hardware")]
        [mp.Column(Name = "Cc5500005Sell")]
        public decimal Cc5500005Sell
        {
            get
            {
                return _cc5500005Sell;
            }

            set
            {
                _cc5500005Sell = value;
                _cc5500005Mu = _cc5500005Mu == 0 ? 0 : (value - _cc5500005Cost) / _cc5500005Cost * 100;
                _cc5500005Margin = _cc5500005Sell == 0 ? 0 : (_cc5500005Sell - _cc5500005Cost) / _cc5500005Sell * 100;
                _cc5500005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5500005SellTax");
                OnPropertyChanged("Cc5500005Margin");
                OnPropertyChanged("Cc5500005Sell");
                OnPropertyChanged("Cc5500005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("560-000-5", "5", "Shop Installation of Glazing")]
        [mp.Column(Name = "Cc5600005Sell")]
        public decimal Cc5600005Sell
        {
            get
            {
                return _cc5600005Sell;
            }

            set
            {
                _cc5600005Sell = value;
                _cc5600005Mu = _cc5600005Mu == 0 ? 0 : (value - _cc5600005Cost) / _cc5600005Cost * 100;
                _cc5600005Margin = _cc5600005Sell == 0 ? 0 : (_cc5600005Sell - _cc5600005Cost) / _cc5600005Sell * 100;
                _cc5600005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5600005SellTax");
                OnPropertyChanged("Cc5600005Margin");
                OnPropertyChanged("Cc5600005Sell");
                OnPropertyChanged("Cc5600005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("570-000-5", "5", "Remedial Work")]
        [mp.Column(Name = "Cc5700005Sell")]
        public decimal Cc5700005Sell
        {
            get
            {
                return _cc5700005Sell;
            }

            set
            {
                _cc5700005Sell = value;
                _cc5700005Mu = _cc5700005Mu == 0 ? 0 : (value - _cc5700005Cost) / _cc5700005Cost * 100;
                _cc5700005Margin = _cc5700005Sell == 0 ? 0 : (_cc5700005Sell - _cc5700005Cost) / _cc5700005Sell * 100;
                _cc5700005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5700005SellTax");
                OnPropertyChanged("Cc5700005Margin");
                OnPropertyChanged("Cc5700005Sell");
                OnPropertyChanged("Cc5700005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("580-000-5", "5", "Travel (UCI)")]
        [mp.Column(Name = "Cc5800005Sell")]
        public decimal Cc5800005Sell
        {
            get
            {
                return _cc5800005Sell;
            }

            set
            {
                _cc5800005Sell = value;
                _cc5800005Mu = _cc5800005Mu == 0 ? 0 : (value - _cc5800005Cost) / _cc5800005Cost * 100;
                _cc5800005Margin = _cc5800005Sell == 0 ? 0 : (_cc5800005Sell - _cc5800005Cost) / _cc5800005Sell * 100;
                _cc5800005SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc5800005SellTax");
                OnPropertyChanged("Cc5800005Margin");
                OnPropertyChanged("Cc5800005Sell");
                OnPropertyChanged("Cc5800005Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("610-000-6", "6", "Install Frames (3rd Party)")]
        [mp.Column(Name = "Cc6100006Sell")]
        public decimal Cc6100006Sell
        {
            get
            {
                return _cc6100006Sell;
            }

            set
            {
                _cc6100006Sell = value;
                _cc6100006Mu = _cc6100006Mu == 0 ? 0 : (value - _cc6100006Cost) / _cc6100006Cost * 100;
                _cc6100006Margin = _cc6100006Sell == 0 ? 0 : (_cc6100006Sell - _cc6100006Cost) / _cc6100006Sell * 100;
                _cc6100006SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc6100006SellTax");
                OnPropertyChanged("Cc6100006Margin");
                OnPropertyChanged("Cc6100006Sell");
                OnPropertyChanged("Cc6100006Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("620-000-6", "6", "Install Doors & Hardware (3rd Party)")]
        [mp.Column(Name = "Cc6200006Sell")]
        public decimal Cc6200006Sell
        {
            get
            {
                return _cc6200006Sell;
            }

            set
            {
                _cc6200006Sell = value;
                _cc6200006Mu = _cc6200006Mu == 0 ? 0 : (value - _cc6200006Cost) / _cc6200006Cost * 100;
                _cc6200006Margin = _cc6200006Sell == 0 ? 0 : (_cc6200006Sell - _cc6200006Cost) / _cc6200006Sell * 100;
                _cc6200006SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc6200006SellTax");
                OnPropertyChanged("Cc6200006Margin");
                OnPropertyChanged("Cc6200006Sell");
                OnPropertyChanged("Cc6200006Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("630-000-6", "6", "Remedial Work (3rd Party)")]
        [mp.Column(Name = "Cc6300006Sell")]
        public decimal Cc6300006Sell
        {
            get
            {
                return _cc6300006Sell;
            }

            set
            {
                _cc6300006Sell = value;
                _cc6300006Mu = _cc6300006Mu == 0 ? 0 : (value - _cc6300006Cost) / _cc6300006Cost * 100;
                _cc6300006Margin = _cc6300006Sell == 0 ? 0 : (_cc6300006Sell - _cc6300006Cost) / _cc6300006Sell * 100;
                _cc6300006SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc6300006SellTax");
                OnPropertyChanged("Cc6300006Margin");
                OnPropertyChanged("Cc6300006Sell");
                OnPropertyChanged("Cc6300006Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("640-000-6", "6", "Supply & Install Auto Op (3rd Party)")]
        [mp.Column(Name = "Cc6400006Sell")]
        public decimal Cc6400006Sell
        {
            get
            {
                return _cc6400006Sell;
            }

            set
            {
                _cc6400006Sell = value;
                _cc6400006Mu = _cc6400006Mu == 0 ? 0 : (value - _cc6400006Cost) / _cc6400006Cost * 100;
                _cc6400006Margin = _cc6400006Sell == 0 ? 0 : (_cc6400006Sell - _cc6400006Cost) / _cc6400006Sell * 100;
                _cc6400006SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc6400006SellTax");
                OnPropertyChanged("Cc6400006Margin");
                OnPropertyChanged("Cc6400006Sell");
                OnPropertyChanged("Cc6400006Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("710-000-7", "7", "Travel Expenses")]
        [mp.Column(Name = "Cc7100007Sell")]
        public decimal Cc7100007Sell
        {
            get
            {
                return _cc7100007Sell;
            }

            set
            {
                _cc7100007Sell = value;
                _cc7100007Mu = _cc7100007Mu == 0 ? 0 : (value - _cc7100007Cost) / _cc7100007Cost * 100;
                _cc7100007Margin = _cc7100007Sell == 0 ? 0 : (_cc7100007Sell - _cc7100007Cost) / _cc7100007Sell * 100;
                _cc7100007SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc7100007SellTax");
                OnPropertyChanged("Cc7100007Margin");
                OnPropertyChanged("Cc7100007Sell");
                OnPropertyChanged("Cc7100007Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("720-000-7", "7", "Automobile Expenses")]
        [mp.Column(Name = "Cc7200007Sell")]
        public decimal Cc7200007Sell
        {
            get
            {
                return _cc7200007Sell;
            }

            set
            {
                _cc7200007Sell = value;
                _cc7200007Mu = _cc7200007Mu == 0 ? 0 : (value - _cc7200007Cost) / _cc7200007Cost * 100;
                _cc7200007Margin = _cc7200007Sell == 0 ? 0 : (_cc7200007Sell - _cc7200007Cost) / _cc7200007Sell * 100;
                _cc7200007SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc7200007SellTax");
                OnPropertyChanged("Cc7200007Margin");
                OnPropertyChanged("Cc7200007Sell");
                OnPropertyChanged("Cc7200007Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("730-000-7", "7", "Gas Expenses")]
        [mp.Column(Name = "Cc7300007Sell")]
        public decimal Cc7300007Sell
        {
            get
            {
                return _cc7300007Sell;
            }

            set
            {
                _cc7300007Sell = value;
                _cc7300007Mu = _cc7300007Mu == 0 ? 0 : (value - _cc7300007Cost) / _cc7300007Cost * 100;
                _cc7300007Margin = _cc7300007Sell == 0 ? 0 : (_cc7300007Sell - _cc7300007Cost) / _cc7300007Sell * 100;
                _cc7300007SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc7300007SellTax");
                OnPropertyChanged("Cc7300007Margin");
                OnPropertyChanged("Cc7300007Sell");
                OnPropertyChanged("Cc7300007Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("800-000-8", "8", "Freight")]
        [mp.Column(Name = "Cc8000008Sell")]
        public decimal Cc8000008Sell
        {
            get
            {
                return _cc8000008Sell;
            }

            set
            {
                _cc8000008Sell = value;
                _cc8000008Mu = _cc8000008Mu == 0 ? 0 : (value - _cc8000008Cost) / _cc8000008Cost * 100;
                _cc8000008Margin = _cc8000008Sell == 0 ? 0 : (_cc8000008Sell - _cc8000008Cost) / _cc8000008Sell * 100;
                _cc8000008SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc8000008SellTax");
                OnPropertyChanged("Cc8000008Margin");
                OnPropertyChanged("Cc8000008Sell");
                OnPropertyChanged("Cc8000008Mu");
                this.IsModified = true;
            }
        }

        [CostCodeSell("900-000-9", "9", "MISC")]
        [mp.Column(Name = "Cc9000009Sell")]
        public decimal Cc9000009Sell
        {
            get
            {
                return _cc9000009Sell;
            }

            set
            {
                _cc9000009Sell = value;
                _cc9000009Mu = _cc9000009Mu == 0 ? 0 : (value - _cc9000009Cost) / _cc9000009Cost * 100;
                _cc9000009Margin = _cc9000009Sell == 0 ? 0 : (_cc9000009Sell - _cc9000009Cost) / _cc9000009Sell * 100;
                _cc9000009SellTax = value * (1 + (_gstTax / 100) + (_pstTax / 100));
                _revenuePerDoor = _numberOfDoorLeafs == 0 ? 0 : this.UiSellTotal / _numberOfDoorLeafs;
                OnPropertyChanged("RevenuePerDoor");
                OnPropertyChanged("Cc9000009SellTax");
                OnPropertyChanged("Cc9000009Margin");
                OnPropertyChanged("Cc9000009Sell");
                OnPropertyChanged("Cc9000009Mu");
                this.IsModified = true;
            }
        }

        #endregion



        #region Markup

        //[CostCodeAttr("210-200-002")]
        [mp.Column(Name = "Cc2102002Mu")]
        public decimal Cc2102002Mu
        {
            get
            {
                return _cc2102002Mu;
            }

            set
            {
                _cc2102002Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("220-000-002")]
        [mp.Column(Name = "Cc2200002Mu")]
        public decimal Cc2200002Mu
        {
            get
            {
                return _cc2200002Mu;
            }

            set
            {
                _cc2200002Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("310-000-003")]
        [mp.Column(Name = "Cc3100003Mu")]
        public decimal Cc3100003Mu
        {
            get
            {
                return _cc3100003Mu;
            }

            set
            {
                _cc3100003Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("320-000-003")]
        [mp.Column(Name = "Cc3200003Mu")]
        public decimal Cc3200003Mu
        {
            get
            {
                return _cc3200003Mu;
            }

            set
            {
                _cc3200003Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("330-000-003")]
        [mp.Column(Name = "Cc3300003Mu")]
        public decimal Cc3300003Mu
        {
            get
            {
                return _cc3300003Mu;
            }

            set
            {
                _cc3300003Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("340-000-003")]
        [mp.Column(Name = "Cc3400003Mu")]
        public decimal Cc3400003Mu
        {
            get
            {
                return _cc3400003Mu;
            }

            set
            {
                _cc3400003Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("350-000-003")]
        [mp.Column(Name = "Cc3500003Mu")]
        public decimal Cc3500003Mu
        {
            get
            {
                return _cc3500003Mu;
            }

            set
            {
                _cc3500003Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("410-000-004")]
        [mp.Column(Name = "Cc4100004Mu")]
        public decimal Cc4100004Mu
        {
            get
            {
                return _cc4100004Mu;
            }

            set
            {
                _cc4100004Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("420-000-004")]
        [mp.Column(Name = "Cc4200004Mu")]
        public decimal Cc4200004Mu
        {
            get
            {
                return _cc4200004Mu;
            }

            set
            {
                _cc4200004Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("430-000-004")]
        [mp.Column(Name = "Cc4300004Mu")]
        public decimal Cc4300004Mu
        {
            get
            {
                return _cc4300004Mu;
            }

            set
            {
                _cc4300004Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("440-000-004")]
        [mp.Column(Name = "Cc4400004Mu")]
        public decimal Cc4400004Mu
        {
            get
            {
                return _cc4400004Mu;
            }

            set
            {
                _cc4400004Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("450-000-004")]
        [mp.Column(Name = "Cc4500004Mu")]
        public decimal Cc4500004Mu
        {
            get
            {
                return _cc4500004Mu;
            }

            set
            {
                _cc4500004Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("460-000-004")]
        [mp.Column(Name = "Cc4600004Mu")]
        public decimal Cc4600004Mu
        {
            get
            {
                return _cc4600004Mu;
            }

            set
            {
                _cc4600004Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("510-000-005")]
        [mp.Column(Name = "Cc5100005Mu")]
        public decimal Cc5100005Mu
        {
            get
            {
                return _cc5100005Mu;
            }

            set
            {
                _cc5100005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("520-000-005")]
        [mp.Column(Name = "Cc5200005Mu")]
        public decimal Cc5200005Mu
        {
            get
            {
                return _cc5200005Mu;
            }

            set
            {
                _cc5200005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("530-000-005")]
        [mp.Column(Name = "Cc5300005Mu")]
        public decimal Cc5300005Mu
        {
            get
            {
                return _cc5300005Mu;
            }

            set
            {
                _cc5300005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("540-000-005")]
        [mp.Column(Name = "Cc5400005Mu")]
        public decimal Cc5400005Mu
        {
            get
            {
                return _cc5400005Mu;
            }

            set
            {
                _cc5400005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("550-000-005")]
        [mp.Column(Name = "Cc5500005Mu")]
        public decimal Cc5500005Mu
        {
            get
            {
                return _cc5500005Mu;
            }

            set
            {
                _cc5500005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("560-000-005")]
        [mp.Column(Name = "Cc5600005Mu")]
        public decimal Cc5600005Mu
        {
            get
            {
                return _cc5600005Mu;
            }

            set
            {
                _cc5600005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("570-000-005")]
        [mp.Column(Name = "Cc5700005Mu")]
        public decimal Cc5700005Mu
        {
            get
            {
                return _cc5700005Mu;
            }

            set
            {
                _cc5700005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("580-000-005")]
        [mp.Column(Name = "Cc5800005Mu")]
        public decimal Cc5800005Mu
        {
            get
            {
                return _cc5800005Mu;
            }

            set
            {
                _cc5800005Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("610-000-006")]
        [mp.Column(Name = "Cc6100006Mu")]
        public decimal Cc6100006Mu
        {
            get
            {
                return _cc6100006Mu;
            }

            set
            {
                _cc6100006Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("620-000-006")]
        [mp.Column(Name = "Cc6200006Mu")]
        public decimal Cc6200006Mu
        {
            get
            {
                return _cc6200006Mu;
            }

            set
            {
                _cc6200006Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("630-000-006")]
        [mp.Column(Name = "Cc6300006Mu")]
        public decimal Cc6300006Mu
        {
            get
            {
                return _cc6300006Mu;
            }

            set
            {
                _cc6300006Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("640-000-006")]
        [mp.Column(Name = "Cc6400006Mu")]
        public decimal Cc6400006Mu
        {
            get
            {
                return _cc6400006Mu;
            }

            set
            {
                _cc6400006Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("710-000-007")]
        [mp.Column(Name = "Cc7100007Mu")]
        public decimal Cc7100007Mu
        {
            get
            {
                return _cc7100007Mu;
            }

            set
            {
                _cc7100007Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("720-000-007")]
        [mp.Column(Name = "Cc7200007Mu")]
        public decimal Cc7200007Mu
        {
            get
            {
                return _cc7200007Mu;
            }

            set
            {
                _cc7200007Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("730-000-007")]
        [mp.Column(Name = "Cc7300007Mu")]
        public decimal Cc7300007Mu
        {
            get
            {
                return _cc7300007Mu;
            }

            set
            {
                _cc7300007Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("800-000-008")]
        [mp.Column(Name = "Cc8000008Mu")]
        public decimal Cc8000008Mu
        {
            get
            {
                return _cc8000008Mu;
            }

            set
            {
                _cc8000008Mu = value;
                this.IsModified = true;
            }
        }

        //[CostCodeAttr("900-000-009")]
        [mp.Column(Name = "Cc9000009Mu")]
        public decimal Cc9000009Mu
        {
            get
            {
                return _cc9000009Mu;
            }

            set
            {
                _cc9000009Mu = value;
                this.IsModified = true;
            }
        }



        public decimal Cc2102002Margin
        {
            get
            {
                return _cc2102002Margin;
            }

            set
            {
                _cc2102002Margin = value;
            }
        }

        public decimal Cc2200002Margin
        {
            get
            {
                return _cc2200002Margin;
            }

            set
            {
                _cc2200002Margin = value;
            }
        }

        public decimal Cc3100003Margin
        {
            get
            {
                return _cc3100003Margin;
            }

            set
            {
                _cc3100003Margin = value;
            }
        }

        public decimal Cc3200003Margin
        {
            get
            {
                return _cc3200003Margin;
            }

            set
            {
                _cc3200003Margin = value;
            }
        }

        public decimal Cc3300003Margin
        {
            get
            {
                return _cc3300003Margin;
            }

            set
            {
                _cc3300003Margin = value;
            }
        }

        public decimal Cc3400003Margin
        {
            get
            {
                return _cc3400003Margin;
            }

            set
            {
                _cc3400003Margin = value;
            }
        }

        public decimal Cc3500003Margin
        {
            get
            {
                return _cc3500003Margin;
            }

            set
            {
                _cc3500003Margin = value;
            }
        }

        public decimal Cc4100004Margin
        {
            get
            {
                return _cc4100004Margin;
            }

            set
            {
                _cc4100004Margin = value;
            }
        }

        public decimal Cc4200004Margin
        {
            get
            {
                return _cc4200004Margin;
            }

            set
            {
                _cc4200004Margin = value;
            }
        }

        public decimal Cc4300004Margin
        {
            get
            {
                return _cc4300004Margin;
            }

            set
            {
                _cc4300004Margin = value;
            }
        }

        public decimal Cc4400004Margin
        {
            get
            {
                return _cc4400004Margin;
            }

            set
            {
                _cc4400004Margin = value;
            }
        }

        public decimal Cc4500004Margin
        {
            get
            {
                return _cc4500004Margin;
            }

            set
            {
                _cc4500004Margin = value;
            }
        }

        public decimal Cc4600004Margin
        {
            get
            {
                return _cc4600004Margin;
            }

            set
            {
                _cc4600004Margin = value;
            }
        }

        public decimal Cc5100005Margin
        {
            get
            {
                return _cc5100005Margin;
            }

            set
            {
                _cc5100005Margin = value;
            }
        }

        public decimal Cc5200005Margin
        {
            get
            {
                return _cc5200005Margin;
            }

            set
            {
                _cc5200005Margin = value;
            }
        }

        public decimal Cc5300005Margin
        {
            get
            {
                return _cc5300005Margin;
            }

            set
            {
                _cc5300005Margin = value;
            }
        }

        public decimal Cc5400005Margin
        {
            get
            {
                return _cc5400005Margin;
            }

            set
            {
                _cc5400005Margin = value;
            }
        }

        public decimal Cc5500005Margin
        {
            get
            {
                return _cc5500005Margin;
            }

            set
            {
                _cc5500005Margin = value;
            }
        }

        public decimal Cc5600005Margin
        {
            get
            {
                return _cc5600005Margin;
            }

            set
            {
                _cc5600005Margin = value;
            }
        }

        public decimal Cc5700005Margin
        {
            get
            {
                return _cc5700005Margin;
            }

            set
            {
                _cc5700005Margin = value;
            }
        }

        public decimal Cc5800005Margin
        {
            get
            {
                return _cc5800005Margin;
            }

            set
            {
                _cc5800005Margin = value;
            }
        }

        public decimal Cc6100006Margin
        {
            get
            {
                return _cc6100006Margin;
            }

            set
            {
                _cc6100006Margin = value;
            }
        }

        public decimal Cc6200006Margin
        {
            get
            {
                return _cc6200006Margin;
            }

            set
            {
                _cc6200006Margin = value;
            }
        }

        public decimal Cc6300006Margin
        {
            get
            {
                return _cc6300006Margin;
            }

            set
            {
                _cc6300006Margin = value;
            }
        }

        public decimal Cc6400006Margin
        {
            get
            {
                return _cc6400006Margin;
            }

            set
            {
                _cc6400006Margin = value;
            }
        }

        public decimal Cc7100007Margin
        {
            get
            {
                return _cc7100007Margin;
            }

            set
            {
                _cc7100007Margin = value;
            }
        }

        public decimal Cc7200007Margin
        {
            get
            {
                return _cc7200007Margin;
            }

            set
            {
                _cc7200007Margin = value;
            }
        }

        public decimal Cc7300007Margin
        {
            get
            {
                return _cc7300007Margin;
            }

            set
            {
                _cc7300007Margin = value;
            }
        }

        public decimal Cc8000008Margin
        {
            get
            {
                return _cc8000008Margin;
            }

            set
            {
                _cc8000008Margin = value;
            }
        }

        public decimal Cc9000009Margin
        {
            get
            {
                return _cc9000009Margin;
            }

            set
            {
                _cc9000009Margin = value;
            }
        }



        public decimal Cc2102002CostTax
        {
            get
            {
                return _cc2102002CostTax;
            }

            set
            {
                _cc2102002CostTax = value;
                OnPropertyChanged("Cc2102002CostTax");
            }
        }

        public decimal Cc2200002CostTax
        {
            get
            {
                return _cc2200002CostTax;
            }

            set
            {
                _cc2200002CostTax = value;
                OnPropertyChanged("Cc2200002CostTax");
            }
        }

        public decimal Cc3100003CostTax
        {
            get
            {
                return _cc3100003CostTax;
            }

            set
            {
                _cc3100003CostTax = value;
                OnPropertyChanged("Cc3100003CostTax");
            }
        }

        public decimal Cc3200003CostTax
        {
            get
            {
                return _cc3200003CostTax;
            }

            set
            {
                _cc3200003CostTax = value;
                OnPropertyChanged("Cc3200003CostTax");
            }
        }

        public decimal Cc3300003CostTax
        {
            get
            {
                return _cc3300003CostTax;
            }

            set
            {
                _cc3300003CostTax = value;
                OnPropertyChanged("Cc3300003CostTax");
            }
        }

        public decimal Cc3400003CostTax
        {
            get
            {
                return _cc3400003CostTax;
            }

            set
            {
                _cc3400003CostTax = value;
                OnPropertyChanged("Cc3400003CostTax");
            }
        }

        public decimal Cc3500003CostTax
        {
            get
            {
                return _cc3500003CostTax;
            }

            set
            {
                _cc3500003CostTax = value;
                OnPropertyChanged("Cc3500003CostTax");
            }
        }

        public decimal Cc4100004CostTax
        {
            get
            {
                return _cc4100004CostTax;
            }

            set
            {
                _cc4100004CostTax = value;
                OnPropertyChanged("Cc4100004CostTax");
            }
        }

        public decimal Cc4200004CostTax
        {
            get
            {
                return _cc4200004CostTax;
            }

            set
            {
                _cc4200004CostTax = value;
                OnPropertyChanged("Cc4200004CostTax");
            }
        }

        public decimal Cc4300004CostTax
        {
            get
            {
                return _cc4300004CostTax;
            }

            set
            {
                _cc4300004CostTax = value;
                OnPropertyChanged("Cc4300004CostTax");
            }
        }

        public decimal Cc4400004CostTax
        {
            get
            {
                return _cc4400004CostTax;
            }

            set
            {
                _cc4400004CostTax = value;
                OnPropertyChanged("Cc4400004CostTax");
            }
        }

        public decimal Cc4500004CostTax
        {
            get
            {
                return _cc4500004CostTax;
            }

            set
            {
                _cc4500004CostTax = value;
                OnPropertyChanged("Cc4500004CostTax");
            }
        }

        public decimal Cc4600004CostTax
        {
            get
            {
                return _cc4600004CostTax;
            }

            set
            {
                _cc4600004CostTax = value;
                OnPropertyChanged("Cc4600004CostTax");
            }
        }

        public decimal Cc5100005CostTax
        {
            get
            {
                return _cc5100005CostTax;
            }

            set
            {
                _cc5100005CostTax = value;
                OnPropertyChanged("Cc5100005CostTax");
            }
        }

        public decimal Cc5200005CostTax
        {
            get
            {
                return _cc5200005CostTax;
            }

            set
            {
                _cc5200005CostTax = value;
                OnPropertyChanged("Cc5200005CostTax");
            }
        }

        public decimal Cc5300005CostTax
        {
            get
            {
                return _cc5300005CostTax;
            }

            set
            {
                _cc5300005CostTax = value;
                OnPropertyChanged("Cc5300005CostTax");
            }
        }

        public decimal Cc5400005CostTax
        {
            get
            {
                return _cc5400005CostTax;
            }

            set
            {
                _cc5400005CostTax = value;
                OnPropertyChanged("Cc5400005CostTax");
            }
        }

        public decimal Cc5500005CostTax
        {
            get
            {
                return _cc5500005CostTax;
            }

            set
            {
                _cc5500005CostTax = value;
                OnPropertyChanged("Cc5500005CostTax");
            }
        }

        public decimal Cc5600005CostTax
        {
            get
            {
                return _cc5600005CostTax;
            }

            set
            {
                _cc5600005CostTax = value;
                OnPropertyChanged("Cc5600005CostTax");
            }
        }

        public decimal Cc5700005CostTax
        {
            get
            {
                return _cc5700005CostTax;
            }

            set
            {
                _cc5700005CostTax = value;
                OnPropertyChanged("Cc5700005CostTax");
            }
        }

        public decimal Cc5800005CostTax
        {
            get
            {
                return _cc5800005CostTax;
            }

            set
            {
                _cc5800005CostTax = value;
                OnPropertyChanged("Cc5800005CostTax");
            }
        }

        public decimal Cc6100006CostTax
        {
            get
            {
                return _cc6100006CostTax;
            }

            set
            {
                _cc6100006CostTax = value;
                OnPropertyChanged("Cc6100006CostTax");
            }
        }

        public decimal Cc6200006CostTax
        {
            get
            {
                return _cc6200006CostTax;
            }

            set
            {
                _cc6200006CostTax = value;
                OnPropertyChanged("Cc6200006CostTax");
            }
        }

        public decimal Cc6300006CostTax
        {
            get
            {
                return _cc6300006CostTax;
            }

            set
            {
                _cc6300006CostTax = value;
                OnPropertyChanged("Cc6300006CostTax");
            }
        }

        public decimal Cc6400006CostTax
        {
            get
            {
                return _cc6400006CostTax;
            }

            set
            {
                _cc6400006CostTax = value;
                OnPropertyChanged("Cc6400006CostTax");
            }
        }

        public decimal Cc7100007CostTax
        {
            get
            {
                return _cc7100007CostTax;
            }

            set
            {
                _cc7100007CostTax = value;
                OnPropertyChanged("Cc7100007CostTax");
            }
        }

        public decimal Cc7200007CostTax
        {
            get
            {
                return _cc7200007CostTax;
            }

            set
            {
                _cc7200007CostTax = value;
                OnPropertyChanged("Cc7100007CostTax");
            }
        }

        public decimal Cc7300007CostTax
        {
            get
            {
                return _cc7300007CostTax;
            }

            set
            {
                _cc7300007CostTax = value;
                OnPropertyChanged("Cc7300007CostTax");
            }
        }

        public decimal Cc8000008CostTax
        {
            get
            {
                return _cc8000008CostTax;
            }

            set
            {
                _cc8000008CostTax = value;
                OnPropertyChanged("Cc8000008CostTax");
            }
        }

        public decimal Cc9000009CostTax
        {
            get
            {
                return _cc9000009CostTax;
            }

            set
            {
                _cc9000009CostTax = value;
                OnPropertyChanged("Cc9000009CostTax");
            }
        }


        [CostCodeSellWithTax("210-200-2", "2", "Supply Hardware")]
        public decimal Cc2102002SellTax
        {
            get
            {
                return _cc2102002SellTax;
            }

            set
            {
                _cc2102002SellTax = value;
                OnPropertyChanged("Cc2102002SellTax");
            }
        }

        [CostCodeSellWithTax("220-000-2", "2", "Supply Washroom Accessories")]
        public decimal Cc2200002SellTax
        {
            get
            {
                return _cc2200002SellTax;
            }

            set
            {
                _cc2200002SellTax = value;
                OnPropertyChanged("Cc2200002SellTax");
            }
        }

        [CostCodeSellWithTax("310-000-3", "3", "Supply HM Frames & Screens")]
        public decimal Cc3100003SellTax
        {
            get
            {
                return _cc3100003SellTax;
            }

            set
            {
                _cc3100003SellTax = value;
                OnPropertyChanged("Cc3100003SellTax");
            }
        }

        [CostCodeSellWithTax("320-000-3", "3", "Supply Hollow Metal Doors")]
        public decimal Cc3200003SellTax
        {
            get
            {
                return _cc3200003SellTax;
            }

            set
            {
                _cc3200003SellTax = value;
                OnPropertyChanged("Cc3200003SellTax");
            }
        }

        [CostCodeSellWithTax("330-000-3", "3", "Supply Wood Doors & Frames")]
        public decimal Cc3300003SellTax
        {
            get
            {
                return _cc3300003SellTax;
            }

            set
            {
                _cc3300003SellTax = value;
                OnPropertyChanged("Cc3300003SellTax");
            }
        }

        [CostCodeSellWithTax("340-000-3", "3", "Supply Glazing")]
        public decimal Cc3400003SellTax
        {
            get
            {
                return _cc3400003SellTax;
            }

            set
            {
                _cc3400003SellTax = value;
                OnPropertyChanged("Cc3400003SellTax");
            }
        }

        [CostCodeSellWithTax("350-000-3", "3", "Specialty Doors & Frames")]
        public decimal Cc3500003SellTax
        {
            get
            {
                return _cc3500003SellTax;
            }

            set
            {
                _cc3500003SellTax = value;
                OnPropertyChanged("Cc3500003SellTax");
            }
        }

        [CostCodeSellWithTax("410-000-4", "4", "Supply Auto Door Operator")]
        public decimal Cc4100004SellTax
        {
            get
            {
                return _cc4100004SellTax;
            }

            set
            {
                _cc4100004SellTax = value;
                OnPropertyChanged("Cc4100004SellTax");
            }
        }

        [CostCodeSellWithTax("420-000-4", "4", "None")]
        public decimal Cc4200004SellTax
        {
            get
            {
                return _cc4200004SellTax;
            }

            set
            {
                _cc4200004SellTax = value;
                OnPropertyChanged("Cc4200004SellTax");
            }
        }

        [CostCodeSellWithTax("430-000-4", "4", "Install Auto Door Operators")]
        public decimal Cc4300004SellTax
        {
            get
            {
                return _cc4300004SellTax;
            }

            set
            {
                _cc4300004SellTax = value;
                OnPropertyChanged("Cc4300004SellTax");
            }
        }

        [CostCodeSellWithTax("440-000-4", "4", "Install/Comm Electrical Integration Hardware")]
        public decimal Cc4400004SellTax
        {
            get
            {
                return _cc4400004SellTax;
            }

            set
            {
                _cc4400004SellTax = value;
                OnPropertyChanged("Cc4400004SellTax");
            }
        }

        [CostCodeSellWithTax("450-000-4", "4", "Shop Installation Hardware")]
        public decimal Cc4500004SellTax
        {
            get
            {
                return _cc4500004SellTax;
            }

            set
            {
                _cc4500004SellTax = value;
                OnPropertyChanged("Cc4500004SellTax");
            }
        }

        [CostCodeSellWithTax("460-000-4", "4", "Shop Installation Glazing")]
        public decimal Cc4600004SellTax
        {
            get
            {
                return _cc4600004SellTax;
            }

            set
            {
                _cc4600004SellTax = value;
                OnPropertyChanged("Cc4600004SellTax");
            }
        }

        [CostCodeSellWithTax("510-000-5", "5", "Field Install Doors & Hardware")]
        public decimal Cc5100005SellTax
        {
            get
            {
                return _cc5100005SellTax;
            }

            set
            {
                _cc5100005SellTax = value;
                OnPropertyChanged("Cc5100005SellTax");
            }
        }

        [CostCodeSellWithTax("520-000-5", "5", "Field Install Frames")]
        public decimal Cc5200005SellTax
        {
            get
            {
                return _cc5200005SellTax;
            }

            set
            {
                _cc5200005SellTax = value;
                OnPropertyChanged("Cc5200005SellTax");
            }
        }

        [CostCodeSellWithTax("530-000-5", "5", "Warranty Work")]
        public decimal Cc5300005SellTax
        {
            get
            {
                return _cc5300005SellTax;
            }

            set
            {
                _cc5300005SellTax = value;
                OnPropertyChanged("Cc5300005SellTax");
            }
        }

        [CostCodeSellWithTax("540-000-5", "5", "Service Work")]
        public decimal Cc5400005SellTax
        {
            get
            {
                return _cc5400005SellTax;
            }

            set
            {
                _cc5400005SellTax = value;
                OnPropertyChanged("Cc5400005SellTax");
            }
        }

        [CostCodeSellWithTax("550-000-5", "5", "Shop Installation of Hardware")]
        public decimal Cc5500005SellTax
        {
            get
            {
                return _cc5500005SellTax;
            }

            set
            {
                _cc5500005SellTax = value;
                OnPropertyChanged("Cc5500005SellTax");
            }
        }

        [CostCodeSellWithTax("560-000-5", "5", "Shop Installation of Glazing")]
        public decimal Cc5600005SellTax
        {
            get
            {
                return _cc5600005SellTax;
            }

            set
            {
                _cc5600005SellTax = value;
                OnPropertyChanged("Cc5600005SellTax");
            }
        }

        [CostCodeSellWithTax("570-000-5", "5", "Remedial Work")]
        public decimal Cc5700005SellTax
        {
            get
            {
                return _cc5700005SellTax;
            }

            set
            {
                _cc5700005SellTax = value;
                OnPropertyChanged("Cc5700005SellTax");
            }
        }

        [CostCodeSellWithTax("580-000-5", "5", "Travel (UCI)")]
        public decimal Cc5800005SellTax
        {
            get
            {
                return _cc5800005SellTax;
            }

            set
            {
                _cc5800005SellTax = value;
                OnPropertyChanged("Cc5800005SellTax");
            }
        }

        [CostCodeSellWithTax("610-000-6", "6", "Install Frames (3rd Party)")]
        public decimal Cc6100006SellTax
        {
            get
            {
                return _cc6100006SellTax;
            }

            set
            {
                _cc6100006SellTax = value;
                OnPropertyChanged("Cc6100006SellTax");
            }
        }

        [CostCodeSellWithTax("620-000-6", "6", "Install Doors & Hardware (3rd Party)")]
        public decimal Cc6200006SellTax
        {
            get
            {
                return _cc6200006SellTax;
            }

            set
            {
                _cc6200006SellTax = value;
                OnPropertyChanged("Cc6200006SellTax");
            }
        }

        [CostCodeSellWithTax("630-000-6", "6", "Remedial Work (3rd Party)")]
        public decimal Cc6300006SellTax
        {
            get
            {
                return _cc6300006SellTax;
            }

            set
            {
                _cc6300006SellTax = value;
                OnPropertyChanged("Cc6300006SellTax");
            }
        }

        [CostCodeSellWithTax("640-000-6", "6", "Supply & Install Auto Op (3rd Party)")]
        public decimal Cc6400006SellTax
        {
            get
            {
                return _cc6400006SellTax;
            }

            set
            {
                _cc6400006SellTax = value;
                OnPropertyChanged("Cc6400006SellTax");
            }
        }

        [CostCodeSellWithTax("710-000-7", "7", "Travel Expenses")]
        public decimal Cc7100007SellTax
        {
            get
            {
                return _cc7100007SellTax;
            }

            set
            {
                _cc7100007SellTax = value;
                OnPropertyChanged("Cc7100007SellTax");
            }
        }

        [CostCodeSellWithTax("720-000-7", "7", "Automobile Expenses")]
        public decimal Cc7200007SellTax
        {
            get
            {
                return _cc7200007SellTax;
            }

            set
            {
                _cc7200007SellTax = value;
                OnPropertyChanged("Cc7200007SellTax");
            }
        }

        [CostCodeSellWithTax("730-000-7", "7", "Gas Expenses")]
        public decimal Cc7300007SellTax
        {
            get
            {
                return _cc7300007SellTax;
            }

            set
            {
                _cc7300007SellTax = value;
                OnPropertyChanged("Cc7300007SellTax");
            }
        }

        [CostCodeSellWithTax("800-000-8", "8", "Freight")]
        public decimal Cc8000008SellTax
        {
            get
            {
                return _cc8000008SellTax;
            }

            set
            {
                _cc8000008SellTax = value;
                OnPropertyChanged("Cc8000008SellTax");
            }
        }

        [CostCodeSellWithTax("900-000-9", "9", "MISC")]
        public decimal Cc9000009SellTax
        {
            get
            {
                return _cc9000009SellTax;
            }

            set
            {
                _cc9000009SellTax = value;
                OnPropertyChanged("Cc9000009SellTax");
            }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set
            {
                _dateCreated = value;
                OnPropertyChanged("DateCreated");
            }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set
            {
                _timeCreated = value;
                OnPropertyChanged("TimeCreated");
            }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set
            {
                _updatingUser = value;
                OnPropertyChanged("UpdatingUser");
            }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set
            {
                _updatingMachine = value;
                OnPropertyChanged("UpdatingMachine");
            }
        }

        public bool IsModified
        {
            get { return _isModified; }
            set
            {
                _isModified = value;
                OnPropertyChanged("IsModified");
                OnPropertyChanged("UiSellTotal");
                OnPropertyChanged("UiSellTotalWithTax");
                OnPropertyChanged("RevenuePerDoor");
            }
        }

        public bool IsDeleted
        {
            get { return _isDeleted; }
            set { _isDeleted = value; }
        }

        public bool IsNew
        {
            get { return _isNew; }
            set { _isNew = value; }
        }



        #endregion

        public QuoteSummary()
        {

        }

        //Basic new quote for a job that hasn't had any quotes made for it before
        public QuoteSummary(KeyValuePair<string, string> kvp)
        {
            _id = 0;
            _jobNumber = kvp.Key;
            _jobName = kvp.Value;
            _quoteNumber = "Q001";
            _originatingDocumentNumber = _quoteNumber;
            _isModified = false;
            _iteration = 1;
            _revisionIteration = 0;
            _isRevision = false;
        }

        //LINQ Constructor
        public QuoteSummary(int id,
                            int iteration,
                            string jobNumber,
                            string jobName,
                            string quoteNumber,
                            bool isRevision,
                            string originatingDocumentNumber,
                            int revisionIteration,
                            string contractor,
                            DateTime? closingDate,

                            decimal pstTax,
                            decimal gstTax,

                            QsInstaller fieldInstall,
                            QsInstaller frameInstall,
                            QsInstaller autoOperatorInstall,

                            decimal numberOfDoorLeafs,
                            decimal revenuePerDoor,

                            decimal cc2102002Cost,
                            decimal cc2200002Cost,
                            decimal cc3100003Cost,
                            decimal cc3200003Cost,
                            decimal cc3300003Cost,
                            decimal cc3400003Cost,
                            decimal cc3500003Cost,
                            decimal cc4100004Cost,
                            decimal cc4200004Cost,
                            decimal cc4300004Cost,
                            decimal cc4400004Cost,
                            decimal cc4500004Cost,
                            decimal cc4600004Cost,
                            decimal cc5100005Cost,
                            decimal cc5200005Cost,
                            decimal cc5300005Cost,
                            decimal cc5400005Cost,
                            decimal cc5500005Cost,
                            decimal cc5600005Cost,
                            decimal cc5700005Cost,
                            decimal cc5800005Cost,
                            decimal cc6100006Cost,
                            decimal cc6200006Cost,
                            decimal cc6300006Cost,
                            decimal cc6400006Cost,
                            decimal cc7100007Cost,
                            decimal cc7200007Cost,
                            decimal cc7300007Cost,
                            decimal cc8000008Cost,
                            decimal cc9000009Cost,


                            decimal cc2102002Sell,
                            decimal cc2200002Sell,
                            decimal cc3100003Sell,
                            decimal cc3200003Sell,
                            decimal cc3300003Sell,
                            decimal cc3400003Sell,
                            decimal cc3500003Sell,
                            decimal cc4100004Sell,
                            decimal cc4200004Sell,
                            decimal cc4300004Sell,
                            decimal cc4400004Sell,
                            decimal cc4500004Sell,
                            decimal cc4600004Sell,
                            decimal cc5100005Sell,
                            decimal cc5200005Sell,
                            decimal cc5300005Sell,
                            decimal cc5400005Sell,
                            decimal cc5500005Sell,
                            decimal cc5600005Sell,
                            decimal cc5700005Sell,
                            decimal cc5800005Sell,
                            decimal cc6100006Sell,
                            decimal cc6200006Sell,
                            decimal cc6300006Sell,
                            decimal cc6400006Sell,
                            decimal cc7100007Sell,
                            decimal cc7200007Sell,
                            decimal cc7300007Sell,
                            decimal cc8000008Sell,
                            decimal cc9000009Sell,


                            decimal cc2102002Mu,
                            decimal cc2200002Mu,
                            decimal cc3100003Mu,
                            decimal cc3200003Mu,
                            decimal cc3300003Mu,
                            decimal cc3400003Mu,
                            decimal cc3500003Mu,
                            decimal cc4100004Mu,
                            decimal cc4200004Mu,
                            decimal cc4300004Mu,
                            decimal cc4400004Mu,
                            decimal cc4500004Mu,
                            decimal cc4600004Mu,
                            decimal cc5100005Mu,
                            decimal cc5200005Mu,
                            decimal cc5300005Mu,
                            decimal cc5400005Mu,
                            decimal cc5500005Mu,
                            decimal cc5600005Mu,
                            decimal cc5700005Mu,
                            decimal cc5800005Mu,
                            decimal cc6100006Mu,
                            decimal cc6200006Mu,
                            decimal cc6300006Mu,
                            decimal cc6400006Mu,
                            decimal cc7100007Mu,
                            decimal cc7200007Mu,
                            decimal cc7300007Mu,
                            decimal cc8000008Mu,
                            decimal cc9000009Mu,

                            DateTime? dateCreated,
                            DateTime? timeCreated,
                            string updatingUser,
                            string updatingMachine
            )
        {
            _id = id;
            _iteration = iteration;
            _jobNumber = jobNumber;
            _jobName = jobName;
            _quoteNumber = quoteNumber;
            _isRevision = isRevision;
            _originatingDocumentNumber = originatingDocumentNumber;
            _revisionIteration = revisionIteration;
            _contractor = contractor;
            _closingDate = closingDate;

            _pstTax = pstTax;
            _gstTax = gstTax;

            _fieldInstall = fieldInstall;
            _frameInstall = frameInstall;
            _autoOperatorInstall = autoOperatorInstall;

            _numberOfDoorLeafs = numberOfDoorLeafs;
            _revenuePerDoor = revenuePerDoor;

            _cc2102002Cost = cc2102002Cost;
            _cc2200002Cost = cc2200002Cost;
            _cc3100003Cost = cc3100003Cost;
            _cc3200003Cost = cc3200003Cost;
            _cc3300003Cost = cc3300003Cost;
            _cc3400003Cost = cc3400003Cost;
            _cc3500003Cost = cc3500003Cost;
            _cc4100004Cost = cc4100004Cost;
            _cc4200004Cost = cc4200004Cost;
            _cc4300004Cost = cc4300004Cost;
            _cc4400004Cost = cc4400004Cost;
            _cc4500004Cost = cc4500004Cost;
            _cc4600004Cost = cc4600004Cost;
            _cc5100005Cost = cc5100005Cost;
            _cc5200005Cost = cc5200005Cost;
            _cc5300005Cost = cc5300005Cost;
            _cc5400005Cost = cc5400005Cost;
            _cc5500005Cost = cc5500005Cost;
            _cc5600005Cost = cc5600005Cost;
            _cc5700005Cost = cc5700005Cost;
            _cc5800005Cost = cc5800005Cost;
            _cc6100006Cost = cc6100006Cost;
            _cc6200006Cost = cc6200006Cost;
            _cc6300006Cost = cc6300006Cost;
            _cc6400006Cost = cc6400006Cost;
            _cc7100007Cost = cc7100007Cost;
            _cc7200007Cost = cc7200007Cost;
            _cc7300007Cost = cc7300007Cost;
            _cc8000008Cost = cc8000008Cost;
            _cc9000009Cost = cc9000009Cost;

            _cc2102002Sell = cc2102002Sell;
            _cc2200002Sell = cc2200002Sell;
            _cc3100003Sell = cc3100003Sell;
            _cc3200003Sell = cc3200003Sell;
            _cc3300003Sell = cc3300003Sell;
            _cc3400003Sell = cc3400003Sell;
            _cc3500003Sell = cc3500003Sell;
            _cc4100004Sell = cc4100004Sell;
            _cc4200004Sell = cc4200004Sell;
            _cc4300004Sell = cc4300004Sell;
            _cc4400004Sell = cc4400004Sell;
            _cc4500004Sell = cc4500004Sell;
            _cc4600004Sell = cc4600004Sell;
            _cc5100005Sell = cc5100005Sell;
            _cc5200005Sell = cc5200005Sell;
            _cc5300005Sell = cc5300005Sell;
            _cc5400005Sell = cc5400005Sell;
            _cc5500005Sell = cc5500005Sell;
            _cc5600005Sell = cc5600005Sell;
            _cc5700005Sell = cc5700005Sell;
            _cc5800005Sell = cc5800005Sell;
            _cc6100006Sell = cc6100006Sell;
            _cc6200006Sell = cc6200006Sell;
            _cc6300006Sell = cc6300006Sell;
            _cc6400006Sell = cc6400006Sell;
            _cc7100007Sell = cc7100007Sell;
            _cc7200007Sell = cc7200007Sell;
            _cc7300007Sell = cc7300007Sell;
            _cc8000008Sell = cc8000008Sell;
            _cc9000009Sell = cc9000009Sell;

            _cc2102002Mu = cc2102002Mu;
            _cc2200002Mu = cc2200002Mu;
            _cc3100003Mu = cc3100003Mu;
            _cc3200003Mu = cc3200003Mu;
            _cc3300003Mu = cc3300003Mu;
            _cc3400003Mu = cc3400003Mu;
            _cc3500003Mu = cc3500003Mu;
            _cc4100004Mu = cc4100004Mu;
            _cc4200004Mu = cc4200004Mu;
            _cc4300004Mu = cc4300004Mu;
            _cc4400004Mu = cc4400004Mu;
            _cc4500004Mu = cc4500004Mu;
            _cc4600004Mu = cc4600004Mu;
            _cc5100005Mu = cc5100005Mu;
            _cc5200005Mu = cc5200005Mu;
            _cc5300005Mu = cc5300005Mu;
            _cc5400005Mu = cc5400005Mu;
            _cc5500005Mu = cc5500005Mu;
            _cc5600005Mu = cc5600005Mu;
            _cc5700005Mu = cc5700005Mu;
            _cc5800005Mu = cc5800005Mu;
            _cc6100006Mu = cc6100006Mu;
            _cc6200006Mu = cc6200006Mu;
            _cc6300006Mu = cc6300006Mu;
            _cc6400006Mu = cc6400006Mu;
            _cc7100007Mu = cc7100007Mu;
            _cc7200007Mu = cc7200007Mu;
            _cc7300007Mu = cc7300007Mu;
            _cc8000008Mu = cc8000008Mu;
            _cc9000009Mu = cc9000009Mu;

            _cc2102002CostTax = _cc2102002Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc2200002CostTax = _cc2200002Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3100003CostTax = _cc3100003Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3200003CostTax = _cc3200003Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3300003CostTax = _cc3300003Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3400003CostTax = _cc3400003Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3500003CostTax = _cc3500003Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4100004CostTax = _cc4100004Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4200004CostTax = _cc4200004Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4300004CostTax = _cc4300004Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4400004CostTax = _cc4400004Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4500004CostTax = _cc4500004Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4600004CostTax = _cc4600004Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5100005CostTax = _cc5100005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5200005CostTax = _cc5200005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5300005CostTax = _cc5300005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5400005CostTax = _cc5400005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5500005CostTax = _cc5500005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5600005CostTax = _cc5600005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5700005CostTax = _cc5700005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5800005CostTax = _cc5800005Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6100006CostTax = _cc6100006Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6200006CostTax = _cc6200006Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6300006CostTax = _cc6300006Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6400006CostTax = _cc6400006Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc7100007CostTax = _cc7100007Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc7200007CostTax = _cc7200007Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc7300007CostTax = _cc7300007Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc8000008CostTax = _cc8000008Cost * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc9000009CostTax = _cc9000009Cost * (1 + (_gstTax / 100) + (_pstTax / 100));

            _cc2102002SellTax = _cc2102002Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc2200002SellTax = _cc2200002Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3100003SellTax = _cc3100003Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3200003SellTax = _cc3200003Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3300003SellTax = _cc3300003Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3400003SellTax = _cc3400003Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc3500003SellTax = _cc3500003Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4100004SellTax = _cc4100004Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4200004SellTax = _cc4200004Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4300004SellTax = _cc4300004Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4400004SellTax = _cc4400004Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4500004SellTax = _cc4500004Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc4600004SellTax = _cc4600004Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5100005SellTax = _cc5100005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5200005SellTax = _cc5200005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5300005SellTax = _cc5300005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5400005SellTax = _cc5400005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5500005SellTax = _cc5500005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5600005SellTax = _cc5600005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5700005SellTax = _cc5700005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc5800005SellTax = _cc5800005Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6100006SellTax = _cc6100006Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6200006SellTax = _cc6200006Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6300006SellTax = _cc6300006Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc6400006SellTax = _cc6400006Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc7100007SellTax = _cc7100007Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc7200007SellTax = _cc7200007Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc7300007SellTax = _cc7300007Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc8000008SellTax = _cc8000008Sell * (1 + (_gstTax / 100) + (_pstTax / 100));
            _cc9000009SellTax = _cc9000009Sell * (1 + (_gstTax / 100) + (_pstTax / 100));

            _dateCreated = dateCreated;
            _timeCreated = timeCreated;
            _updatingUser = updatingUser;
            _updatingMachine = updatingMachine;

        }

        //UI new quote constructor which is already fed to it the newest quote (denoted as "qs" in the constructor parameters) with both highest iteration and highest iteration number from the calling code
        public QuoteSummary(QuoteSummary qs, bool isRevFromUi)
        {
            //IT STILL NEEDS TO BE GIVEN AN ID WHEN IT GETS SENT TO BE CREATED IN THE DB
            if (isRevFromUi == false)
            {
                GenerateNewQuoteNumber(qs.Iteration);
                _originatingDocumentNumber = this._quoteNumber;
                _revisionIteration = 0;
            }
            else
            {
                _iteration = qs.Iteration;
                _isRevision = true;
                _revisionIteration = qs.RevisionIteration + 1;
                _quoteNumber = qs.OriginatingDocumentNumber + "r" + _revisionIteration;  //We just iterated the _revision iteration up one increment the line above, so no need to add "+1" here
                _originatingDocumentNumber = qs.OriginatingDocumentNumber;
            }

            _jobNumber = qs.JobNumber;
            _jobName = qs.JobName;
            _contractor = qs.Contractor;
            _closingDate = qs.ClosingDate;

            _pstTax = qs.PstTax;
            _gstTax = qs.GstTax;

            _fieldInstall = qs.FieldInstall;
            _frameInstall = qs.FrameInstall;
            _autoOperatorInstall = qs.AutoOperatorInstall;

            _numberOfDoorLeafs = qs.NumberOfDoorLeafs;
            _revenuePerDoor = qs.RevenuePerDoor;

            _cc2102002Cost = qs.Cc2102002Cost;
            _cc2200002Cost = qs.Cc2200002Cost;
            _cc3100003Cost = qs.Cc3100003Cost;
            _cc3200003Cost = qs.Cc3200003Cost;
            _cc3300003Cost = qs.Cc3300003Cost;
            _cc3400003Cost = qs.Cc3400003Cost;
            _cc3500003Cost = qs.Cc3500003Cost;
            _cc4100004Cost = qs.Cc4100004Cost;
            _cc4200004Cost = qs.Cc4200004Cost;
            _cc4300004Cost = qs.Cc4300004Cost;
            _cc4400004Cost = qs.Cc4400004Cost;
            _cc4500004Cost = qs.Cc4500004Cost;
            _cc4600004Cost = qs.Cc4600004Cost;
            _cc5100005Cost = qs.Cc5100005Cost;
            _cc5200005Cost = qs.Cc5200005Cost;
            _cc5300005Cost = qs.Cc5300005Cost;
            _cc5400005Cost = qs.Cc5400005Cost;
            _cc5500005Cost = qs.Cc5500005Cost;
            _cc5600005Cost = qs.Cc5600005Cost;
            _cc5700005Cost = qs.Cc5700005Cost;
            _cc5800005Cost = qs.Cc5800005Cost;
            _cc6100006Cost = qs.Cc6100006Cost;
            _cc6200006Cost = qs.Cc6200006Cost;
            _cc6300006Cost = qs.Cc6300006Cost;
            _cc6400006Cost = qs.Cc6400006Cost;
            _cc7100007Cost = qs.Cc7100007Cost;
            _cc7200007Cost = qs.Cc7200007Cost;
            _cc7300007Cost = qs.Cc7300007Cost;
            _cc8000008Cost = qs.Cc8000008Cost;
            _cc9000009Cost = qs.Cc9000009Cost;


            _cc2102002Sell = qs.Cc2102002Sell;
            _cc2200002Sell = qs.Cc2200002Sell;
            _cc3100003Sell = qs.Cc3100003Sell;
            _cc3200003Sell = qs.Cc3200003Sell;
            _cc3300003Sell = qs.Cc3300003Sell;
            _cc3400003Sell = qs.Cc3400003Sell;
            _cc3500003Sell = qs.Cc3500003Sell;
            _cc4100004Sell = qs.Cc4100004Sell;
            _cc4200004Sell = qs.Cc4200004Sell;
            _cc4300004Sell = qs.Cc4300004Sell;
            _cc4400004Sell = qs.Cc4400004Sell;
            _cc4500004Sell = qs.Cc4500004Sell;
            _cc4600004Sell = qs.Cc4600004Sell;
            _cc5100005Sell = qs.Cc5100005Sell;
            _cc5200005Sell = qs.Cc5200005Sell;
            _cc5300005Sell = qs.Cc5300005Sell;
            _cc5400005Sell = qs.Cc5400005Sell;
            _cc5500005Sell = qs.Cc5500005Sell;
            _cc5600005Sell = qs.Cc5600005Sell;
            _cc5700005Sell = qs.Cc5700005Sell;
            _cc5800005Sell = qs.Cc5800005Sell;
            _cc6100006Sell = qs.Cc6100006Sell;
            _cc6200006Sell = qs.Cc6200006Sell;
            _cc6300006Sell = qs.Cc6300006Sell;
            _cc6400006Sell = qs.Cc6400006Sell;
            _cc7100007Sell = qs.Cc7100007Sell;
            _cc7200007Sell = qs.Cc7200007Sell;
            _cc7300007Sell = qs.Cc7300007Sell;
            _cc8000008Sell = qs.Cc8000008Sell;
            _cc9000009Sell = qs.Cc9000009Sell;


            _cc2102002Mu = qs.Cc2102002Mu;
            _cc2200002Mu = qs.Cc2200002Mu;
            _cc3100003Mu = qs.Cc3100003Mu;
            _cc3200003Mu = qs.Cc3200003Mu;
            _cc3300003Mu = qs.Cc3300003Mu;
            _cc3400003Mu = qs.Cc3400003Mu;
            _cc3500003Mu = qs.Cc3500003Mu;
            _cc4100004Mu = qs.Cc4100004Mu;
            _cc4200004Mu = qs.Cc4200004Mu;
            _cc4300004Mu = qs.Cc4300004Mu;
            _cc4400004Mu = qs.Cc4400004Mu;
            _cc4500004Mu = qs.Cc4500004Mu;
            _cc4600004Mu = qs.Cc4600004Mu;
            _cc5100005Mu = qs.Cc5100005Mu;
            _cc5200005Mu = qs.Cc5200005Mu;
            _cc5300005Mu = qs.Cc5300005Mu;
            _cc5400005Mu = qs.Cc5400005Mu;
            _cc5500005Mu = qs.Cc5500005Mu;
            _cc5600005Mu = qs.Cc5600005Mu;
            _cc5700005Mu = qs.Cc5700005Mu;
            _cc5800005Mu = qs.Cc5800005Mu;
            _cc6100006Mu = qs.Cc6100006Mu;
            _cc6200006Mu = qs.Cc6200006Mu;
            _cc6300006Mu = qs.Cc6300006Mu;
            _cc6400006Mu = qs.Cc6400006Mu;
            _cc7100007Mu = qs.Cc7100007Mu;
            _cc7200007Mu = qs.Cc7200007Mu;
            _cc7300007Mu = qs.Cc7300007Mu;
            _cc8000008Mu = qs.Cc8000008Mu;
            _cc9000009Mu = qs.Cc9000009Mu;

            _dateCreated = qs.DateCreated;
            _timeCreated = qs.TimeCreated;
            _updatingUser = qs.UpdatingUser;
            _updatingMachine = qs.UpdatingMachine;

        }

        private void GenerateNewQuoteNumber(int iteration)
        {
            this.Iteration = iteration + 1;

            if (iteration < 10)
            {
                this._quoteNumber = "Q00" + this.Iteration;
                return;
            }

            if (iteration < 100)
            {
                this._quoteNumber = "Q0" + this.Iteration;
                return;
            }

            if (iteration < 999)
            {
                this._quoteNumber = "Q" + this.Iteration;
                return;

            }

            if (iteration > 999)
            {
                this._quoteNumber = "Q" + this.Iteration;
                return;
            }

            this._originatingDocumentNumber = this._quoteNumber;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

    }

    public class QuoteSummaryDataContext : lq.DataContext
    {
        public QuoteSummaryDataContext(string cs)
            : base(cs)
        {
        }

        public QuoteSummaryDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<QuoteSummary> QuoteSummary;
    }


    public enum QsInstaller : int
    {
        None = 0,
        UCI,
        UCA,
        ThirdParty
    }

    [AttributeUsage(AttributeTargets.Property | AttributeTargets.Field, Inherited = true, AllowMultiple = false)]
    [ImmutableObject(true)]
    public sealed class CostCodeSellWithTax : Attribute
    {
        private readonly string _costCodeNumber;
        private readonly string _costCodeNumberFamily;
        private readonly string _costCodeName;

        public string CostCodeNumber { get { return _costCodeNumber; } }
        public string CostCodeName { get { return _costCodeName; } }
        public string CostCodeNumberFamily { get { return _costCodeNumberFamily; } }

        public CostCodeSellWithTax(string costCodeNumber, string costCodeNumberFamily, string costCode)
        {
            this._costCodeNumber = costCodeNumber;
            this._costCodeNumberFamily = costCodeNumberFamily;
            this._costCodeName = costCode;
        }
    }

    [AttributeUsage(AttributeTargets.Property | AttributeTargets.Field, Inherited = true, AllowMultiple = false)]
    [ImmutableObject(true)]
    public sealed class CostCodeSell : Attribute
    {
        private readonly string _costCodeNumber;
        private readonly string _costCodeNumberFamily;
        private readonly string _costCodeName;

        public string CostCodeNumber { get { return _costCodeNumber; } }
        public string CostCodeName { get { return _costCodeName; } }
        public string CostCodeNumberFamily { get { return _costCodeNumberFamily; } }

        public CostCodeSell(string costCodeNumber, string costCodeNumberFamily, string costCode)
        {
            this._costCodeNumber = costCodeNumber;
            this._costCodeNumberFamily = costCodeNumberFamily;
            this._costCodeName = costCode;
        }
    }
}
