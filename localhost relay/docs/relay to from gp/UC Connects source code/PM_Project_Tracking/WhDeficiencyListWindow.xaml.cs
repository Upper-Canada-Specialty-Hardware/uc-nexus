using System;
using System.Collections.Generic;
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
using System.Collections.ObjectModel;
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using pmw = PM_Project_Tracking.ProjectManagementWindows;
using olc = PM_Project_Tracking.OutlookConverters;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhDeficiencyListWindow.xaml
    /// </summary>
    public partial class WhDeficiencyListWindow : Window
    {
        private string _poNumber;
        private dc.PurchaseOrderHeader _poHeader = null;
        private ObservableCollection<dc.WhDeficiency> _defList = null;
        private Label _mwDefLabel;

        public WhDeficiencyListWindow()
        {
            InitializeComponent();
        }

        public WhDeficiencyListWindow(dc.PurchaseOrderHeader poHeader, ref Label mwDefLabel)
        {
            InitializeComponent();
            _poHeader = poHeader;
            _defList = dc.WhDeficiencies.GetDeficienciesByPo(poHeader.PoNumber);
            DG_DeficiencyList.ItemsSource = _defList;
            _mwDefLabel = mwDefLabel;
        }

        private void BTN_CreateDeficienty_Click(object sender, RoutedEventArgs e)
        {
            dc.WhDeficiency _whDef = new dc.WhDeficiency(_poHeader);
            _whDef.UpdatingUser = Environment.UserName;
            _defList.Add(_whDef);
        }

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            List<dc.WhDeficiency> _newDefs = _defList.Where(x => x.IsNew == true).ToList();
            _newDefs.ForEach(delegate (dc.WhDeficiency x) { dc.WhDeficiencies.AddWhDeficiency(x); });
            _defList.Where(x => x.IsModified == true).ToList().ForEach(delegate (dc.WhDeficiency x) {dc.WhDeficiencies.UpdateWhDeficiency(x);});
            if (_defList.Where(x => x.Completed == false).Count() > 0)
                _mwDefLabel.Visibility = Visibility.Visible;
            else
                _mwDefLabel.Visibility = Visibility.Hidden;

            if (_newDefs.Count > 0)
            {
                OutlookConverters.OutlookGenerator<List<dc.WhDeficiency>> _defEmail = new OutlookConverters.OutlookGenerator<List<dc.WhDeficiency>>(_newDefs[0], _newDefs);
            }
        }
    }


}
