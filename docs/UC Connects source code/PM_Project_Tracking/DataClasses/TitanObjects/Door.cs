using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    public class Door
    {
        int _doorId;
        int _projectId;
        string _archType;
        string _name;
        string _description;
        string _manufacturer;
        string _vendorName;
        string _materialCode;
        string _materialName;
        string _notes;
        string _userDefined1;
        string _userDefined2;
        string _userDefined3;
        string _userDefined4;
        string _userDefined5;
        int _labor;
        int _installation;
        bool _customElevation;
        string _orderSpecialInstructions;
        int _openingDoorQty;
        string _apogeeWidth;
        string _apogeeHeight;
        string _apogeeThickness;
        bool _hasAttachment;
        string[] _fscLeedValue;
        DoorAttribute[] _attributes;
        string _doorAddOn;
        string _doorBevel;
        string _doorBlocking;
        string _doorBottomRail;
        string _doorColor;
        string _doorCore;
        string _doorEdge;
        string _doorFaceType;
        string _doorFinish;
        string _doorGauge;
        string _doorGlass;
        string _doorGroup;
        string _doorHdwPrep;
        string _doorLabel;
        string _doorLouver;
        string _doorMfrLocation;
        string _doorMoulding;
        string _doorMuntinBar;
        string _doorNONEHMD;
        string _doorNONESSD;
        string _doorNONEWDD;
        string _doorQuantity;
        string _doorSeries;
        string _doorSet;
        string _doorSpecies;
        string _doorSteelType;
        string _doorStile;
        string _doorSurface;
        string _doorTopRail;
        string _doorVisionKit;

        public int DoorId
        {
            get
            {
                return _doorId;
            }

            set
            {
                _doorId = value;
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

        public string ArchType
        {
            get
            {
                return _archType;
            }

            set
            {
                _archType = value;
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

        public string Manufacturer
        {
            get
            {
                return _manufacturer;
            }

            set
            {
                _manufacturer = value;
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

        public string MaterialName
        {
            get
            {
                return _materialName;
            }

            set
            {
                _materialName = value;
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

        public bool CustomElevation
        {
            get
            {
                return _customElevation;
            }

            set
            {
                _customElevation = value;
            }
        }

        public string OrderSpecialInstructions
        {
            get
            {
                return _orderSpecialInstructions;
            }

            set
            {
                _orderSpecialInstructions = value;
            }
        }

        public int OpeningDoorQty
        {
            get
            {
                return _openingDoorQty;
            }

            set
            {
                _openingDoorQty = value;
            }
        }

        public string ApogeeWidth
        {
            get
            {
                return _apogeeWidth;
            }

            set
            {
                _apogeeWidth = value;
            }
        }

        public string ApogeeHeight
        {
            get
            {
                return _apogeeHeight;
            }

            set
            {
                _apogeeHeight = value;
            }
        }

        public string ApogeeThickness
        {
            get
            {
                return _apogeeThickness;
            }

            set
            {
                _apogeeThickness = value;
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

        public string[] FscLeedValue
        {
            get
            {
                return _fscLeedValue;
            }

            set
            {
                _fscLeedValue = value;
            }
        }

        internal DoorAttribute[] Attributes
        {
            get
            {
                return _attributes;
            }

            set
            {
                _attributes = value;
            }
        }

        public string DoorAddOn
        {
            get
            {
                return _doorAddOn;
            }

            set
            {
                _doorAddOn = value;
            }
        }

        public string DoorBevel
        {
            get
            {
                return _doorBevel;
            }

            set
            {
                _doorBevel = value;
            }
        }

        public string DoorBlocking
        {
            get
            {
                return _doorBlocking;
            }

            set
            {
                _doorBlocking = value;
            }
        }

        public string DoorBottomRail
        {
            get
            {
                return _doorBottomRail;
            }

            set
            {
                _doorBottomRail = value;
            }
        }

        public string DoorColor
        {
            get
            {
                return _doorColor;
            }

            set
            {
                _doorColor = value;
            }
        }

        public string DoorCore
        {
            get
            {
                return _doorCore;
            }

            set
            {
                _doorCore = value;
            }
        }

        public string DoorEdge
        {
            get
            {
                return _doorEdge;
            }

            set
            {
                _doorEdge = value;
            }
        }

        public string DoorFaceType
        {
            get
            {
                return _doorFaceType;
            }

            set
            {
                _doorFaceType = value;
            }
        }

        public string DoorFinish
        {
            get
            {
                return _doorFinish;
            }

            set
            {
                _doorFinish = value;
            }
        }

        public string DoorGauge
        {
            get
            {
                return _doorGauge;
            }

            set
            {
                _doorGauge = value;
            }
        }

        public string DoorGlass
        {
            get
            {
                return _doorGlass;
            }

            set
            {
                _doorGlass = value;
            }
        }

        public string DoorGroup
        {
            get
            {
                return _doorGroup;
            }

            set
            {
                _doorGroup = value;
            }
        }

        public string DoorHdwPrep
        {
            get
            {
                return _doorHdwPrep;
            }

            set
            {
                _doorHdwPrep = value;
            }
        }

        public string DoorLabel
        {
            get
            {
                return _doorLabel;
            }

            set
            {
                _doorLabel = value;
            }
        }

        public string DoorLouver
        {
            get
            {
                return _doorLouver;
            }

            set
            {
                _doorLouver = value;
            }
        }

        public string DoorMfrLocation
        {
            get
            {
                return _doorMfrLocation;
            }

            set
            {
                _doorMfrLocation = value;
            }
        }

        public string DoorMoulding
        {
            get
            {
                return _doorMoulding;
            }

            set
            {
                _doorMoulding = value;
            }
        }

        public string DoorMuntinBar
        {
            get
            {
                return _doorMuntinBar;
            }

            set
            {
                _doorMuntinBar = value;
            }
        }

        public string DoorNONEHMD
        {
            get
            {
                return _doorNONEHMD;
            }

            set
            {
                _doorNONEHMD = value;
            }
        }

        public string DoorNONESSD
        {
            get
            {
                return _doorNONESSD;
            }

            set
            {
                _doorNONESSD = value;
            }
        }

        public string DoorNONEWDD
        {
            get
            {
                return _doorNONEWDD;
            }

            set
            {
                _doorNONEWDD = value;
            }
        }

        public string DoorQuantity
        {
            get
            {
                return _doorQuantity;
            }

            set
            {
                _doorQuantity = value;
            }
        }

        public string DoorSeries
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

        public string DoorSet
        {
            get
            {
                return _doorSet;
            }

            set
            {
                _doorSet = value;
            }
        }

        public string DoorSpecies
        {
            get
            {
                return _doorSpecies;
            }

            set
            {
                _doorSpecies = value;
            }
        }

        public string DoorSteelType
        {
            get
            {
                return _doorSteelType;
            }

            set
            {
                _doorSteelType = value;
            }
        }

        public string DoorStile
        {
            get
            {
                return _doorStile;
            }

            set
            {
                _doorStile = value;
            }
        }

        public string DoorSurface
        {
            get
            {
                return _doorSurface;
            }

            set
            {
                _doorSurface = value;
            }
        }

        public string DoorTopRail
        {
            get
            {
                return _doorTopRail;
            }

            set
            {
                _doorTopRail = value;
            }
        }

        public string DoorVisionKit
        {
            get
            {
                return _doorVisionKit;
            }

            set
            {
                _doorVisionKit = value;
            }
        }

    }
}
