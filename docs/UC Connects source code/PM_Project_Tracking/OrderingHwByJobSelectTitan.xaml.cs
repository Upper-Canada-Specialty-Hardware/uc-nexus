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
using ti = PM_Project_Tracking.DataClasses.TitanObjects;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for OrderingSelectJobHardwareTitan.xaml
    /// </summary>
    public partial class OrderingSelectJobHardwareTitan : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        //private ObservableCollection<KeyValuePair<string, string>> _jobList = null;

        private List<ti.Project> _projList = null;
        List<ti.Hardware> _hardwareCollection = null;
        List<ti.Frame> _frameCollection = null;
        List<ti.Door> _doorCollection = null;
        //private StackPanel _projSp = null;
        DeferredAction _wrDa = null;
        HdwDoorFrameSelect _selEnum;
        public OrderingSelectJobHardwareTitan()
        {
            InitializeComponent();
        }

        public OrderingSelectJobHardwareTitan(MainWindow mw, DataGrid dg, HdwDoorFrameSelect selEnum)
        {
            InitializeComponent();
            _mw = mw;
            _dg = dg;
            _selEnum = selEnum;
            GetProjects();
        }

        //Move the call to the asynchronous API get method to an asynchronous method and call it at the end of the ordering method
        private async void GetProjects()
        {
            _projList = await TitanApi.GetProjects.GetProjectsList();
            DG_JobList.ItemsSource = _projList;
            CollectionViewSource.GetDefaultView(DG_JobList.ItemsSource).Filter = WhShipGetProjectFilter;
            TB_JobNumberSearch.Focus();
        }

        private void DG_JobList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_JobList.SelectedIndex != -1)
            {
                ti.Project selProj = (ti.Project)DG_JobList.SelectedItem;
                if (_selEnum == HdwDoorFrameSelect.Hardware)
                    GetHardware(selProj);
                else if (_selEnum == HdwDoorFrameSelect.Frame)
                    GetFrames(selProj);
                else if (_selEnum == HdwDoorFrameSelect.Door)
                    GetDoors(selProj);
            }
        }

        private async void GetHardware(ti.Project proj)
        {
            _hardwareCollection = await TitanApi.GetHardwares.GetHardwaresList(proj.ProjectId);
            _mw.DG_Ordering_HardwareOrdering_SelectableHardwareList_Titan.ItemsSource = _hardwareCollection;
            this.Close();
        }

        private async void GetFrames(ti.Project proj)
        {
            _frameCollection = await TitanApi.GetFrames.GetFramesList(proj.ProjectId);
            _mw.DG_Ordering_FrameOrdering_SelectableFrameList_Titan.ItemsSource = _frameCollection;
            this.Close();
        }

        private async void GetDoors(ti.Project proj)
        {
            _doorCollection = await TitanApi.GetDoors.GetDoorsList(proj.ProjectId);
            _mw.DG_Ordering_DoorOrdering_SelectableDoorList_Titan.ItemsSource = _doorCollection;
            this.Close();
        }

        private void TB_JobNumberSearch_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._wrDa == null)
            {
                this._wrDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_JobList.ItemsSource).Refresh());
            }
            this._wrDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private bool WhShipGetProjectFilter(object job)
        {
            var _jobObject = (ti.Project)job;
            return ( _jobObject.ProjectId.ToString().IndexOf(TB_JobNumberSearch.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }

    }

    public enum HdwDoorFrameSelect
    {
        Hardware = 1,
        Frame,
        Door
    }
}
