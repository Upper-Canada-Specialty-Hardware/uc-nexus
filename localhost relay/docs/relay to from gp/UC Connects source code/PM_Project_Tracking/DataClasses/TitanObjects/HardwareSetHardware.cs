using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    class HardwareSetHardware
    {
        int _hardwareSetHardwareId;
        int _hardwareSetId;
        string _hardwareSetName;
        string _hardwareSetDescription;
        int _hardwareId;
        int _projectId;
        string _projectName;
        string _vendorName;
        string _vendorAbbr;
        string _vendorNotificationText;
        bool _priceBookMismatch;
        string _hdwTypeId;
        string _hdwTypeDescription;
        int _sortOrder;
        int _sequence;
        string _item;
        string _printDescription;
        string _orderDescription;
        string _hdwStdDescription;
        string _uomCode;
        bool _sized;
        string _hdwLength;
        string _hdwWidth;
        string _hdwHeight;
        string _sizeString;
        string _subTypeDescription;
        bool _specialNet;
        decimal _specialNetCost;
        decimal _listCost;
        decimal _cost;
        decimal _listCostPlusModifiers;
        decimal _costPlusModifiers;
        decimal _extendedListCostPlusModifiers;
        decimal _extendedCostPlusModifiers;
        bool _byOthers;
        string _byOthersSupplier;
        string _notes;
        int _qty;
        string _leafCode;
        bool _a;
        bool _b;
        bool _i;
        int _hardwareSetQty;
        int _orderCount;
        int _orderable;

        public int HardwareSetHardwareId
        {
            get
            {
                return _hardwareSetHardwareId;
            }

            set
            {
                _hardwareSetHardwareId = value;
            }
        }

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

        public string HardwareSetName
        {
            get
            {
                return _hardwareSetName;
            }

            set
            {
                _hardwareSetName = value;
            }
        }

        public string HardwareSetDescription
        {
            get
            {
                return _hardwareSetDescription;
            }

            set
            {
                _hardwareSetDescription = value;
            }
        }

        public int HardwareId
        {
            get
            {
                return _hardwareId;
            }

            set
            {
                _hardwareId = value;
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

        public string ProjectName
        {
            get
            {
                return _projectName;
            }

            set
            {
                _projectName = value;
            }
        }

        public string VendorName
        {
            get
            {
                return _vendorName;
            }

            set
            {
                _vendorName = value;
            }
        }

        public string VendorAbbr
        {
            get
            {
                return _vendorAbbr;
            }

            set
            {
                _vendorAbbr = value;
            }
        }

        public string VendorNotificationText
        {
            get
            {
                return _vendorNotificationText;
            }

            set
            {
                _vendorNotificationText = value;
            }
        }

        public bool PriceBookMismatch
        {
            get
            {
                return _priceBookMismatch;
            }

            set
            {
                _priceBookMismatch = value;
            }
        }

        public string HdwTypeId
        {
            get
            {
                return _hdwTypeId;
            }

            set
            {
                _hdwTypeId = value;
            }
        }

        public string HdwTypeDescription
        {
            get
            {
                return _hdwTypeDescription;
            }

            set
            {
                _hdwTypeDescription = value;
            }
        }

        public int SortOrder
        {
            get
            {
                return _sortOrder;
            }

            set
            {
                _sortOrder = value;
            }
        }

        public int Sequence
        {
            get
            {
                return _sequence;
            }

            set
            {
                _sequence = value;
            }
        }

        public string Item
        {
            get
            {
                return _item;
            }

            set
            {
                _item = value;
            }
        }

        public string PrintDescription
        {
            get
            {
                return _printDescription;
            }

            set
            {
                _printDescription = value;
            }
        }

        public string OrderDescription
        {
            get
            {
                return _orderDescription;
            }

            set
            {
                _orderDescription = value;
            }
        }

        public string HdwStdDescription
        {
            get
            {
                return _hdwStdDescription;
            }

            set
            {
                _hdwStdDescription = value;
            }
        }

        public string UomCode
        {
            get
            {
                return _uomCode;
            }

            set
            {
                _uomCode = value;
            }
        }

        public bool Sized
        {
            get
            {
                return _sized;
            }

            set
            {
                _sized = value;
            }
        }

        public string HdwLength
        {
            get
            {
                return _hdwLength;
            }

            set
            {
                _hdwLength = value;
            }
        }

        public string HdwWidth
        {
            get
            {
                return _hdwWidth;
            }

            set
            {
                _hdwWidth = value;
            }
        }

        public string HdwHeight
        {
            get
            {
                return _hdwHeight;
            }

            set
            {
                _hdwHeight = value;
            }
        }

        public string SizeString
        {
            get
            {
                return _sizeString;
            }

            set
            {
                _sizeString = value;
            }
        }

        public string SubTypeDescription
        {
            get
            {
                return _subTypeDescription;
            }

            set
            {
                _subTypeDescription = value;
            }
        }

        public bool SpecialNet
        {
            get
            {
                return _specialNet;
            }

            set
            {
                _specialNet = value;
            }
        }

        public decimal SpecialNetCost
        {
            get
            {
                return _specialNetCost;
            }

            set
            {
                _specialNetCost = value;
            }
        }

        public decimal ListCost
        {
            get
            {
                return _listCost;
            }

            set
            {
                _listCost = value;
            }
        }

        public decimal Cost
        {
            get
            {
                return _cost;
            }

            set
            {
                _cost = value;
            }
        }

        public decimal ListCostPlusModifiers
        {
            get
            {
                return _listCostPlusModifiers;
            }

            set
            {
                _listCostPlusModifiers = value;
            }
        }

        public decimal CostPlusModifiers
        {
            get
            {
                return _costPlusModifiers;
            }

            set
            {
                _costPlusModifiers = value;
            }
        }

        public decimal ExtendedListCostPlusModifiers
        {
            get
            {
                return _extendedListCostPlusModifiers;
            }

            set
            {
                _extendedListCostPlusModifiers = value;
            }
        }

        public decimal ExtendedCostPlusModifiers
        {
            get
            {
                return _extendedCostPlusModifiers;
            }

            set
            {
                _extendedCostPlusModifiers = value;
            }
        }

        public bool ByOthers
        {
            get
            {
                return _byOthers;
            }

            set
            {
                _byOthers = value;
            }
        }

        public string ByOthersSupplier
        {
            get
            {
                return _byOthersSupplier;
            }

            set
            {
                _byOthersSupplier = value;
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

        public int Qty
        {
            get
            {
                return _qty;
            }

            set
            {
                _qty = value;
            }
        }

        public string LeafCode
        {
            get
            {
                return _leafCode;
            }

            set
            {
                _leafCode = value;
            }
        }

        public bool A
        {
            get
            {
                return _a;
            }

            set
            {
                _a = value;
            }
        }

        public bool B
        {
            get
            {
                return _b;
            }

            set
            {
                _b = value;
            }
        }

        public bool I
        {
            get
            {
                return _i;
            }

            set
            {
                _i = value;
            }
        }

        public int HardwareSetQty
        {
            get
            {
                return _hardwareSetQty;
            }

            set
            {
                _hardwareSetQty = value;
            }
        }

        public int OrderCount
        {
            get
            {
                return _orderCount;
            }

            set
            {
                _orderCount = value;
            }
        }

        public int Orderable
        {
            get
            {
                return _orderable;
            }

            set
            {
                _orderable = value;
            }
        }
    }
}
