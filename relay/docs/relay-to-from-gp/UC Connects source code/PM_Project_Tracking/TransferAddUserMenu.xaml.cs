using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Data.SqlClient;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using dc = PM_Project_Tracking.DataClasses;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for TransferAddUserMenu.xaml
    /// </summary>
    public partial class TransferAddUserMenu : Window
    {
        DataGrid _dg = null;
        ObservableCollection<dc.User> _userObCol = null;

        public TransferAddUserMenu()
        {
            InitializeComponent();
        }

        public TransferAddUserMenu(DataGrid dg, ObservableCollection<dc.User> userObCol)
        {
            InitializeComponent();
            _dg = dg;
            _userObCol = userObCol;
        }

        private void BTN_AddUser_Click(object sender, RoutedEventArgs e)
        {
            dc.User _newUser = new dc.User();
            _newUser.DomainUserName = TB_DomainUserName.Text.Trim();
            _newUser.Email = TB_UserEmail.Text.Trim();
            //_newUser.CompanyId = 1;
            _newUser.IsActive = true;

            if (_userObCol.Where(x => x.DomainUserName == _newUser.DomainUserName).Count() > 0)
            {
                MessageBox.Show("User with the name '" + _newUser.DomainUserName + "' already exists in the database.");
                return;
            }
            if (_newUser.DomainUserName == "" || CBox_PermissionTier.SelectedIndex == -1)
            {
                MessageBox.Show("Must have both a username and a permission tier selected.");
                return;
            }

            if (CBox_PermissionTier.SelectedIndex == 0)
            {
                _newUser.PermissionTier = 2;
                _newUser.TierName = "Administrator";
            }
            else if (CBox_PermissionTier.SelectedIndex == 1)
            {
                _newUser.PermissionTier = 3;
                _newUser.TierName = "Curator";
            }
            else if (CBox_PermissionTier.SelectedIndex == 2)
            {
                _newUser.PermissionTier = 4;
                _newUser.TierName = "Project Manager";
            }
            else if (CBox_PermissionTier.SelectedIndex == 3)
            {
                _newUser.PermissionTier = 5;
                _newUser.TierName = "Project Coordinator";
            }
            else if (CBox_PermissionTier.SelectedIndex == 4)
            {
                _newUser.PermissionTier = 6;
                _newUser.TierName = "Hardware Coordinator";
            }
            else
            {
                _newUser.PermissionTier = 7;
                _newUser.TierName = "Undefined";
            }

            if(CBox_CompanyId.SelectedIndex == 0)
            {
                //UCSH
                _newUser.CompanyId = 1;
            }
            else if(CBox_CompanyId.SelectedIndex == 0)
            {
                //UCSH BC
                _newUser.CompanyId = 2;
            }

                try
            {
                _newUser.Id = dc.Users.GetMaxUserId(_newUser);
                if (_newUser.Id == 0)
                    throw new Exception("Request for next user ID number returned DBNull.  It is likely the users database has no entries in it.");
            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
                this.Close();
                return;
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                this.Close();
                return;
            }

            dc.Users.AddUser(_newUser);
            _userObCol = dc.Users.GetUsers();
            _dg.ItemsSource = _userObCol;
            _dg.Items.Refresh();
            this.Close();
        }
    }
}
