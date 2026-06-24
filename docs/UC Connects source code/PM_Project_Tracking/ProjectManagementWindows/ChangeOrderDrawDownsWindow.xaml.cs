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
using pm = PM_Project_Tracking.ProjectManagementClasses;

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>
    /// Interaction logic for ChangeOrderDrawDownsWindow.xaml
    /// </summary>
    public partial class ChangeOrderDrawDownsWindow : Window
    {
        pm.ProgressBillingHeader _pbHeader = null;
        pm.ProgressBillingLine _pbLine = null;
        ObservableCollection<pm.ChangeLine> _changeLines = null;

        public ChangeOrderDrawDownsWindow()
        {
            InitializeComponent();
        }

        public ChangeOrderDrawDownsWindow(ref pm.ProgressBillingHeader pbHeader, ref pm.ProgressBillingLine pbLine, string costCode, string quoteNumber)
        {
            InitializeComponent();

            _pbHeader = pbHeader;
            _pbLine = pbLine;

            //add a view filter to group lines by quote
            _changeLines = pm.ChangeLines.GetChangeLinesByJobAndCostCodeAndQuoteNumber(pbHeader, costCode, quoteNumber);
            DG_ChangeLineList.ItemsSource = _changeLines;
            DG_DrawDowns.ItemsSource = _pbLine.DrawDownsList;

            StckPan_SelectedPbLine.DataContext = _pbLine;
        }


        public ChangeOrderDrawDownsWindow(ref pm.ProgressBillingHeader pbHeader, ref pm.ProgressBillingLine pbLine)
        {
            InitializeComponent();

            _pbHeader = pbHeader;
            _pbLine = pbLine;

            //add a view filter to group lines by quote
            _changeLines = pm.ChangeLines.GetChangeLinesByJobAndCostCodeAndQuoteNumber(pbHeader, pbLine.CostCode, pbLine.QuoteNumber);
            DG_ChangeLineList.ItemsSource = _changeLines;
            DG_DrawDowns.ItemsSource = _pbLine.DrawDownsList;

            StckPan_SelectedPbLine.DataContext = _pbLine;
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
                            if (cell.Column.DisplayIndex == 10)
                            {
                                if (MessageBox.Show("Would you like to transfer this amount?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    pm.ChangeLine _selChangeLine = (pm.ChangeLine)row.Item;
                                    decimal _quantRemainder = _selChangeLine.Quantity - (_selChangeLine.QuantityDrawnPrevious + _selChangeLine.QuantitySelectedFromDataGrid);        //make it so that this is up to date, so we don't have to check other things
                                    if (_quantRemainder < 0)
                                    {
                                        MessageBox.Show("You have drawn more than the alotted quantity");
                                        _selChangeLine.QuantitySelectedFromDataGrid = 0;
                                        DG_ChangeLineList.CancelEdit();
                                        DG_ChangeLineList.Items.Refresh();
                                        return;
                                    }
                                    else
                                    {
                                        pm.ChangeLineDrawDown _foundDrawDown = _pbLine.DrawDownsList.Where(x => x.QuoteNumber == _selChangeLine.QuoteNumber
                                                                                                           && x.CostCode == _selChangeLine.CostCode
                                                                                                           && x.CostCodeSerial == _selChangeLine.CostCodeSerial).FirstOrDefault();

                                        if (_foundDrawDown == null)
                                        {
                                            pm.ChangeLineDrawDown _newDrawDown = new pm.ChangeLineDrawDown(_pbLine, _selChangeLine);
                                            _pbLine.DrawDownsList.Add(_newDrawDown);
                                            _selChangeLine.QuantityDrawnPrevious = _selChangeLine.QuantitySelectedFromDataGrid;
                                        }
                                        else
                                        {
                                            _foundDrawDown.QuantityDrawn = _foundDrawDown.QuantityDrawn + _selChangeLine.QuantitySelectedFromDataGrid;
                                            _selChangeLine.QuantityDrawnPrevious = _selChangeLine.QuantityDrawnPrevious + _selChangeLine.QuantitySelectedFromDataGrid; //
                                            //needs to be previous plus what's taken from datagrid now. the old "_selChangeLine.QuantityDrawnPrevious = _foundDrawDown.QuantityDrawn;" didn't
                                            //work because it didn't take into account the draw downs on this particular quote line used against OTHER progress bill lines
                                        }

                                    }
                                }
                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 10)
                            {
                                if (MessageBox.Show("Would you like to transfer this amount?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    pm.ChangeLine _selChangeLine = (pm.ChangeLine)row.Item;
                                    decimal _quantRemainder = _selChangeLine.Quantity - (_selChangeLine.QuantityDrawnPrevious + _selChangeLine.QuantitySelectedFromDataGrid);        //make it so that this is up to date, so we don't have to check other things
                                    if (_quantRemainder < 0)
                                    {
                                        MessageBox.Show("You have drawn more than the alotted quantity");
                                        _selChangeLine.QuantitySelectedFromDataGrid = 0;
                                        DG_ChangeLineList.CancelEdit();
                                        DG_ChangeLineList.Items.Refresh();
                                        return;
                                    }
                                    else
                                    {
                                        pm.ChangeLineDrawDown _foundDrawDown = _pbLine.DrawDownsList.Where(x => x.QuoteNumber == _selChangeLine.QuoteNumber
                                                                                                           && x.CostCode == _selChangeLine.CostCode
                                                                                                           && x.CostCodeSerial == _selChangeLine.CostCodeSerial).FirstOrDefault();

                                        if (_foundDrawDown == null)
                                        {
                                            pm.ChangeLineDrawDown _newDrawDown = new pm.ChangeLineDrawDown(_pbLine, _selChangeLine);
                                            _pbLine.DrawDownsList.Add(_newDrawDown);
                                            _selChangeLine.QuantityDrawnPrevious = _selChangeLine.QuantitySelectedFromDataGrid;
                                        }
                                        else
                                        {
                                            _foundDrawDown.QuantityDrawn = _foundDrawDown.QuantityDrawn + _selChangeLine.QuantitySelectedFromDataGrid;
                                            _selChangeLine.QuantityDrawnPrevious = _selChangeLine.QuantityDrawnPrevious + _selChangeLine.QuantitySelectedFromDataGrid; //
                                        }

                                    }
                                }
                            }
                            row.IsSelected = true;
                        }
                    }
                }
            }
        }

        private void DG_DrawDowns_PreviewMouseLeftButtonDownShipRec(object sender, MouseButtonEventArgs e)
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
                            if (cell.Column.DisplayIndex == 8)
                            {
                                if (MessageBox.Show("Would you like to delete this amount?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    pm.ChangeLineDrawDown _selDrawDown = (pm.ChangeLineDrawDown)row.Item;

                                    pm.ChangeLine _matchedCl = _changeLines.Where(x => x.QuoteNumber == _selDrawDown.QuoteNumber
                                                                                  && x.CostCode == _selDrawDown.CostCode
                                                                                  && x.CostCodeSerial == _selDrawDown.CostCodeSerial).FirstOrDefault();

                                    if (_matchedCl != null)
                                    {
                                        _matchedCl.QuantityDrawnPrevious = _matchedCl.QuantityDrawnPrevious - _selDrawDown.QuantityDrawn;
                                        _pbLine.DrawDownsList.Remove(_selDrawDown);
                                    }
                                    else
                                    {
                                        MessageBox.Show("Oddly, there was no change quote line item that matched this draw-down, please contact administrator.");
                                    }
                                }
                                // DG_PoList.Items.Refresh();
                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 8)
                            {
                                if (MessageBox.Show("Would you like to delete this amount?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    pm.ChangeLineDrawDown _selDrawDown = (pm.ChangeLineDrawDown)row.Item;

                                    pm.ChangeLine _matchedCl = _changeLines.Where(x => x.QuoteNumber == _selDrawDown.QuoteNumber
                                                                                  && x.CostCode == _selDrawDown.CostCode
                                                                                  && x.CostCodeSerial == _selDrawDown.CostCodeSerial).FirstOrDefault();

                                    if (_matchedCl != null)
                                    {
                                        _matchedCl.QuantityDrawnPrevious = _matchedCl.QuantityDrawnPrevious - _selDrawDown.QuantityDrawn;
                                        _pbLine.DrawDownsList.Remove(_selDrawDown);
                                    }
                                    else
                                    {
                                        MessageBox.Show("Oddly, there was no change quote line item that matched this draw-down, please contact administrator.");
                                    }
                                }
                                // DG_PoList.Items.Refresh();
                            }
                            row.IsSelected = true;
                        }
                    }
                }
            }
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
