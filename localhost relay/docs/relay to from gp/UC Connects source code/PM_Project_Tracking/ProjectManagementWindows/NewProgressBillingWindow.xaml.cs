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
using pm = PM_Project_Tracking.ProjectManagementClasses;

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>
    /// Interaction logic for NewProgressBillingWindow.xaml
    /// </summary>
    public partial class NewProgressBillingWindow : Window
    {
        //public DateTime? BillDate {get; set;}
        //public string HstNumber {get; set;}
        //string ContractNumber {get; set;}
        pm.ProgressBillingHeader _pbHeader;
        public NewProgressBillingWindow()
        {
            InitializeComponent();
        }

        public NewProgressBillingWindow(ref pm.ProgressBillingHeader pbHeader)
        {
            InitializeComponent();
            _pbHeader = pbHeader;
            this.DataContext = _pbHeader;
        }

        private void TB_Accept_Click(object sender, RoutedEventArgs e)
        {
            DateTime? _selDate = DP_BillingDate.SelectedDate;
            
            if (_selDate != null)
            {
                var _dSpan = DateTime.Today - _selDate;
                if ((_dSpan > TimeSpan.FromDays(10)) | _dSpan < TimeSpan.FromDays(-10))
                {
                    MessageBox.Show("The progress billing creation date cannot be more or less than 10 days from the current date");
                }
                else if (_pbHeader.ContractNumber != "" && _pbHeader.HstNumber != "")
                {
                    _pbHeader.BillingName = "Client Breakdown " + _selDate.Value.ToString("dd") + "-" + _selDate.Value.ToString("MMM").ToUpper() + "-" + _selDate.Value.ToString("yyyy");
                    this.Close();
                }
            }
            else
            {
                if (_selDate == null)
                {
                    MessageBox.Show("No billing date has been selected.");
                    return;
                }
                else if (_pbHeader.ContractNumber == "" && _pbHeader.HstNumber == "")
                {
                    MessageBox.Show("Progress billing header must have both a contract number and HST number.");
                    return;
                }
            }
        }

    }
}
