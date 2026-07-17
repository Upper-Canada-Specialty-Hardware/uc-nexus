using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    class FrameAttribute
    {
        string _materialAttrTypeDescription;
        string _printCode;
        string _description;

        public string MaterialAttrTypeDescription
        {
            get
            {
                return _materialAttrTypeDescription;
            }

            set
            {
                _materialAttrTypeDescription = value;
            }
        }

        public string PrintCode
        {
            get
            {
                return _printCode;
            }

            set
            {
                _printCode = value;
            }
        }

        public string Description
        {
            get
            {
                return _description;
            }

            set
            {
                _description = value;
            }
        }
    }
}
