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

namespace PM_Project_Tracking.DataClasses
{
    class PoUcshHeaderComments
    {
        internal static ObservableCollection<PoUcshHeaderComment> GetPoUcshHeaderComments(string poNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<PoUcshHeaderComment> headerCommentList = null;

            try
            {
                headerCommentList = dtCtx.GetTable<PoUcshHeaderComment>().Where(n => n.PoNumber == poNumber).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<PoUcshHeaderComment>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<PoUcshHeaderComment>(headerCommentList);
        }

        public static void InsertUpdatePoUcshHeaderComment(ObservableCollection<PoUcshHeaderComment> headers)
        {
            bool _moreThanOneNew = false;
            int _newId = 0;
            using (PoUcshHeaderCommentDataContext dtCtx = new PoUcshHeaderCommentDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime? _dCreate = DateTime.Today;
                DateTime? _tCreate = DateTime.Now;
                string _cUser = Environment.UserName;
                string _cMachine = Environment.MachineName;

                try
                {
                    foreach (PoUcshHeaderComment hdr in headers)
                    {
                        if (hdr.Id == 0)
                        {
                            if (_moreThanOneNew)
                            {
                                _newId += 1;
                                hdr.Id = _newId;
                            }
                            else
                            {
                                _newId = GetNextHeaderCommentId();
                                hdr.Id = _newId;
                                _moreThanOneNew = true;
                            }

                            //hdr.DateCreated = _dCreate;
                            //hdr.TimeCreated = _tCreate;
                            dtCtx.PoUcshHeaderComment.InsertOnSubmit(hdr);

                        }
                        else if (hdr.Id != 0 && hdr.IsModified == true)
                        {
                            //hdr.DateEdited = _dCreate;
                            //hdr.TimeEdited = _tCreate;
                            //hdr.EditingUser = _cUser;
                            dtCtx.PoUcshHeaderComment.Attach(hdr, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, hdr);
                        }
                    }

                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                
            }
        }

        public static int GetNextHeaderCommentId()
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[POUCSHHEADERCOMMENT101]";
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

    [mp.Table(Name = "[POUCSHHEADERCOMMENT101]")]
    public class PoUcshHeaderComment : IPoUcshComment, INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _poNumber;
        private string _jobNumber;
        private string _commentText;

        private DateTime? _doNotShipBeforeDate;

        private DateTime? _dateEdited;
        private DateTime? _timeEdited;
        private string _editingUser;

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _creatingUser;
        private string _creatingMachine;

        private bool _isModified;
        private string _currentUserName;

        [mp.Column(Name = "ID", IsPrimaryKey=true)]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "PONUMBER")]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "CommentText")]
        public string CommentText
        {
            get { return _commentText; }
            set
            {
                _commentText = value;
                this.OnPropertyChanged("CommentText");
                if (Id != 0)    //IDs with value of 0 mean they are new and haven't been entered into the database yet
                {
                    _editingUser = Environment.UserName;
                    _dateEdited = DateTime.Today;
                    _timeEdited = DateTime.Now;
                    _isModified = true;
                    this.OnPropertyChanged("Mod");
                }
            }
        }

        [mp.Column(Name = "DoNotShipBeforeDate")]
        public DateTime? DoNotShipBeforeDate
        {
            get { return _doNotShipBeforeDate; }
            set { _doNotShipBeforeDate = value; }
        }

        [mp.Column(Name = "DateEdited")]
        public DateTime? DateEdited
        {
            get { return _dateEdited; }
            set { _dateEdited = value; }
        }

        [mp.Column(Name = "TimeEdited", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeEdited
        {
            get { return _timeEdited; }
            set { _timeEdited = value; }
        }

        [mp.Column(Name = "EditingUser")]
        public string EditingUser
        {
            get { return _editingUser; }
            set { _editingUser = value; }
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

        [mp.Column(Name = "CreatingUser")]
        public string CreatingUser
        {
            get { return _creatingUser; }
            set { _creatingUser = value; }
        }

        [mp.Column(Name = "CreatingMachine")]
        public string CreatingMachine
        {
            get { return _creatingMachine; }
            set { _creatingMachine = value; }
        }

        public bool IsModified
        {
            get { return _isModified; }
            set { _isModified = value; }
        }

        public PoUcshHeaderComment()
        {
        }

        public PoUcshHeaderComment(string jobNumber, string poNumber)
        {
            this._jobNumber = jobNumber;
            this._poNumber = poNumber;
            this._creatingUser = Environment.UserName;
            this._creatingMachine = Environment.MachineName;
            this._dateCreated = DateTime.Today;
            this._timeCreated = DateTime.Now;
        }

        public PoUcshHeaderComment(string curUserName)
        {
            this._currentUserName = curUserName;
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

    }

    public class PoUcshHeaderCommentDataContext : lq.DataContext
    {
        public PoUcshHeaderCommentDataContext(string cs)
            : base(cs)
        {
        }

        public PoUcshHeaderCommentDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<PoUcshHeaderComment> PoUcshHeaderComment;
    }
}
