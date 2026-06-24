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
    class PoUcshLineComments
    {
        internal static ObservableCollection<PoUcshLineComment> GetPoUcshLineComments(string poNumber, int order)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<PoUcshLineComment> lineCommentList = null;

            try
            {
                lineCommentList = dtCtx.GetTable<PoUcshLineComment>().Where(n => n.PoNumber == poNumber && n.Order == order).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<PoUcshLineComment>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<PoUcshLineComment>(lineCommentList);
        }

        public static void InsertUpdatePoUcshLineComment(ObservableCollection<PoUcshLineComment> lines)
        {
            bool _moreThanOneNew = false;
            int _newId = 0;

            using (PoUcshLineCommentDataContext dtCtx = new PoUcshLineCommentDataContext(GlobalVars.UcshConnectionString))
            {
                DateTime? _dCreate = DateTime.Today;
                DateTime? _tCreate = DateTime.Now;
                string _cUser = Environment.UserName;
                string _cMachine = Environment.MachineName;

                try
                {
                    foreach (PoUcshLineComment line in lines)
                    {
                        if (line.Id == 0)
                        {
                            if (_moreThanOneNew)
                            {
                                _newId += 1;
                                line.Id = _newId;
                            }
                            else
                            {
                                _newId = GetNextLineCommentId();
                                line.Id = _newId;
                                _moreThanOneNew = true;
                            }

                            //line.CreatingUser = _cUser;
                            //line.CreatingMachine = _cMachine;
                            dtCtx.PoUcshLineComment.InsertOnSubmit(line);
                        }
                        else if (line.Id != 0 && line.IsModified == true)
                        {
                            //line.DateEdited = _dCreate;
                            //line.TimeEdited = _tCreate;
                            //line.EditingUser = _cUser;
                            dtCtx.PoUcshLineComment.Attach(line, false);
                            dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, line);
                        }
                    }

                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }

            }
        }

        public static int GetNextLineCommentId()
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.CurrentPmDatabaseName + "].[dbo].[POUCSHLINECOMMENT101]";
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

    [mp.Table(Name = "[POUCSHLINECOMMENT101]")]
    public class PoUcshLineComment : IPoUcshComment, INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _poNumber;
        private int _order;
        private string _jobNumber;
        private string _commentText;

        private DateTime? _dateEdited;
        private DateTime? _timeEdited;
        private string _editingUser;

        private DateTime? _dateCreated;
        private DateTime? _timeCreated;
        private string _creatingUser;
        private string _creatingMachine;

        private bool _isModified;
        private string _currentUserName;

        [mp.Column(Name = "ID", IsPrimaryKey = true)]
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

        [mp.Column(Name = "ORD")]
        public int Order
        {
            get { return _order; }
            set { _order = value; }
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

        public PoUcshLineComment()
        {
        }

        public PoUcshLineComment(string jobNumber, string poNumber, int order)
        {
            this._jobNumber = jobNumber;
            this._poNumber = poNumber;
            this._order = order;
            this._creatingUser = Environment.UserName;
            this._creatingMachine = Environment.MachineName;
            this._dateCreated = DateTime.Today;
            this._timeCreated = DateTime.Now;
        }

        public PoUcshLineComment(string curUserName)
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

    public class PoUcshLineCommentDataContext : lq.DataContext
    {
        public PoUcshLineCommentDataContext(string cs)
            : base(cs)
        {
        }

        public PoUcshLineCommentDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<PoUcshLineComment> PoUcshLineComment;
    }
}
