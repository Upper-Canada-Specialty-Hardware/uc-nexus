using System;
using System.Collections.Generic;
using System.ComponentModel;
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

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for WhRecsBlankLinesShippingMemo.xaml
    /// </summary>
    public partial class WhRecsBlankLinesShippingMemo : Window, INotifyPropertyChanged
    {
        private int _lineCount;
        private bool _canProceed = false;
        public int LineCount
        {
            get { return _lineCount;  }
            set
            {
                _lineCount = value;
                OnPropertyChanged("LineCount");
            }
        }

        public bool CanProceed
        {
            get
            {
                return _canProceed;
            }

            set
            {
                _canProceed = value;
            }
        }

        public WhRecsBlankLinesShippingMemo()
        {
            InitializeComponent();
            TB_LineCount.DataContext = this;
            TB_LineCount.Focus();
        }

        private void BTN_Confirm_Click(object sender, RoutedEventArgs e)
        {
            if (_lineCount > 0 && (_lineCount.ToString() == TB_LineCount.Text))
            {
                this._canProceed = true;
                this.Close();
            }
            else
                this._canProceed = false;

        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }
}
