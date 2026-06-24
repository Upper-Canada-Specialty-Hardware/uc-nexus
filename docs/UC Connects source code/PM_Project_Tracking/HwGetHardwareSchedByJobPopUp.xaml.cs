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
    /// Interaction logic for HwGetHardwareSchedByJobPopUp.xaml
    /// </summary>
    public partial class HwGetHardwareSchedByJobPopUp : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        ObservableCollection<dc.AVA_FUSION_FileList> _hwJobList = null;
        private ObservableCollection<dc.HardwareSchedule> _hwSchedule;
        bool _inProgress = false;
        DeferredAction _hwDa = null;

        public ObservableCollection<dc.HardwareSchedule> HwSchedule
        {
            get
            {
                return _hwSchedule;
            }

            set
            {
                _hwSchedule = value;
            }
        }

        public HwGetHardwareSchedByJobPopUp()
        {
            InitializeComponent();
        }

        public HwGetHardwareSchedByJobPopUp(MainWindow mw, DataGrid dg)
        {
            InitializeComponent();
            _mw = mw;
            _dg = dg;
            _hwJobList = dc.Hardware.GetHWSchedJobsList();
            DG_JobsList.ItemsSource = _hwJobList;
            CollectionViewSource.GetDefaultView(DG_JobsList.ItemsSource).Filter = JobListFilter;
            TB_JobNumberFilter.Focus();
        }

        public HwGetHardwareSchedByJobPopUp(MainWindow mw, ref ObservableCollection<dc.HardwareSchedule> hws)
        {
            InitializeComponent();
            _mw = mw;
            HwSchedule = hws;
            _hwJobList = dc.Hardware.GetHWSchedJobsList();
            DG_JobsList.ItemsSource = _hwJobList;
            CollectionViewSource.GetDefaultView(DG_JobsList.ItemsSource).Filter = JobListFilter;
            TB_JobNumberFilter.Focus();
        }

        private void TB_JobNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwDa == null)
            {
                this._hwDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_JobsList.ItemsSource).Refresh());
            }
            this._hwDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void TB_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwDa == null)
            {
                this._hwDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_JobsList.ItemsSource).Refresh());
            }
            this._hwDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        //private void DG_JobsList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        //{
        //    if (DG_JobsList.SelectedIndex != -1 && _inProgress == false)
        //    {
        //        dc.AVA_FUSION_FileList _shopDrawProject = (dc.AVA_FUSION_FileList)DG_JobsList.SelectedItem;

        //        _inProgress = true;
        //        ObservableCollection<dc.HardwareSchedule> _detHardwareSchedule = dc.Hardware.GetHardwareSchedule(_shopDrawProject.Id);
        //        _dg.ItemsSource = _detHardwareSchedule;
        //        _dg.Items.Refresh();
        //        _inProgress = false;

        //    }
        //    // Refresh pre projects datagrid?
        //    //_dg.Items.Refresh();
        //}

        private void DG_JobsList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_JobsList.SelectedIndex != -1 && _inProgress == false)
            {
                dc.AVA_FUSION_FileList _shopDrawProject = (dc.AVA_FUSION_FileList)DG_JobsList.SelectedItem;

                _inProgress = true;
                HwSchedule = dc.Hardware.GetHardwareSchedule(_shopDrawProject.Id);
                //_dg.ItemsSource = _detHardwareSchedule;
                //_dg.Items.Refresh();
                _inProgress = false;
                _mw._hwSelectedJobNum = _shopDrawProject.Id;
            }
            // Refresh pre projects datagrid?
            //_dg.Items.Refresh();
            this.Close();
        }

        private bool JobListFilter(object fl)
        {
            var _avaFileListObject = (dc.AVA_FUSION_FileList)fl;
            return (_avaFileListObject.ProjectNumber.IndexOf(TB_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                     && _avaFileListObject.ProjectName.IndexOf(TB_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }
    }
}
