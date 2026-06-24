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

namespace PM_Project_Tracking.ProjectManagementClasses
{
    class ChangeLineDrawDowns
    {
        //Not referenced at all
        //public static ObservableCollection<ChangeLineDrawDown> GetChangeLineDrawDowns(ProgressBillingHeader pbHeader)   //This probably won't be used much, if at all
        //{
        //    lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
        //    lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
        //    List<ChangeLineDrawDown> lineList = null;

        //    try
        //    {
        //        var headerQuery = from dd in dtCtx.GetTable<ChangeLineDrawDown>()
        //                          where dd.JobNumber == pbHeader.JobNumber && dd.ProgressBillIteration == pbHeader.Iteration //&& pb.ChangeOrder == false
        //                          select new
        //                          {
        //                              Id = dd.Id,
        //                              JobNumber = dd.JobNumber,
        //                              QuoteNumber = dd.QuoteNumber,
        //                              BillingHeaderIteration = dd.ProgressBillIteration,
        //                              BillingHeaderRevision = dd.ProgressBillRevision,
        //                              BillingLineSerial = dd.ProgressBillLineSerial,
        //                              CostCode = dd.CostCode,
        //                              CostCodeSerial = dd.CostCodeSerial,
        //                              OriginalQuantity = dd.OriginalQuantity,
        //                              QuantityDrawn = dd.QuantityDrawn,
        //                              SellPrice = dd.SellPrice,
        //                              AmountCommitted = dd.AmountCommitted,
        //                              DateCreated = dd.DateCreated,
        //                              TimeCreated = dd.TimeCreated,
        //                              UpdatingUser = dd.UpdatingUser,
        //                              UpdatingMachine = dd.UpdatingMachine
        //                          };

        //        lineList = headerQuery.AsEnumerable().Select(x => new ChangeLineDrawDown(x.Id, x.JobNumber, x.QuoteNumber, x.BillingHeaderIteration, x.BillingHeaderRevision
        //                                                                                  , x.BillingLineSerial
        //                                                                                  , x.CostCode, x.CostCodeSerial, x.OriginalQuantity, x.QuantityDrawn , x.SellPrice
        //                                                                                  , x.AmountCommitted, x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine)).ToList();

        //        if (lineList.Count == 0)
        //        {
        //            lineList = new List<ChangeLineDrawDown>();
        //            return new ObservableCollection<ChangeLineDrawDown>(lineList);
        //        }
        //    }
        //    catch (Exception ex)
        //    {
        //        MessageBox.Show(ex.ToString());
        //    }
        //    finally
        //    {
        //        dtCtx.Dispose();
        //    }
        //    return new ObservableCollection<ChangeLineDrawDown>(lineList);
        //}

        public static List<ChangeLineDrawDown> GetChangeLineDrawDownsViaBillingLine(string jobNumber, int iteration, int revision, int serial, ProgressBillingLine pbLine)   //This probably won't be used much, if at all
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ChangeLineDrawDown> lineList = null;

