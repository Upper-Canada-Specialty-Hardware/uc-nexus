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
    /// Interaction logic for WhShipProjectSelect.xaml
    /// </summary>
    public partial class WhShipSelProject : Window
    {
        MainWindow _mw = null;
        private ObservableCollection<dc.CombinedProject> _cpCol = null;
        //private dc.ShippingHeader _selSh = null;
        private StackPanel _projSp = null;
        DeferredAction _wrDa = null;

        public WhShipSelProject()
        {
            InitializeComponent();
        }

        public WhShipSelProject(MainWindow mw, StackPanel projSp)
        {
            InitializeComponent();
            _mw = mw;
            _projSp = projSp;
            _cpCol = dc.WhShippingHeaders.GetCombinedShipHeaderProject();
            DG_JobList.ItemsSource = _cpCol;
            CollectionViewSource.GetDefaultView(DG_JobList.ItemsSource).Filter = WhShipGetProjectFilter;
            TB_JobNumberSearch.Focus();
        }

        private void TB_JobNumberSearch_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._wrDa == null)
            {
                this._wrDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_JobList.ItemsSource).Refresh());
            }
            this._wrDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void DG_JobList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_JobList.SelectedIndex != -1)
            {
                dc.CombinedProject _selCp = (dc.CombinedProject)DG_JobList.SelectedItem;
                try
                {
                    _mw._whShipHeader = new dc.ShippingHeader(_selCp);
                    _projSp.DataContext = _mw._whShipHeader;
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
            }
            this.Close();
        }

        private bool WhShipGetProjectFilter(object po)
        {
            var _jobObject = (dc.CombinedProject)po;
            return (_jobObject.Jc00102.JobNumber.IndexOf(TB_JobNumberSearch.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }
    }
}
