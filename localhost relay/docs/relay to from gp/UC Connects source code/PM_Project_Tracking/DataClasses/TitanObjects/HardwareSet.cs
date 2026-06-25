using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    class HardwareSet
    {
        int _hardwareSetId;
        int _projectId;
        string _name;
        string _description;
        string _alternateSetDescription;
        string _notes;
        string _notesAbove;
        bool _autosize;
        int _hardwareQty;
        int _openingCount;
        int _itemsOrderedCount;

        public int HardwareSetId
        {
            get
            {
                return _hardwareSetId;
            }

            set
            {
                _hardwareSetId = value;
            }
        }

        public int ProjectId
        {
            get
            {
                return _projectId;
            }

            set
            {
                _projectId = value;
            }
        }

        public string Name
        {
            get
            {
                return _name;
            }

            set
            {
                _name = value;
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

        public string AlternateSetDescription
        {
            get
            {
                return _alternateSetDescription;
            }

            set
            {
                _alternateSetDescription = value;
            }
        }

        public string Notes
        {
            get
            {
                return _notes;
            }

            set
            {
                _notes = value;
            }
        }

        public string NotesAbove
        {
            get
            {
                return _notesAbove;
            }

            set
            {
                _notesAbove = value;
            }
        }

        public bool Autosize
        {
            get
            {
                return _autosize;
            }

            set
            {
                _autosize = value;
            }
        }

        public int HardwareQty
        {
            get
            {
                return _hardwareQty;
            }

            set
            {
                _hardwareQty = value;
            }
        }

        public int OpeningCount
        {
            get
            {
                return _openingCount;
            }

            set
            {
                _openingCount = value;
            }
        }

        public int ItemsOrderedCount
        {
            get
            {
                return _itemsOrderedCount;
            }

            set
            {
                _itemsOrderedCount = value;
            }
        }
    }
}
