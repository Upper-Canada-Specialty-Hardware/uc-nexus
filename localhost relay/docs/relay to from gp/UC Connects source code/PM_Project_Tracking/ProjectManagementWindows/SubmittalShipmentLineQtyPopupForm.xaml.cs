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
using System.ComponentModel;
using dc = PM_Project_Tracking.DataClasses;


using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Windows.Controls.Primitives;
using System.Windows.Media.Imaging;
using System.Windows.Navigation;

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>
    /// Interaction logic for SubmittalShipmentLineQtyPopupForm.xaml
    /// </summary>
    public partial class SubmittalShipmentLineQtyPopupForm : Window, INotifyPropertyChanged
    {
        private bool _contWindow;
        private int _shipLineCount;
        private dc.ShippingHeader _shipHeader = null;
        private ObservableCollection<dc.ShippingLine> _shipLines = new ObservableCollection<dc.ShippingLine>();
        private dc.CombinedProject _combProj = null;

        public int ShipLineCount 
        {
            get { return _shipLineCount; }
            set
            {
                _shipLineCount = value;
                OnPropertyChanged("ShipLineCount");
            }
        }

        public bool ContWindow
        {
            get { return _contWindow; }
            set { _contWindow = value; }
        }

        public dc.ShippingHeader ShipHeader
        {
            get
            {
                return _shipHeader;
            }

            set
            {
                _shipHeader = value;
            }
        }

        public ObservableCollection<dc.ShippingLine> ShipLines
        {
            get
            {
                return _shipLines;
            }

            set
            {
                _shipLines = value;
            }
        }

        public SubmittalShipmentLineQtyPopupForm(dc.ShippingHeader shipHeader, dc.CombinedProject combProj)
        {
            InitializeComponent();
            this.DataContext = this;
            DG_ShipLineList.ItemsSource = this._shipLines;
            this._combProj = combProj;
            this._shipHeader = shipHeader;
            BTN_Yes.IsEnabled = false;
        }

        private void BTN_Yes_Click(object sender, RoutedEventArgs e)
        {
            this.ContWindow = true;
            this.Close();
        }

        private void BTN_No_Click(object sender, RoutedEventArgs e)
        {
            this.ContWindow = false;
            this.Close();
        }

        private void BTN_YesShip_Click(object sender, RoutedEventArgs e)
        {
            if (ShipLines.Count > 0)
            {
                this._contWindow = true;
                this.Close();
            }
            else
            {
                MessageBox.Show("There must be at least one shipping line in order to generate a shipping document for this sample.");
            }
        }

        private void BTN_AddShipRow_Click(object sender, RoutedEventArgs e)
        {
            ShipLines.Add(new dc.ShippingLine(_shipHeader, _combProj));
        }


        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

        private void TextBox_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (ShipLineCount > 1 & BTN_Yes != null)
                BTN_Yes.IsEnabled = true;
            else if (BTN_Yes != null)
                BTN_Yes.IsEnabled = false;
        }

        private void DataGridCell_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            //http://wpf.codeplex.com/wikipage?title=Single-Click%20Editing
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
                            if (cell.Column.DisplayIndex == 0)
                            {
                                if (MessageBox.Show("Would you like to delete this item?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ShippingLine _selShipLine = (dc.ShippingLine)row.Item;
                                    ShipLines.Remove(_selShipLine);
                                    //_sopDoc.LineItems.RemoveAt(row.GetIndex());
                                    DG_ShipLineList.Items.Refresh();
                                }
                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 0)
                            {
                                if (MessageBox.Show("Would you like to delete this item?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ShippingLine _selShipLine = (dc.ShippingLine)row.Item;
                                    ShipLines.Remove(_selShipLine);
                                    //_sopDoc.LineItems.RemoveAt(row.GetIndex());
                                    DG_ShipLineList.Items.Refresh();
                                }
                            }
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


    internal class CanPressYes : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            bool _retBool = false;
            if ((int)value > 0)
                _retBool = true;
            else
                _retBool = false;

            return _retBool;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }
}
