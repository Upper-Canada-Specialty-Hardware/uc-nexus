using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using lq = System.Data.Linq;
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
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhRetrievePo.xaml
    /// </summary>
    public partial class WhRecSelectPo : Window
    {
        bool _excludeComplete = false;
        private ObservableCollection<dc.PurchaseOrderHeader> _poCol = null;
        private ObservableCollection<dc.ReceivingLine> _whRecLineCol = null;
        private DataGrid _dg = null;
        DeferredAction _wrDa = null;
        dc.PurchaseOrderHeader _selPo;
        private bool _deficiencyCheck = false;

        public WhRecSelectPo(ObservableCollection<dc.ReceivingLine> whRecLineCol, DataGrid dg, bool excludeComplete)
        {
            InitializeComponent();
            _dg = dg;
            _whRecLineCol = whRecLineCol;
            _excludeComplete = excludeComplete;
            _poCol = dc.PurchaseOrderHeaders.GetPoHeaders();
            DG_PoHeaderList.ItemsSource = _poCol;
            CollectionViewSource.GetDefaultView(DG_PoHeaderList.ItemsSource).Filter = WhRetrieverItemFilter;
            TB_PoSearch.Focus();
        }

        private void TB_PoSearch_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._wrDa == null)
            {
                this._wrDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_PoHeaderList.ItemsSource).Refresh());
            }
            this._wrDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void DG_PoHeaderList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_PoHeaderList.SelectedIndex != -1)
            {
                _selPo = (dc.PurchaseOrderHeader)DG_PoHeaderList.SelectedItem; 
                try
                {
                    ObservableCollection<dc.ReceivingLine> tempRl = dc.WhReceivingLines.GetPoReceivingLineItemsByPoNum(_selPo.PoNumber, _excludeComplete);
                    _whRecLineCol.Clear();
                    foreach (dc.ReceivingLine rl in tempRl)
                    {
                        _whRecLineCol.Add(rl);
                    }
                    _dg.ItemsSource = _whRecLineCol;
                    _dg.Items.Refresh();
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
            }
            this.Close();
        }

        private bool WhRetrieverItemFilter(object po)
        {
            var _poHeaderObject = (dc.PurchaseOrderHeader)po;
            return (_poHeaderObject.PoNumber.IndexOf(TB_PoSearch.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }
        public bool DeficiencyCheck
        {
            get
            {
                return _deficiencyCheck;
            }

            set
            {
                _deficiencyCheck = value;
            }
        }

        private void Window_Closed(object sender, EventArgs e)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));

            if (_poCol != null && _selPo != null)
                _deficiencyCheck = dtCtx.GetTable<dc.WhDeficiency>().Where(x => x.PoNumber == _selPo.PoNumber && x.Completed == false).Count() > 0;
        }
    }

    internal class DoNotShipConverter : IValueConverter
    {
    public object Convert(object DoNotShipDate, Type targetType, object parameter, System.Globalization.CultureInfo culture)
    {
        if (DoNotShipDate == null)
        {
            //return Brushes.Gold;
            return (SolidColorBrush)new BrushConverter().ConvertFrom("#FF575555");
        }
        else if (((DateTime)DoNotShipDate) > DateTime.Today)
        {
            return Brushes.Tomato;
        }
        else
            return (SolidColorBrush)new BrushConverter().ConvertFrom("#FF575555");

        }
    public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
    {
        throw new NotSupportedException();
    }

    }
}
