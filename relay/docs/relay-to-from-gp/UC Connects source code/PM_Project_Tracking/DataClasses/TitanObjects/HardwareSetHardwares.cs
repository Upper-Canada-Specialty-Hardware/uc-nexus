using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    class HardwareSetHardwares
    {
        int _startRow;
        int _endRow;
        int _totalRows;
        HardwareSetHardware[] _data;

        public int StartRow
        {
            get
            {
                return _startRow;
            }

            set
            {
                _startRow = value;
            }
        }

        public int EndRow
        {
            get
            {
                return _endRow;
            }

            set
            {
                _endRow = value;
            }
        }

        public int TotalRows
        {
            get
            {
                return _totalRows;
            }

            set
            {
                _totalRows = value;
            }
        }

        internal HardwareSetHardware[] Data
        {
            get
            {
                return _data;
            }

            set
            {
                _data = value;
            }
        }
    }
}
