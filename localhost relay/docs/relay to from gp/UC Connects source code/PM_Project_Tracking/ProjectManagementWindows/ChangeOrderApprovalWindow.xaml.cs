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
    /// Interaction logic for ChangeOrderApprovalWindow.xaml
    /// </summary>
    public partial class ChangeOrderApprovalWindow : Window
    {
        private bool _approve = false;

        public ChangeOrderApprovalWindow()
        {
            InitializeComponent();
        }

        public ChangeOrderApprovalWindow(string approvalNum)
        {
            InitializeComponent();
            this.TB_ApprovalNumber.Text = approvalNum;
        }

        public string TextBoxApprovalConf
        {
            get
            {
                return this.TB_ApprovalNumber.Text;
            }
        }

        public bool Approve
        {
            get
            {
                return this._approve;
            }
        }

        private void BTN_Accept_Click(object sender, RoutedEventArgs e)
        {
            if (MessageBox.Show("Once this quote is approved, it cannot be reversed.\r\n" + 
                                "YOUR QUOTE AS IT IS CURRENTLY WILL BE THE FINAL QUOTE.\r\n" +
                                "IF YOU ARE STILL EDITIING THIS QUOTE, DO NOT APPROVE IT YET AND PRESS 'NO'. " +
                                "Would you like to mark this quote as approved?", "Prompt",
            MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
            {
                this._approve = true;
                this.Close();
            }
            else
            {
                this.Close();
            }
        }

        private void BTN_Cancel_Click(object sender, RoutedEventArgs e)
        {
            this.Close();
        }
    }
}