            try
            {
                var headerQuery = from dd in dtCtx.GetTable<ChangeLineDrawDown>()
                                  join ql in dtCtx.GetTable<ChangeLine>() on new { dd.JobNumber, dd.QuoteNumber, dd.CostCode, dd.CostCodeSerial } equals new { ql.JobNumber, ql.QuoteNumber, ql.CostCode, ql.CostCodeSerial } into full
                                  from ql in full.DefaultIfEmpty()
                                  where dd.JobNumber == jobNumber && dd.ProgressBillIteration == iteration
                                  && dd.ProgressBillRevision == revision && dd.ProgressBillLineSerial == serial
                                  select new
                                  {
                                      Id = dd.Id,
                                      JobNumber = dd.JobNumber,
                                      QuoteNumber = dd.QuoteNumber,
                                      BillingHeaderIteration = dd.ProgressBillIteration,
                                      BillingHeaderRevision = dd.ProgressBillRevision,
                                      BillingLineSerial = dd.ProgressBillLineSerial,
                                      CostCode = dd.CostCode,
                                      CostCodeSerial = dd.CostCodeSerial,
                                      OriginalQuantity = dd.OriginalQuantity,
                                      QuantityDrawn = dd.QuantityDrawn,
                                      SellPrice = dd.SellPrice,
                                      AmountCommitted = dd.AmountCommitted,
                                      DateCreated = dd.DateCreated,
                                      TimeCreated = dd.TimeCreated,
                                      UpdatingUser = dd.UpdatingUser,
                                      UpdatingMachine = dd.UpdatingMachine,

                                      LineDescription = ql.LineDescription

                                      //ProgressBillingLine = pbLine
                                  };

                lineList = headerQuery.AsEnumerable().Select(x => new ChangeLineDrawDown(x.Id, x.JobNumber, x.QuoteNumber, x.BillingHeaderIteration, x.BillingHeaderRevision
                                                                                          , x.BillingLineSerial
                                                                                          , x.CostCode, x.CostCodeSerial, x.OriginalQuantity, x.QuantityDrawn, x.SellPrice
                                                                                          , x.AmountCommitted, x.DateCreated, x.TimeCreated, x.UpdatingUser, x.UpdatingMachine
                                                                                          , x.LineDescription
                                                                                          //, x.ProgressBillingLine
                                                                                          )).ToList();

                if (lineList.Count == 0)
                {
                    lineList = new List<ChangeLineDrawDown>();
                    return lineList;
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
            return lineList;
        }

        public static void UpdateDrawDowns(ObservableCollection<ChangeLineDrawDown> _drawDownCol)
        {
            using (ChangeLineDrawDownDataContext dtCtx = new ChangeLineDrawDownDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ChangeLineDrawDown cl in _drawDownCol)
                {
                    try
                    {
                        if (cl.Id == 0 && cl.IsDeleted != true)
                        {
                            cl.DateCreated = DateTime.Today;
                            cl.TimeCreated = DateTime.Now;
                            cl.UpdatingUser = Environment.UserName;
                            cl.UpdatingMachine = Environment.MachineName;
                            cl.Id = GetNextChangeDrawDownLineId(cl.JobNumber);
                            dtCtx.ChangeLineDrawDown.InsertOnSubmit(cl);
                        }
                        else if (cl.Id != 0 && cl.IsModified == true)
                        {
                            dtCtx.ChangeLineDrawDown.Attach(cl, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, cl);
                        }
                        else if (cl.Id != 0 && cl.IsDeleted == true)
                        {
                            dtCtx.ChangeLineDrawDown.Attach(cl, cl);
                            dtCtx.ChangeLineDrawDown.DeleteOnSubmit(cl);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static void DeleteDrawDowns(ObservableCollection<ChangeLineDrawDown> _drawDownCol)
        {
            using (ChangeLineDrawDownDataContext dtCtx = new ChangeLineDrawDownDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ChangeLineDrawDown cl in _drawDownCol)
                {
                    try
                    {
                        if (cl.IsNew)
                        {
                            dtCtx.ChangeLineDrawDown.Attach(cl, cl);
                            dtCtx.ChangeLineDrawDown.DeleteOnSubmit(cl);
                        }
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static int GetNextChangeDrawDownLineId(string jobNumber)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[PMCHANGELINEDRAWDOWNS101]";
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

    [mp.Table(Name = "PMCHANGELINEDRAWDOWNS101")]
    public class ChangeLineDrawDown : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _jobNumber;
        private string _quoteNumber;
        private string _costCode;
        private string _lineDescription; //Used for the UI only, no need to store it in the database.
        private int _costCodeSerial;
        private int _progressBillIteration;
        private int _progressBillRevision;
        private int _progressBillLineSerial;

        private decimal _originalQuantity;
        private int _quantityDrawn;
        private decimal _sellPrice;
        private decimal _amountCommitted;    //extended cost

        private ProgressBillingLine _ParentProgressBillLine;

        public ProgressBillingLine ParentProgressBillLine
        {
            get { return _ParentProgressBillLine; }
            set { _ParentProgressBillLine = value; }
        }

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _isModified;
        private bool _isDeleted;
        private bool _isNew;

        [mp.Column(Name = "ID")]
        public int Id   //am I going to use this one?
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

        [mp.Column(Name = "CostCode", IsPrimaryKey = true)]
        public string CostCode
        {
            get { return _costCode; }
            set { _costCode = value; }
        }


        public string LineDescription   //
        {
            get { return _lineDescription; }
            set { _lineDescription = value; }
        }

        [mp.Column(Name = "CostCodeSerial", IsPrimaryKey = true)]
        public int CostCodeSerial
        {
            get { return _costCodeSerial; }
            set { _costCodeSerial = value; }
        }

        [mp.Column(Name = "ProgressBillIteration", IsPrimaryKey = true)]
        public int ProgressBillIteration
        {
            get { return _progressBillIteration; }
            set { _progressBillIteration = value; }
        }

        [mp.Column(Name = "ProgressBillRevision", IsPrimaryKey = true)]
        public int ProgressBillRevision
        {
            get { return _progressBillRevision; }
            set { _progressBillRevision = value; }
        }

        [mp.Column(Name = "ProgressBillLineSerial", IsPrimaryKey = true)]
        public int ProgressBillLineSerial
        {
            get { return _progressBillLineSerial; }
            set { _progressBillLineSerial = value; }
        }

        [mp.Column(Name = "OriginalQuantity")]
        public decimal OriginalQuantity
        {
            get { return _originalQuantity; }
            set { _originalQuantity = value; }
        }

        [mp.Column(Name = "QuantityDrawn")]
        public int QuantityDrawn
        {
            get { return _quantityDrawn; }
            set 
            { 
                _quantityDrawn = value;
                decimal _oldAmountCommitted = _amountCommitted; //Grab the previous value of amount committed so we can compare it to the new amount and see if we need to add or subtract from pb line current amnt
                _amountCommitted = _sellPrice * _quantityDrawn;

                if (_oldAmountCommitted < _amountCommitted)
                    _ParentProgressBillLine.CurrentAmount = _ParentProgressBillLine.CurrentAmount + (_amountCommitted - _oldAmountCommitted);
                else if (_oldAmountCommitted > _amountCommitted)
                    _ParentProgressBillLine.CurrentAmount = _ParentProgressBillLine.CurrentAmount - (_oldAmountCommitted - _amountCommitted);

                OnPropertyChanged("QuantityDrawn");
                OnPropertyChanged("AmountCommitted");
                _isModified = true;
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "SellPrice")]  //Change the name of this column later
        public decimal SellPrice
        {
            get { return _sellPrice; }
            set
            {
                _sellPrice = value;
            }
        }

        [mp.Column(Name = "AmountCommitted")]
        public decimal AmountCommitted
        {
            get { return _amountCommitted; }
            set { _amountCommitted = value; }
        }

        [mp.Column(Name = "DateCreated")]
        public DateTime? DateCreated
        {
            get { return _dateCreated; }
            set { _dateCreated = value; }
        }

        [mp.Column(Name = "TimeCreated", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeCreated
        {
            get { return _timeCreated; }
            set { _timeCreated = value; }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set { _updatingUser = value; }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set { _updatingMachine = value; }
        }

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


        public ChangeLineDrawDown()
        {
        }

        //Constructor for making new lines in the UI
        public ChangeLineDrawDown(ProgressBillingLine pbLine, ChangeLine cl)
        {
            this._jobNumber = cl.JobNumber;
            this._quoteNumber = cl.QuoteNumber;
            this._costCode = cl.CostCode;
            this._costCodeSerial = cl.CostCodeSerial;
            this._lineDescription = cl.LineDescription;
            this._progressBillIteration = pbLine.BillingHeaderIteration;
            this._progressBillRevision = pbLine.BillingHeaderRevision;
            this._progressBillLineSerial = pbLine.Serial;
            this._originalQuantity = cl.Quantity;
            this._quantityDrawn = cl.QuantitySelectedFromDataGrid;
            this._sellPrice = cl.SellPrice;
            this._amountCommitted = _quantityDrawn * _sellPrice;

            this._isNew = true;
            this._isModified = true;

            _ParentProgressBillLine = pbLine;

            OnPropertyChanged("IsModified");
        }

        //Constructor for populating the collection of the parent progress bill line object
        public ChangeLineDrawDown(int id, string jobNumber, string quoteNumber, int billingHeaderIteration, int billingHeaderRevision
                                  , int serial
                                  , string costCode, int costCodeSerial, decimal originalQuantity, int quantityDrawn, decimal sellPrice
                                  , decimal amountCommitted, DateTime? dateCreated, DateTime? timeCreated, string updatingUser, string updatingMachine
                                  , string lineDescription
                                  //, ProgressBillingLine pbLine
                                    )
        {
            this._id = id;
            this._jobNumber = jobNumber;
            this._quoteNumber = quoteNumber;
            this._progressBillIteration = billingHeaderIteration;
            this._progressBillRevision = billingHeaderRevision;
            this._progressBillLineSerial = serial;
            this._costCode = costCode;
            this._costCodeSerial = costCodeSerial;
            this._originalQuantity = originalQuantity;
            this._quantityDrawn = quantityDrawn;
            this._sellPrice = sellPrice;
            this._amountCommitted = amountCommitted;
            this._dateCreated = dateCreated;
            this._timeCreated = timeCreated;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this._lineDescription = lineDescription;

            this._isNew = false;

            //this._ParentProgressBillLine = pbLine;
            //

        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class ChangeLineDrawDownCollection : ObservableCollection<ChangeLineDrawDown>
    {
        private ProgressBillingLine _pbChangeLine;



        public ChangeLineDrawDownCollection(ProgressBillingLine pbChangeLine)
        {
            this._pbChangeLine = pbChangeLine;
        }

        public ChangeLineDrawDownCollection(List<ChangeLineDrawDown> col)
            : base(col)
        {

        }

        public ProgressBillingLine PbChangeLine
        {
            get { return _pbChangeLine; }
            set 
            { 
                _pbChangeLine = value;
                for (int x = 0; x < this.Items.Count; x++)
                {
                    this.Items[x].ParentProgressBillLine = value;
                }
            }
        }

        public void Add(ChangeLineDrawDown drawDown)
        {
            base.Add(drawDown);
            _pbChangeLine.CurrentAmount += drawDown.AmountCommitted;
        }

        public void Remove(ChangeLineDrawDown drawDown)
        {
            base.Remove(drawDown);
            _pbChangeLine.CurrentAmount -= drawDown.AmountCommitted;
        }
    }

    public class ChangeLineDrawDownDataContext : lq.DataContext
    {
        public ChangeLineDrawDownDataContext(string cs)
            : base(cs)
        {
        }

        public ChangeLineDrawDownDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ChangeLineDrawDown> ChangeLineDrawDown;
    }
}
