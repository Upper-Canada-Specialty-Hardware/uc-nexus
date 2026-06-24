using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Collections.ObjectModel;
using System.Data.SqlClient;
using System.Windows;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using System.ComponentModel;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using pm = PM_Project_Tracking.ProjectManagementClasses;

namespace PM_Project_Tracking.DataClasses
{
    class WhShippingLines
    {
        internal static ObservableCollection<ShippingLine> GetWhShippingLinesByMemoNum(int memoNum)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ShippingLine> shipList = null;

            try
            {
                var shipQuery = from shipLine in dtCtx.GetTable<ShippingLine>()
                                orderby shipLine.PoNumber descending, shipLine.Polnenum ascending
                                where shipLine.MemoNumber == memoNum
                                select new
                                {
                                    MemoNumber = shipLine.MemoNumber,
                                    PoNumber = shipLine.PoNumber,
                                    Order = shipLine.Polnenum,
                                    ItemNumber = shipLine.ItemNumber,
                                    ItemDescription = shipLine.ItemDescription,
                                    JobNumber = shipLine.JobNumber,
                                    Courier = shipLine.Courier,           //Don't need anymore because it's in the header
                                    Destination = shipLine.Destination,   //Don't need anymore because it's in the header
                                    QuantityOrdered = shipLine.QuantityOrdered,
                                    QuantityShipped = shipLine.QuantityShipped,
                                    DateReceived = shipLine.DateShipped,
                                    TimeReceived = shipLine.TimeShipped,
                                    UpdatingUser = shipLine.UpdatingUser,
                                    UpdatingMaching = shipLine.UpdatingMachine
                                };

                shipList = shipQuery.AsEnumerable().Select(x => new ShippingLine(x.MemoNumber, 
                                                                                x.PoNumber, 
                                                                                x.Order,
                                                                                x.ItemNumber,
                                                                                x.ItemDescription,
                                                                                x.JobNumber,
                                                                                x.Courier,
                                                                                x.Destination,
                                                                                x.QuantityOrdered,
                                                                                x.QuantityShipped,
                                                                                x.DateReceived,
                                                                                x.TimeReceived,
                                                                                x.UpdatingUser,
                                                                                x.UpdatingMaching
                                                                                )).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
                if (shipList.Count == 0)
                    MessageBox.Show("Shipping lines returned no entries from the database.");
            }

            return new ObservableCollection<ShippingLine>(shipList);
        }

