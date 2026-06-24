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
    /// Interaction logic for TransferPursuitMenu.xaml
    /// </summary>
    public partial class TransferPursuitMenu : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        bool _inProgress = false;
        ObservableCollection<dc.Pursuit> _ptObCol = null;
        public TransferPursuitMenu()
        {
            InitializeComponent();
        }

        public TransferPursuitMenu(MainWindow mw, DataGrid dg, ObservableCollection<dc.Pursuit> ptObCol)
        {
            InitializeComponent();
            LoadProjects();
            _mw = mw;
            _dg = dg;
            //_ptObCol = ptObCol;
        }
    
        private void LoadProjects()
        {
            _ptObCol = dc.UtilityMethods.EligiblePursuitRetrieval.GetEligiblePursuits();
            DG_PursuitList.ItemsSource = _ptObCol;
        }

        private void DG_PursuitList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_PursuitList.SelectedIndex != -1 && _inProgress == false)
            {
                dc.Pursuit _selPursuit = (dc.Pursuit)DG_PursuitList.SelectedItem;

                if (MessageBox.Show("Do you want to transfer project " + _selPursuit.JobName.Trim() + "?",
                    "Question", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.No)
                {
                    //Want to transfer yes/no?
                    _inProgress = true;
                    dc.Pursuits.UpdateSinglePursuit(_selPursuit);    //CHANGE THE ACTUAL PROPERTY CHANGED HERE
                    dc.BidProject _bidProj = new dc.BidProject() {  JobNumber = _selPursuit.JobNumber, JobName = _selPursuit.JobName,
                                                                    ProjectStatus = _selPursuit.TenderPhase,
                                                                    Consultant = _selPursuit.HardwareSchedWriter, CustomerName = _selPursuit.Contractor,
                                                                    BidClosingDate = _selPursuit.BidClosingDate, BidClosingTime = _selPursuit.BidClosingTime,
                                                                    EstProjValue = _selPursuit.EstimatedProjectValue};
                    dc.BidProjects.AddBidProject(_bidProj);

                    
                    //Auto e-mail here
                    LoadProjects();
                    _mw.RefreshPursuits();
                    _mw.RefreshOfferToTenders();
                    _mw.RefreshBidProjects();
                    _inProgress = false;
                }
            }
        }
    }
}
