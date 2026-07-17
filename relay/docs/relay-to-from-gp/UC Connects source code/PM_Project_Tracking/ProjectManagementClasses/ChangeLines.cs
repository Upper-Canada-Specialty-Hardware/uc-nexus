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
    class ChangeLines
    {
        public static ObservableCollection<ChangeLine> GetChangeLinesByQuote(string jobNumber, string quoteNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ChangeLine> lineList = null;
            int latestIter = 0;
            int latestRev = 0;

            try
            {
                var maxIter = um.CreatingNewProgressBilling.GetMaxHeaderIteration(jobNumber);
                ProgressBillingHeader latestPb = um.CreatingNewProgressBilling.GetLatestProgressBilling(jobNumber, maxIter);
                if (latestPb != null) { latestIter = latestPb.Iteration; latestRev = latestPb.Revision; }

                var lineQuery = from cl in dtCtx.GetTable<ChangeLine>()
                                where cl.JobNumber == jobNumber && cl.QuoteNumber == quoteNumber
                                orderby cl.CostCode ascending, cl.CostCodeSerial ascending
                                select new
                                {
                                    Id = cl.Id,
                                    JobNumber = cl.JobNumber,
                                    QuoteNumber = cl.QuoteNumber,
                                    CostCodeSerial = cl.CostCodeSerial,
                                    CostCode = cl.CostCode,
                                    CostCodeName = cl.CostCodeName,
                                    LineDescription = cl.LineDescription,
                                    AvaFileLocation = cl.AvaFileLocation,
                                    AvaFileName = cl.AvaFileName,
                                    AvaScheduleDate = cl.AvaImportDate,
                                    PoNumber = cl.PoNumber,
                                    Order = cl.Order,
                                    PoTagDate = cl.PoTagDate,
                                    Billed = cl.Billed,
                                    BilledDate = cl.BilledDate,
                                    BilledUser = cl.BilledUser,
                                    Quantity = cl.Quantity,
                                    SellPrice = cl.SellPrice,
                                    ExtendedSellPrice = cl.ExtendedSellPrice,
                                    cl.Discount,
                                    Multiplier = cl.Multiplier,
                                    CostUcsh = cl.CostUcsh,
                                    TotalLineCostUcsh = cl.TotalLineCostUcsh,
                                    Remarks = cl.Remarks,
                                    IsLabour = cl.IsLabour,
                                    LabourType = cl.LabourType,
                                    //need to get latest progress bill/revision numbers for this, since they're the only relevant ones at any given time
                                    //QuantityDrawnPrevious = 0,
                                    QuantityDrawnPrevious = dtCtx.GetTable<ChangeLineDrawDown>().Where(n => n.JobNumber == cl.JobNumber
                                                                   && n.QuoteNumber == cl.QuoteNumber
                                                                   && n.CostCode == cl.CostCode
                                                                   && n.CostCodeSerial == cl.CostCodeSerial
                                                                   && n.ProgressBillIteration == latestIter //2
                                                                   && n.ProgressBillRevision == latestRev).Select(r => r.QuantityDrawn).Sum() == null //0
                                                                   ? 0 :
                                                                   dtCtx.GetTable<ChangeLineDrawDown>().Where(n => n.JobNumber == cl.JobNumber
                                                                   && n.QuoteNumber == cl.QuoteNumber
                                                                   && n.CostCode == cl.CostCode
                                                                   && n.CostCodeSerial == cl.CostCodeSerial
                                                                   && n.ProgressBillIteration == latestIter //2
                                                                   && n.ProgressBillRevision == latestRev).Select(r => r.QuantityDrawn).Sum(), //0

                                    DateCreated = cl.DateCreated,
                                    TimeCreated = cl.TimeCreated,
                                    UpdatingUser = cl.UpdatingUser,
                                    UpdatingMachine = cl.UpdatingMachine
                                };

                lineList = lineQuery.AsEnumerable().Select(x => new ChangeLine(x.Id, x.JobNumber, x.QuoteNumber, x.CostCodeSerial, x.CostCode,
                                                                                x.CostCodeName,
                                                                                x.LineDescription, x.AvaFileLocation, x.AvaFileName, x.AvaScheduleDate, x.PoNumber,
                                                                                x.Order, x.PoTagDate, 
                                                                                x.Billed,
                                                                                x.BilledDate,
                                                                                x.BilledUser,
                                                                                x.Quantity, x.SellPrice, x.ExtendedSellPrice,
                                                                                x.Discount,
                                                                                x.Multiplier, x.CostUcsh, x.TotalLineCostUcsh, x.Remarks, x.IsLabour,
                                                                                (ChangeLabourType)x.LabourType, x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine
                                                                                ,x.QuantityDrawnPrevious)).ToList();

                if (lineList.Count == 0)
                {
                    lineList = new List<ChangeLine>();
                    return new ObservableCollection<ChangeLine>(lineList);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return new ObservableCollection<ChangeLine>(lineList);
        }

        public static ObservableCollection<ChangeLine> GetChangeLinesByJob(ProgressBillingHeader pbHeader)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ChangeLine> lineList = null;

            try
            {
                var lineQuery = from cl in dtCtx.GetTable<ChangeLine>()
                                where cl.JobNumber == pbHeader.JobNumber
                                orderby cl.CostCode ascending, cl.CostCodeSerial ascending
                                select new
                                {
                                    Id = cl.Id,
                                    JobNumber = cl.JobNumber,
                                    QuoteNumber = cl.QuoteNumber,
                                    CostCodeSerial = cl.CostCodeSerial,
                                    CostCode = cl.CostCode,
                                    CostCodeName = cl.CostCodeName,
                                    LineDescription = cl.LineDescription,
                                    AvaFileLocation = cl.AvaFileLocation,
                                    AvaFileName = cl.AvaFileName,
                                    AvaScheduleDate = cl.AvaImportDate,
                                    PoNumber = cl.PoNumber,
                                    Order = cl.Order,
                                    PoTagDate = cl.PoTagDate,
                                    Billed = cl.Billed,
                                    BilledDate = cl.BilledDate,
                                    BilledUser = cl.BilledUser,
                                    Quantity = cl.Quantity,
                                    SellPrice = cl.SellPrice,
                                    ExtendedSellPrice = cl.ExtendedSellPrice,
                                    cl.Discount,
                                    Multiplier = cl.Multiplier,
                                    CostUcsh = cl.CostUcsh,
                                    TotalLineCostUcsh = cl.TotalLineCostUcsh,
                                    Remarks = cl.Remarks,
                                    IsLabour = cl.IsLabour,
                                    LabourType = cl.LabourType,
                                    QuantityDrawnPrevious = dtCtx.GetTable<ChangeLineDrawDown>().Where(n => n.JobNumber == pbHeader.JobNumber
                                                                   && n.QuoteNumber == cl.QuoteNumber
                                                                   && n.CostCode == cl.CostCode
                                                                   && n.CostCodeSerial == cl.CostCodeSerial
                                                                   && n.ProgressBillIteration == pbHeader.Iteration
                                                                   && n.ProgressBillRevision == pbHeader.Revision).Select(r => r.QuantityDrawn).Sum() == null
                                                                   ? 0 :
                                                                   dtCtx.GetTable<ChangeLineDrawDown>().Where(n => n.JobNumber == pbHeader.JobNumber
                                                                   && n.QuoteNumber == cl.QuoteNumber
                                                                   && n.CostCode == cl.CostCode
                                                                   && n.CostCodeSerial == cl.CostCodeSerial
                                                                   && n.ProgressBillIteration == pbHeader.Iteration
                                                                   && n.ProgressBillRevision == pbHeader.Revision).Select(r => r.QuantityDrawn).Sum(),

                                    DateCreated = cl.DateCreated,
                                    TimeCreated = cl.TimeCreated,
                                    UpdatingUser = cl.UpdatingUser,
                                    UpdatingMachine = cl.UpdatingMachine
                                };

                lineList = lineQuery.AsEnumerable().Select(x => new ChangeLine(x.Id, x.JobNumber, x.QuoteNumber, x.CostCodeSerial, x.CostCode,
                                                                                x.CostCodeName,
                                                                                x.LineDescription, x.AvaFileLocation, x.AvaFileName, x.AvaScheduleDate, x.PoNumber,
                                                                                x.Order, x.PoTagDate,
                                                                                x.Billed,
                                                                                x.BilledDate,
                                                                                x.BilledUser,
                                                                                x.Quantity, x.SellPrice, x.ExtendedSellPrice,
                                                                                x.Discount,
                                                                                x.Multiplier, 
                                                                                x.CostUcsh, x.TotalLineCostUcsh, x.Remarks, x.IsLabour,
                                                                                (ChangeLabourType)x.LabourType, x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine
                                                                                ,x.QuantityDrawnPrevious)).ToList();

                if (lineList.Count == 0)
                {
                    lineList = new List<ChangeLine>();
                    return new ObservableCollection<ChangeLine>(lineList);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return new ObservableCollection<ChangeLine>(lineList);
        }

        public static ObservableCollection<ChangeLine> GetChangeLinesByJobAndCostCodeAndQuoteNumber(ProgressBillingHeader pbHeader, string costCode, string quoteNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ChangeLine> lineList = null;

            try
            {
                var lineQuery = from cl in dtCtx.GetTable<ChangeLine>()
                                join ch in dtCtx.GetTable<ChangeHeader>() on new { cl.JobNumber, cl.QuoteNumber } equals new { ch.JobNumber, ch.QuoteNumber }
                                where cl.JobNumber == pbHeader.JobNumber && cl.CostCode == costCode && cl.QuoteNumber == quoteNumber && ch.Approved == true
                                orderby cl.QuoteNumber ascending, cl.CostCode ascending, cl.CostCodeSerial ascending
                                select new
                                {
                                    Id = cl.Id,
                                    JobNumber = cl.JobNumber,
                                    QuoteNumber = cl.QuoteNumber,
                                    CostCodeSerial = cl.CostCodeSerial,
                                    CostCode = cl.CostCode,
                                    CostCodeName = cl.CostCodeName,
                                    LineDescription = cl.LineDescription,
                                    AvaFileLocation = cl.AvaFileLocation,
                                    AvaFileName = cl.AvaFileName,
                                    AvaScheduleDate = cl.AvaImportDate,
                                    PoNumber = cl.PoNumber,
                                    Order = cl.Order,
                                    PoTagDate = cl.PoTagDate,
                                    Billed = cl.Billed,
                                    BilledDate = cl.BilledDate,
                                    BilledUser = cl.BilledUser,
                                    Quantity = cl.Quantity,
                                    SellPrice = cl.SellPrice,
                                    ExtendedSellPrice = cl.ExtendedSellPrice,
                                    cl.Discount,
                                    Multiplier = cl.Multiplier,
                                    CostUcsh = cl.CostUcsh,
                                    TotalLineCostUcsh = cl.TotalLineCostUcsh,
                                    Remarks = cl.Remarks,
                                    IsLabour = cl.IsLabour,
                                    LabourType = cl.LabourType,
                                    QuantityDrawnPrevious = dtCtx.GetTable<ChangeLineDrawDown>().Where(n => n.JobNumber == pbHeader.JobNumber
                                                                   && n.QuoteNumber == cl.QuoteNumber
                                                                   && n.CostCode == cl.CostCode
                                                                   && n.CostCodeSerial == cl.CostCodeSerial
                                                                   && n.ProgressBillIteration == pbHeader.Iteration
                                                                   && n.ProgressBillRevision == pbHeader.Revision).Select(r => r.QuantityDrawn).Sum() == null 
                                                                   ? 0 :
                                                                   dtCtx.GetTable<ChangeLineDrawDown>().Where(n => n.JobNumber == pbHeader.JobNumber
                                                                   && n.QuoteNumber == cl.QuoteNumber
                                                                   && n.CostCode == cl.CostCode
                                                                   && n.CostCodeSerial == cl.CostCodeSerial
                                                                   && n.ProgressBillIteration == pbHeader.Iteration
                                                                   && n.ProgressBillRevision == pbHeader.Revision).Select(r => r.QuantityDrawn).Sum(),

                                    DateCreated = cl.DateCreated,
                                    TimeCreated = cl.TimeCreated,
                                    UpdatingUser = cl.UpdatingUser,
                                    UpdatingMachine = cl.UpdatingMachine
                                };

                lineList = lineQuery.AsEnumerable().Select(x => new ChangeLine(x.Id, x.JobNumber, x.QuoteNumber, x.CostCodeSerial, x.CostCode,
                                                                                x.CostCodeName,
                                                                                x.LineDescription, x.AvaFileLocation, x.AvaFileName, x.AvaScheduleDate, x.PoNumber,
                                                                                x.Order, x.PoTagDate,
                                                                                x.Billed,
                                                                                x.BilledDate,
                                                                                x.BilledUser,
                                                                                x.Quantity, x.SellPrice, x.ExtendedSellPrice,
                                                                                x.Discount,
                                                                                x.Multiplier, x.CostUcsh, x.TotalLineCostUcsh, x.Remarks, x.IsLabour,
                                                                                (ChangeLabourType)x.LabourType, x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine
                                                                                ,x.QuantityDrawnPrevious)).ToList();

                if (lineList.Count == 0)
                {
                    lineList = new List<ChangeLine>();
                    return new ObservableCollection<ChangeLine>(lineList);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return new ObservableCollection<ChangeLine>(lineList);
        }

        public static void UpdateChangeLines(ObservableCollection<ChangeLine> _changeLineCol)
        {
            using (ChangeLineDataContext dtCtx = new ChangeLineDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime? _dc = DateTime.Today;
                DateTime? _tc = DateTime.Now;
                string _uu = Environment.UserName;
                string _um = Environment.MachineName;
                int _id = GetNextChangeLineId();
                foreach (ChangeLine cl in _changeLineCol)
                {
                    try 
                    {
                        if (cl.Id == 0 && cl.IsDeleted != true)
                        {
                            cl.DateCreated = _dc;
                            cl.TimeCreated = _tc;
                            cl.UpdatingUser = _uu;
                            cl.UpdatingMachine = _um;
                            cl.Id = _id++;
                            dtCtx.ChangeLine.InsertOnSubmit(cl);
                        }
                        else if (cl.Id != 0 && cl.IsModified == true)
                        {
                            dtCtx.ChangeLine.Attach(cl, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, cl);
                        }
                        else if (cl.Id != 0 && cl.IsDeleted == true)
                        {
                            dtCtx.ChangeLine.Attach(cl, cl); 
                            dtCtx.ChangeLine.DeleteOnSubmit(cl);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                try
                {
                    dtCtx.SubmitChanges();
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

        public static void AddRevisionChangeLines(ObservableCollection<ChangeLine> _changeLineCol)
        {
            using (ChangeLineDataContext dtCtx = new ChangeLineDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime? _dc = DateTime.Today;
                DateTime? _tc = DateTime.Now;
                string _uu = Environment.UserName;
                string _um = Environment.MachineName;
                foreach (ChangeLine cl in _changeLineCol)
                {
                    try
                    {
                        cl.DateCreated = _dc;
                        cl.TimeCreated = _tc;
                        cl.UpdatingUser = _uu;
                        cl.UpdatingMachine = _um;
                        cl.Id = GetNextChangeLineId();
                        dtCtx.ChangeLine.InsertOnSubmit(cl);
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                try
                {
                    dtCtx.SubmitChanges();
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

        //NEVER USED
        public static bool UpdateChangeLineOverheadProfit(ChangeHeader ch)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                //change db name eventually
                strQuery = "UPDATE [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMCHANGELINE101] SET InitApprOverheadPercentage=@initOver, " +
                                                                       " InitApprProfitPercentage=@initProfit, InitQuoteApprDate=@initDate WHERE " +
                                                                       " JobNumber=@jobNumber and QuoteNumber=@quoteNumber ";
                comm = new SqlCommand(strQuery, conn);
                comm.Parameters.AddWithValue("@initOver", ch.OverheadPercentage);
                comm.Parameters.AddWithValue("@initProfit", ch.ProfitPercentage);
                comm.Parameters.AddWithValue("@initDate", ch.ApprovalDate);
                comm.Parameters.AddWithValue("@jobNumber", ch.JobNumber);
                comm.Parameters.AddWithValue("@quoteNumber", ch.QuoteNumber);

                conn.Open();
                comm.ExecuteNonQuery();
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

            return false;
        }

        public static int GetNextChangeLineId()
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMCHANGELINE101]";
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

    [mp.Table(Name = "PMCHANGELINE101")]
    public class ChangeLine : INotifyPropertyChanged
    {
        //http://stackoverflow.com/questions/35883522/how-to-add-all-the-column-values-of-grouped-rows-in-data-grid-row-header

        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private ChangeHeader _parentHeader;
        private int _id;
        private string _jobNumber;
        private string _quoteNumber;
        private int _costCodeSerial;
        private string _costCode;
        private string _costCodeName;           //Could use a separate master table for cost codes but as they get added, removed, or more importantly, replaced, a name of  of a replaced code
        //might backwards affect an onlder one.  Ex: Code 710 used to be "oranges" and now it's apples. Using a master table, all 710s that were billed as "oranges" now show up as "apples," which is wrong.
        private string _lineDescription;        //If this is hardware, populate it from the AVAware SQL tables to get matching item descriptions for the hardware. - AVA_APJ_D8-HardwareList - column H02
        //AVA_APJ_D8-HardwareList - column H02 is Product code. H03 is description. HC2 is Category and HM0 is manufacturer.
        private string _avaProductId;
        private string _avaFileLocation;    //All the meta AVAware file information that goes with the item description for the hardware pulled from the AVAware SQL tables
        private string _avaFileName;        //All the meta AVAware file information that goes with the item description for the hardware pulled from the AVAware SQL tables
        private DateTime? _avaImportDate;    //All the meta AVAware file information that goes with the item description for the hardware pulled from the AVAware SQL tables
        private DateTime? _avaImportTime;

        private string _poNumber;
        private int _order;     //Polnenum
        private DateTime? _poTagDate;
        private bool _billed;      //Added Aug 23 2021
        private DateTime? _billedDate;
        private string _billedUser;

        private decimal _quantity;
        private decimal _sellPrice;
        private decimal _sellPriceMinusDiscount;
        private decimal _extendedSellPrice;    //extended cost
        private decimal _discount;              //new
        private decimal _multiplier;
        private decimal _costUcsh;
        private decimal _totalLineCostUcsh;
        private string _remarks;

        private bool _isLabour;     //Use this to delineate labour/quasi general conditions.  The descriptions are taken from 
        private ChangeLabourType _labourType;

        private string _manufacturerQuoteNumber;
        private DateTime? _manufacturerQuoteExpiration;
        private decimal _initApprOverheadPercentage;
        private decimal _initApprProfitPercentage;
        private DateTime? _initQuoteApprDate;

        private int _quantityDrawnPrevious;
        private decimal _percentBilled;

        private int _quantitySelectedFromDataGrid;

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;
        private bool _isNew;

        public ChangeHeader ParentHeader
        {
            get { return _parentHeader; }
            set { _parentHeader = value; }
        }

        [mp.Column(Name = "ID", UpdateCheck=mp.UpdateCheck.Never)]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "JobNumber", IsPrimaryKey=true)]
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

        [mp.Column(Name = "CostCodeSerial", IsPrimaryKey = true)]
        public int CostCodeSerial
        {
            get { return _costCodeSerial; }
            set { _costCodeSerial = value; }
        }

        [mp.Column(Name = "CostCode", IsPrimaryKey = true)]
        public string CostCode
        {
            get { return _costCode; }
            set
            {
                _costCode = value;
                this.IsModified = true;
                OnPropertyChanged("CostCode");
            }
        }

        [mp.Column(Name = "CostCodeName", UpdateCheck = mp.UpdateCheck.Never)]
        public string CostCodeName
        {
            get { return _costCodeName; }
            set { _costCodeName = value; }
        }

        [mp.Column(Name = "LineDescription", UpdateCheck = mp.UpdateCheck.Never)]
        public string LineDescription       //Not the same as the database name because "Description" seems to be a reserved word in SQL Server
        {
            get { return _lineDescription; }
            set
            {
                _lineDescription = value;
                this.IsModified = true;
                OnPropertyChanged("LineDescription");
            }
        }

        [mp.Column(Name = "AvaPRODUCTID", UpdateCheck = mp.UpdateCheck.Never)]
        public string AvaProductId
        {
            get { return _avaProductId; }
            set { _avaProductId = value; }
        }

        [mp.Column(Name = "AvaFileLocation", UpdateCheck = mp.UpdateCheck.Never)]
        public string AvaFileLocation
        {
            get { return _avaFileLocation; }
            set { _avaFileLocation = value; }
        }

        [mp.Column(Name = "AvaFileName", UpdateCheck = mp.UpdateCheck.Never)]
        public string AvaFileName
        {
            get { return _avaFileName; }
            set { _avaFileName = value; }
        }

        [mp.Column(Name = "AvaImportDate", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? AvaImportDate
        {
            get { return _avaImportDate; }
            set { _avaImportDate = value; }
        }

        [mp.Column(Name = "AvaImportTime", DbType = "Time", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? AvaImportTime
        {
            get { return _avaImportTime; }
            set { _avaImportTime = value; }
        }

        [mp.Column(Name = "PoNumber", UpdateCheck = mp.UpdateCheck.Never)]
        public string PoNumber
        {
            get { return _poNumber; }
            set
            {
                _poNumber = value;
                this.IsModified = true;
                OnPropertyChanged("PoNumber");
            }
        }

        [mp.Column(Name = "Polnenum", UpdateCheck = mp.UpdateCheck.Never)]
        public int Order
        {
            get { return _order; }
            set
            {
                _order = value;
                this.IsModified = true;
                OnPropertyChanged("Order");
            }
        }

        [mp.Column(Name = "PoTagDate", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? PoTagDate
        {
            get { return _poTagDate; }
            set
            {
                _poTagDate = value;
                this.IsModified = true;
                OnPropertyChanged("PoTagDate");
            }
        }

        [mp.Column(Name = "Billed", UpdateCheck = mp.UpdateCheck.Never)]
        public bool Billed
        {
            get
            {
                return _billed;
            }

            set
            {
                _billed = value;
                this.IsModified = true;
                _billedDate = DateTime.Today;
                _billedUser = Environment.UserName;
                OnPropertyChanged("Billed");
            }
        }

        [mp.Column(Name = "BilledDate", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? BilledDate
        {
            get
            {
                return _billedDate;
            }

            set
            {
                _billedDate = value;
            }
        }

        [mp.Column(Name = "BilledUser", UpdateCheck = mp.UpdateCheck.Never)]
        public string BilledUser
        {
            get
            {
                return _billedUser;
            }

            set
            {
                _billedUser = value;
            }
        }


        [mp.Column(Name = "Quantity", UpdateCheck = mp.UpdateCheck.Never)]
        public decimal Quantity
        {
            get { return _quantity; }
            set
            {
                _quantity = value;
                _extendedSellPrice = value * _sellPriceMinusDiscount;
                _totalLineCostUcsh = _costUcsh * _quantity;
                this.IsModified = true;
                OnPropertyChanged("ExtendedSellPrice");
                OnPropertyChanged("TotalLineCostUcsh");
            }
        }

        //[mp.Column(Name = "CostCustomer")]
        [mp.Column(Name = "SellPrice", UpdateCheck = mp.UpdateCheck.Never)]
        public decimal SellPrice
        {
            get { return _sellPrice; }
            set
            {
                _sellPrice = value;
                _sellPriceMinusDiscount = _sellPrice - (_sellPrice * (_discount / 100));
                _multiplier = (_costUcsh == 0) ? 0 : _sellPriceMinusDiscount / _costUcsh;
                _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                _totalLineCostUcsh = _costUcsh * _quantity;
                this.IsModified = true;
                OnPropertyChanged("SellPrice");
                OnPropertyChanged("SellPriceMinusDiscount");
                OnPropertyChanged("Multiplier");
                OnPropertyChanged("ExtendedSellPrice");
                OnPropertyChanged("CostUcsh");
                OnPropertyChanged("TotalLineCostUcsh");
            }
        }

        public decimal SellPriceMinusDiscount
        {
            get
            {
                return _sellPriceMinusDiscount;
            }

            set
            {
                _sellPriceMinusDiscount = value;
            }
        }

        //[mp.Column(Name = "ExtendedCostCustomer")]      //Change this name later
        [mp.Column(Name = "ExtendedSellPrice", UpdateCheck = mp.UpdateCheck.Never, CanBeNull=true)]    //Change this name later
        public decimal ExtendedSellPrice
        {
            get { return _extendedSellPrice; }
            set { _extendedSellPrice = value; }
        }

        [mp.Column(Name = "Discount", UpdateCheck = mp.UpdateCheck.Never, CanBeNull=true,DbType="numeric(19,5)")]
        public decimal Discount
        {
            get { return _discount; }
            set
            {
                _discount = value;
                _sellPriceMinusDiscount = _sellPrice - (_sellPrice * (value / 100));
                _multiplier = (_costUcsh == 0) ? 0 : _sellPriceMinusDiscount / _costUcsh;
                //cost stays unchanged
                _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                _totalLineCostUcsh = _costUcsh * _quantity;
                this.IsModified = true;
                OnPropertyChanged("SellPrice");
                OnPropertyChanged("SellPriceMinusDiscount");
                OnPropertyChanged("ExtendedSellPrice");
                OnPropertyChanged("Multiplier");
            }
        }

        [mp.Column(Name = "Multiplier", UpdateCheck = mp.UpdateCheck.Never, CanBeNull=true)]
        public decimal Multiplier
        {
            get { return _multiplier; }
            set
            {
                _multiplier = value;
                _sellPriceMinusDiscount = (_costUcsh == 0) ? _sellPriceMinusDiscount : (value * _costUcsh);
                _sellPrice = (_sellPriceMinusDiscount / (100 - _discount)) * 100;
                _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                this.IsModified = true;
                OnPropertyChanged("SellPrice");
                OnPropertyChanged("SellPriceMinusDiscount");
                OnPropertyChanged("ExtendedSellPrice");
            }
        }

        [mp.Column(Name = "CostUcsh", UpdateCheck = mp.UpdateCheck.Never, CanBeNull = true)]
        public decimal CostUcsh
        {
            get { return _costUcsh; }
            set
            {
                _costUcsh = value;
                _multiplier = (value == 0) ? 0 : _sellPriceMinusDiscount / value;
                _sellPriceMinusDiscount = value * _multiplier;
                _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                _totalLineCostUcsh = _costUcsh * _quantity;
                this.IsModified = true;
                OnPropertyChanged("SellPrice");
                OnPropertyChanged("SellPriceMinusDiscount");
                OnPropertyChanged("CostUcsh");
                OnPropertyChanged("Multiplier");
                OnPropertyChanged("ExtendedSellPrice");
                OnPropertyChanged("TotalLineCostUcsh");
            }
        }

        [mp.Column(Name = "TotalLineCostUcsh", UpdateCheck = mp.UpdateCheck.Never, CanBeNull = true)]
        public decimal TotalLineCostUcsh
        {
            get { return _totalLineCostUcsh; }
            set { _totalLineCostUcsh = value; }
        }

        [mp.Column(Name = "Remarks", UpdateCheck = mp.UpdateCheck.Never)]
        public string Remarks
        {
            get { return _remarks; }
            set
            {
                _remarks = value;
                this.IsModified = true;
                OnPropertyChanged("Remarks");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "IsLabour", UpdateCheck = mp.UpdateCheck.Never)]
        public bool IsLabour
        {
            get { return _isLabour; }
            set
            {
                _isLabour = value;
                this.IsModified = true;
                OnPropertyChanged("IsLabour");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "ChangeLabourType", DbType = "SmallInt", UpdateCheck = mp.UpdateCheck.Never)]
        public ChangeLabourType LabourType
        {
            get { return _labourType; }
            set
            {
                if (_isLabour)
                {
                    _labourType = value;
                    switch (value)
                    {
                        case ChangeLabourType.Consulting:
                            _sellPrice = 210;
                            _sellPriceMinusDiscount = _sellPrice - (_sellPrice * (_discount / 100));
                            _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                            _costUcsh = _sellPriceMinusDiscount / 1.5m;
                            _totalLineCostUcsh = _costUcsh + Quantity;
                            this.IsModified = true;
                            OnPropertyChanged("SellPrice");
                            OnPropertyChanged("SellPriceMinusDiscount");
                            OnPropertyChanged("ExtendedSellPrice");
                            OnPropertyChanged("LabourType");
                            break;
                        case ChangeLabourType.ShopDrawingRevision:
                            _sellPrice = 150;
                            _sellPriceMinusDiscount = _sellPrice - (_sellPrice * (_discount / 100));
                            _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                            _costUcsh = _sellPriceMinusDiscount / 1.5m;
                            _totalLineCostUcsh = _costUcsh + Quantity;
                            this.IsModified = true;
                            OnPropertyChanged("SellPrice");
                            OnPropertyChanged("SellPriceMinusDiscount");
                            OnPropertyChanged("ExtendedSellPrice");
                            OnPropertyChanged("LabourType");
                            break;
                        case ChangeLabourType.ProjectManagement:
                            _sellPrice = 125;
                            _sellPriceMinusDiscount = _sellPrice - (_sellPrice * (_discount / 100));
                            _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                            _costUcsh = _sellPriceMinusDiscount / 1.5m;
                            _totalLineCostUcsh = _costUcsh + Quantity;
                            this.IsModified = true;
                            OnPropertyChanged("SellPrice");
                            OnPropertyChanged("SellPriceMinusDiscount");
                            OnPropertyChanged("ExtendedSellPrice");
                            OnPropertyChanged("LabourType");
                            break;
                        case ChangeLabourType.Coordinator:
                            _sellPrice = 100;
                            _sellPriceMinusDiscount = _sellPrice - (_sellPrice * (_discount / 100));
                            _extendedSellPrice = _sellPriceMinusDiscount * _quantity;
                            _costUcsh = _sellPriceMinusDiscount / 1.5m;
                            _totalLineCostUcsh = _costUcsh + Quantity;
                            this.IsModified = true;
                            OnPropertyChanged("SellPrice");
                            OnPropertyChanged("SellPriceMinusDiscount");
                            OnPropertyChanged("ExtendedSellPrice");
                            OnPropertyChanged("LabourType");
                            break;
                    }
                }
                else
                    _labourType = 0; this._isModified = true;   //unassigned
            }
        }

        [mp.Column(Name = "ManufacturerQuoteNumber", UpdateCheck = mp.UpdateCheck.Never)]
        public string ManufacturerQuoteNumber
        {
            get { return _manufacturerQuoteNumber; }
            set { _manufacturerQuoteNumber = value; }
        }

        [mp.Column(Name = "ManufacturerQuoteExpiration", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? ManufacturerQuoteExpiration
        {
            get { return _manufacturerQuoteExpiration; }
            set { _manufacturerQuoteExpiration = value; }
        }

        [mp.Column(Name = "InitApprOverheadPercentage", UpdateCheck = mp.UpdateCheck.Never, DbType = "numeric(19,5)")]
        public decimal InitApprOverheadPercentage
        {
            get { return _initApprOverheadPercentage; }
            set
            {
                _initApprOverheadPercentage = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "InitApprProfitPercentage", UpdateCheck = mp.UpdateCheck.Never, DbType = "numeric(19,5)")]
        public decimal InitApprProfitPercentage
        {
            get { return _initApprProfitPercentage; }
            set
            {
                _initApprProfitPercentage = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "InitQuoteApprDate")]
        public DateTime? InitQuoteApprDate
        {
            get { return _initQuoteApprDate; }
            set
            {
                _initQuoteApprDate = value;
                this.IsModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        //Properties for draw downs on change quote progress billing lines

        public int QuantityDrawnPrevious
        {
            get { return _quantityDrawnPrevious; }
            set 
            { 
                _quantityDrawnPrevious = value;
                OnPropertyChanged("QuantityDrawnPrevious");
            }
        }

        public decimal PercentBilled
        {
            get { return _percentBilled; }
            set { _percentBilled = value; }
        }

        public int QuantitySelectedFromDataGrid
        {
            get { return _quantitySelectedFromDataGrid; }
            set { _quantitySelectedFromDataGrid = value; }
        }

        //Properties for draw downs on change quote progress billing lines

        [mp.Column(Name = "DateCreated", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set { _dateCreated = value; }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set { _timeCreated = value; }
        }

        [mp.Column(Name = "UpdatingUser", UpdateCheck = mp.UpdateCheck.Never)]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set { _updatingUser = value; }
        }

        [mp.Column(Name = "UpdatingMachine", UpdateCheck = mp.UpdateCheck.Never)]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set { _updatingMachine = value; }
        }

        //
        public bool IsModified
        {
            get { return _isModified; }
            set
            {
                _isModified = value;
                OnPropertyChanged("IsModified");
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

        public ChangeLine()
        {
            this._isNew = true;
        }

        public ChangeLine(string jobNumber, string quoteNumber)
        {
            this._isNew = true;
            this._jobNumber = jobNumber;
            this._quoteNumber = quoteNumber;

        }

        public ChangeLine(string jobNumber, string quoteNumber, string costCode, ObservableCollection<ChangeLine> clList)
        {
            this._isNew = true;
            this._jobNumber = jobNumber;
            this._quoteNumber = quoteNumber;
            this._costCode = costCode;
            GetCostCodeSerial(costCode, clList);
        }

        public ChangeLine(int id, string jobNumber, string quoteNumber, int costCodeSerial, string costCode,
                            string costCodeName,
                            string lineDescription, string avaFileLocation, string avaFileName, DateTime? avaScheduleDate, string poNumber,
                            int order, DateTime? poTagDate, 
                            bool billed,
                            DateTime? billedDate,
                            string billedUser,

                            decimal quantity, decimal SellPrice, decimal extendedSellPrice,
                            decimal discount,
                            decimal multiplier, decimal costUcsh, decimal totalLineCostUcsh, string remarks, bool isLabour,
                            ChangeLabourType labourType, DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine
                            ,int quantityDrawnPrevious
            )
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._quoteNumber = quoteNumber;
            this._costCodeSerial = costCodeSerial;
            this._costCode = costCode;
            this._costCodeName = costCodeName;
            this._lineDescription = lineDescription;
            this._avaFileLocation = avaFileLocation;
            this._avaFileName = avaFileName;
            this._avaImportDate = avaScheduleDate;
            this._poNumber = poNumber;
            this._order = order;
            this._poTagDate = poTagDate;
            this._billed = billed;
            this._billedDate = billedDate;
            this._billedUser = billedUser;
            this._quantity = quantity;
            this._sellPrice = SellPrice;
            this._extendedSellPrice = extendedSellPrice;
            this._multiplier = multiplier;
            this._discount = discount;
            //Add March 30th 2021
                this._sellPriceMinusDiscount = this._sellPrice - (this._sellPrice * (_discount / 100));
            //
            this._costUcsh = costUcsh;
            this._totalLineCostUcsh = totalLineCostUcsh;
            this._remarks = remarks;
            this._isLabour = isLabour;
            this._labourType = labourType;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this._quantityDrawnPrevious = quantityDrawnPrevious;
            //Change lines using this constructor are obviously existing AKA not new, so the _isNew field is set to false
            this._isNew = false;

            //Never use these values when retrieving the list, only using these values to write back to the database, so we don't care if they get initialized to 0.
            //this._initApprOverheadPercentage = 0;
            //this._initApprProfitPercentage = 0;
        }

        public ChangeLine(ChangeLine cl, ObservableCollection<ChangeLine> clList)
        {
            this._isNew = true;
            this._isModified = true;
            this._billed = false;   //Sep 09, 2021
            this._quantity = 1;
            this._jobNumber = cl.JobNumber;
            this._quoteNumber = cl.QuoteNumber;
            this._costCode = cl.CostCode;
            this._costCodeName = cl.CostCodeName;
            this._avaFileLocation = "";
            this._avaFileName = "";
            
            if (cl.IsLabour)
            {
                this._isLabour = true;
                this.LabourType = cl.LabourType;
            }
            GetCostCodeSerial(cl.CostCode, clList);
        }

        private void GetCostCodeSerial(string costCode, ObservableCollection<ChangeLine> clList)
        {
            int iter = 1;
            foreach (ChangeLine ch in clList)
            {
                if ((ch.CostCode == costCode) && (ch.CostCodeSerial >= iter))
                    iter = ch.CostCodeSerial + 1;
            }
            this._costCodeSerial = iter;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class ChangeLineDataContext : lq.DataContext
    {
        public ChangeLineDataContext(string cs)
            : base(cs)
        {
        }

        public ChangeLineDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ChangeLine> ChangeLine;
    }

    public enum ChangeLabourType
    {
        Unassigned = 0,
        Indeterminate,
        Consulting,
        ShopDrawingRevision,
        ProjectManagement,
        Coordinator
    }
}
