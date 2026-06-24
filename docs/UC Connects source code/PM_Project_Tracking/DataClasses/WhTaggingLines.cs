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

namespace PM_Project_Tracking.DataClasses
{
    public static class WhTaggingLines
    {
        internal static ObservableCollection<TaggingLine> GetAllTagLines()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<TaggingLine> tagList = null;

            try
            {
                var tagQuery = from tag in dtCtx.GetTable<TaggingLine>()
                               join jc in dtCtx.GetTable<gp.Jc00102>() on tag.JobNumber equals jc.JobNumber into fullc
                               from jc in fullc.DefaultIfEmpty()
                                      select new
                                      {
                                          PoNumber = tag.PoNumber,
                                          Polnenum = tag.Polnenum,
                                          PopRctNum = tag.PopRctNum,
                                          RcptLnNum = tag.RcptLnNm,
                                          Iteration = tag.Iteration,
                                          TagReceiptNum = tag.TagReceiptNumber,
                                          TagReceiptLineNum  = tag.TagReceiptLineNumber,
                                          OrigReceiptQuantity = tag.OrigReceiptQuantity,
                                          OrigTaggedQuantity = tag.OrigTaggedQuantity,
                                          //Qty Rem on Skid
                                          CartNumbers = tag.CartNumbers,
                                          SopNumber = tag.SopNumber == null ? "" : tag.SopNumber,
                                          JobNumber = tag.JobNumber == null ? "" : tag.JobNumber,
                                          Location = tag.Location,
                                          Comments = tag.Comments,
                                          JobName = jc.JobName == null ? "" : jc.JobName,
                                          DateReceived = tag.DateReceived,
                                          TimeReceived = tag.TimeReceived,
                                          UpdatingUser = tag.UpdatingUser,
                                          UpdatingMachine = tag.UpdatingMachine

                                      };

                tagList = tagQuery.AsEnumerable().Select(x => new TaggingLine(x.PoNumber, x.Polnenum, x.PopRctNum, x.RcptLnNum, x.Iteration
                                                                             ,x.TagReceiptNum, x.TagReceiptLineNum, x.OrigReceiptQuantity, x.OrigTaggedQuantity, x.CartNumbers
                                                                             ,x.SopNumber, x.JobNumber, x.Location, x.Comments, x.JobName
                                                                             ,x.DateReceived, x.TimeReceived, x.UpdatingUser, x.UpdatingMachine)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<TaggingLine>(tagList);
        }

        internal static bool DeleteTagLine(TaggingLine tagLine)
        {
            bool _cont = true;
            using (TaggingLineDataContext dtCtx = new TaggingLineDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.TaggingLine.DeleteOnSubmit(tagLine);
                    dtCtx.SubmitChanges();
                    //tagLine.InsertedToDb = true;
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); _cont = false; }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; }
            }

