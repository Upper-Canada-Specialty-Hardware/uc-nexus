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
    /// Interaction logic for TransferTenderMenu.xaml
    /// </summary>
    public partial class TransferTenderMenu : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        bool _inProgress = false;
        ObservableCollection<dc.OfferToTender> _ottProjObCol = null;

        public TransferTenderMenu()
        {
            InitializeComponent();
        }

        public TransferTenderMenu(MainWindow mw, DataGrid dg, ObservableCollection<dc.OfferToTender> ottProjObCol)
        {
            InitializeComponent();
            //how in the fuck does this work; _ottProjObCol gets loaded in "LoadProjects()" and then re-assigned 3 lines later at "_ottProjObCol = ottProjObCol;"
            LoadProjects();
            _mw = mw;
            _dg = dg;
            //_ottProjObCol = ottProjObCol;
        }

        private void LoadProjects()
        {
            _ottProjObCol = dc.UtilityMethods.EligibleTenderRetrieval.GetEligibleTenders();
            DG_TenderProjList.ItemsSource = _ottProjObCol;
        }

        private void DG_TenderProjList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_TenderProjList.SelectedIndex != -1 && _inProgress == false)
            {
                dc.OfferToTender _ottProj = (dc.OfferToTender)DG_TenderProjList.SelectedItem;

                if (MessageBox.Show("Do you want to transfer project " + _ottProj.JobName.Trim() + "?",
                    "Question", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.No)
                {
                    //Want to transfer yes/no?
                    _inProgress = true;
                    dc.OfferToTenders.UpdateSingleOfferToTender(_ottProj);
                    dc.BidProject _bidContr = new dc.BidProject() { JobName = _ottProj.JobName, Consultant = _ottProj.Consultant };
                    //_bidContr.Id = dc.BidProjects.GetNextBidProjectId();
                    dc.BidProjects.AddBidProject(_bidContr);
                    //dc.OfferToTenders.DeleteOfferToTender(_ottProj);
                    LoadProjects();
                    _mw.RefreshOfferToTenders();
                    _mw.RefreshBidProjects();
                    _inProgress = false;
                }
            }
            // Refresh pre projects datagrid?
            _dg.Items.Refresh();
        }
    }
}
