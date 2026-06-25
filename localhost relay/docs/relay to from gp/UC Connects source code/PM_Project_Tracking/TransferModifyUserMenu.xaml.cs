using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
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
    /// Interaction logic for TransferUserMenu.xaml
    /// </summary>
    public partial class TransferModifyUserMenu : Window
    {
        DataGrid _dg = null;
        ObservableCollection<dc.User> _userObCol = null;
        ObservableCollection<dc.UserRoleList> _userRoleObCol = null;
        ObservableCollection<dc.UserAssociation> _distinctUserAssocTypes = null; //Get the different associations used the database.  Instead of fully hardcoding in the list, use what's already in the db
        ObservableCollection<dc.UserAssociation> _projManagerList = null;
        ObservableCollection<dc.UserAssociation> _conultantList = null;
        ObservableCollection<string> _distinctOverrideTypes;
        ObservableCollection<dc.UserOverride> _distinctAccessList = null;
        ObservableCollection<dc.UserOverride> _distinctViewList = null;

        dc.User _selUser = null;

        public TransferModifyUserMenu()
        {
            InitializeComponent();
        }
        public TransferModifyUserMenu(DataGrid dg, dc.User _user, ObservableCollection<dc.User> userObCol)
        {
            InitializeComponent();
            _dg = dg;
            _selUser = _user;
            _userObCol = userObCol;
            _userRoleObCol = dc.Users.GetUserRoleList();
            _distinctUserAssocTypes = dc.Users.GetDistinctAssociationTypes();
            _projManagerList = dc.Users.GetDistinctGpManagers();
            _conultantList = dc.Users.GetDistinctGpConsultants();
            _distinctAccessList = dc.Users.GetDistinctOverrideAccess();
            _distinctViewList = dc.Users.GetDistinctOverrideViews();
            _distinctOverrideTypes = dc.Users.GetDistinctOverrideTypes();
            TB_DomainUserName.Text = _selUser.DomainUserName;
            ChkBox_IsActive.DataContext = _selUser;
            //ChkBox_IsActive.IsChecked = _selUser.IsActive;
            CBox_PermissionTier.SelectedIndex = (int)_selUser.PermissionTier - 2;
            TB_UserEmail.Text = _selUser.Email;
            TB_SecondaryRoles_ExistingUser.Text = _selUser.DomainUserName;
            TB_Associations_ExistingUser.Text = _selUser.DomainUserName;
            TB_Overrides_ExistingUser.Text = _selUser.DomainUserName;
            //Cbox_Associations_SelectExistingUser.ItemsSource = _userObCol;
            Cbox_SecondaryRoles_SelectUserRole.ItemsSource = _userRoleObCol;
            Cbox_Associations_SelectAssociationType.ItemsSource = _distinctUserAssocTypes;
            Cbox_Overrides_SelectOverrideType.ItemsSource = _distinctOverrideTypes;
        }

        private void BTN_ModifyUser_Click(object sender, RoutedEventArgs e)
        {
            _selUser.Email = TB_UserEmail.Text.Trim();
            _selUser.IsActive = (bool)ChkBox_IsActive.IsChecked;

            if (CBox_PermissionTier.SelectedIndex == 0)
            {
                _selUser.PermissionTier = 2;
                _selUser.TierName = "Administrator";
            }
            else if (CBox_PermissionTier.SelectedIndex == 1)
            {
                _selUser.PermissionTier = 3;
                _selUser.TierName = "Curator";
            }
            else if (CBox_PermissionTier.SelectedIndex == 2)
            {
                _selUser.PermissionTier = 4;
                _selUser.TierName = "Project Manager";
            }
            else if (CBox_PermissionTier.SelectedIndex == 3)
            {
                _selUser.PermissionTier = 5;
                _selUser.TierName = "Project Coordinator";
            }
            else if (CBox_PermissionTier.SelectedIndex == 4)
            {
                _selUser.PermissionTier = 6;
                _selUser.TierName = "Hardware Coordinator";
            }
            else if (CBox_PermissionTier.SelectedIndex == 5)
            {
                _selUser.PermissionTier = 7;
                _selUser.TierName = "Undefined";
            }

            dc.Users.UpdateUser(_selUser);
            _userObCol = dc.Users.GetUsers();
            _dg.ItemsSource = _userObCol;
            _dg.Items.Refresh();
            this.Close();
        }

        private void BTN_DeleteUser_Click(object sender, RoutedEventArgs e)
        {
            if (MessageBox.Show("Do you want to delete user " + _selUser.DomainUserName + "?",
                "Question", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.No)
            {
                dc.Users.DeleteUser(_selUser);
                _userObCol = dc.Users.GetUsers();
                _dg.ItemsSource = _userObCol;
                _dg.Items.Refresh();
                this.Close();
            }

        }

        #region secondary roles


        private void BTN_SecondaryRoles_SecondaryRole_Click(object sender, RoutedEventArgs e)
        {
            if (Cbox_SecondaryRoles_SelectUserRole.SelectedIndex != -1)
            {
                dc.UserRoleList _selRoleList = (dc.UserRoleList)Cbox_SecondaryRoles_SelectUserRole.SelectedItem;
                dc.UserRole _newRole = new dc.UserRole() { UserId = _selUser.Id, DomainUserName = _selUser.DomainUserName, RoleId = _selRoleList.RoleId, RoleName = _selRoleList.RoleName, Email = _selUser.Email };
                dc.Users.AddUserSecondaryRole(_newRole);
            }
        }

        #endregion

        #region associations

        private void Cbox_Associations_SelectAssociationType_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (Cbox_Associations_SelectAssociationType.SelectedIndex != -1)
            {//if ever there are more than two types of association (PM and consultant) this code block will have to change to a switch/case or something else
                dc.UserAssociation _selAssoc = (dc.UserAssociation)Cbox_Associations_SelectAssociationType.SelectedItem;
                if (_selAssoc.AssociationType == 1)
                    Cbox_Associations_SelectUserToAssociate.ItemsSource = _projManagerList;
                else
                    Cbox_Associations_SelectUserToAssociate.ItemsSource = _conultantList;
            }
        }

        private void BTN_Associations_AddAssociation_Click(object sender, RoutedEventArgs e)
        {
            if (Cbox_Associations_SelectUserToAssociate.SelectedIndex != -1
                && Cbox_Associations_SelectAssociationType.SelectedIndex != -1)
            {
                try
                {
                    dc.UserAssociation _newAssoc = new dc.UserAssociation();
                    _newAssoc.UserId = _selUser.Id;
                    _newAssoc.DomainUserName = _selUser.DomainUserName;
                    _newAssoc.AssociationType = ((dc.UserAssociation)Cbox_Associations_SelectAssociationType.SelectedItem).AssociationType;
                    _newAssoc.AssociationValue = ((dc.UserAssociation)Cbox_Associations_SelectUserToAssociate.SelectedItem).AssociationValue;

                    dc.Users.AddNewUserAssociation(_newAssoc);
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }

            }
        }

        #endregion


        #region overrides

        private void Cbox_Overrides_SelectOverrideType_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (Cbox_Overrides_SelectOverrideType.SelectedIndex != -1)
            {//if ever there are more than two types of overridetype (view and access) this code block will have to change to a switch/case or something else
                string _selAssoc = (string)Cbox_Overrides_SelectOverrideType.SelectedValue;
                if (_selAssoc == "view")
                    Cbox_Overrides_SelectOverrideName.ItemsSource = _distinctViewList;
                else
                    Cbox_Overrides_SelectOverrideName.ItemsSource = _distinctAccessList;
            }
        }

        private void BTN_Overrides_AddOverride_Click(object sender, RoutedEventArgs e)
        {
            if (Cbox_Overrides_SelectOverrideType.SelectedIndex != -1
                && Cbox_Overrides_SelectOverrideName.SelectedIndex != -1)
            {
                dc.UserOverride _newOverride = new dc.UserOverride();
                _newOverride.UserId = _selUser.Id;
                _newOverride.DomainUserName = _selUser.DomainUserName;
                //Don't need to cast 'Cbox_Overrides_SelectOverrideType' because the collections the combobox is bound to seems to return string collections, not object collection
                _newOverride.OverrideType = (string)Cbox_Overrides_SelectOverrideType.SelectedItem;
                _newOverride.OverrideName = ((dc.UserOverride)Cbox_Overrides_SelectOverrideName.SelectedItem).OverrideName;

                dc.Users.AddNewUserOverride(_newOverride);
            }
        }

        #endregion

    }
}
