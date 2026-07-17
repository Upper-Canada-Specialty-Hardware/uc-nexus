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
    /// Interaction logic for OrderingHwByJobSelect.xaml
    /// </summary>
    public partial class OrderingHwByJobSelect : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        ObservableCollection<dc.AVA_FUSION_FileList> _avaFileList = new ObservableCollection<dc.AVA_FUSION_FileList>();
        ObservableCollection<dc.HardwareSchedule> _hwSched = new ObservableCollection<dc.HardwareSchedule>();
        bool _inProgress = false;

        public OrderingHwByJobSelect(MainWindow mw, DataGrid dg)
        {
            InitializeComponent();
            _mw = mw;
            _dg = dg;
            _avaFileList = dc.Hardware.GetHWSchedJobsList();
            DG_AvawareProjList.ItemsSource = _avaFileList;
        }

        public OrderingHwByJobSelect()
        {
        }

        private void DG_AvawareProjList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_AvawareProjList.SelectedIndex != -1 && _inProgress == false)
            {
                dc.AVA_FUSION_FileList _selProj = (dc.AVA_FUSION_FileList)DG_AvawareProjList.SelectedItem;

                if (MessageBox.Show("Do you want to transfer project " + _selProj.ProjectNumber.Trim() + "?",
                    "Question", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.No)
                {
                    //Want to transfer yes/no?
                    _inProgress = true;
                    dc.matListFunctionV2 objContext = null;
                    try
                    {
                        objContext = new dc.matListFunctionV2("Data Source=UCSHSQL2\\MSSQL2014; Initial Catalog=Avaware;Integrated Security=SSPI");
                        _hwSched = new ObservableCollection<dc.HardwareSchedule>(objContext.getMatListByProjectv2(_selProj.Id).ToList().OrderBy(x => x.OpeningNumber));
                        _dg.ItemsSource = _hwSched;
                        _mw.LBL_Ordering_Hardware_JobNumberJobName.Content = _selProj.ProjectNumber + " - " + _selProj.ProjectName;
                    }
                    catch (Exception ex)
                    {
                        MessageBox.Show(ex.ToString());
                        if (objContext != null)
                            objContext.Dispose();
                    }
                    finally
                    {
                        if (objContext != null)
                            objContext.Dispose();
                    }

                    _inProgress = false;
                }
            }
            // Refresh pre projects datagrid?
            _dg.Items.Refresh();
        }
    }
}
