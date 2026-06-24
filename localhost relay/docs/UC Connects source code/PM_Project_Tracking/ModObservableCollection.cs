using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking
{
    public class ModObservableCollection<T> : ObservableCollection<T>
    {
        //int _currentPosition;

        public int CurrentPosition
        {
            get
            {
                return GetDefaultView().CurrentPosition;
            }
        }

        public ModObservableCollection()
            : base()
        {
        }

        public ModObservableCollection(List<T> list)
            : base(list)
        {
        }

        public ModObservableCollection(IEnumerable<T> collection)
            : base(collection)
        {
        }   

        //create my method to return my instance of ICollectionView.
        private System.ComponentModel.ICollectionView GetDefaultView()
        {
            return System.Windows.Data.CollectionViewSource.GetDefaultView(this);
        }

        public void MoveFirst()
        {
            GetDefaultView().MoveCurrentToFirst();
        }

        public void MovePrevious()
        {
            GetDefaultView().MoveCurrentToPrevious();
        }

        public void MoveNext()
        {
            GetDefaultView().MoveCurrentToNext();
        }

        public void MoveLast()
        {
            GetDefaultView().MoveCurrentToLast();
        }

        public void MoveCurrentTo(int pos)
        {
            GetDefaultView().MoveCurrentToPosition(pos);
        }

    }
}
