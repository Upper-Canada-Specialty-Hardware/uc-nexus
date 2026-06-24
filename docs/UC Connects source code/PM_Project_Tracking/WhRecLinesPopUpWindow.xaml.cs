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
using dc = PM_Project_Tracking.DataClasses;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhRecLinesPopUpWindow.xaml
    /// </summary>
    public partial class WhRecLinesPopUpWindow : Window
    {
        dc.ReceivingLine _recLine = null;
        DataGrid _dg = null;

        public WhRecLinesPopUpWindow()
        {
            InitializeComponent();
        }

        public WhRecLinesPopUpWindow(DataGrid dg, ref dc.ReceivingLine recLine)
        {
            InitializeComponent();
            _recLine = recLine;
            _dg = dg;
            GD_RecLineProperties.DataContext = recLine;
        }

        private void Btn_CommitEdit_Click(object sender, RoutedEventArgs e)
        {
            Btn_CommitEdit.IsEnabled = false;
            bool _cont = dc.WhReceivingLines.UpdateReceivingLine(_recLine);
            if (_cont)
                MessageBox.Show("Receipt has been updated.");

            Btn_CommitEdit.IsEnabled = true;
        }

    }
}
