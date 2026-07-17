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
using System.Collections.ObjectModel;
using dc = PM_Project_Tracking.DataClasses;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhShipAdjust.xaml
    /// </summary>
    public partial class WhShipAdjust : Window
    {
        ObservableCollection<StringValue> _memoList;
        DeferredAction _memoDa;
        ObservableCollection<dc.ShippingLine> _shipLines;
        lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);

        public class StringValue
        {
            public StringValue(string s)
            {
                _value = s;
            }
            public string SingleValue { get { return _value; } set { _value = value; } }
            string _value;
        }

        public WhShipAdjust()
        {
            InitializeComponent();
            TBLCK_SeletedItem.TextWrapping = TextWrapping.WrapWithOverflow;
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            _memoList = new ObservableCollection<StringValue>( dtCtx.GetTable<dc.ShippingHeader>().Select(x => new StringValue(x.MemoNumber.ToString())).ToList() );
            DG_MemoNumList.ItemsSource = _memoList;
            CollectionViewSource.GetDefaultView(DG_MemoNumList.ItemsSource).Filter = MemoItemFilter;
        }

        private void TB_MemoNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._memoDa == null)
            {
                this._memoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MemoNumList.ItemsSource).Refresh());
            }
            this._memoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void DG_MemoNumList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_MemoNumList.SelectedIndex != -1)
            {
                StringValue _selCp = (StringValue)DG_MemoNumList.SelectedItem;
                try
                {
                    _shipLines = dc.WhShippingLines.GetWhShippingLinesByMemoNum(Convert.ToInt32(_selCp.SingleValue));
                    DG_ShipLineList.ItemsSource = _shipLines;
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
            }
        }

        private void DG_ShipLineList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_ShipLineList.SelectedIndex != -1)
            {
                dc.ShippingLine _selLine = (dc.ShippingLine)DG_ShipLineList.SelectedItem;
                TBLCK_SeletedItem.Text = _selLine.ItemDescription;
                LBL_OriginalQuantity.Content = _selLine.QuantityShipped;
            }
        }

        private void BTN_CommitChanges_Click(object sender, RoutedEventArgs e)
        {
            TBLCK_SeletedItem.Text = "";

        }

        private bool MemoItemFilter(object memonum)
        {
            var _memoObject = (StringValue)memonum;
            return _memoObject.SingleValue.IndexOf(TB_MemoNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private void Button_Click(object sender, RoutedEventArgs e)
        {
            dc.ShippingLine _selShLine = (dc.ShippingLine)((Button)e.Source).DataContext;
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<uc.RecLineTracker> _delDrawDowns = dtCtx.GetTable<uc.RecLineTracker>().Where(x => x.MemoNumber == _selShLine.MemoNumber 
                                                                                                && x.PoNumber == _selShLine.PoNumber
                                                                                                && x.Polnenum == _selShLine.Polnenum).ToList();

            try
            {
                foreach (uc.RecLineTracker rlt in _delDrawDowns)
                {
                    dc.ReceivingLine _matchedRl = dtCtx.GetTable<dc.ReceivingLine>().Where(x => x.PoNumber == rlt.PoNumber
                                                                                            && x.Polnenum == rlt.Polnenum
                                                                                            && x.PopRctNum == rlt.PopRctNum
                                                                                            && x.RcptLnNm == rlt.RcptLnNm).FirstOrDefault();
                    _matchedRl.QtyRemainingOnRec += rlt.QuantityDrawn;
                    dc.WhReceivingLines.UpdateReceivingLine(_matchedRl);
                    uc.RecLineTrackers.DeleteRecLines(rlt);
                    dc.ShippingLineDataContext slDtCtx = new dc.ShippingLineDataContext(GlobalVars.UcshConnectionString);
                    slDtCtx.Log = Console.Out;
                    slDtCtx.ShippingLine.Attach(_selShLine, _selShLine);
                    slDtCtx.ShippingLine.DeleteOnSubmit(_selShLine);
                    slDtCtx.SubmitChanges();
                    slDtCtx.Dispose();
                    _shipLines.Clear();
                }
            }
            catch(Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            dtCtx.Dispose();
        }
    }
}
