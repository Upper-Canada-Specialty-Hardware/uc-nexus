using PM_Project_Tracking.DataClasses.Interfaces;
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

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for PoAddNewUcshComment.xaml
    /// </summary>
    public partial class PoAddNewUcshComment : Window
    {
        dc.PurchaseOrderLineItem _poLine = null;
        private bool _lineHeader;
        ObservableCollection<dc.PoUcshHeaderComment> _poHeaderComs = null;
        ObservableCollection<dc.PoUcshLineComment> _poLineComs = null;
        ObservableCollection<dc.PurchaseOrderLineItem> _allPoLines;

        public PoAddNewUcshComment()
        {
            InitializeComponent();
        }

        public PoAddNewUcshComment(ref dc.PurchaseOrderLineItem poLine, bool lineHeader, ref ObservableCollection<dc.PurchaseOrderLineItem> poLines)
        {
            InitializeComponent();
            _lineHeader = lineHeader;
            _poLine = poLine;
            _allPoLines = poLines;
            if (_lineHeader)
            {
                _poHeaderComs = poLine.UcHeaderCommentCol;
                DG_HeaderCommentList.ItemsSource = _poHeaderComs;
                DG_HeaderCommentList.Visibility = System.Windows.Visibility.Visible;
                DG_LineCommentList.Visibility = System.Windows.Visibility.Hidden;
            }
            else
            {
                _poLineComs = poLine.UcLineCommentCol;
                DG_LineCommentList.ItemsSource = _poLineComs;
                DG_LineCommentList.Visibility = System.Windows.Visibility.Visible;
                DG_HeaderCommentList.Visibility = System.Windows.Visibility.Hidden;
            }
        }

        public PoAddNewUcshComment(IEnumerable<IPoUcshComment> col)
        {
            InitializeComponent();

            if (col.GetType() == typeof(ObservableCollection<dc.PoUcshHeaderComment>))
            {
                _poHeaderComs = (ObservableCollection<dc.PoUcshHeaderComment>)col;
                DG_HeaderCommentList.ItemsSource = _poHeaderComs;
                DG_HeaderCommentList.Visibility = System.Windows.Visibility.Visible;
                DG_LineCommentList.Visibility = System.Windows.Visibility.Hidden;
                DG_HeaderCommentList.IsReadOnly = true;
            }
            else
            {
                _poLineComs = (ObservableCollection<dc.PoUcshLineComment>)col;
                DG_LineCommentList.ItemsSource = _poLineComs;
                DG_HeaderCommentList.Visibility = System.Windows.Visibility.Hidden;
                DG_LineCommentList.Visibility = System.Windows.Visibility.Visible;
                DG_LineCommentList.IsReadOnly = true;
            }

            BTN_NewComment.Visibility = System.Windows.Visibility.Hidden;
        }

        private void BTN_NewComment_Click(object sender, RoutedEventArgs e)
        {
            if (_lineHeader)
            {
                dc.PoUcshHeaderComment _newHdrCom = new dc.PoUcshHeaderComment(_poLine.JobNumber, _poLine.PoNumber);
                _poHeaderComs.Add(_newHdrCom);
            }
            else
            {
                dc.PoUcshLineComment _newLineCom = new dc.PoUcshLineComment(_poLine.JobNumber, _poLine.PoNumber, _poLine.Order);
                _poLineComs.Add(_newLineCom);
            }
        }

        private void Window_Closed(object sender, EventArgs e)
        {
            if (_lineHeader)
            {
                for (int i = _poHeaderComs.Count - 1; i >= 0; i--)
                {
                    if (string.IsNullOrEmpty(_poHeaderComs[i].CommentText))
                        _poHeaderComs.RemoveAt(i);
                }
                dc.PoUcshHeaderComments.InsertUpdatePoUcshHeaderComment(_poHeaderComs);
                //if (_poHeaderComs != null)
                //    _poHeaderComs = dc.PoUcshHeaderComments.GetPoUcshHeaderComments(_poHeaderComs[0].PoNumber);
                if (_poHeaderComs.Count > 0)
                {
                    foreach (dc.PurchaseOrderLineItem po in _allPoLines)
                    {
                        if (po.PoNumber == _poHeaderComs[0].PoNumber)
                            po.UcHeaderHasComments = true;
                    }
                }
            }
            else
            {
                for (int i = _poLineComs.Count - 1; i >= 0; i--)
                {
                    if (string.IsNullOrEmpty(_poLineComs[i].CommentText))
                        _poLineComs.RemoveAt(i);
                }
                dc.PoUcshLineComments.InsertUpdatePoUcshLineComment(_poLineComs);
                if (_poLineComs.Count > 0)
                    _poLine.UcLineHasComments = true;
            }

        }

        private void DG_HeaderCommentList_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            DataGridCell cell = sender as DataGridCell;
            var _curComType = cell.DataContext.GetType();
            string _origCreator;

            if (_curComType == typeof(dc.PoUcshLineComment))
                _origCreator = ((dc.PoUcshLineComment)cell.DataContext).CreatingUser;
            else
                _origCreator = ((dc.PoUcshHeaderComment)cell.DataContext).CreatingUser;

            //_origCreator = "sdfsdF";
            
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
                        if (Environment.UserName != _origCreator)
                        {
                            DataGridRow row = FindVisualParent<DataGridRow>(cell);
                            row.IsSelected = false;
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
