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
    /// Interaction logic for WhShipCustomerSelect.xaml
    /// </summary>
    public partial class WhShipSelCustomer : Window
    {
        MainWindow _mw = null;
        private ObservableCollection<dc.CustomerShipment> _cpCol = null;
        //private dc.ShippingHeader _selSh = null;
        private StackPanel _custSp = null;
        DeferredAction _wrDa = null;

        public WhShipSelCustomer()
        {
            InitializeComponent();
        }

        public WhShipSelCustomer(MainWindow mw, StackPanel custSp)
        {
            InitializeComponent();
            _mw = mw;
            _custSp = custSp;
            _cpCol = dc.WhShippingHeaders.GetCustomerHeaderByRtlOrder();
            DG_RtlOrdList.ItemsSource = _cpCol;
            CollectionViewSource.GetDefaultView(DG_RtlOrdList.ItemsSource).Filter = WhShipGetCustomerFilter;
            TB_RtlOrdSearch.Focus();
        }

        private void TB_RtlOrdSearch_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._wrDa == null)
            {
                this._wrDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_RtlOrdList.ItemsSource).Refresh());
            }
            this._wrDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void DG_RtlOrdList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_RtlOrdList.SelectedIndex != -1)
            {
                dc.CustomerShipment _selCp = (dc.CustomerShipment)DG_RtlOrdList.SelectedItem;
                try
                {
                    //https://blogs.msdn.microsoft.com/ericlippert/2010/02/11/chaining-simple-assignments-is-not-so-simple/
                    //_selSh = new dc.ShippingHeader(_selCp);
                    _mw._whShipHeader = new dc.ShippingHeader(_selCp);
                    _custSp.DataContext = _mw._whShipHeader;
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
            }
            this.Close();
        }

        private bool WhShipGetCustomerFilter(object po)
        {
            var _custObject = (dc.CustomerShipment)po;
            return (_custObject.SopNumber.IndexOf(TB_RtlOrdSearch.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }
    }
}
