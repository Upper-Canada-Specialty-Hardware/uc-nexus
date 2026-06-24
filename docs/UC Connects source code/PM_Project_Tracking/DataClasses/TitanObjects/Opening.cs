using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    class Opening
    {
        int _openingId;
        int _projectId;
        string _projectName;
        string _openingTypeCode;
        bool _bank;
        bool _needsAttention;
        string _mark;
        string _groupName;
        int _qty;
        string _style;
        string _width;
        string _height;
        string _jambDepth;
        string _handCode;
        string _label;
        string _description;
        bool _exterior;
        string _location1;
        string _fromTo;
        string _location2;
        string _wallType;
        string _wallThickness;
        string _frameType;
        string _frameMaterial;
        string _frameMaterialCode;
        string _frameVendor;
        string _hardwareSetName;
        string _notes;
        string _userDefined1;
        string _userDefined2;
        string _userDefined3;
        string _userDefined4;
        string _userDefined5;
        decimal _frameListCost;
        decimal _frameCost;
        decimal _frameWeldListCost;
        decimal _frameWeldCost;
        decimal _frameShopWeldCost;
        decimal _frameTotalCost;
        bool _frameSpecialNet;
        decimal _frameSpecialNetCost;
        int _jointCount;
        string _overallWidth;
        string _overallHeight;
        string _building;
        string _level;
        string _curtainPanel;
        bool _installed;
        string _locations;
        bool _locationException;
        string _needBy;
        string _architectsMark;
        string _architectsLabel;
        string _architectsJamb;
        string _architectsHead;
        string _architectsSill;
        bool _preHung;
        bool _existingFrame;
        bool _frameByOthers;
        string _frameByOthersSupplier;
        decimal _existingDoor;
        decimal _doorByOthers;
        decimal _doorByOthersSupplier;
        decimal _openingDoors;
        decimal _openingDoorName;
        decimal _openingDoorListCosts;
        decimal _openingDoorCosts;
        decimal _doorQty;
        decimal _doorMaterial;
        decimal _doorMaterialCode;
        decimal _doorVendor;
        decimal _doorSeries;
        decimal _frameElevationType;
        decimal _degrees;
        decimal _orderLineItemQty;
        decimal _orderLineItemFrameQty;
        decimal _hasAttachment;
        decimal _doorsUnorderedQty;
        decimal _extendedFrameCost;
        decimal _extendedDoorCost;
        decimal _openingListCosts;

        public int OpeningId
        {
            get
            {
                return _openingId;
            }

            set
            {
                _openingId = value;
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

        public string OpeningTypeCode
        {
            get
            {
                return _openingTypeCode;
            }

            set
            {
                _openingTypeCode = value;
            }
        }

        public bool Bank
        {
            get
            {
                return _bank;
            }

            set
            {
                _bank = value;
            }
        }

        public bool NeedsAttention
        {
            get
            {
                return _needsAttention;
            }

            set
            {
                _needsAttention = value;
            }
        }

        public string Mark
        {
            get
            {
                return _mark;
            }

            set
            {
                _mark = value;
            }
        }

        public string GroupName
        {
            get
            {
                return _groupName;
            }

            set
            {
                _groupName = value;
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

        public string Style
        {
            get
            {
                return _style;
            }

            set
            {
                _style = value;
            }
        }

        public string Width
        {
            get
            {
                return _width;
            }

            set
            {
                _width = value;
            }
        }

        public string Height
        {
            get
            {
                return _height;
            }

            set
            {
                _height = value;
            }
        }

        public string JambDepth
        {
            get
            {
                return _jambDepth;
            }

            set
            {
                _jambDepth = value;
            }
        }

        public string HandCode
        {
            get
            {
                return _handCode;
            }

            set
            {
                _handCode = value;
            }
        }

        public string Label
        {
            get
            {
                return _label;
            }

            set
            {
                _label = value;
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

        public bool Exterior
        {
            get
            {
                return _exterior;
            }

            set
            {
                _exterior = value;
            }
        }

        public string Location1
        {
            get
            {
                return _location1;
            }

            set
            {
                _location1 = value;
            }
        }

        public string FromTo
        {
            get
            {
                return _fromTo;
            }

            set
            {
                _fromTo = value;
            }
        }

        public string Location2
        {
            get
            {
                return _location2;
            }

            set
            {
                _location2 = value;
            }
        }

        public string WallType
        {
            get
            {
                return _wallType;
            }

            set
            {
                _wallType = value;
            }
        }

        public string WallThickness
        {
            get
            {
                return _wallThickness;
            }

            set
            {
                _wallThickness = value;
            }
        }

        public string FrameType
        {
            get
            {
                return _frameType;
            }

            set
            {
                _frameType = value;
            }
        }

        public string FrameMaterial
        {
            get
            {
                return _frameMaterial;
            }

            set
            {
                _frameMaterial = value;
            }
        }

        public string FrameMaterialCode
        {
            get
            {
                return _frameMaterialCode;
            }

            set
            {
                _frameMaterialCode = value;
            }
        }

        public string FrameVendor
        {
            get
            {
                return _frameVendor;
            }

            set
            {
                _frameVendor = value;
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

        public string UserDefined1
        {
            get
            {
                return _userDefined1;
            }

            set
            {
                _userDefined1 = value;
            }
        }

        public string UserDefined2
        {
            get
            {
                return _userDefined2;
            }

            set
            {
                _userDefined2 = value;
            }
        }

        public string UserDefined3
        {
            get
            {
                return _userDefined3;
            }

            set
            {
                _userDefined3 = value;
            }
        }

        public string UserDefined4
        {
            get
            {
                return _userDefined4;
            }

            set
            {
                _userDefined4 = value;
            }
        }

        public string UserDefined5
        {
            get
            {
                return _userDefined5;
            }

            set
            {
                _userDefined5 = value;
            }
        }

        public decimal FrameListCost
        {
            get
            {
                return _frameListCost;
            }

            set
            {
                _frameListCost = value;
            }
        }

        public decimal FrameCost
        {
            get
            {
                return _frameCost;
            }

            set
            {
                _frameCost = value;
            }
        }

        public decimal FrameWeldListCost
        {
            get
            {
                return _frameWeldListCost;
            }

            set
            {
                _frameWeldListCost = value;
            }
        }

        public decimal FrameWeldCost
        {
            get
            {
                return _frameWeldCost;
            }

            set
            {
                _frameWeldCost = value;
            }
        }

        public decimal FrameShopWeldCost
        {
            get
            {
                return _frameShopWeldCost;
            }

            set
            {
                _frameShopWeldCost = value;
            }
        }

        public decimal FrameTotalCost
        {
            get
            {
                return _frameTotalCost;
            }

            set
            {
                _frameTotalCost = value;
            }
        }

        public bool FrameSpecialNet
        {
            get
            {
                return _frameSpecialNet;
            }

            set
            {
                _frameSpecialNet = value;
            }
        }

        public decimal FrameSpecialNetCost
        {
            get
            {
                return _frameSpecialNetCost;
            }

            set
            {
                _frameSpecialNetCost = value;
            }
        }

        public int JointCount
        {
            get
            {
                return _jointCount;
            }

            set
            {
                _jointCount = value;
            }
        }

        public string OverallWidth
        {
            get
            {
                return _overallWidth;
            }

            set
            {
                _overallWidth = value;
            }
        }

        public string OverallHeight
        {
            get
            {
                return _overallHeight;
            }

            set
            {
                _overallHeight = value;
            }
        }

        public string Building
        {
            get
            {
                return _building;
            }

            set
            {
                _building = value;
            }
        }

        public string Level
        {
            get
            {
                return _level;
            }

            set
            {
                _level = value;
            }
        }

        public string CurtainPanel
        {
            get
            {
                return _curtainPanel;
            }

            set
            {
                _curtainPanel = value;
            }
        }

        public bool Installed
        {
            get
            {
                return _installed;
            }

            set
            {
                _installed = value;
            }
        }

        public string Locations
        {
            get
            {
                return _locations;
            }

            set
            {
                _locations = value;
            }
        }

        public bool LocationException
        {
            get
            {
                return _locationException;
            }

            set
            {
                _locationException = value;
            }
        }

        public string NeedBy
        {
            get
            {
                return _needBy;
            }

            set
            {
                _needBy = value;
            }
        }

        public string ArchitectsMark
        {
            get
            {
                return _architectsMark;
            }

            set
            {
                _architectsMark = value;
            }
        }

        public string ArchitectsLabel
        {
            get
            {
                return _architectsLabel;
            }

            set
            {
                _architectsLabel = value;
            }
        }

        public string ArchitectsJamb
        {
            get
            {
                return _architectsJamb;
            }

            set
            {
                _architectsJamb = value;
            }
        }

        public string ArchitectsHead
        {
            get
            {
                return _architectsHead;
            }

            set
            {
                _architectsHead = value;
            }
        }

        public string ArchitectsSill
        {
            get
            {
                return _architectsSill;
            }

            set
            {
                _architectsSill = value;
            }
        }

        public bool PreHung
        {
            get
            {
                return _preHung;
            }

            set
            {
                _preHung = value;
            }
        }

        public bool ExistingFrame
        {
            get
            {
                return _existingFrame;
            }

            set
            {
                _existingFrame = value;
            }
        }

        public bool FrameByOthers
        {
            get
            {
                return _frameByOthers;
            }

            set
            {
                _frameByOthers = value;
            }
        }

        public string FrameByOthersSupplier
        {
            get
            {
                return _frameByOthersSupplier;
            }

            set
            {
                _frameByOthersSupplier = value;
            }
        }

        public decimal ExistingDoor
        {
            get
            {
                return _existingDoor;
            }

            set
            {
                _existingDoor = value;
            }
        }

        public decimal DoorByOthers
        {
            get
            {
                return _doorByOthers;
            }

            set
            {
                _doorByOthers = value;
            }
        }

        public decimal DoorByOthersSupplier
        {
            get
            {
                return _doorByOthersSupplier;
            }

            set
            {
                _doorByOthersSupplier = value;
            }
        }

        public decimal OpeningDoors
        {
            get
            {
                return _openingDoors;
            }

            set
            {
                _openingDoors = value;
            }
        }

        public decimal OpeningDoorName
        {
            get
            {
                return _openingDoorName;
            }

            set
            {
                _openingDoorName = value;
            }
        }

        public decimal OpeningDoorListCosts
        {
            get
            {
                return _openingDoorListCosts;
            }

            set
            {
                _openingDoorListCosts = value;
            }
        }

        public decimal OpeningDoorCosts
        {
            get
            {
                return _openingDoorCosts;
            }

            set
            {
                _openingDoorCosts = value;
            }
        }

        public decimal DoorQty
        {
            get
            {
                return _doorQty;
            }

            set
            {
                _doorQty = value;
            }
        }

        public decimal DoorMaterial
        {
            get
            {
                return _doorMaterial;
            }

            set
            {
                _doorMaterial = value;
            }
        }

        public decimal DoorMaterialCode
        {
            get
            {
                return _doorMaterialCode;
            }

            set
            {
                _doorMaterialCode = value;
            }
        }

        public decimal DoorVendor
        {
            get
            {
                return _doorVendor;
            }

            set
            {
                _doorVendor = value;
            }
        }

        public decimal DoorSeries
        {
            get
            {
                return _doorSeries;
            }

            set
            {
                _doorSeries = value;
            }
        }

        public decimal FrameElevationType
        {
            get
            {
                return _frameElevationType;
            }

            set
            {
                _frameElevationType = value;
            }
        }

        public decimal Degrees
        {
            get
            {
                return _degrees;
            }

            set
            {
                _degrees = value;
            }
        }

        public decimal OrderLineItemQty
        {
            get
            {
                return _orderLineItemQty;
            }

            set
            {
                _orderLineItemQty = value;
            }
        }

        public decimal OrderLineItemFrameQty
        {
            get
            {
                return _orderLineItemFrameQty;
            }

            set
            {
                _orderLineItemFrameQty = value;
            }
        }

        public decimal HasAttachment
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

        public decimal DoorsUnorderedQty
        {
            get
            {
                return _doorsUnorderedQty;
            }

            set
            {
                _doorsUnorderedQty = value;
            }
        }

        public decimal ExtendedFrameCost
        {
            get
            {
                return _extendedFrameCost;
            }

            set
            {
                _extendedFrameCost = value;
            }
        }

        public decimal ExtendedDoorCost
        {
            get
            {
                return _extendedDoorCost;
            }

            set
            {
                _extendedDoorCost = value;
            }
        }

        public decimal OpeningListCosts
        {
            get
            {
                return _openingListCosts;
            }

            set
            {
                _openingListCosts = value;
            }
        }
    }
}
