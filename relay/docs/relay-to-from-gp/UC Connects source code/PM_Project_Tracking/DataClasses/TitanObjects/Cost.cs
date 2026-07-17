using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.TitanObjects
{
    class Cost
    {
        int _displayOrder;
        string _mark;
        int _baseOpeningId;
        int _changeOpeningId;
        int _baseOpeningQty;
        int _changeOpeningQty;
        string _typeCode;
        string _item;
        string _description;
        string _descriptionDisplay;
        string _itemSeqId;
        string _baseVendorName;
        string _vendorName;
        string _materialCode;
        string _materialName;
        int _baseItemQty;
        int _changeItemQty;
        string _partNumber;
        decimal _baseListCost;
        decimal _baseCost;
        decimal _baseSellPrice;
        decimal _changeListCost;
        decimal _changeSellPrice;
        decimal _discount;
        decimal _deltaCost;
        bool _useDeltaCost;
        decimal _finalCost;
        int _qty;
        decimal _extendedCost;
        decimal _markup;
        decimal _sellPriceAdjustment;
        decimal _sellPrice;
        decimal _freightBasis;
        decimal _freightBasisWithMarkup;
        decimal _freight;
        decimal _tax;
        decimal _totalAdjust;
        decimal _margin;
        string _comment;
        decimal _proposalPrice;
        int _totalQty;
        decimal _totalListCost;
        decimal _totalCost;
        decimal _totalExtendedCost;
        decimal _extendedProposalPrice;
        decimal _freightCost;

        public int DisplayOrder
        {
            get
            {
                return _displayOrder;
            }

            set
            {
                _displayOrder = value;
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

        public int BaseOpeningId
        {
            get
            {
                return _baseOpeningId;
            }

            set
            {
                _baseOpeningId = value;
            }
        }

        public int ChangeOpeningId
        {
            get
            {
                return _changeOpeningId;
            }

            set
            {
                _changeOpeningId = value;
            }
        }

        public int BaseOpeningQty
        {
            get
            {
                return _baseOpeningQty;
            }

            set
            {
                _baseOpeningQty = value;
            }
        }

        public int ChangeOpeningQty
        {
            get
            {
                return _changeOpeningQty;
            }

            set
            {
                _changeOpeningQty = value;
            }
        }

        public string TypeCode
        {
            get
            {
                return _typeCode;
            }

            set
            {
                _typeCode = value;
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

        public string DescriptionDisplay
        {
            get
            {
                return _descriptionDisplay;
            }

            set
            {
                _descriptionDisplay = value;
            }
        }

        public string ItemSeqId
        {
            get
            {
                return _itemSeqId;
            }

            set
            {
                _itemSeqId = value;
            }
        }

        public string BaseVendorName
        {
            get
            {
                return _baseVendorName;
            }

            set
            {
                _baseVendorName = value;
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

        public int BaseItemQty
        {
            get
            {
                return _baseItemQty;
            }

            set
            {
                _baseItemQty = value;
            }
        }

        public int ChangeItemQty
        {
            get
            {
                return _changeItemQty;
            }

            set
            {
                _changeItemQty = value;
            }
        }

        public string PartNumber
        {
            get
            {
                return _partNumber;
            }

            set
            {
                _partNumber = value;
            }
        }

        public decimal BaseListCost
        {
            get
            {
                return _baseListCost;
            }

            set
            {
                _baseListCost = value;
            }
        }

        public decimal BaseCost
        {
            get
            {
                return _baseCost;
            }

            set
            {
                _baseCost = value;
            }
        }

        public decimal BaseSellPrice
        {
            get
            {
                return _baseSellPrice;
            }

            set
            {
                _baseSellPrice = value;
            }
        }

        public decimal ChangeListCost
        {
            get
            {
                return _changeListCost;
            }

            set
            {
                _changeListCost = value;
            }
        }

        public decimal ChangeSellPrice
        {
            get
            {
                return _changeSellPrice;
            }

            set
            {
                _changeSellPrice = value;
            }
        }

        public decimal Discount
        {
            get
            {
                return _discount;
            }

            set
            {
                _discount = value;
            }
        }

        public decimal DeltaCost
        {
            get
            {
                return _deltaCost;
            }

            set
            {
                _deltaCost = value;
            }
        }

        public bool UseDeltaCost
        {
            get
            {
                return _useDeltaCost;
            }

            set
            {
                _useDeltaCost = value;
            }
        }

        public decimal FinalCost
        {
            get
            {
                return _finalCost;
            }

            set
            {
                _finalCost = value;
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

        public decimal Markup
        {
            get
            {
                return _markup;
            }

            set
            {
                _markup = value;
            }
        }

        public decimal SellPriceAdjustment
        {
            get
            {
                return _sellPriceAdjustment;
            }

            set
            {
                _sellPriceAdjustment = value;
            }
        }

        public decimal SellPrice
        {
            get
            {
                return _sellPrice;
            }

            set
            {
                _sellPrice = value;
            }
        }

        public decimal FreightBasis
        {
            get
            {
                return _freightBasis;
            }

            set
            {
                _freightBasis = value;
            }
        }

        public decimal FreightBasisWithMarkup
        {
            get
            {
                return _freightBasisWithMarkup;
            }

            set
            {
                _freightBasisWithMarkup = value;
            }
        }

        public decimal Freight
        {
            get
            {
                return _freight;
            }

            set
            {
                _freight = value;
            }
        }

        public decimal Tax
        {
            get
            {
                return _tax;
            }

            set
            {
                _tax = value;
            }
        }

        public decimal TotalAdjust
        {
            get
            {
                return _totalAdjust;
            }

            set
            {
                _totalAdjust = value;
            }
        }

        public decimal Margin
        {
            get
            {
                return _margin;
            }

            set
            {
                _margin = value;
            }
        }

        public string Comment
        {
            get
            {
                return _comment;
            }

            set
            {
                _comment = value;
            }
        }

        public decimal ProposalPrice
        {
            get
            {
                return _proposalPrice;
            }

            set
            {
                _proposalPrice = value;
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

        public decimal TotalListCost
        {
            get
            {
                return _totalListCost;
            }

            set
            {
                _totalListCost = value;
            }
        }

        public decimal TotalCost
        {
            get
            {
                return _totalCost;
            }

            set
            {
                _totalCost = value;
            }
        }

        public decimal TotalExtendedCost
        {
            get
            {
                return _totalExtendedCost;
            }

            set
            {
                _totalExtendedCost = value;
            }
        }

        public decimal ExtendedProposalPrice
        {
            get
            {
                return _extendedProposalPrice;
            }

            set
            {
                _extendedProposalPrice = value;
            }
        }

        public decimal FreightCost
        {
            get
            {
                return _freightCost;
            }

            set
            {
                _freightCost = value;
            }
        }
    }
}
