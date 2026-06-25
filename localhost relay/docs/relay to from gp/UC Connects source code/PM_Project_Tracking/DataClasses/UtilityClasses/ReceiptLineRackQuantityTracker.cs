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
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking.DataClasses.UtilityClasses
{
    public class ReceiptLineRackQuantityTracker : ObservableCollection<RecLineTracker>
    {
        public void DeleteItems()
        {
            for (int x = this.Items.Count - 1; x >= 0; x--)
            {
                if (this.Items[x].Delete)
                    this.Items.Remove(this.Items[x]);
            }
        }

        public void AssignSerial()
        {
            int i = 0;
            for (int x = 0; x < this.Items.Count; x++)
            {
                i++;
                this.Items[x].SerialLine = i;
            }
        }

        public void GetReceivingLines()
        {
            //var colQuery = this.Items.GroupBy(x => new { x.PoNumber, x.Polnenum, x.PopRctNum, x.RcptLnNm, TotalDraw = Items.Select(r => r.QuantityDrawn).Sum() });
            //var colQuery = this.Items.GroupBy(x => new { x.PoNumber, x.Polnenum, x.PopRctNum, x.RcptLnNm, TotalDraw = Items.GroupBy(n => new {n.PoNumber, n.Polnenum, n.PopRctNum, n.RcptLnNm }).Select(r => x.QuantityDrawn).Sum() });
            //var colQuery = this.Items.GroupBy(x => new { x.PoNumber, x.Polnenum, x.PopRctNum, x.RcptLnNm, TotalDraw = Items.Select(n => new { n.PoNumber, n.Polnenum, n.PopRctNum, n.RcptLnNm, n.QuantityDrawn }).GroupBy(r => new { r.PoNumber, r.Polnenum, r.PopRctNum, r.RcptLnNm }).Select(z => x.QuantityDrawn).Sum()  });
            //var colQuery = this.Items.GroupBy(x => new { x.PoNumber, x.Polnenum, x.PopRctNum, x.RcptLnNm, TotalDraw = Items.Select(n => new { n.PoNumber, n.Polnenum, n.PopRctNum, n.RcptLnNm, n.QuantityDrawn }).GroupBy(r => new { r.PoNumber, r.Polnenum, r.PopRctNum, r.RcptLnNm }).Select(z => x.QuantityDrawn).Sum() });
            //var colQuery = this.Items.Select(x => new { x.PoNumber, x.Polnenum, x.PopRctNum, x.RcptLnNm, x.QuantityDrawn}).GroupBy(n => new { n.PoNumber, n.Polnenum, n.PopRctNum, n.RcptLnNm }) ;

            //var colQuery = from asdf in this.Items.Select(x => new { x.PoNumber, x.Polnenum, x.PopRctNum, x.RcptLnNm, x.QuantityDrawn }).GroupBy(r => new { r.PoNumber, r.Polnenum, r.PopRctNum, r.RcptLnNm, TotalDraw = r })
            //               select new
            //               {
            //               };

            var colQuery = from asdf in this.Items
                           group asdf by new { PoNumber = asdf.PoNumber, Polnenum = asdf.Polnenum, asdf.PopRctNum, asdf.RcptLnNm } into grp
                           select new
                           {
                               grp.Key.PoNumber,
                               grp.Key.Polnenum,
                               grp.Key.PopRctNum,
                               grp.Key.RcptLnNm,
                               TotalDraw = grp.Select(x => x.QuantityDrawn).Sum()
                           };
                           
        }
    }

    class RecLineTrackers
    {
        internal static bool AddRecLineTrackers(ObservableCollection<RecLineTracker> rltCol, int memoNum)
        {
            bool _cont = true;
            using (RecLineTrackerDataContext dtCtx = new RecLineTrackerDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (RecLineTracker rlt in rltCol)
                {
                    try
                    {
                        rlt.MemoNumber = memoNum;
                        rlt.DateShipped = DateTime.Today;
                        rlt.TimeShipped = DateTime.Now;
                        dtCtx.RecLineTracker.InsertOnSubmit(rlt);
                        rlt.InsertedToDb = true;
                    }
                    catch (SqlException sqlEx)
                    {
                        //
                        MessageBox.Show(sqlEx.ToString());
                        _cont = false;
                        break;
                    }
                    catch (Exception ex)
                    {
                        //
                        MessageBox.Show(ex.ToString());
                        _cont = false;
                        break;
                    }
                }
                dtCtx.SubmitChanges();
            }
            if (!_cont)
            {
                RollbackRecLineTrackers(memoNum);
                WhShippingLines.RollBackShippingLines(memoNum);
                WhShippingLines.RollbackShippingHeader(memoNum);
            }
            return _cont;
        }

        public static void DeleteRecLines(RecLineTracker rlt)
        {
            using (RecLineTrackerDataContext dtCtx = new RecLineTrackerDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.RecLineTracker.Attach(rlt, rlt);
                    dtCtx.RecLineTracker.DeleteOnSubmit(rlt);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void RollbackRecLineTrackers(int memoNum)
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "DELETE FROM WHRECLINEDRAWDOWNS101 WHERE MemoNumber='" + memoNum + "'";

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
    }

    [mp.Table(Name = "WHRECLINEDRAWDOWNS101")]
    public class RecLineTracker
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _memoNumber;
        private int _serialLine;
        private string _poNumber;
        private int _polnenum;
        private string _popRctNum;
        private int _rcptLnNm;
        private int _quantityDrawn;
        private DateTime? _dateShipped;
        private DateTime? _timeShipped;
        private bool _delete;

        private bool _insertedToDb;     //I believe this was made to check what was already inserted and what wasn't so that the database insert method wouldn't try to delete what wasn't there and return an error
                                        //because as far as I can tell, the only time it shows up in references is once, where it doesn't do much except get set to true.

        [mp.Column(Name = "MemoNumber", IsPrimaryKey=true)]         //DOUBLE CHECK TO SET PRIMARY KEYS TOMORROW
        public int MemoNumber
        {
            get { return _memoNumber; }
            set { _memoNumber = value; }
        }

        [mp.Column(Name = "SerialLine", IsPrimaryKey = true)]         //DOUBLE CHECK TO SET PRIMARY KEYS TOMORROW
        public int SerialLine
        {
            get { return _serialLine; }
            set { _serialLine = value; }
        }

        [mp.Column(Name = "PONUMBER")]         //DOUBLE CHECK TO SET PRIMARY KEYS TOMORROW
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "POLNENUM")]         //DOUBLE CHECK TO SET PRIMARY KEYS TOMORROW
        public int Polnenum
        {
            get { return _polnenum; }
            set { _polnenum = value; }
        }

        [mp.Column(Name = "POPRCTNM")]         //DOUBLE CHECK TO SET PRIMARY KEYS TOMORROW
        public string PopRctNum
        {
            get { return _popRctNum; }
            set { _popRctNum = value; }
        }

        [mp.Column(Name = "RCPTLNNM")]         //DOUBLE CHECK TO SET PRIMARY KEYS TOMORROW
        public int RcptLnNm
        {
            get { return _rcptLnNm; }
            set { _rcptLnNm = value; }
        }

        [mp.Column(Name = "QuantityDrawn")]
        public int QuantityDrawn
        {
            get { return _quantityDrawn; }
            set { _quantityDrawn = value; }
        }

        [mp.Column(Name = "DateShipped")]
        public DateTime? DateShipped
        {
            get { return _dateShipped; }
            set { _dateShipped = value; }
        }

        [mp.Column(Name = "TimeShipped", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeShipped
        {
            get { return _timeShipped; }
            set { _timeShipped = value; }
        }

        public bool Delete
        {
            get { return _delete; }
            set { _delete = value; }
        }

        public bool InsertedToDb
        {
            get { return _insertedToDb; }
            set { _insertedToDb = value; }
        }

        public RecLineTracker()
        {
        }

        public RecLineTracker(DataClasses.ReceivingLine rl, int quantDrawn)
        {
            this._poNumber = rl.PoNumber;
            this._polnenum = rl.Polnenum;
            this._popRctNum = rl.PopRctNum;
            this._rcptLnNm = rl.RcptLnNm;
            this._quantityDrawn = quantDrawn;
        }
    }

    public class RecLineTrackerDataContext : lq.DataContext
    {
        public RecLineTrackerDataContext(string cs)
            : base(cs)
        {

        }

        public RecLineTrackerDataContext(SqlConnection conn)
            : base(conn)
        {

        }

        public lq.Table<RecLineTracker> RecLineTracker;
    }
}
