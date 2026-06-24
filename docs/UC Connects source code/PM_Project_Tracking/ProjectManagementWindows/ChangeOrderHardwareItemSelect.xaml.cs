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
using pm = PM_Project_Tracking.ProjectManagementClasses;

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>
    /// Interaction logic for ChangeOrderHardwareItemSelect.xaml
    /// </summary>
    public partial class ChangeOrderHardwareItemSelect : Window
    {
        ObservableCollection<dc.HardwareSchedule> _jobHardwareList = null;
        ObservableCollection<dc.AVA_FUSION_FileList> _avaJobList = null;
        pm.ChangeLine _cline = null;
        DeferredAction _hwDa;
        public bool CanOpen { get; set; } = false;

        public ChangeOrderHardwareItemSelect()
        {
            InitializeComponent();
        }

        public ChangeOrderHardwareItemSelect(ref pm.ChangeLine cLine)
        {
            InitializeComponent();
            _cline = cLine;
            _avaJobList = dc.Hardware.GetHWSchedJobId(cLine.JobNumber); // dc.Hardware.GetHWSchedJobId(cLine.JobNumber);
            if (_avaJobList == null || _avaJobList.Count == 0)
            {
                MessageBox.Show("No hardware in SQL Server for this job number.");
                this.Close();
            }
            else if (_avaJobList.Count > 1)
            {
                MessageBox.Show("Returned more than one ID for this job number.");
                this.Close();
            }
            else if (_avaJobList.Count == 1)
            {
                _jobHardwareList = dc.Hardware.GetHardwareSchedule(_avaJobList[0].Id);
                DG_HardwareItemList.ItemsSource = _jobHardwareList;
                CollectionViewSource.GetDefaultView(DG_HardwareItemList.ItemsSource).Filter = HWItemFilter;
                this.CanOpen = true;
            }
            //MessageBox.Show("Sample hardware from TD Generator room project - 21123");
        }

        private void DG_HardwareItemList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_HardwareItemList.SelectedIndex != -1)
            {
                dc.HardwareSchedule _selHwLine = (dc.HardwareSchedule)DG_HardwareItemList.SelectedItem;
                _cline.LineDescription = _selHwLine.ProductHash;
                _cline.SellPrice = Convert.ToDecimal(_selHwLine.PriceBasis);
                _cline.CostUcsh = Convert.ToDecimal(_selHwLine.OpeningCost);
                _cline.Quantity = 1;
                _cline.AvaProductId = _selHwLine.ProductId;
                _cline.AvaImportDate = _selHwLine.ImportDate;
                _cline.AvaImportTime = _selHwLine.ImportTime;
                this.Close();
            }
        }

        private void TB_SearchItemDescription_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwDa == null)
            {
                this._hwDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_HardwareItemList.ItemsSource).Refresh());
            }
            this._hwDa.Defer(new TimeSpan(0, 0, 0, 0, 100));
        }

        private bool HWItemFilter(object hw)
        {
            var _hwLine = (dc.HardwareSchedule)hw;
            return (_hwLine.ProductHash.IndexOf(TB_SearchItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0);       
        }

    }
}
