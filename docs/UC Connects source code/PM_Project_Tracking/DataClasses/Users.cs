using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Collections.ObjectModel;
using System.Windows;
using System.Data.SqlClient;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using System.Linq.Expressions;

namespace PM_Project_Tracking.DataClasses
{
    class Users
    {
        internal static ObservableCollection<User> GetUsers()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<User> userList = null;

            try
            {
                var userQuery = from users in dtCtx.GetTable<User>()
                                orderby users.DomainUserName
                                where users.IsActive == true
                                select new
                                {
                                    Id = users.Id,
                                    DomainUserName = users.DomainUserName,
                                    PermissionTier = users.PermissionTier,
                                    TierName = users.TierName,
                                    Email = users.Email,
                                    IsActive = users.IsActive,
                                    CompanyId = users.CompanyId,
                                    UserAssocs = dtCtx.GetTable<UserAssociation>().Where(n => n.DomainUserName == users.DomainUserName).ToList(),
                                    Overrides = dtCtx.GetTable<UserOverride>().Where(n => n.DomainUserName == users.DomainUserName).ToList()
                                };

                userList = userQuery.AsEnumerable().Select(x => new User(x.Id, x.DomainUserName, x.PermissionTier, x.TierName, x.Email, x.IsActive, x.CompanyId, x.UserAssocs, x.Overrides)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<User>();  
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<User>(userList);
        }

        internal static User GetCurrentUser()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            User _user = null;
            string userName = Environment.UserName;
            //string userName = "markd"; 

            try
            {
                var userQuery = from users in dtCtx.GetTable<User>()
                                where users.DomainUserName == userName
                                select new
                                {
                                    Id = users.Id,
                                    DomainUserName = users.DomainUserName,
                                    PermissionTier = users.PermissionTier,
                                    TierName = users.TierName,
                                    Email = users.Email,
                                    IsActive = users.IsActive,
                                    CompanyId = users.CompanyId,
                                    UserAssocs = dtCtx.GetTable<UserAssociation>().Where(n => n.DomainUserName == userName).ToList(),
                                    Overrides = dtCtx.GetTable<UserOverride>().Where(n => n.DomainUserName == userName).ToList()
                                };

                _user = userQuery.AsEnumerable().Select(x => new User(x.Id, x.DomainUserName, x.PermissionTier, x.TierName, x.Email, x.IsActive, x.CompanyId, x.UserAssocs, x.Overrides)).ToList().FirstOrDefault();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            if (_user == null)
            {
                MessageBox.Show("Current user '" + Environment.UserName + "' does not exist in the database.  Closing program.");
                return null;
            }
            else
            {
                return _user;
            }
        }

        internal static User GetDummyUser()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(@"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=UCUsers;Integrated Security=SSPI;");
            //lq.DataContext dtCtx = new lq.DataContext(@"Data Source=UCSHSQL2\MSSQL2014;Initial Catalog=UCUsers;Integrated Security=SSPI;", um.DatabaseSwitcher.Convert(ref tempdtCtx));

            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            User _user = null;
            //string userName = Environment.UserName;
            string userName = "danz"; 

            try
            {       
                var userQuery = from users in dtCtx.GetTable<User>()
                                where users.DomainUserName == userName
                                select new
                                {
                                    Id = users.Id,
                                    DomainUserName = users.DomainUserName,
                                    PermissionTier = users.PermissionTier,
                                    TierName = users.TierName,
                                    Email = users.Email,
                                    IsActive = users.IsActive,
                                    CompanyId = users.CompanyId,
                                    UserAssocs = dtCtx.GetTable<UserAssociation>().Where(n => n.DomainUserName == userName).ToList(),
                                    Overrides = dtCtx.GetTable<UserOverride>().Where(n => n.DomainUserName == userName).ToList()
                                };

                _user = userQuery.AsEnumerable().Select(x => new User(x.Id, x.DomainUserName, x.PermissionTier, x.TierName, x.Email, x.IsActive, x.CompanyId, x.UserAssocs, x.Overrides)).ToList().FirstOrDefault();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            if (_user == null)
            {
                MessageBox.Show("Current user '" + Environment.UserName + "' does not exist in the database.  Closing program.");
                return null;
            }
            else
            {
                return _user;
            }
        }

        internal static int GetMaxUserId(object objWithTableAttrib)
        {
            int _idVal = 0;
            SqlConnection conn = new SqlConnection(GlobalVars.UcUsersConnectionString);
            SqlCommand comm = null;
            string strQuery = null;

            string tableName = um.GetClassDbTableName.GetTableName(objWithTableAttrib);
            if (tableName == "")
            {
                MessageBox.Show("No table name in the database associated with " + objWithTableAttrib.GetType().Name);
                return 0;
            }

            try
            {
                strQuery = "select MAX(ID) from [" + GlobalVars.UcUserDatabaseName + "].[dbo]." + tableName ;
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

        public static void AddUser(User us)
        {
            using (UserDataContext dtCtx = new UserDataContext(GlobalVars.UcUsersConnectionString))
            {
                try
                {
                    dtCtx.User.InsertOnSubmit(us);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void UpdateUser(User us)
        {
            using (UserDataContext dtCtx = new UserDataContext(GlobalVars.UcUsersConnectionString))
            {
                try
                {
                    dtCtx.User.Attach(us, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, us);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static void DeleteUser(User us)
        {
            using (UserDataContext dtCtx = new UserDataContext(GlobalVars.UcUsersConnectionString))
            {
                try
                {
                    dtCtx.User.Attach(us, us);
                    dtCtx.User.DeleteOnSubmit(us);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        private static string ConcatenatedPermission(UserOverride um)
        {
            return um.OverrideName;
        }

        //------------------------------------------

        internal static ObservableCollection<UserAssociation> GetDistinctAssociationTypes()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<UserAssociation> assocList = null;

            try
            {
                var userQuery = from assoc in dtCtx.GetTable<UserAssociation>()
                                group assoc by new { AssociationType = assoc.AssociationType } into grp
                                select new
                                {
                                    grp.Key.AssociationType
                                };

                assocList = userQuery.AsEnumerable().Select(x => new UserAssociation(x.AssociationType)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<UserAssociation>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<UserAssociation>(assocList);
        }

        internal static ObservableCollection<UserAssociation> GetDistinctGpManagers()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<UserAssociation> pmList = null;

            try
            {
                pmList = dtCtx.GetTable<gp.Jc00102>().Select(x => x.ProjectManager).Distinct().AsEnumerable().Select(n => new UserAssociation(1, n.Trim()))
                    .Where(c => c.AssociationValue != "").OrderBy(r => r.AssociationValue).ToList();
                pmList.OrderBy(x => x.AssociationValue);
                //var unionQuery = dtCtx.GetTable<gp.Jc00102>().Select(x => x.ProjectManager).Distinct().Union(dtCtx.GetTable<gp.Jc00102>().Select(x => x.Consultant).Distinct());
                //pmList = pmQuery.AsEnumerable().Select(x => new UserAssociation(1, x)).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<UserAssociation>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<UserAssociation>(pmList);
        }

        internal static ObservableCollection<UserAssociation> GetDistinctGpConsultants()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<UserAssociation> consultantList = null;

            try
            {
                consultantList = dtCtx.GetTable<gp.Jc00102>().Select(x => x.Consultant).Distinct().AsEnumerable().Select(n => new UserAssociation(2, n)).OrderBy(r => r.AssociationValue).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<UserAssociation>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<UserAssociation>(consultantList);
        }

        internal static void AddNewUserAssociation(UserAssociation userAssoc)
        {
            userAssoc.Id = GetMaxUserId(userAssoc);
            if (userAssoc.Id == 0)
            {
                MessageBox.Show("ID of 0 returned, no record created");
                return;
            }

            using (UserAssociationDataContext dtCtx = new UserAssociationDataContext(GlobalVars.UcUsersConnectionString))
            {
                try
                {
                    dtCtx.UserAssociation.InsertOnSubmit(userAssoc);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        //----------------------------------------------------------

        internal static ObservableCollection<string> GetDistinctOverrideTypes()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<string> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<UserOverride>().Select(x => x.OverrideType).Distinct().ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<string>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<string>(viewsList);
        }

        internal static ObservableCollection<UserOverride> GetDistinctOverrideViews()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<UserOverride> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<UserOverride>().Where(i => i.OverrideType == "view").Select(x => x.OverrideName).Distinct().AsEnumerable().Select(n => new UserOverride("view", n)).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<UserOverride>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<UserOverride>(viewsList);
        }

        internal static ObservableCollection<UserOverride> GetDistinctOverrideAccess()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<UserOverride> accessList = null;

            try
            {
                accessList = dtCtx.GetTable<UserOverride>().Where(i => i.OverrideType == "access").Select(x => x.OverrideName).Distinct().AsEnumerable().Select(n => new UserOverride("access", n)).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<UserOverride>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<UserOverride>(accessList);
        }

        internal static void AddNewUserOverride(UserOverride userOverride)
        {
            userOverride.Id = GetMaxUserId(userOverride);
            if (userOverride.Id == 0)
            {
                MessageBox.Show("ID of 0 returned, no record created");
                return;
            }

            using (UserOverrideDataContext dtCtx = new UserOverrideDataContext(GlobalVars.UcUsersConnectionString))
            {
                try
                {
                    dtCtx.UserOverride.InsertOnSubmit(userOverride);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        //----------------------------
        internal static ObservableCollection<UserRoleList> GetUserRoleList()
        {
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcUsersConnectionString);
            List<UserRoleList> userRoleList = null;

            try
            {
                userRoleList = dtCtx.GetTable<UserRoleList>().ToList();
                //userRoleList = dtCtx.GetTable<UserRoleList>().AsEnumerable().Select(x => new UserRoleList(x.RoleId, x.RoleName)).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<UserRoleList>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<UserRoleList>(userRoleList);
        }

        internal static void AddUserSecondaryRole(UserRole roleItem)
        {
            using (UserRoleDataContext dtCtx = new UserRoleDataContext(GlobalVars.UcUsersConnectionString))
            {
                try
                {
                    dtCtx.UserRole.InsertOnSubmit(roleItem);
                    dtCtx.SubmitChanges();
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }
    }

    [mp.Table(Name = "[SYSUCUSERS]")]
    public class User
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private string _domainUserName;
        private int? _permissionTier;
        private string _tierName;
        private string _email;
        private bool _isActive;
        private int _companyId;
        private List<UserAssociation> _userAssocs;

        private List<string> _gpEstimators = new List<string>();
        private List<string> _wsManagers = new List<string>();
        private List<string> _viewOverrides = new List<string>();
        private List<string> _accessOverrides = new List<string>();

        [mp.Column(Name = "ID", IsPrimaryKey = true)]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "DomainUserName")]
        public string DomainUserName
        {
            get { return _domainUserName; }
            set { _domainUserName = value; }
        }

        [mp.Column(Name = "PermissionTier")]
        public int? PermissionTier
        {
            get { return _permissionTier; }
            set { _permissionTier = value; }
        }

        [mp.Column(Name = "TierName")]
        public string TierName
        {
            get { return _tierName; }
            set { _tierName = value; }
        }

        [mp.Column(Name = "Email")]
        public string Email
        {
            get
            {
                return _email;
            }

            set
            {
                _email = value;
            }
        }

        [mp.Column(Name = "IsActive", DbType = "bit")]
        public bool IsActive
        {
            get
            {
                return _isActive;
            }

            set
            {
                _isActive = value;
            }
        }

        public List<string> GpEstimators
        {
            get { return _gpEstimators; }
            set { _gpEstimators = value; }
        }

        public List<string> WsManagers
        {
            get { return _wsManagers; }
            set { _wsManagers = value; }
        }

        public List<string> ViewOverrides
        {
            get { return _viewOverrides; }
            set { _viewOverrides = value; }
        }

        public List<string> AccessOverrides
        {
            get { return _accessOverrides; }
            set { _accessOverrides = value; }
        }

        public List<UserAssociation> UserAssocs
        {
          get { return _userAssocs; }
          set { _userAssocs = value; }
        }

        [mp.Column(Name = "CompanyId", DbType = "int")]
        public int CompanyId
        {
            get
            {
                return _companyId;
            }

            set
            {
                _companyId = value;
            }
        }

        public User()
        {
        }

        public User(string dName)
        {
            this._domainUserName = dName;
        }

        public User(string dName, List<UserAssociation> userAssoc)
        {
            this._domainUserName = dName;
            this._userAssocs = userAssoc;
        }

        public User(int id, string dName, int? pTier, string tName)
        {
            this._id = id;
            this._domainUserName = dName;
            this._permissionTier = pTier;
            this._tierName = tName;
        }

        public User(int id, string dName, int? pTier, string tName, string email, bool isActive, int companyId, List<UserAssociation> userAssoc, List<UserOverride> overrides)
        {
            this._id = id;
            this._domainUserName = dName;
            this._permissionTier = pTier;
            this._tierName = tName;
            this._email = email;
            this._isActive = isActive;
            this._companyId = companyId;
            //Association Type 1 = Project Manager, Association Type 2 = Consultant
            this._userAssocs = userAssoc;
            foreach (UserAssociation assoc in this.UserAssocs)
            {
                switch (assoc.AssociationType)
                {
                    case 1:
                        this._wsManagers.Add(assoc.AssociationValue);
                        break;
                    case 2:
                        this._gpEstimators.Add(assoc.AssociationValue);
                        break;
                }
            }

            foreach (UserOverride over in overrides)
            {
                switch (over.OverrideType)
                {
                    case "view":
                        this._viewOverrides.Add(over.OverrideName);
                        break;
                    case "access":
                        this._accessOverrides.Add(over.OverrideName);
                        break;
                }
            }
        }

        // Need this? http://stackoverflow.com/questions/19616711/howto-use-predicates-in-linq-to-entities-for-entity-framework-objects
        // Or this https://msdn.microsoft.com/en-us/library/mt654267.aspx
        public IEnumerable<string> IsGpEstimator()
        {
            foreach (UserAssociation userAssoc in this._userAssocs)
                yield return userAssoc.AssociationValue;
        }

    }

    public class UserDataContext : lq.DataContext
    {
        public UserDataContext(string cs)
            : base(cs)
        {
        }

        public UserDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<User> User;
    }

    [mp.Table(Name = "[SYSUCUSERSROLEASSIGN]")]
    public class UserRole
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _roleId;
        private string _roleName;
        private int _userId;
        private string _domainUserName;
        private string _email;

        [mp.Column(Name = "RoleID", IsPrimaryKey=true)]
        public int RoleId
        {
            get
            {
                return _roleId;
            }

            set
            {
                _roleId = value;
            }
        }

        [mp.Column(Name = "RoleName")]
        public string RoleName
        {
            get
            {
                return _roleName;
            }

            set
            {
                _roleName = value;
            }
        }

        [mp.Column(Name = "ID", IsPrimaryKey = true)]
        public int UserId
        {
            get
            {
                return _userId;
            }

            set
            {
                _userId = value;
            }
        }

        [mp.Column(Name = "DomainUserName")]
        public string DomainUserName
        {
            get
            {
                return _domainUserName;
            }

            set
            {
                _domainUserName = value;
            }
        }

        [mp.Column(Name = "Email")]
        public string Email
        {
            get
            {
                return _email;
            }

            set
            {
                _email = value;
            }
        }

        public UserRole()
        {

        }
    }

    public class UserRoleDataContext : lq.DataContext
    {
        public UserRoleDataContext(string cs)
            : base(cs)
        {
        }

        public UserRoleDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<UserRole> UserRole;
    }

    [mp.Table(Name = "[SYSUCUSERSROLELIST]")]
    public class UserRoleList
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _roleId;
        private string _roleName;

        [mp.Column(Name = "RoleID")]
        public int RoleId
        {
            get
            {
                return _roleId;
            }

            set
            {
                _roleId = value;
            }
        }

        [mp.Column(Name = "RoleName")]
        public string RoleName
        {
            get
            {
                return _roleName;
            }

            set
            {
                _roleName = value;
            }
        }

        public UserRoleList()
        {
        }

        public UserRoleList(int roleId, string roleName)
        {
            _roleId = roleId;
            _roleName = roleName;
        }
    }

    public class UserRoleListDataContext : lq.DataContext
    {
        public UserRoleListDataContext(string cs)
            : base(cs)
        {
        }

        public UserRoleListDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<UserRole> UserRoleList;
    }

    [mp.Table(Name = "[SYSUCUSERSASSOC]")]
    public class UserAssociation
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        //useful for later - http://stackoverflow.com/questions/1248232/combine-multiple-predicates

        private int _id;
        private int _userId;
        private string _domainUserName;
        private int _associationType;       //Association Type 1 = Project Manager (goes into WsManagers collection), Association Type 2 = Consultant (goes into GpEstimators collection)
                                            //*Note, because someone messed up early on, the field in GP used for consultant is 'WS_Manager_ID' and the field used for project manager is 
                                            //the "Estimator_ID" field (both) in JC00102
        private string _associationValue;

        [mp.Column(Name = "ID")]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "UserId", IsPrimaryKey=true)]
        public int UserId
        {
            get { return _userId; }
            set { _userId = value; }
        }

        [mp.Column(Name = "DomainUserName", IsPrimaryKey = true)]
        public string DomainUserName
        {
            get { return _domainUserName; }
            set { _domainUserName = value; }
        }

        [mp.Column(Name = "AssociationType", IsPrimaryKey = true)]
        public int AssociationType
        {
            get { return _associationType; }
            set 
            { 
                _associationType = value;
                switch (value)
                {
                    case 1:
                        this._associationValue = "Project Manager";
                        break;
                    case 2:
                        this._associationValue = "Consultant";
                        break;
                }
            }
        }

        [mp.Column(Name = "AssociationName", IsPrimaryKey = true)]
        public string AssociationValue
        {
            get { return _associationValue; }
            set { _associationValue = value; }
        }

        public UserAssociation()
        {
        }

        public UserAssociation(int associationType)
        {
            AssociationType = associationType;  //Using the property to set hte name
        }

        public UserAssociation(int associationType, string associationName)
        {
            AssociationType = associationType;  //Using the property to set hte name
            _associationValue = associationName;
        }
    }

    public class UserAssociationDataContext : lq.DataContext
    {
        public UserAssociationDataContext(string cs)
            : base(cs)
        {
        }

        public UserAssociationDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<UserAssociation> UserAssociation;
    }

    [mp.Table(Name = "[SYSUCUSERSOVERRIDES]")]
    public class UserOverride
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _id;
        private int _userId;
        private string _domainUserName;
        private string _overrideType;       //view or access
        private string _overrideName;
        private string _method;
        private string _methodType;
        private string _methodLevel;

        [mp.Column(Name = "ID")]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "UserId", IsPrimaryKey = true)]
        public int UserId
        {
            get { return _userId; }
            set { _userId = value; }
        }

        [mp.Column(Name = "DomainUserName")]
        public string DomainUserName
        {
            get { return _domainUserName; }
            set { _domainUserName = value; }
        }

        [mp.Column(Name = "OverrideType", IsPrimaryKey = true)]
        public string OverrideType
        {
            get { return _overrideType; }
            set { _overrideType = value; }
        }

        [mp.Column(Name = "OverrideName", IsPrimaryKey = true)]
        public string OverrideName
        {
            get { return _overrideName; }
            set { _overrideName = value; }
        }

        public UserOverride()
        {
        }

        //Get distinct for users management section
        public UserOverride(string overrideType, string overrideName)
        {
            this._overrideType = overrideType;
            this._overrideName = overrideName;
        }

        public UserOverride(int id, string domainUserName, string overrideType, string overrideName)
        {
            this._id = id;
            this._domainUserName = domainUserName;
            this._overrideType = overrideType;
            this._overrideName = overrideName;
        }
    }

    public class UserOverrideDataContext : lq.DataContext
    {
        public UserOverrideDataContext(string cs) 
            : base(cs)
        {
        }

        public UserOverrideDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<UserOverride> UserOverride;
    }
}