            return _cont;
        }

        internal static bool UpdateTagLine(TaggingLine tagLine)
        {
            return false;
        }

        internal static bool AddTaggingLine(TaggingLine tagLine, int totalTags)
        {
            if (totalTags != CheckChangesBeforeInsert(tagLine))
            {
                MessageBox.Show("This receipt has been modified since you last refreshed the tag list. Please click 'REFRESH TAGS' once more then try this operation again.");
                return false;
            }

            bool _cont = true;
            using (TaggingLineDataContext dtCtx = new TaggingLineDataContext(GlobalVars.UcshConnectionString))
            {
                int i = 0;
                try
                {
                    tagLine.DateReceived = DateTime.Today;
                    tagLine.TimeReceived = DateTime.Now;
                    tagLine.UpdatingUser = Environment.UserName;
                    tagLine.UpdatingMachine = Environment.MachineName;
                    tagLine.TagReceiptNumber = GetNewTagRcptNumber(out i);
                    tagLine.Iteration = i;
                    tagLine.TagReceiptLineNumber = 1; //At the moment only one line can be created a time so there's no way this can be anything other than 1
                    dtCtx.TaggingLine.InsertOnSubmit(tagLine);
                    dtCtx.SubmitChanges();
                    //tagLine.InsertedToDb = true;
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); _cont = false; }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; }
            }
            return _cont;
        }

        private static int CheckChangesBeforeInsert(TaggingLine tl)
        {
            int _retVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select Sum(OrigTaggedQuantity) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[WHTAGGINGLINE101] "
                    + "where PONUMBER='" + tl.PoNumber 
                    + "' and POLNENUM='" + tl.Polnenum
                    + "' and POPRCTNM='" + tl.PopRctNum
                    + "' and RCPTLNNM='" + tl.RcptLnNm + "'";
                comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var _sumVal = comm.ExecuteScalar();
                if (_sumVal.GetType() != typeof(System.DBNull))
                    _retVal = (int)_sumVal;
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

            return _retVal;
        }

        private static string GetNewTagRcptNumber(out int iter)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(Iteration) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[WHTAGGINGLINE101]";
                comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var _maxVal = comm.ExecuteScalar();
                if (_maxVal.GetType() == typeof(System.DBNull))
                    _idVal =  1;
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

            iter = _idVal;
            return GenerateNextTagNumber(_idVal);
        }

        public static string GenerateNextTagNumber(int iter)
        {
            int[] _zeros = Enumerable.Repeat(0, 9 - iter.ToString().Length).ToArray();
            if (_zeros.Length > 0)
                return "TAG-" + string.Concat(_zeros) + iter;
            else
                return "TAG-" + iter;
        }
    }

    [mp.Table(Name = "[WHTAGGINGLINE101]")]
    public class TaggingLine : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private string _poNumber;
        private int _polnenum;
        private string _popRctNum;
        private int _rcptLnNm;
        private int _iteration;
        private string _tagReceiptNumber;
        private int _tagReceiptLineNumber;

        private int _origReceiptQuantity;
        private int _origTaggedQuantity;

        private string _cartNumbers;

        private string _sopNumber;
        private string _jobNumber;
        private string _location;
        private string _comments;

        //Not part of database model for tagging line
        private string _jobName;


        private DateTime? _dateReceived;
        private DateTime? _timeReceived;
        private string _updatingUser;
        private string _updatingMachine;

        //Ui
        private int _uiAmountToTag;
        private ReceivingLine _receivingLineParent;

        private bool _isModified;


        [mp.Column(Name = "PONUMBER")]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "POLNENUM")]
        public int Polnenum
        {
            get { return _polnenum; }
            set { _polnenum = value; }
        }

        [mp.Column(Name = "POPRCTNM")]
        public string PopRctNum
        {
            get { return _popRctNum; }
            set { _popRctNum = value; }
        }

        [mp.Column(Name = "RCPTLNNM")]
        public int RcptLnNm
        {
            get { return _rcptLnNm; }
            set { _rcptLnNm = value; }
        }

        [mp.Column(Name = "Iteration")]
        public int Iteration
        {
            get { return _iteration; }
            set { _iteration = value; }
        }

        [mp.Column(Name = "TagReceiptNumber", IsPrimaryKey = true)]
        public string TagReceiptNumber
        {
            get { return _tagReceiptNumber; }
            set { _tagReceiptNumber = value; }
        }

        [mp.Column(Name = "TagReceiptLineNumber", IsPrimaryKey = true)]
        public int TagReceiptLineNumber
        {
            get { return _tagReceiptLineNumber; }
            set { _tagReceiptLineNumber = value; }
        }

        [mp.Column(Name = "OrigReceiptQuantity")]
        public int OrigReceiptQuantity
        {
            get { return _origReceiptQuantity; }
            set { _origReceiptQuantity = value; }
        }

        [mp.Column(Name = "OrigTaggedQuantity")]
        public int OrigTaggedQuantity
        {
            get { return _origTaggedQuantity; }
            set
            {
                _origTaggedQuantity = value;
                _isModified = true;
                OnPropertyChanged("TaggedQuantity");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "CartNumbers")]
        public string CartNumbers
        {
            get { return _cartNumbers; }
            set 
            { 
                _cartNumbers = value;
                _isModified = true;
                OnPropertyChanged("CartNumbers");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "SopNumber")]
        public string SopNumber
        {
            get { return _sopNumber; }
            set { _sopNumber = value; }
        }

        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "Location")]
        public string Location
        {
            get { return _location; }
            set 
            { 
                _location = value;
                _isModified = true;
                OnPropertyChanged("Location");
                OnPropertyChanged("IsModified");
            }
        }

        [mp.Column(Name = "Comments")]
        public string Comments
        {
            get { return _comments; }
            set 
            { 
                _comments = value;
                _isModified = true;
                OnPropertyChanged("Comments");
                OnPropertyChanged("IsModified");
            }
        }

        public string JobName
        {
            get { return _jobName; }
            set { _jobName = value; }
        }

        [mp.Column(Name = "DateReceived")]
        public DateTime? DateReceived
        {
            get { return _dateReceived; }
            set { _dateReceived = value; }
        }

        [mp.Column(Name = "TimeReceived", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeReceived
        {
            get { return _timeReceived; }
            set { _timeReceived = value; }
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
            set { _isModified = value; }
        }

        public TaggingLine()
        {
        }

        //There can be many tag lines for a receiving line, but we only create one tag at a time, so for purposes of binding to the UI in the datagrid, a
        //1-to-1 relationship works.
        public TaggingLine(ReceivingLine rl)
        {
            _receivingLineParent = rl;
            this._jobNumber = rl.JobNumber;
            this._poNumber = rl.PoNumber;
            this._polnenum = rl.Polnenum;
            this._popRctNum = rl.PopRctNum;
            this._rcptLnNm = rl.RcptLnNm;
            this._sopNumber = rl.SopNumber;
            this._origReceiptQuantity = rl.QtyRecForGp;
        }

        public TaggingLine(string poNumber, int polnenum, string popRctNum, int rcptLineNum, int iteration
                           , string tagReceiptNumber, int tagReceiptLineNumber, int origReceiptQuantity, int taggedQuantity, string cartNumbers
                           , string sopNumber, string jobNumber, string location, string comments, string jobName
                           , DateTime? dateReceived , DateTime? timeReceived, string updatingUser, string updatingMachine
                           )
        {
            this._poNumber = poNumber;
            this._polnenum = polnenum;
            this._popRctNum = popRctNum;
            this._rcptLnNm = rcptLineNum;
            this._iteration = iteration;
            this._tagReceiptNumber = tagReceiptNumber;
            this._tagReceiptLineNumber = tagReceiptLineNumber;
            this._origReceiptQuantity = origReceiptQuantity;
            this._origTaggedQuantity = taggedQuantity;
            this._cartNumbers = cartNumbers;
            this._sopNumber = sopNumber;
            this._jobNumber = jobNumber;
            this._location = location;
            this._comments = comments;
            this._jobName = jobName;
            this._dateReceived = dateReceived;
            this._timeReceived = timeReceived;
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

    public class TaggingLineDataContext : lq.DataContext
    {
        public TaggingLineDataContext(string cs)
            : base(cs)
        {

        }

        public TaggingLineDataContext(SqlConnection conn)
            : base(conn)
        {

        }

        public lq.Table<TaggingLine> TaggingLine;
    }
}
