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
    /// Interaction logic for TransferProjectMenu.xaml
    /// </summary>
    public partial class TransferBidMenu : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        ObservableCollection<dc.BidProject> _bidProjObCol = null;
        dc.User _user = null;
        bool _inProgress = false;

        public TransferBidMenu()
        {
            InitializeComponent();
        }

        public TransferBidMenu(MainWindow mw, DataGrid dg, ObservableCollection<dc.BidProject> bidProjObCol, dc.User user)
        {
            InitializeComponent();
            LoadProjects();
            _mw = mw;
            _dg = dg;
            _user = user;
            _bidProjObCol = bidProjObCol;
        }

        private void LoadProjects()
        {
            _bidProjObCol = dc.UtilityMethods.EligibleProjectRetrieval.GetEligibleProjects();
            DG_EligibleProjList.ItemsSource = _bidProjObCol;
        }

        private void DG_EligibleProjList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_EligibleProjList.SelectedIndex != -1 && _inProgress == false)
            {
                dc.BidProject _bidProj = (dc.BidProject)DG_EligibleProjList.SelectedItem;

                if (MessageBox.Show("Do you want to transfer project " + _bidProj.JobName.Trim() + "?", 
                    "Question", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.No)
                {
                    //Want to transfer yes/no?
                    _inProgress = true;
                    //_bidProj.ProjectStatus = "AWARDED";
                    dc.BidProjects.UpdateSingleBidProject(_bidProj);
                    dc.BidProject _detBidProj = dc.UtilityMethods.TransferBidToAwContrMainProj.GetDetailedBidProject(_bidProj);
                    //_detBidProj.EstProjValue = 0;
                    if (_detBidProj.EstProjValue == 0)
                    {
                        MessageBox.Show("Cannot transfer a project with an estimated project value of 0.");
                        return;
                    }

                    if (_detBidProj != null)
                    {
                        dc.AwardedContract _awContr = new dc.AwardedContract()
                        {
                            JobNumber = _detBidProj.JobNumber,
                            JobName = _bidProj.JobName,
                            CustomerNumber = _detBidProj.CustomerNumber,
                            CustomerName = _detBidProj.CustomerName
                        };
                        dc.MainProject _mainProj = new dc.MainProject() { JobNumber = _bidProj.JobNumber };
                        //dc.BidProjects.DeleteBidProject(_bidProj);
                        dc.AwardedContracts.AddAwardedContract(_awContr);
                        dc.MainProjects.AddMainProject(_mainProj);
                    }
                    else { MessageBox.Show("Somehow no bid project was returned from method 'GetDetailedBidProject'"); }
                    LoadProjects();
                    _mw.SetModulesAccess(_user);
                    //_mw.RefreshDataGrids();
                    _inProgress = false;
                }
            }
            // Refresh pre projects datagrid?
            _dg.Items.Refresh();
        }
    }
}
