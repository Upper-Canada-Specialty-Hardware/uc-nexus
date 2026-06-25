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
    /// Interaction logic for OrderingSelectJobFramesTitan.xaml
    /// </summary>
    public partial class OrderingSelectJobFramesTitan : Window
    {
        MainWindow _mw = null;
        DataGrid _dg = null;
        //private ObservableCollection<KeyValuePair<string, string>> _jobList = null;

        private List<ti.Project> _projList = null;
        List<ti.Hardware> hardwareCollection = null;
        //private StackPanel _projSp = null;
        DeferredAction _wrDa = null;
        public OrderingSelectJobFramesTitan()
        {
            InitializeComponent();
        }
    }
}
