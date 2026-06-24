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

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhShipAdjustYesNo.xaml
    /// </summary>
    public partial class WhShipAdjustYesNo : Window
    {
        public bool YesCancel { get; set; }

        public WhShipAdjustYesNo()
        {
            InitializeComponent();
        }

        public WhShipAdjustYesNo(MainWindow mw)
        {
            InitializeComponent();
        }

        private void BTN_Yes_Click(object sender, RoutedEventArgs e)
        {
            YesCancel = true;
            this.Close();
        }

        private void BTN_Cancel_Click(object sender, RoutedEventArgs e)
        {
            YesCancel = false;
            this.Close();
        }
    }
}
