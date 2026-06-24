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
    /// Interaction logic for HmGetShopDrawByJobPopUp.xaml
    /// </summary>
    public partial class HmGetShopDrawByJobPopUp : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        ObservableCollection<dc.ShopDrawingLine> _hmJobList = null;
        bool _inProgress = false;
        DeferredAction _hmDa = null;

        public HmGetShopDrawByJobPopUp()
        {
            InitializeComponent();
        }

        public HmGetShopDrawByJobPopUp(MainWindow mw, DataGrid dg)
        {
            InitializeComponent();
            _mw = mw;
            _dg = dg;
            _hmJobList = dc.HollowMetal.GetShopDrawingJobsList();
            DG_JobsList.ItemsSource = _hmJobList;
            CollectionViewSource.GetDefaultView(DG_JobsList.ItemsSource).Filter = JobListFilter;
            TB_JobNumberFilter.Focus();
        }

        private void TB_JobNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hmDa == null)
            {
                this._hmDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_JobsList.ItemsSource).Refresh());
            }
            this._hmDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void TB_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hmDa == null)
            {
                this._hmDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_JobsList.ItemsSource).Refresh());
            }
            this._hmDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void DG_JobsList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_JobsList.SelectedIndex != -1 && _inProgress == false)
            {
                dc.ShopDrawingLine _shopDrawProject = (dc.ShopDrawingLine)DG_JobsList.SelectedItem;

                _inProgress = true;
                ObservableCollection<dc.ShopDrawingLine> _detShopDraw = dc.HollowMetal.GetShopDrawing(_shopDrawProject.JobNumber);
                //_dg.ItemsSource = null;
                //_detShopDraw = new ObservableCollection<DataClasses.ShopDrawingLine>();
                _dg.ItemsSource = _detShopDraw;
                _dg.Items.Refresh();
                _inProgress = false;
            }
            // Refresh pre projects datagrid?
            //_dg.Items.Refresh();
        }

        private bool JobListFilter(object sd)
        {
            var _shopDrawLine = (dc.ShopDrawingLine)sd;
            return (_shopDrawLine.JobNumber.IndexOf(TB_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                     && _shopDrawLine.JobName.IndexOf(TB_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }
    }
}
