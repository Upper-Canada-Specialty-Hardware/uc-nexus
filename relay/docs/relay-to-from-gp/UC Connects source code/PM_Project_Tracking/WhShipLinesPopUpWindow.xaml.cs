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
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhRecSelectPoLines.xaml
    /// </summary>
    public partial class WhShipLinesPopUpWindow : Window
    {
        private readonly bool _ISREADONLY;
        dc.ShippingHeader _shipHead = null;
        dc.ShippingHeader _shipHeadClone = null;
        ObservableCollection<dc.ShippingLine> _shipLineCol = null;
        DeferredAction _wsDa = null;

        public WhShipLinesPopUpWindow()
        {
            InitializeComponent();
        }

        public WhShipLinesPopUpWindow(ref dc.ShippingHeader shipHead, bool rdonly)
        {
            InitializeComponent();
            _ISREADONLY = rdonly;

            _shipHeadClone = uc.CloneClass.Clone<dc.ShippingHeader>(shipHead);
            _shipHeadClone.AssignForeignShippingHeader(ref shipHead);
            _shipLineCol = dc.WhShippingLines.GetWhShippingLinesByMemoNum(shipHead.MemoNumber);
            DG_ShipLineList.ItemsSource = _shipLineCol;
            if (shipHead.HeaderType == 1)
            {
                StckPan_Warehouse_Shipping_CustProperties.Visibility = System.Windows.Visibility.Hidden;
                StckPan_Warehouse_Shipping_JobProperties.Visibility = System.Windows.Visibility.Visible;
                StckPan_Warehouse_Shipping_JobProperties.DataContext = _shipHeadClone;
            }
            else
            {
                StckPan_Warehouse_Shipping_CustProperties.Visibility = System.Windows.Visibility.Visible;
                StckPan_Warehouse_Shipping_JobProperties.Visibility = System.Windows.Visibility.Hidden;
                StckPan_Warehouse_Shipping_CustProperties.DataContext = _shipHeadClone;
            }
        }

        private void TB_PoNumberSearch_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._wsDa == null)
            {
                this._wsDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ShipLineList.ItemsSource).Refresh());
            }
            this._wsDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }
            
        private void DG_PoList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_ShipLineList.SelectedIndex != -1)
            {
                dc.PurchaseOrderLineItem _selPoLine = (dc.PurchaseOrderLineItem)DG_ShipLineList.SelectedItem;
                try
                {
                    dc.ShippingLine _addShipLine = new dc.ShippingLine(_selPoLine);
                    _shipLineCol.Add(_addShipLine);
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }
            }
        }

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            
            if (_ISREADONLY == false && _shipHeadClone.IsModified) //if ((_ISREADONLY == false && _modifiedOrNewChangeLines) || (_ISREADONLY == false && _newApproved))
            {
                if (MessageBox.Show("Would you like to save the changes made to this shipment header?", "Prompt",
                                    MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                {
                    //yes and window closing event resumes
                    dc.WhShippingHeaders.UpdateShippingHeader(_shipHeadClone);
                    dc.ShipHeaderSessions.DeleteSession(_shipHeadClone.JobNumber, _shipHeadClone.MemoNumber);
                    _shipHeadClone.ApplyDeferredShipHeadChanges();

                    return;
                }
                else
                {
                    //User answers 'no' and the window closes without saving
                    dc.ShipHeaderSessions.DeleteSession(_shipHeadClone.JobNumber, _shipHeadClone.MemoNumber);
                    return;
                }
            }

            dc.ShipHeaderSessions.DeleteSession(_shipHeadClone.JobNumber, _shipHeadClone.MemoNumber);
        }
    }
}
