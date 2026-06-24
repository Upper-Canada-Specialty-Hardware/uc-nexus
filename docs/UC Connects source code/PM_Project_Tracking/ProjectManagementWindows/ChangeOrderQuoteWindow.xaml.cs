using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
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
using pmw = PM_Project_Tracking.ProjectManagementWindows;
using pmuc = PM_Project_Tracking.ProjectManagementClasses.ProjectManagementUtililtyClasses;

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>f
    /// Interaction logic for ChangeOrderQuoteWindow.xaml
    /// </summary>
    public partial class ChangeOrderQuoteWindow : Window
    {
        private readonly bool _ISREADONLY;
        private bool _newApproved;  //For use in the instance where a quote has been approved in a session. Needed where a user decides NOT to update quote lines, but the OH and profit
                                    //percentages need to updated in the server for the sake of continuity
        private ObservableCollection<pm.ChangeHeader> _changeHeaderCol;
        private string _jobNumber;
        private string _quoteNumber;
        private bool _appBeforeLoad = false;
        private bool _tentAppBeforeLoad = false;
        private decimal _headerMargin = 0;
        //private LabourValueContainer _labourContainer = new LabourValueContainer();
        pm.ChangeIndex _changeIndex = null;
        pm.ChangeHeader _changeHeader = null;
        //ObservableCollection<pm.ChangeLine> _changeLines = null;
        pmuc.PmItemsChangeObservableCollection.ItemsChangeObservableCollection<pm.ChangeLine> _changeLines = null;
        ListCollectionView _lineLevelView = null;
        ListCollectionView _sumLevelView = null;
        ListCollectionView _labourSumsView = null;
        pm.ChangeLine _changeLine = null;
        dc.User _curUser = null;
        

        public ChangeOrderQuoteWindow()
        {
            InitializeComponent();
        }

        public ChangeOrderQuoteWindow(ref pm.ChangeHeader changeHeader, ref pm.ChangeIndex changeIndex, bool rdonly, dc.User curUser, ref ObservableCollection<pm.ChangeHeader> changeHeaderCol)
        {
            InitializeComponent();
            _ISREADONLY = rdonly;
            _curUser = curUser;

            this._changeHeaderCol = changeHeaderCol;
            this._changeIndex = changeIndex;
            this._tentAppBeforeLoad = changeHeader.TentativeApproval;
            this._appBeforeLoad = changeHeader.Approved;

            this._changeHeader = changeHeader;
            this._jobNumber = changeHeader.JobNumber;
            this._quoteNumber = changeHeader.QuoteNumber;
            //_changeLines = pm.ChangeLines.GetChangeLinesByQuote(changeHeader.JobNumber, changeHeader.QuoteNumber);
            _changeLines = new pmuc.PmItemsChangeObservableCollection.ItemsChangeObservableCollection<pm.ChangeLine>( pm.ChangeLines.GetChangeLinesByQuote(changeHeader.JobNumber, changeHeader.QuoteNumber).ToList( ) );

            ChkBox_Approval.Unchecked -= ChkBox_Approval_Unchecked;
            ChkBox_Approval.Checked -= ChkBox_Approval_Checked;

            _changeHeader.ChangeLineItems = _changeLines;
            StckPan_HeaderInfo.DataContext = _changeHeader;

            //DG_ChangeOrderLines.ItemsSource = _changeLines;

            _lineLevelView = new ListCollectionView(_changeLines);
            _lineLevelView.GroupDescriptions.Add(new PropertyGroupDescription("CostCode"));
            DG_ChangeOrderLines.ItemsSource = _lineLevelView;

            _changeLine = new pm.ChangeLine(changeHeader.JobNumber, changeHeader.QuoteNumber);
            StckPan_AddChangeLine.DataContext = _changeLine;
            CBox_CostCode.DataContext = _changeLine;
            CBox_LabourType.Visibility = System.Windows.Visibility.Hidden;

            //Sums datagrid
            _sumLevelView = new ListCollectionView(_changeLines);
            _sumLevelView.GroupDescriptions.Add(new PropertyGroupDescription("CostCode"));
            DG_ChangeOrderSums.ItemsSource = _lineLevelView;

            //Labour datagrid
            _labourSumsView = new ListCollectionView(_changeLines);
            _labourSumsView.GroupDescriptions.Add(new PropertyGroupDescription("CostCode"));
            _labourSumsView.Filter = (e) =>
            {
                pm.ChangeLine cl = e as pm.ChangeLine;
                if (cl.IsLabour)
                    return true;
                return false;
            };
            DG_LabourSums.ItemsSource = _labourSumsView;

            if (_ISREADONLY)
            {
                TB_OverheadPercentage.IsReadOnly = true;
                TB_ProfitPercentage.IsReadOnly = true;
                TB_OverheadAmount.IsReadOnly = true;
                TB_ProfitAmount.IsReadOnly = true;
                TB_TotalCost.IsReadOnly = true;
                TB_Total.IsReadOnly = true;
                TB_SubTotal.IsReadOnly = true;
                TB_Margin.IsReadOnly = true;

                //DG_ChangeOrderLines.IsReadOnly = true;

                //DG_ChangeOrderLines_Billed.IsReadOnly = true;
                DG_ChangeOrderLines_CostCode.IsReadOnly = true;
                DG_ChangeOrderLines_CostCodeNumber.IsReadOnly = true;
                DG_ChangeOrderLines_Delete.IsReadOnly = true;
                DG_ChangeOrderLines_Description.IsReadOnly = true;
                DG_ChangeOrderLines_Discount.IsReadOnly = true;
                DG_ChangeOrderLines_ExtendedCost.IsReadOnly = true;
                DG_ChangeOrderLines_ExtendedPrice.IsReadOnly = true;
                DG_ChangeOrderLines_IsLabour.IsReadOnly = true;
                DG_ChangeOrderLines_LineCost.IsReadOnly = true;
                DG_ChangeOrderLines_ListMinusTwenty.IsReadOnly = true;
                DG_ChangeOrderLines_ListPrice.IsReadOnly = true;
                DG_ChangeOrderLines_Multiplier.IsReadOnly = true;
                DG_ChangeOrderLines_Quantity.IsReadOnly = true;
                DG_ChangeOrderLines_QuantityBilled.IsReadOnly = true;
                DG_ChangeOrderLines_Remarks.IsReadOnly = true;
                DG_ChangeOrderLines_SourceHardwareSched.IsReadOnly = true;

                BTN_AddChangeLine.IsEnabled = false;
                //BTN_UpdateServer.IsEnabled = false;
                BTN_AddHwFromSchedule.IsEnabled = false;
            }

            this.Title = changeHeader.QuoteNumber + " - " + changeIndex.JobNumber + " - " + changeIndex.JobName;

            //_changeLine = new pm.ChangeLine(jobNumber, quoteNumber);

            //http://stackoverflow.com/questions/32984669/wpf-datagrid-grouping-by-two-columns-layout

        }


        private void Window_Loaded(object sender, RoutedEventArgs e)
        {
            if (_changeHeader.Approved)
                ChkBox_Approval.IsChecked = true;

            ChkBox_Approval.Checked += ChkBox_Approval_Checked;
            ChkBox_Approval.Unchecked += ChkBox_Approval_Unchecked;
            //_changeLines.CollectionChanged += OnUpdateMargin;
            //UpdateMargin();
        }

        private void SubscribeUnsubscribeCheckboxes(string onOff)
        {
            if (onOff == "off")
            {
                ChkBox_Approval.Unchecked -= ChkBox_Approval_Unchecked;
                ChkBox_Approval.Checked -= ChkBox_Approval_Checked;
            }
            else if (onOff == "on") //A bit redundant, I know, but it's clearer than a simple 'else' with no condition
            {
                ChkBox_Approval.Checked += ChkBox_Approval_Checked;
                ChkBox_Approval.Unchecked += ChkBox_Approval_Unchecked;
            }
        }

        //private void OnUpdateMargin(object sender, System.Collections.Specialized.NotifyCollectionChangedEventArgs e)
        //{
        //    UpdateMargin();
        //}

        //private void UpdateMargin()
        //{
        //    decimal _totalRev = _changeLines.Sum(x => x.ExtendedSellPrice);
        //    decimal _totalCost = _changeLines.Sum(x => x.TotalLineCostUcsh);
        //    //Running the _changeLines.Clear() method in the window closing event causes this to run again, where we have no items, so there's a divide by zero error if this isn't placed here
        //    if (_totalRev != 0)
        //    {
        //        decimal _marginTotal = ((_totalRev - _totalCost) / _totalRev) * 100;
        //        TB_Margin.Text = decimal.Round(_marginTotal, 2).ToString();
        //    }
        //}

        private void BTN_CreateNewChangeLine_Click(object sender, RoutedEventArgs e)
        {
            //ChangeLineCreationWindow _cLineCreateWin = new ChangeLineCreationWindow();
            //_cLineCreateWin.Owner = this;
            //_cLineCreateWin.Show();
        }
        
        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            bool _modifiedOrNewChangeLines = false;
            var _modLinesCount = _changeLines.Where(x => x.IsModified == true || x.Id == 0).Count();    //Return count of number of lines that are newly created or modified
            if (_modLinesCount > 0)
                _modifiedOrNewChangeLines = true;

            if (_ISREADONLY == false && _modifiedOrNewChangeLines) //if ((_ISREADONLY == false && _modifiedOrNewChangeLines) || (_ISREADONLY == false && _newApproved))
            {
                if (MessageBox.Show("Would you like to close your quote without saving your changes?", "Prompt",
                                    MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                {
                    //yes and window closing event resumes
                    //pm.ChangeHeaders.UpdateHeader(_changeHeader);
                    //pm.ChangeLines.UpdateChangeLines(_changeLines);
                    pm.ChangeQuoteSessions.DeleteSession(_jobNumber, _quoteNumber);

                    //e.Cancel = true;
                    return;
                }
                else
                {
                    //User answers 'no' and keeps the window/session open
                    e.Cancel = true;
                    return;
                }
            }
            _changeHeader.TotalQuoteValue = _changeLines.Where(x => x.IsModified == false).Select(x => x.ExtendedSellPrice).Sum()
                                                        + (_changeLines.Where(i => i.IsLabour == false).Select(r => r.ExtendedSellPrice).Sum() * _changeHeader.OverheadPercentage / 100)
                                                        + (_changeLines.Where(i => i.IsLabour == false).Select(r => r.ExtendedSellPrice).Sum() * _changeHeader.ProfitPercentage / 100);

            _changeIndex.ChangesToDate = _changeHeaderCol.Where(i => i.Approved == true && i.Cancelled == false).Select(x => x.TotalQuoteValue).Sum(r => r.HasValue ? r.Value : 0);
            pm.ChangeQuoteSessions.DeleteSession(_jobNumber, _quoteNumber);
            _changeLines.Clear();   //added when switched to observable collection that notifies collection changed
        }

        private void CBox_CostCode_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            pm.CostCodeType _selChange = (pm.CostCodeType)CBox_CostCode.SelectedItem;
            _changeLine.CostCode = _selChange.CostCode;
            _changeLine.CostCodeName = _selChange.Description; 
            LBL_CostCodeDescription.Content = _selChange.Description;
        }

        private void BTN_AddChangeLine_Click(object sender, RoutedEventArgs e)
        {
            pm.ChangeLine _addedChangeLine = new pm.ChangeLine(_changeLine, _changeLines);

            if (_changeHeader.Approved)
            {
                MessageBox.Show("Change has already been approved, no lines can be added to it.");
                return;
            }

            if (string.IsNullOrEmpty(_addedChangeLine.CostCode))
            {
                MessageBox.Show("A cost code needs to be selected before a new line is added.");
                return;
            }
            _changeLines.Add(_addedChangeLine);
        }

        private void BTN_ClearFields_Click(object sender, RoutedEventArgs e)
        {
            //var asdf = CBox_CostCode.SelectedIndex;
            //if (CBox_CostCode.SelectedIndex != -1)
            //    CBox_CostCode.SelectedIndex = 0;

            CBox_CostCode.SelectedIndex = 0;

            LBL_CostCodeDescription.Content = "";

            LBL_LabourCodeDescription.Content = "";
        }

        private void CBox_LabourType_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            pm.LabourValuePair _labVal = (pm.LabourValuePair)CBox_LabourType.SelectedItem;
            if (_labVal != null)
            {
                _changeLine.IsLabour = true;
                _changeLine.LabourType = (pm.ChangeLabourType)_labVal.Key;
            }
        }

        private void ChkBx_Labour_Checked(object sender, RoutedEventArgs e)
        {
            CBox_LabourType.Visibility = System.Windows.Visibility.Visible;
        }

        private void ChkBx_Labour_Unchecked(object sender, RoutedEventArgs e)
        {
            CBox_LabourType.Visibility = System.Windows.Visibility.Hidden;
        }

        private void BTN_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            UpdateAndRefreshData(true);
            //see just below
        }

        private void UpdateAndRefreshData(bool updateHeader)
        {
            if (updateHeader)
                pm.ChangeHeaders.UpdateHeader(_changeHeader);

            pm.ChangeLines.UpdateChangeLines(_changeLines);
            //_changeLines = pm.ChangeLines.GetChangeLinesByQuote(_jobNumber, _quoteNumber);
            _changeLines = new pmuc.PmItemsChangeObservableCollection.ItemsChangeObservableCollection<pm.ChangeLine>(pm.ChangeLines.GetChangeLinesByQuote(_jobNumber, _quoteNumber).ToList());
            DG_ChangeOrderLines.ItemsSource = _changeLines;

            _lineLevelView = new ListCollectionView(_changeLines);
            _lineLevelView.GroupDescriptions.Add(new PropertyGroupDescription("CostCode"));
            DG_ChangeOrderLines.ItemsSource = _lineLevelView;

            _changeLine = new pm.ChangeLine(this._jobNumber, this._quoteNumber);
            pm.CostCodeType _ccType = (pm.CostCodeType)CBox_CostCode.SelectedItem;
            if (_ccType != null)
                _changeLine.CostCode = _ccType.CostCode;

            StckPan_AddChangeLine.DataContext = _changeLine;

            //Sums datagrid
            _sumLevelView = new ListCollectionView(_changeLines);
            _sumLevelView.GroupDescriptions.Add(new PropertyGroupDescription("CostCode"));
            DG_ChangeOrderSums.ItemsSource = _lineLevelView;
        }

        private void DG_ChangeOrderLines_AddingNewItem(object sender, AddingNewItemEventArgs e)
        {
            _lineLevelView.Refresh();
        }

        private void DG_ChangeOrderLines_SourceUpdated(object sender, DataTransferEventArgs e)
        {
            //colView.Refresh();
        }

        private void BTN_AddHwFromSchedule_Click(object sender, RoutedEventArgs e)
        {

        }

        private void BTN_DeleteChangeLine_Click(object sender, RoutedEventArgs e)
        {
            //if (_changeHeader.Approved || _changeHeader.TentativeApproval)
            //{
            //    MessageBox.Show("Change order has already been approved and/or tentatively approved; no lines can be added to it.");
            //    return;
            //}

            //var button = (FrameworkElement)sender;
            //var row = (DataGridRow)button.Tag;
            //pm.ChangeLine cl = (pm.ChangeLine)row.Item;
            //_changeLines.Remove(cl);
        }

        private void ChkBox_TentativeApproval_Checked(object sender, RoutedEventArgs e)
        {
            this._changeHeader.TentativeApproval = true;
            this._changeHeader.TentativeApprovalDate = DateTime.Today;
        }

        private void ChkBox_TentativeApproval_Unchecked(object sender, RoutedEventArgs e)
        {
            this._changeHeader.TentativeApproval = false;
            this._changeHeader.TentativeApprovalDate = null;
        }

        private void ChkBox_Approval_Checked(object sender, RoutedEventArgs e)
        {
            if (string.IsNullOrEmpty(TB_ChangeReference.Text))
            {
                MessageBox.Show("No change reference number exists.  Cannot approve change order without a prior SI, FWO, or Edge Builder number.");
                ChkBox_Approval.Unchecked -= ChkBox_Approval_Unchecked;
                ChkBox_Approval.IsChecked = false;
                ChkBox_Approval.Unchecked += ChkBox_Approval_Unchecked;
                return;
            }

            ChangeOrderApprovalWindow _coAppWin = new ChangeOrderApprovalWindow();
            _coAppWin.Owner = this;
            _coAppWin.ShowDialog();

            if (_coAppWin.Approve == true & !string.IsNullOrEmpty(_coAppWin.TextBoxApprovalConf))
            {
                //_newApproved = true;
                this._changeHeader.Approved = true;
                this._changeHeader.ApprovalDate = DateTime.Today;
                this._changeHeader.AuthorizationNumber = _coAppWin.TextBoxApprovalConf;

                //will have to work on a rollback later if the header update works but the line update doesn't
                for (int i = 0; i < _changeLines.Count; i++)
                {
                    if (_changeLines[i].IsLabour == false)
                    {
                        _changeLines[i].InitApprOverheadPercentage = _changeHeader.OverheadPercentage;
                        _changeLines[i].InitApprProfitPercentage = _changeHeader.ProfitPercentage;
                        _changeLines[i].InitQuoteApprDate = _changeHeader.ApprovalDate;
                    }
                }

                try { UpdateAndRefreshData(true); }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }

                TB_OverheadPercentage.IsReadOnly = true;
                TB_ProfitPercentage.IsReadOnly = true;
                DG_ChangeOrderLines.IsReadOnly = true;
                BTN_AddChangeLine.IsEnabled = false;
                BTN_UpdateServer.IsEnabled = false;
                BTN_AddHwFromSchedule.IsEnabled = false;

                e.Handled = true;
                return;
            }
            else
            {
                if (_coAppWin.Approve == true & string.IsNullOrEmpty(_coAppWin.TextBoxApprovalConf)) //Pressed 'approve' button but left the textbox for the confirmation number empty
                    MessageBox.Show("No approval confirmation number was entered");

                ChkBox_Approval.Unchecked -= ChkBox_Approval_Unchecked;
                ChkBox_Approval.IsChecked = false;
                ChkBox_Approval.Unchecked += ChkBox_Approval_Unchecked;
            }
        }

        private void ChkBox_Approval_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._changeHeader.Approved)
            {
                MessageBox.Show("Change order is already approved. A new change order must be made.");
                ChkBox_Approval.Checked -= ChkBox_Approval_Checked;
                ChkBox_Approval.IsChecked = true;
                ChkBox_Approval.Checked += ChkBox_Approval_Checked;
            }
        }

        //'Priced By' is done on a change line level, or at least is intended to be, so having this field for the entire change header makes no sense.
        //private void Cbox_PricingBy_SelectionChanged(object sender, SelectionChangedEventArgs e)
        //{
        //    dc.User _selUser = (dc.User)Cbox_PricingBy.SelectedItem;
        //    if (Cbox_PricingBy.SelectedIndex != -1)
        //    {
        //        if (_curUser.DomainUserName == _changeHeader.Manager || _curUser.PermissionTier <= 2) //Must be the PM or administrator to change
        //        {
        //            //_changeHeader.PricedBy = _selUser.DomainUserName; //Complete junk now that we know a change can't be priced at a the header level
        //        }
        //        else
        //        {
        //            MessageBox.Show("Only the designated PM or an administrator can modify this field.");
        //            ComboBox combo = (ComboBox)sender;
        //            if (e.RemovedItems.Count > 0)
        //                combo.SelectedItem = e.RemovedItems[0];
        //            else
        //                combo.SelectedItem = null;

        //            return;
        //        }
        //    }
        //}

        private void BTN_GenerateWordExport_Click(object sender, RoutedEventArgs e)
        {
            if ((bool)CBox_ItemizedWordExport.IsChecked)
                WordConverters.ExportChangeOrder.CreateChangeOrderDocument(_changeHeader, _changeLines, _changeIndex, true);
            else
                WordConverters.ExportChangeOrder.CreateChangeOrderDocument(_changeHeader, _changeLines, _changeIndex, false);
        }

        private void OpenHardwareItemWindow(object sender, RoutedEventArgs e)
        {
            pm.ChangeLine _selChangeLine = (pm.ChangeLine)((Button)e.Source).DataContext;

            if (_ISREADONLY)
                MessageBox.Show("Cannot add new items or edit a read-only quote.");
            else
            {
                pmw.ChangeOrderHardwareItemSelect _hwSelWin = new ChangeOrderHardwareItemSelect(ref _selChangeLine);
                if (_hwSelWin.CanOpen)
                {
                    _hwSelWin.Owner = this;
                    _hwSelWin.ShowDialog();
                }
            }
        }

    }

    public class BackgroundColorCell : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            pm.ChangeLine cl = (pm.ChangeLine)value;
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if (cl != null)
            {
                if (cl.QuantityDrawnPrevious == 0)
                    retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
                else if (cl.QuantityDrawnPrevious < cl.Quantity)
                    retColor.Color = (Color)ColorConverter.ConvertFromString("Gold");
                else
                    retColor.Color = (Color)ColorConverter.ConvertFromString("DarkGreen");
            }
            else
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");

            return retColor;
        }
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotSupportedException("Cannot convert back");
        }
    }

    internal class StatusToColorCo : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((bool)value)
            {
                //retColor.Color = System.Windows.Media.Color.FromRgb(255, 0, 0);
                retColor.Color = (Color)ColorConverter.ConvertFromString("Orange");
            }
            else
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
                //retColor.Color = System.Windows.Media.Color.FromRgb(0, 128, 0);
            }
            return retColor;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    internal class IsLabourToColour : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((bool)value)
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("Yellow");
            }
            else
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
            }
            return retColor;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    //http://stackoverflow.com/questions/35883522/how-to-add-all-the-column-values-of-grouped-rows-in-data-grid-row-header
    //AND
    //http://dotnetpattern.com/wpf-datagrid-grouping
    //AND
    //http://stackoverflow.com/questions/678690/how-can-i-create-a-group-footer-in-a-wpf-listview-gridview

    public class SumSellGroupConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            GroupItem groupItem = value as GroupItem;
            CollectionViewGroup collectionViewGroup = groupItem.Content as CollectionViewGroup;
            decimal sum = 0;

            foreach (var item in collectionViewGroup.Items)
            {
                pm.ChangeLine cLine = item as pm.ChangeLine;
                decimal costGroupTotal = 0;
                costGroupTotal = cLine.ExtendedSellPrice;
                sum += costGroupTotal;
            }

            return string.Format("SELL   ${0}", decimal.Round(sum, 2, MidpointRounding.AwayFromZero));
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    public class SumCostGroupConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            GroupItem groupItem = value as GroupItem;
            CollectionViewGroup collectionViewGroup = groupItem.Content as CollectionViewGroup;
            decimal sum = 0;

            foreach (var item in collectionViewGroup.Items)
            {
                pm.ChangeLine cLine = item as pm.ChangeLine;
                decimal costGroupTotal = 0;
                costGroupTotal = cLine.TotalLineCostUcsh;
                sum += costGroupTotal;
            }

            return string.Format("COST   ${0}", decimal.Round(sum, 2, MidpointRounding.AwayFromZero));
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    public class SumGroupCostCodeName : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            GroupItem groupItem = value as GroupItem;
            CollectionViewGroup collectionViewGroup = groupItem.Content as CollectionViewGroup;
            pm.ChangeLine cLine = (pm.ChangeLine)collectionViewGroup.Items[0];
            return cLine.CostCode + " - " + cLine.CostCodeName;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }
}
