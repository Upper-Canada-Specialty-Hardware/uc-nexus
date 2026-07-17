using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    public class Frame
    {
        int _frameId;
        int _projectId;
        string _archType;
        string _name;
        string _description;
        string _manufacturer;
        string _vendorName;
        string _materialCode;
        string _materialName;
        string _notes;
        bool _shopWeld;
        string _shopWeldConstructionAttrDescription;
        string _weldTypeCode;
        string _weldTypeDescription;
        string _userDefined1;
        string _userDefined2;
        string _userDefined3;
        string _userDefined4;
        string _userDefined5;
        int _labor;
        int _installation;
        bool _customElevation;
        string _orderSpecialInstructions;
        string _fscLeedCode;
        int _openingQty;
        string _apogeeWidth;
        string _apogeeHeight;
        string _apogeeJambDepth;
        string _apogeeStyle;
        string _apogeeHanding;
        bool _hasAttachment;
        FrameAttribute[]  _attributes;
        string _frameAddOn;
        string _frameAnchor;
        string _frameBackType;
        string _frameBlankdescriptionforwoodframe;
        string _frameColor;
        string _frameConstruction;
        string _frameElevationType;
        string _frameFinish;
        string _frameGauge;
        string _frameHdwPrep;
        string _frameHeadFace;
        string _frameHeadMullion;
        string _frameJambFace;
        string _frameJambMullion;
        string _frameJambThickness;
        string _frameLabel;
        string _frameMemberType;
        string _frameMfrLocation;
        string _frameNONEHMF;
        string _frameNONESSF;
        string _framePackaging;
        string _frameProfile;
        string _frameScribe;
        string _frameSKU;
        string _frameStop;
        string _frameSpecies;
        string _frameSteelType;
        string _frameSurface;
        string _frameThroat;
        string _frameTrim;

        public int FrameId
        {
            get
            {
                return _frameId;
            }

            set
            {
                _frameId = value;
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

        public bool ShopWeld
        {
            get
            {
                return _shopWeld;
            }

            set
            {
                _shopWeld = value;
            }
        }

        public string ShopWeldConstructionAttrDescription
        {
            get
            {
                return _shopWeldConstructionAttrDescription;
            }

            set
            {
                _shopWeldConstructionAttrDescription = value;
            }
        }

        public string WeldTypeCode
        {
            get
            {
                return _weldTypeCode;
            }

            set
            {
                _weldTypeCode = value;
            }
        }

        public string WeldTypeDescription
        {
            get
            {
                return _weldTypeDescription;
            }

            set
            {
                _weldTypeDescription = value;
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

        public string FscLeedCode
        {
            get
            {
                return _fscLeedCode;
            }

            set
            {
                _fscLeedCode = value;
            }
        }

        public int OpeningQty
        {
            get
            {
                return _openingQty;
            }

            set
            {
                _openingQty = value;
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

        public string ApogeeJambDepth
        {
            get
            {
                return _apogeeJambDepth;
            }

            set
            {
                _apogeeJambDepth = value;
            }
        }

        public string ApogeeStyle
        {
            get
            {
                return _apogeeStyle;
            }

            set
            {
                _apogeeStyle = value;
            }
        }

        public string ApogeeHanding
        {
            get
            {
                return _apogeeHanding;
            }

            set
            {
                _apogeeHanding = value;
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

        internal FrameAttribute[] Attributes
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

        public string FrameAddOn
        {
            get
            {
                return _frameAddOn;
            }

            set
            {
                _frameAddOn = value;
            }
        }

        public string FrameAnchor
        {
            get
            {
                return _frameAnchor;
            }

            set
            {
                _frameAnchor = value;
            }
        }

        public string FrameBackType
        {
            get
            {
                return _frameBackType;
            }

            set
            {
                _frameBackType = value;
            }
        }

        public string FrameBlankdescriptionforwoodframe
        {
            get
            {
                return _frameBlankdescriptionforwoodframe;
            }

            set
            {
                _frameBlankdescriptionforwoodframe = value;
            }
        }

        public string FrameColor
        {
            get
            {
                return _frameColor;
            }

            set
            {
                _frameColor = value;
            }
        }

        public string FrameConstruction
        {
            get
            {
                return _frameConstruction;
            }

            set
            {
                _frameConstruction = value;
            }
        }

        public string FrameElevationType
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

        public string FrameFinish
        {
            get
            {
                return _frameFinish;
            }

            set
            {
                _frameFinish = value;
            }
        }

        public string FrameGauge
        {
            get
            {
                return _frameGauge;
            }

            set
            {
                _frameGauge = value;
            }
        }

        public string FrameHdwPrep
        {
            get
            {
                return _frameHdwPrep;
            }

            set
            {
                _frameHdwPrep = value;
            }
        }

        public string FrameHeadFace
        {
            get
            {
                return _frameHeadFace;
            }

            set
            {
                _frameHeadFace = value;
            }
        }

        public string FrameHeadMullion
        {
            get
            {
                return _frameHeadMullion;
            }

            set
            {
                _frameHeadMullion = value;
            }
        }

        public string FrameJambFace
        {
            get
            {
                return _frameJambFace;
            }

            set
            {
                _frameJambFace = value;
            }
        }

        public string FrameJambMullion
        {
            get
            {
                return _frameJambMullion;
            }

            set
            {
                _frameJambMullion = value;
            }
        }

        public string FrameJambThickness
        {
            get
            {
                return _frameJambThickness;
            }

            set
            {
                _frameJambThickness = value;
            }
        }

        public string FrameLabel
        {
            get
            {
                return _frameLabel;
            }

            set
            {
                _frameLabel = value;
            }
        }

        public string FrameMemberType
        {
            get
            {
                return _frameMemberType;
            }

            set
            {
                _frameMemberType = value;
            }
        }

        public string FrameMfrLocation
        {
            get
            {
                return _frameMfrLocation;
            }

            set
            {
                _frameMfrLocation = value;
            }
        }

        public string FrameNONEHMF
        {
            get
            {
                return _frameNONEHMF;
            }

            set
            {
                _frameNONEHMF = value;
            }
        }

        public string FrameNONESSF
        {
            get
            {
                return _frameNONESSF;
            }

            set
            {
                _frameNONESSF = value;
            }
        }

        public string FramePackaging
        {
            get
            {
                return _framePackaging;
            }

            set
            {
                _framePackaging = value;
            }
        }

        public string FrameProfile
        {
            get
            {
                return _frameProfile;
            }

            set
            {
                _frameProfile = value;
            }
        }

        public string FrameScribe
        {
            get
            {
                return _frameScribe;
            }

            set
            {
                _frameScribe = value;
            }
        }

        public string FrameSKU
        {
            get
            {
                return _frameSKU;
            }

            set
            {
                _frameSKU = value;
            }
        }

        public string FrameStop
        {
            get
            {
                return _frameStop;
            }

            set
            {
                _frameStop = value;
            }
        }

        public string FrameSpecies
        {
            get
            {
                return _frameSpecies;
            }

            set
            {
                _frameSpecies = value;
            }
        }

        public string FrameSteelType
        {
            get
            {
                return _frameSteelType;
            }

            set
            {
                _frameSteelType = value;
            }
        }

        public string FrameSurface
        {
            get
            {
                return _frameSurface;
            }

            set
            {
                _frameSurface = value;
            }
        }

        public string FrameThroat
        {
            get
            {
                return _frameThroat;
            }

            set
            {
                _frameThroat = value;
            }
        }

        public string FrameTrim
        {
            get
            {
                return _frameTrim;
            }

            set
            {
                _frameTrim = value;
            }
        }

    }
}
