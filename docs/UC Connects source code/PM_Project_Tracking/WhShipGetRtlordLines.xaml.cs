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
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhShippingRetRtlordLines.xaml
    /// </summary>
    public partial class WhShipGetRtlordLines : Window
    {
        //ObservableCollection<dc.ReceivingLine> _rlLineList = null;
        ObservableCollection<dc.ShippingLine> _shipLineCol = null;
        internal uc.ReceiptLineRackQuantityTracker _whShipRlDataTrack = null;
        DeferredAction _wsDa = null;

        public WhShipGetRtlordLines()
        {
            InitializeComponent();
        }

        public WhShipGetRtlordLines(ObservableCollection<dc.ShippingLine> shipLineCol, ref ObservableCollection<dc.ReceivingLine> rlLineList, ref uc.ReceiptLineRackQuantityTracker whShipRlDataTrack)
        {
            InitializeComponent();
            _shipLineCol = shipLineCol;
            //_rlLineList = dc.WH_ShippingLines.GetReceivingLinesByProject(jobNumber);
            DG_PoList.ItemsSource = rlLineList;
            _whShipRlDataTrack = whShipRlDataTrack;

            //http://stackoverflow.com/questions/32984669/wpf-datagrid-grouping-by-two-columns-layout
            CollectionView cv = (CollectionView)CollectionViewSource.GetDefaultView(DG_PoList.ItemsSource);
            cv.GroupDescriptions.Clear();
            PropertyGroupDescription pgd = new PropertyGroupDescription("PoNumber");
            cv.GroupDescriptions.Add(pgd);
            pgd = new PropertyGroupDescription("Polnenum");
            cv.GroupDescriptions.Add(pgd);

            CollectionViewSource.GetDefaultView(DG_PoList.ItemsSource).Filter = WhShipGetRecLineFilter;
            TB_PoNumberSearch.Focus();
        }


        private void TB_PoNumberSearch_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._wsDa == null)
            {
                this._wsDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_PoList.ItemsSource).Refresh());
            }
            this._wsDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void TB_VendorNameSearch_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._wsDa == null)
            {
                this._wsDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_PoList.ItemsSource).Refresh());
            }
            this._wsDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void AddShipmentQuantities(dc.ReceivingLine rl, int quant)
        {
            bool _found = false;
            foreach (dc.ShippingLine sl in _shipLineCol)
            {
                if ((rl.PoNumber == sl.PoNumber) && (rl.Polnenum == sl.Polnenum))
                {
                    _found = true;
                    sl.QuantityShipped += quant;
                    rl.QtyRemainingOnRec = rl.QtyRemainingOnRec - quant;
                    _whShipRlDataTrack.Add(new uc.RecLineTracker(rl, quant));
                }
            }
            if (!_found)
            {
                dc.ShippingLine _newSl = new dc.ShippingLine(rl, quant);
                rl.QtyRemainingOnRec = rl.QtyRemainingOnRec - quant;
                _whShipRlDataTrack.Add(new uc.RecLineTracker(rl, quant));
                _shipLineCol.Add(_newSl);
            }
        }

        private bool WhShipGetRecLineFilter(object rl)
        {
            var _recLineObject = (dc.ReceivingLine)rl;
            return (_recLineObject.PoNumber.IndexOf(TB_PoNumberSearch.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _recLineObject.VendorName.IndexOf(TB_VendorNameSearch.Text, StringComparison.OrdinalIgnoreCase) >= 0
                // add other criteria still - hardware description
                    );
        }

        private void DataGridCell_PreviewMouseLeftButtonDownShipRec(object sender, MouseButtonEventArgs e)
        {
            DataGridCell cell = sender as DataGridCell;

            if (cell != null && !cell.IsEditing && !cell.IsReadOnly)
            {
                if (!cell.IsFocused)
                {
                    cell.Focus();
                }
                DataGrid dataGrid = FindVisualParent<DataGrid>(cell);
                if (dataGrid != null)
                {
                    if (dataGrid.SelectionUnit != DataGridSelectionUnit.FullRow)
                    {
                        if (!cell.IsSelected)
                            cell.IsSelected = true;
                    }
                    else
                    {
                        DataGridRow row = FindVisualParent<DataGridRow>(cell);
                        if (row != null && !row.IsSelected)
                        {
                            if (cell.Column.DisplayIndex == 11)
                            {
                                if (MessageBox.Show("Would you like to transfer this amount?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ReceivingLine _selItem = (dc.ReceivingLine)row.Item;
                                    int _quant = _selItem.UiQuantityToTransfer;
                                    if (_quant > _selItem.QtyRemainingOnRec)
                                    {
                                        MessageBox.Show("You can't draw down a greater quantity than is remaining on the rack for this receipt.");
                                        return;
                                    }
                                    AddShipmentQuantities(_selItem, _quant);
                                    DG_PoList.CancelEdit();
                                    DG_PoList.Items.Refresh();
                                    //TextBlock x = DG_PoList.Columns[9].GetCellContent(DG_PoList.Items[2]) as TextBlock;
                                }
                                DG_PoList.Items.Refresh();
                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 11)
                            {
                                if (MessageBox.Show("Would you like to transfer this amount?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ReceivingLine _selItem = (dc.ReceivingLine)row.Item;
                                    int _quant = _selItem.UiQuantityToTransfer;
                                    if (_quant > _selItem.QtyRemainingOnRec)
                                    {
                                        MessageBox.Show("You can't draw down a greater quantity than is remaining on the rack for this receipt.");
                                        return;
                                    }
                                    AddShipmentQuantities(_selItem, _quant);
                                    DG_PoList.CancelEdit();
                                    DG_PoList.Items.Refresh();
                                    //TextBlock x = DG_PoList.Columns[9].GetCellContent(DG_PoList.Items[2]) as TextBlock;
                                }
                            }
                        }
                    }
                }
            }
            //DG_PoList.Items.Refresh();
        }

        static T FindVisualParent<T>(UIElement element) where T : UIElement
        {
            UIElement parent = element;
            while (parent != null)
            {
                T correctlyTyped = parent as T;
                if (correctlyTyped != null)
                {
                    return correctlyTyped;
                }

                parent = VisualTreeHelper.GetParent(parent) as UIElement;
            }
            return null;
        }
    }
}
