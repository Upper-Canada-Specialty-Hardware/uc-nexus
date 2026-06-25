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
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using pmw = PM_Project_Tracking.ProjectManagementWindows;
using pmuvm = PM_Project_Tracking.ProjectManagementClasses.ProjectManagementUtililtyClasses.CostCodeAggregateViewModel;
using System.Collections.ObjectModel;

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>
    /// Interaction logic for ProgressBillingWindow.xaml
    /// </summary>
    public partial class ProgressBillingWindow : Window
    {
        private readonly bool _ISREADONLY;
        private ObservableCollection<pm.ProgressBillingLine> _pbRegularLines = null;
        private ObservableCollection<pm.ProgressBillingLine> _pbChangeLines = null;
        private pm.ProgressBillingHeader _pbHeader = null;

        public ProgressBillingWindow()
        {
            InitializeComponent();
        }

        public ProgressBillingWindow(ref pm.ProgressBillingHeader pbHeader, bool rdonly)
        {
            InitializeComponent();
            _ISREADONLY = rdonly;

            _pbHeader = pbHeader;
            _pbRegularLines = pm.ProgressBillingLines.GetProgressBillingStandardLines(pbHeader);
            _pbChangeLines = pm.ProgressBillingLines.GetProgressBillingChangeLines(pbHeader);
            CBox_CostCodeQuoteNumber.ItemsSource = pm.ChangeHeaders.GetChangeQuotesForProgressBillDropDown(pbHeader.JobNumber);

            DG_BaseContractLines.ItemsSource = _pbRegularLines;
            DG_ChangeLines.ItemsSource = _pbChangeLines;

            if (_ISREADONLY)
            {
                DG_BaseContractLines.IsReadOnly = true;
                DG_ChangeLines.IsReadOnly = true;
                BTN_AddRegularLine.IsEnabled = false;

                //BTN_ClearRegularLines.IsEnabled = false;
                BTN_RegularLines_UpdateServer.IsEnabled = false;
                BTN_AddChangeLine.IsEnabled = false;
                //BTN_ClearChangeLines.IsEnabled = false;
                BTN_ChangeLines_UpdateServer.IsEnabled = false;
            }
        }

        private void BTN_AddRegularLine_Click(object sender, RoutedEventArgs e)
        {
            if (CBox_CostCode.SelectedIndex != -1)
            {
                pm.CostCodeType _costCode = (pm.CostCodeType)CBox_CostCode.SelectedItem;
                int _serial = 1;
                if (_pbRegularLines.Count > 0)
                    _serial = _pbRegularLines.Max(x => x.Serial) + 1;

                pm.ProgressBillingLine _newPbLine = new pm.ProgressBillingLine(_pbHeader,_costCode.CostCode, _serial, false, "");
                _pbRegularLines.Add(_newPbLine);
            }
            else
            {
                MessageBox.Show("You must select a costcode first.");
            }
        }

        private void BTN_ClearRegularLines_Click(object sender, RoutedEventArgs e)
        {

        }

        private void BTN_RegularLines_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            int _count = _pbRegularLines.Where(x => x.IsModified == true || x.IsDeleted == true || x.Id == 0).Count();

            if (_count > 0)
            {
                try
                {
                    pm.ProgressBillingLines.UpdateProgBillLines(_pbRegularLines);

                }
                catch (Exception ex)
                {
                    pm.ProgressBillingLines.DeleteProgressBillChangeLines(_pbRegularLines);
                    MessageBox.Show(ex.ToString());
                }

                _pbRegularLines = pm.ProgressBillingLines.GetProgressBillingStandardLines(_pbHeader);
                DG_BaseContractLines.ItemsSource = _pbRegularLines;
            }
        }

        private void DG_ChangeLines_PreviewMouseLeftButtonDownShipRec(object sender, MouseButtonEventArgs e)
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
                            if (cell.Column.DisplayIndex == 12)
                            {
                                pm.ProgressBillingLine _selPbLine = (pm.ProgressBillingLine)row.Item;

                                ChangeOrderDrawDownsWindow _coDdWin = new ChangeOrderDrawDownsWindow(ref _pbHeader, ref _selPbLine);
                                _coDdWin.Owner = this;
                                _coDdWin.ShowDialog();
                                DG_ChangeLines.Items.Refresh();
                                //if someone closes the window by committing, add to collection, otherwise do nothing
                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 12)
                            {
                                pm.ProgressBillingLine _selPbLine = (pm.ProgressBillingLine)row.Item;

                                ChangeOrderDrawDownsWindow _coDdWin = new ChangeOrderDrawDownsWindow(ref _pbHeader, ref _selPbLine);
                                _coDdWin.Owner = this;
                                _coDdWin.ShowDialog();
                                DG_ChangeLines.Items.Refresh();
                                //if someone closes the window by committing, add to collection, otherwise do nothing
                            }
                            row.IsSelected = true;
                        }
                    }
                }
            }
        }

        private void BTN_AddChangeLine_Click(object sender, RoutedEventArgs e)
        {
            //bool _added = false;
            if (CBox_CostCodeChangeLine.SelectedIndex != -1 && CBox_CostCodeQuoteNumber.SelectedIndex != -1)
            {
                pm.CostCodeType _costCode = (pm.CostCodeType)CBox_CostCodeChangeLine.SelectedItem;
                string _quoteNumber = ((pm.ChangeHeader)CBox_CostCodeQuoteNumber.SelectedItem).QuoteNumber;

                int _serial = 1;
                if (_pbChangeLines.Count > 0)
                    _serial = _pbChangeLines.Max(x => x.Serial) + 1;

                pm.ProgressBillingLine _pbChangeLine = new pm.ProgressBillingLine(_pbHeader, _costCode.CostCode, _serial, true, _quoteNumber );

                ChangeOrderDrawDownsWindow _coDdWin = new ChangeOrderDrawDownsWindow(ref _pbHeader, ref _pbChangeLine, _costCode.CostCode, _quoteNumber);
                _coDdWin.Owner = this;
                _coDdWin.ShowDialog();
                _pbChangeLines.Add(_pbChangeLine);

                //if someone closes the window by committing, add to collection, otherwise do nothing
            }
            else
            {
                MessageBox.Show("You must select a cost code and quote number first.");
            }
        }

        private void BTN_ClearChangeLines_Click(object sender, RoutedEventArgs e)
        {

        }

        private void BTN_ChangeLines_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            int _count = _pbChangeLines.Where(x => x.IsModified == true || x.IsDeleted == true || x.Id == 0).Count();

            if (_count > 0)
            {
                try
                {
                    pm.ProgressBillingLines.UpdateProgBillLines(_pbChangeLines);
                    foreach (pm.ProgressBillingLine line in _pbChangeLines)
                        pm.ChangeLineDrawDowns.UpdateDrawDowns(line.DrawDownsList);
                        
                }
                catch (Exception ex)
                {
                    pm.ProgressBillingLines.DeleteProgressBillChangeLines(_pbChangeLines);
                    foreach (pm.ProgressBillingLine line in _pbChangeLines)
                        pm.ChangeLineDrawDowns.DeleteDrawDowns(line.DrawDownsList);

                    MessageBox.Show(ex.ToString());
                }
                
                _pbChangeLines = pm.ProgressBillingLines.GetProgressBillingChangeLines(_pbHeader);      //this also gets the updated draw downs
                DG_ChangeLines.ItemsSource = _pbChangeLines;
            }
        }

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            if (_ISREADONLY == false)
            {
                int _moddedLines = new List<pm.ProgressBillingLine>(_pbRegularLines.Concat(_pbChangeLines)).Where(x => x.IsModified == true || x.IsDeleted == true || x.Id == 0).Count(); ;

                if (_moddedLines > 0)
                {
                    if (MessageBox.Show("This progress billing has been modified without updating the server, " +
                                        "would you like to keep this window open until you have saved your changes?" +
                                        " If you click 'No' then your changes WILL NOT BE SAVED.", "Prompt",
                                        MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    {
                        e.Cancel = true;
                        return;
                    }
                }
            }

            if (_ISREADONLY == false)
                pm.ProgressBillSessions.DeleteSession(_pbHeader.JobNumber, _pbHeader.Iteration, _pbHeader.Revision);
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

    internal class StatusToColor : IValueConverter
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
}
