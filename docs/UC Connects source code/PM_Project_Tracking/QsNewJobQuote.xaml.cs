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
    /// Interaction logic for QsNewJobQuote.xaml
    /// </summary>
    public partial class QsNewJobQuote : Window
    {
        MainWindow _mw = null;
        private ObservableCollection<KeyValuePair<string, string>> _jobList = null;
        private ObservableCollection<dc.QuoteSummary> _jobQuotes = null;
        private dc.QuoteSummary _newQs;
        //private dc.ShippingHeader _selSh = null;
        private StackPanel _projSp = null;
        DeferredAction _wrDa = null;
        public QsNewJobQuote()
        {
            InitializeComponent();
        }

        public QsNewJobQuote(MainWindow mw)
        {
            InitializeComponent();
            _mw = mw;
            //
            _jobList = new ObservableCollection<KeyValuePair<string, string>>(dc.QuoteSummaries.GetEligibleJobList());
            DG_JobList.ItemsSource = _jobList;
            CollectionViewSource.GetDefaultView(DG_JobList.ItemsSource).Filter = WhShipGetProjectFilter;
            TB_JobNumberSearch.Focus();
        }

        private void DG_JobList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_JobList.SelectedIndex != -1)
            {
                KeyValuePair<string, string> _selKvp = (KeyValuePair<string, string>)DG_JobList.SelectedItem;
                this.NewQs = new dc.QuoteSummary(_selKvp);
            }
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
            var _jobObject = (KeyValuePair<string, string>)job;
            return (_jobObject.Key.IndexOf(TB_JobNumberSearch.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }

        public ObservableCollection<dc.QuoteSummary> QuoteList
        {
            get
            {
                return _jobQuotes;
            }

            set
            {
                _jobQuotes = value;
            }
        }

        public bool ReturnQuoteList { get; set; }

        public dc.QuoteSummary NewQs
        {
            get
            {
                return _newQs;
            }

            set
            {
                _newQs = value;
            }
        }
    }
}
