using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    public class Hardware
    {
        int _hardwareId;
        int _projectId;
        string _projectName;
        string _vendorName;
        string _vendorAbbr;
        string _materialCode;
        string _priceBookDescription;
        string _hdwTypeId;
        string _hdwTypeDescription;
        int _sortOrder;
        int _sequence;
        string _item;
        string _printDescription;
        string _partDescriptionWithModifiers;
        string _orderDescription;
        string _hdwStdDescription;
        string _sku;
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
        decimal _extendedListCost;
        decimal _extendedCost;
        int _labor;
        int _installation;
        string _doorPrep1Code;
        string _doorPrep2Code;
        string _framePrep1Code;
        string _framePrep2Code;
        string _inactivePrepCode;
        int _cylinders;
        bool _deadlock;
        bool _electric;
        bool _handed;
        bool _byOthers;
        string _byOthersSupplier;
        bool _hdwUsed;
        bool _priceBookMismatch;
        string _allAttributeXrefs;
        bool _hasAttachment;
        string _vendorNotificationText;
        string _exportXref;
        string _exportModifierXrefs;
        int _totalQty;
        int _openingPlusQty;

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

        public string MaterialCode
        {
            get
            {
                return _materialCode;
            }

            set
            {
                _materialCode = value;
            }
        }

        public string PriceBookDescription
        {
            get
            {
                return _priceBookDescription;
            }

            set
            {
                _priceBookDescription = value;
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

        public string PartDescriptionWithModifiers
        {
            get
            {
                return _partDescriptionWithModifiers;
            }

            set
            {
                _partDescriptionWithModifiers = value;
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

        public string Sku
        {
            get
            {
                return _sku;
            }

            set
            {
                _sku = value;
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

        public decimal ExtendedListCost
        {
            get
            {
                return _extendedListCost;
            }

            set
            {
                _extendedListCost = value;
            }
        }

        public decimal ExtendedCost
        {
            get
            {
                return _extendedCost;
            }

            set
            {
                _extendedCost = value;
            }
        }

        public int Labor
        {
            get
            {
                return _labor;
            }

            set
            {
                _labor = value;
            }
        }

        public int Installation
        {
            get
            {
                return _installation;
            }

            set
            {
                _installation = value;
            }
        }

        public string DoorPrep1Code
        {
            get
            {
                return _doorPrep1Code;
            }

            set
            {
                _doorPrep1Code = value;
            }
        }

        public string DoorPrep2Code
        {
            get
            {
                return _doorPrep2Code;
            }

            set
            {
                _doorPrep2Code = value;
            }
        }

        public string FramePrep1Code
        {
            get
            {
                return _framePrep1Code;
            }

            set
            {
                _framePrep1Code = value;
            }
        }

        public string FramePrep2Code
        {
            get
            {
                return _framePrep2Code;
            }

            set
            {
                _framePrep2Code = value;
            }
        }

        public string InactivePrepCode
        {
            get
            {
                return _inactivePrepCode;
            }

            set
            {
                _inactivePrepCode = value;
            }
        }

        public int Cylinders
        {
            get
            {
                return _cylinders;
            }

            set
            {
                _cylinders = value;
            }
        }

        public bool Deadlock
        {
            get
            {
                return _deadlock;
            }

            set
            {
                _deadlock = value;
            }
        }

        public bool Electric
        {
            get
            {
                return _electric;
            }

            set
            {
                _electric = value;
            }
        }

        public bool Handed
        {
            get
            {
                return _handed;
            }

            set
            {
                _handed = value;
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

        public bool HdwUsed
        {
            get
            {
                return _hdwUsed;
            }

            set
            {
                _hdwUsed = value;
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

        public string AllAttributeXrefs
        {
            get
            {
                return _allAttributeXrefs;
            }

            set
            {
                _allAttributeXrefs = value;
            }
        }

        public bool HasAttachment
        {
            get
            {
                return _hasAttachment;
            }

            set
            {
                _hasAttachment = value;
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

        public string ExportXref
        {
            get
            {
                return _exportXref;
            }

            set
            {
                _exportXref = value;
            }
        }

        public string ExportModifierXrefs
        {
            get
            {
                return _exportModifierXrefs;
            }

            set
            {
                _exportModifierXrefs = value;
            }
        }

        public int TotalQty
        {
            get
            {
                return _totalQty;
            }

            set
            {
                _totalQty = value;
            }
        }

        public int OpeningPlusQty
        {
            get
            {
                return _openingPlusQty;
            }

            set
            {
                _openingPlusQty = value;
            }
        }
    }
}
