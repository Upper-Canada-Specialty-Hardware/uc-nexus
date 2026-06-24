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

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>
    /// Interaction logic for ChangeOrderQuoteAheadWindow.xaml
    /// </summary>
    public partial class ChangeOrderQuoteAheadWindow : Window
    {
        public int QuoteStartNumber { get; set; } = -1;
        public bool ContinueBool { get; set; }

        public ChangeOrderQuoteAheadWindow()
        {
            InitializeComponent();
        }

        private void BTN_Accept_Click(object sender, RoutedEventArgs e)
        {
            int outInt;
            if (int.TryParse(TB_QuoteInteger.Text, out outInt))
            {
                ContinueBool = true;
                QuoteStartNumber = outInt;
            }

            if (ContinueBool && QuoteStartNumber > 2)
                QuoteStartNumber = outInt;
            else
            {
                MessageBox.Show("The number written into the quote box cannot be parsed as an integer or is less than 2. Please ensure that it is a regular, non-decimal number.");
                return;
            }

            this.Close();
        }

        private void BTN_Cancel_Click(object sender, RoutedEventArgs e)
        {
            this.Close();
        }

        private void Window_Closed(object sender, EventArgs e)
        {

        }
    }
}
