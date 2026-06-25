using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Data.SqlClient;
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

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for UsersChangeSessions.xaml
    /// </summary>
    public partial class UsersChangeSessions : Window
    {
        //ObservableCollection<pm.ChangeQuoteSession> _sessionCol = null;   
        public UsersChangeSessions()
        {
            InitializeComponent();
            DG_ChangeSessions.ItemsSource = pm.ChangeQuoteSessions.GetAllSessions();
        }

        private void DG_ChangeSessions_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_ChangeSessions.SelectedIndex != -1)
            {
                pm.ChangeQuoteSession _selSession = (pm.ChangeQuoteSession)DG_ChangeSessions.SelectedItem;
                pm.ChangeQuoteSessions.DeleteSession(_selSession.JobNumber, _selSession.QuoteNumber);
                MessageBox.Show("Change quote session for quote number " + _selSession.QuoteNumber + " of job number " + _selSession.JobNumber + " has been removed.");
            }
            DG_ChangeSessions.ItemsSource = pm.ChangeQuoteSessions.GetAllSessions();
        }
    }
}
