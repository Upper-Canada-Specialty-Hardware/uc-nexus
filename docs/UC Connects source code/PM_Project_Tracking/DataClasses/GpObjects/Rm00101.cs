using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking.DataClasses.GpObjects
{
    [mp.Table(Name = "[RM00101]")]
    public class Rm00101
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _customerNumber;
        private string _customerName;
        private string _addressCode;
        private string _address;
        private string _address2;
        private string _city;
        private string _province;
        private string _country;
        private string _postalCode;
        private string _phoneNumber;
        private string _faxNumber;
        private string _paymentTermId;
        private string _taxSchedId;
        private string _unifiedAddress;

        [mp.Column(Name = "CUSTNMBR", IsPrimaryKey = true)]
        public string CustomerNumber
        {
            get { return _customerNumber; }
            set { _customerNumber = value; }
        }

        [mp.Column(Name = "CUSTNAME")]
        public string CustomerName
        {
            get { return _customerName; }
            set { _customerName = value; }
        }

        [mp.Column(Name = "ADRSCODE")]
        public string AddressCode
        {
            get { return _addressCode; }
            set
            {
                _addressCode = value;
                //OnPropertyChanged("AddressCode");
            }
        }

        [mp.Column(Name = "ADDRESS1")]
        public string Address
        {
            get { return _address; }
            set
            {
                _address = value;
                //OnPropertyChanged("Address");
            }
        }

        [mp.Column(Name = "ADDRESS2")]
        public string Address2
        {
            get { return _address2; }
            set { _address2 = value; }
        }

        [mp.Column(Name = "CITY")]
        public string City
        {
            get { return _city; }
            set
            {
                _city = value;
                //OnPropertyChanged("City");
            }
        }

        [mp.Column(Name = "STATE")]
        public string Province
        {
            get { return _province; }
            set
            {
                _province = value;
                //OnPropertyChanged("Province");
            }
        }

        [mp.Column(Name = "COUNTRY")]
        public string Country
        {
            get { return _country; }
            set { _country = value; }
        }

        [mp.Column(Name = "ZIP")]
        public string PostalCode
        {
            get { return _postalCode; }
            set
            {
                _postalCode = value;
                //OnPropertyChanged("PostalCode");
            }
        }

        [mp.Column(Name = "PHONE1")]
        public string PhoneNumber
        {
            get { return _phoneNumber; }
            set { _phoneNumber = value; }
        }

        [mp.Column(Name = "FAX")]
        public string FaxNumber
        {
            get { return _faxNumber; }
            set { _faxNumber = value; }
        }

        [mp.Column(Name = "PYMTRMID")]
        public string PaymentTermId
        {
            get { return _paymentTermId; }
            set
            {
                _paymentTermId = value;
                //OnPropertyChanged("PaymentTermId");
            }
        }

        [mp.Column(Name = "TAXSCHID")]
        public string TaxSchedId
        {
            get { return _taxSchedId; }
            set
            {
                _taxSchedId = value;
                //OnPropertyChanged("TaxSchedId");
            }
        }

        public string UnifiedAddress
        {
            get { return _unifiedAddress; }
            set
            {
                _unifiedAddress = value;
                //OnPropertyChanged("UnifiedAddress");
            }
        }
    }
}