        internal static ObservableCollection<ReceivingLine> GetReceivingLinesByProject(string projNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ReceivingLine> recLineList = null;

            try
            {
                //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Hardware and Order Tracking Module\Hardware PO Retrieval\POP10110 annotated LEAN reconfig RTL col v5 - simplified version.sql
                var recLineQuery = from recLine in dtCtx.GetTable<ReceivingLine>()
                                   where recLine.JobNumber == projNumber
                                      orderby recLine.PoNumber descending, recLine.Polnenum
                                      select new
                                      {
                                          PoNumber = recLine.PoNumber,
                                          Polnenum = recLine.Polnenum,
                                          QtyOrdFromGp = recLine.QtyOrdFromGp,
                                          QtyRecForGp = recLine.QtyRecForGp,
                                          QtyRemainingOnRec = recLine.QtyRemainingOnRec,
                                          PopRctNum = recLine.PopRctNum,
                                          RcptLnNm = recLine.RcptLnNm,
                                          SopNumber = recLine.SopNumber.Trim(),

                                          ItemNumber = recLine.ItemNumber.Trim(),
                                          ItemDescription = recLine.ItemDescription.Trim(),
                                          VendorId = recLine.VendorId.Trim(),
                                          VendorName = recLine.VendorName.Trim(),
                                          JobNumber = recLine.JobNumber.Trim(),
                                          JobName = recLine.JobName.Trim(),
                                          RevisionNumber = recLine.RevisionNumber,
                                          Location = recLine.Location,
                                          Comments = recLine.Comments,
                                          DateReceived = recLine.DateReceived,
                                          TimeReceived = recLine.TimeReceived,
                                      };

                recLineList = recLineQuery.AsEnumerable().Select(x => new ReceivingLine(x.PoNumber, x.Polnenum,
                                                                                        x.QtyOrdFromGp,
                                                                                        x.QtyRecForGp, x.QtyRemainingOnRec,
                                                                                        x.PopRctNum, x.RcptLnNm,
                                                                                        x.SopNumber, 
                                                                                        x.ItemNumber, x.ItemDescription, 
                                                                                        x.VendorId, x.VendorName, 
                                                                                        x.JobNumber, x.JobName, 
                                                                                        x.RevisionNumber, x.Location, x.Comments,
                                                                                        x.DateReceived, x.TimeReceived)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ReceivingLine>(recLineList);
        }

        internal static ObservableCollection<ReceivingLine> GetReceivingLinesBySop(string sopNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ReceivingLine> recLineList = null;

            try
            {
                //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Hardware and Order Tracking Module\Hardware PO Retrieval\POP10110 annotated LEAN reconfig RTL col v5 - simplified version.sql
                var recLineQuery = from recLine in dtCtx.GetTable<ReceivingLine>()
                                   where recLine.SopNumber == sopNumber
                                   orderby recLine.PoNumber descending, recLine.Polnenum
                                   select new
                                   {
                                       PoNumber = recLine.PoNumber,
                                       Polnenum = recLine.Polnenum,

                                       QtyOrdFromGp = recLine.QtyOrdFromGp,
                                       QtyRecForGp = recLine.QtyRecForGp,
                                       QtyRemainingOnRec = recLine.QtyRemainingOnRec,
                                       PopRctNum = recLine.PopRctNum,
                                       RcptLnNm = recLine.RcptLnNm,
                                       SopNumber = recLine.SopNumber.Trim(),

                                       ItemNumber = recLine.ItemNumber.Trim(),
                                       ItemDescription = recLine.ItemDescription.Trim(),
                                       VendorId = recLine.VendorId.Trim(),
                                       VendorName = recLine.VendorName.Trim(),
                                       JobNumber = recLine.JobNumber.Trim(),
                                       JobName = recLine.JobName.Trim(),
                                       RevisionNumber = recLine.RevisionNumber,
                                       Location = recLine.Location,
                                       Comments = recLine.Comments,
                                       DateReceived = recLine.DateReceived,
                                       TimeReceived = recLine.TimeReceived,
                                   };

                recLineList = recLineQuery.AsEnumerable().Select(x => new ReceivingLine(x.PoNumber, x.Polnenum,
                                                                                        x.QtyOrdFromGp,
                                                                                        x.QtyRecForGp, x.QtyRemainingOnRec,
                                                                                        x.PopRctNum, x.RcptLnNm,
                                                                                        x.SopNumber, 
                                                                                        x.ItemNumber, x.ItemDescription,
                                                                                        x.VendorId, x.VendorName,
                                                                                        x.JobNumber, x.JobName,
                                                                                        x.RevisionNumber, x.Location, x.Comments,
                                                                                        x.DateReceived, x.TimeReceived)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ReceivingLine>(recLineList);
        }

        public static bool AddShippingLine(ObservableCollection<ShippingLine> slCol, int memoNum)
        {
            bool _cont = true;
            using (ShippingLineDataContext dtCtx = new ShippingLineDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ShippingLine line in slCol)
                {
                    try
                    {
                        line.MemoNumber = memoNum;
                        line.DateShipped = DateTime.Today;
                        line.TimeShipped = DateTime.Now;
                        line.UpdatingUser = Environment.UserName;
                        line.UpdatingMachine = Environment.MachineName;
                        dtCtx.ShippingLine.InsertOnSubmit(line);
                        line.InsertedToDb = true;
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
                RollBackShippingLines(memoNum);
                RollbackShippingHeader(memoNum);
            }
            return _cont;

        }

        public static void RollbackShippingHeader(int memoNum)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "DELETE FROM WHSHIPHEADER101 WHERE MemoNumber='" + memoNum + "'";

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

        public static void RollBackShippingLines(int memoNum)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "DELETE FROM WHSHIPLINE101 WHERE MemoNumber='" + memoNum + "'";

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

        public static void DeleteShippingLines(ObservableCollection<ShippingLine> slCol)
        {
            using (ShippingLineDataContext dtCtx = new ShippingLineDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ShippingLine sl in slCol)
                {
                    if (sl.InsertedToDb)
                    {
                        try
                        {
                            dtCtx.ShippingLine.DeleteOnSubmit(sl);
                            dtCtx.SubmitChanges();
                        }
                        catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); }
                        catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                    }
                }
            }
        }
    }

    [mp.Table(Name = "[WHSHIPLINE101]")]
    public class ShippingLine : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _memoNumber;
        private string _poNumber;
        private int _polnenum;
        private string _sopNumber;

        private string _itemNumber;
        private string _itemDescription;
        private string _vendorId;
        private string _vendorName;
        private string _jobNumber;
        private string _courier;
        private string _destination;
        private int _quantityOrdered;
        private int _quantityShipped;
        private string _comments;
        private DateTime? _dateShipped;
        private DateTime? _timeShipped;
        private string _updatingUser;
        private string _updatingMachine;

        private bool _insertedToDb;

        [mp.Column(Name = "MemoNumber", DbType="int", CanBeNull=false, IsPrimaryKey=true, UpdateCheck = mp.UpdateCheck.Never)]
        public int MemoNumber
        {
            get { return _memoNumber; }
            set { _memoNumber = value; }
        }

        [mp.Column(Name = "PONUMBER", DbType="char(17)", CanBeNull = false, IsPrimaryKey=true, UpdateCheck = mp.UpdateCheck.Never)]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "POLNENUM", DbType="int", CanBeNull = false, IsPrimaryKey=true, UpdateCheck = mp.UpdateCheck.Never)]
        public int Polnenum
        {
            get { return _polnenum; }
            set { _polnenum = value; }
        }

        [mp.Column(Name = "SOPNUMBER", CanBeNull=true, UpdateCheck = mp.UpdateCheck.Never)]
        public string SopNumber
        {
            get { return _sopNumber; }
            set { _sopNumber = value; }
        }

        [mp.Column(Name = "ITEMNMBR", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string ItemNumber
        {
            get { return _itemNumber; }
            set { _itemNumber = value; }
        }

        [mp.Column(Name = "ITEMDESC", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string ItemDescription
        {
            get { return _itemDescription; }
            set { _itemDescription = value; }
        }

        [mp.Column(Name = "VENDORID", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string VendorId
        {
            get { return _vendorId; }
            set { _vendorId = value; }
        }

        [mp.Column(Name = "VENDNAME", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string VendorName
        {
            get { return _vendorName; }
            set { _vendorName = value; }
        }

        [mp.Column(Name = "JobNumber", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "Courier", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Courier
        {
            get { return _courier; }
            set { _courier = value; }
        }

        [mp.Column(Name = "Destination", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Destination
        {
            get { return _destination; }
            set { _destination = value; }
        }

        [mp.Column(Name = "QuantityOrdered", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public int QuantityOrdered
        {
            get { return _quantityOrdered; }
            set { _quantityOrdered = value; }
        }

        [mp.Column(Name = "QuantityShipped", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public int QuantityShipped
        {
            get { return _quantityShipped; }
            set 
            { 
                _quantityShipped = value;
                OnPropertyChanged("QuantityShipped");
            }
        }

        [mp.Column(Name = "Comments", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string Comments
        {
            get { return _comments; }
            set { _comments = value; }
        }

        [mp.Column(Name = "DateShipped", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? DateShipped
        {
            get { return _dateShipped; }
            set { _dateShipped = value; }
        }

        [mp.Column(Name = "TimeShipped", DbType = "Time", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public DateTime? TimeShipped
        {
            get { return _timeShipped; }
            set { _timeShipped = value; }
        }

        [mp.Column(Name = "UpdatingUser", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set { _updatingUser = value; }
        }

        [mp.Column(Name = "UpdatingMachine", CanBeNull = true, UpdateCheck = mp.UpdateCheck.Never)]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set { _updatingMachine = value; }
        }

        public bool InsertedToDb
        {
            get { return _insertedToDb; }
            set { _insertedToDb = value; }
        }

        public ShippingLine()
        {
        }

        public ShippingLine(ShippingHeader sh, CombinedProject cp)
        {
            this._jobNumber = cp.Jc00102.JobNumber;
            this._itemNumber = "SHIPSAMPLE";
        }

        public ShippingLine(PurchaseOrderLineItem po)
        {
            this._poNumber = po.PoNumber;
            this._polnenum = po.Order;
            this._itemNumber = po.ItemNumber;
            this._itemDescription = po.ItemDescription;
            this._vendorId = po.VendorId;
            this._vendorName = po.VendorName;
            this._jobNumber = po.JobNumber;
            this._quantityOrdered = po.QuantityOrdered;
            this._quantityShipped = po.QuantityOrdered;
        }

        public ShippingLine(ReceivingLine rl, int quantityApplied)
        {
            this._poNumber = rl.PoNumber;
            this._polnenum = rl.Polnenum;
            this._sopNumber = rl.SopNumber;
            this._itemNumber = rl.ItemNumber;
            this._itemDescription = rl.ItemDescription;
            this._vendorId = rl.VendorId;
            this._vendorName = rl.VendorName;
            this._jobNumber = rl.JobNumber;
            this._quantityOrdered = rl.QtyOrdFromGp;
            this._quantityShipped = quantityApplied;
        }

        public ShippingLine(int memoNumber, 
                            string poNumber, 
                            int order,
                            string itemNumber,
                            string itemDescription,
                            string jobNumber,
                            string courier,
                            string destination,
                            int quantityOrdered,
                            int quantityShipped,
                            DateTime? dateShipped,
                            DateTime? timeShipped,
                            string updatingUser,
                            string updatingMachine
            )
        {
            this._memoNumber = memoNumber;
            this._poNumber = poNumber;
            this._polnenum = order;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._jobNumber = jobNumber;
            this._courier = courier;
            this._destination = destination;
            this._quantityOrdered = quantityOrdered;
            this._quantityShipped = quantityShipped;
            this._dateShipped = dateShipped;
            this._timeShipped = timeShipped;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class ShippingLineDataContext : lq.DataContext
    {
        public ShippingLineDataContext(string cs)
            : base(cs)
        {

        }

        public ShippingLineDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ShippingLine> ShippingLine;
    }
}
