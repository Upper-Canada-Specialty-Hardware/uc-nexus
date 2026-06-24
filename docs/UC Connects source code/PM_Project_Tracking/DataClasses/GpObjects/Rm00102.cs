using System;
using System.Collections.Generic;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking.DataClasses.GpObjects
{
    [mp.Table(Name = "[RM00102]")]
    class Rm00102
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _customerNumber;
        private string _addressCode;
        private string _address;
        private string _address2;
        private string _city;
        private string _province;
        private string _country;
        private string _postalCode;
        private string _phoneNumber;
        private string _faxNumber;
        private string _unifiedAddress;

        [mp.Column(Name = "CUSTNMBR", IsPrimaryKey = true)]
        public string CustomerNumber
        {
            get { return _customerNumber; }
            set { _customerNumber = value; }
        }

        [mp.Column(Name = "ADRSCODE", IsPrimaryKey = true)]
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
