using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Collections.ObjectModel;
using System.Windows;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using System.Data.SqlClient;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using System.ComponentModel;


namespace PM_Project_Tracking.DataClasses
{
    public class WhShippingHeaders
    {
        public static ObservableCollection<ShippingHeader> GetShippingHeaders(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ShippingHeader> shipList = null;

            try
            {
                var shipQuery = from sH in dtCtx.GetTable<ShippingHeader>()
                                //where sH.MemoNumber == 50
                                select new
                                {
                                    MemoNumber = sH.MemoNumber,
                                    HeaderType = sH.HeaderType,
                                    SopNumber = sH.SopNumber,
                                    JobNumber = sH.JobNumber,
                                    JobName = sH.JobName,
                                    Stat = sH.Stat,
                                    Courier = sH.Courier,
                                    Shipper = sH.Shipper,
                                    ActualShipDate = sH.ActualShipDate,
                                    Waybill = sH.Waybill,
                                    ReschedShipDate = sH.ReschedShipDate,
                                    ReqShipDate = sH.ReqShipDate,
                                    GeneratedBy = sH.GeneratedBy,
                                    RequiredBy = sH.RequiredBy,
                                    CompanyName = sH.CompanyName,
                                    Address1 = sH.Address1,
                                    Attention = sH.Attention,
                                    Address2 = sH.Address2,
                                    City = sH.City,
                                    ProvState = sH.ProvState,
                                    PostalZip = sH.PostalZip,
                                    Country = sH.Country,
                                    PhoneNumber = sH.PhoneNumber,
                                    FaxNumber = sH.FaxNumber,
                                    ShipMethod = sH.ShipMethod,
                                    Comments = sH.Comments,
                                    DateShipped = sH.DateShipped,
                                    TimeShipped = sH.TimeShipped,
                                    UpdatingUser = sH.UpdatingUser,
                                    UpdatingMachine = sH.UpdatingMachine,
                                    
                                    ConcatenatedPos = sH.ConcatenatePoList(dtCtx.GetTable<ShippingLine>().Where(r => r.MemoNumber == sH.MemoNumber).Select(x => x.PoNumber).Distinct().ToList()),
                                    ItemDescpritions = sH.ConcatedItemDescList(dtCtx.GetTable<ShippingLine>().Where(r => r.MemoNumber == sH.MemoNumber).Select(x => x.ItemDescription).Distinct().ToList())
                                };

                if (jobNumber != null)
                    shipQuery = shipQuery.Where(x => x.JobNumber == jobNumber);

                shipList = shipQuery.AsEnumerable().Select(x => new ShippingHeader(x.MemoNumber, x.HeaderType, x.SopNumber, x.JobNumber, x.JobName, x.Stat, x.Courier, 
                                                                                    x.Shipper, x.ActualShipDate, x.Waybill, x.ReschedShipDate, x.ReqShipDate, 
                                                                                    x.GeneratedBy, x.RequiredBy, x.CompanyName, x.Address1, x.Attention, 
                                                                                    x.Address2, x.City, x.ProvState, x.PostalZip, x.Country, 
                                                                                    x.PhoneNumber, x.FaxNumber, x.ShipMethod, x.Comments, x.DateShipped, 
                                                                                    x.TimeShipped, x.UpdatingUser, x.UpdatingMachine,
                                                                                    x.ConcatenatedPos,
                                                                                    x.ItemDescpritions)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ShippingHeader>(shipList);
        }

        public static ObservableCollection<CombinedProject> GetCombinedShipHeaderProject()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<CombinedProject> combinedProjList = null;

            try
            {
                var mainProjQuery = from jc in dtCtx.GetTable<gp.Jc00102>()
                                    join rm in dtCtx.GetTable<gp.Rm00102>() on new { jc.AddressCode, jc.CustomerNumber } equals new { rm.AddressCode, rm.CustomerNumber } into full
                                    from rm in full.DefaultIfEmpty()
                                    join js in dtCtx.GetTable<gp.Jc00901>() on jc.JobNumber equals js.JobNumber
                                    //where jc.JobNumber == "20037"
                                    where js.Inactive == 0
                                    orderby jc.JobNumber descending
                                    select new
                                    {
                                        JobNumber = jc.JobNumber,
                                        JobName = jc.JobName.Trim(),
                                        Address = rm.Address.Trim(),
                                        Address2 = rm.Address2.Trim(),
                                        City = rm.City.Trim(),
                                        Province = rm.Province.Trim(),
                                        Country = rm.Country.Trim(),
                                        PostalCode = rm.PostalCode.Trim(),
                                        PhoneNumber = rm.PhoneNumber.Trim(),
                                        FaxNumber = rm.FaxNumber.Trim()
                                        //UnifiedAddress = proj.City.Trim() + " " + proj.Province.Trim() + " " + proj.PostalCode.Trim(),
                                    };


                combinedProjList = mainProjQuery.AsEnumerable().Select(x => new CombinedProject(x.JobNumber, x.JobName, x.Address, x.Address2, x.City,
                                                                                                x.Province, x.Country, x.PostalCode, x.PhoneNumber, x.FaxNumber)).ToList();

                if (combinedProjList.Count == 0) { return new ObservableCollection<CombinedProject>(); }

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
                if (combinedProjList.Count == 0)
                    MessageBox.Show("Main projects returned no entries from the database.");
            }
            return new ObservableCollection<CombinedProject>(combinedProjList);
        }

        public static ObservableCollection<CustomerShipment> GetCustomerHeaderByRtlOrder()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<CustomerShipment> combinedProjList = null;

            try
            {
                //The union automatically disposes of duplicates, the concat method does not.  This may explain the difference in results between both
                //Perhaps using the concat method instead?
                //http://stackoverflow.com/questions/2744205/how-to-convert-sql-union-to-linq


                //Come back to this and figure out why this query doesn't generate as many results as what are actually in the database when SOP10100 and SOP30200 are unioned

                var unionQuery = (from c in dtCtx.GetTable<gp.Sop10100>() select new { c.SopNumber, c.SopType, c.OriginNumber, c.CustomerNumber }).Union(
                                (from d in dtCtx.GetTable<gp.Sop30200>() select new { d.SopNumber, d.SopType, d.OriginNumber, d.CustomerNumber }));

                //var lll = unionQuery.ToList();

                var fullQuery = from un in unionQuery
                                join rm in dtCtx.GetTable<gp.Rm00101>() on un.CustomerNumber equals rm.CustomerNumber
                                where un.SopType == 2
                                select new
                                {
                                    SopNumber = un.SopNumber,
                                    CustomerNumber = un.CustomerNumber.Trim(),
                                    CustomerName = rm.CustomerName.Trim(),
                                    Address = rm.Address.Trim(),
                                    Address2 = rm.Address2.Trim(),
                                    City = rm.City.Trim(),
                                    Province = rm.Province.Trim(),
                                    Country = rm.Country.Trim(),
                                    PostalCode = rm.PostalCode.Trim(),
                                    PhoneNumber = rm.PhoneNumber.Trim(),
                                    FaxNumber = rm.FaxNumber.Trim()
                                };

                combinedProjList = fullQuery.AsEnumerable().Select(x => new CustomerShipment(x.SopNumber, x.CustomerNumber, x.CustomerName, x.Address, x.Address2, x.City,
                                                                                                x.Province, x.Country, x.PostalCode, x.PhoneNumber, x.FaxNumber)).ToList();


                //var mainProjQuery = from rtl in dtCtx.GetTable<gp.Sop10100>()
                //                    join rm in dtCtx.GetTable<gp.Rm00101>() on rtl.CustomerNumber equals rm.CustomerNumber
                //                    where rtl.SopType == 2
                //                    //where rtl.SopNumber == "RTLORD-026430"
                //                    select new
                //                    {
                //                        SopNumber = rtl.SopNumber,
                //                        CustomerNumber = rtl.CustomerNumber.Trim(),
                //                        CustomerName = rm.CustomerName.Trim(),
                //                        Address = rm.Address.Trim(),
                //                        Address2 = rm.Address2.Trim(),
                //                        City = rm.City.Trim(),
                //                        Province = rm.Province.Trim(),
                //                        Country = rm.Country.Trim(),
                //                        PostalCode = rm.PostalCode.Trim(),
                //                        PhoneNumber = rm.PhoneNumber.Trim(),
                //                        FaxNumber = rm.FaxNumber.Trim()
                //                    };

                //combinedProjList = mainProjQuery.AsEnumerable().Select(x => new CustomerShipment(x.SopNumber, x.CustomerNumber, x.CustomerName, x.Address, x.Address2, x.City,
                //                                                                                x.Province, x.Country, x.PostalCode, x.PhoneNumber, x.FaxNumber)).ToList();


            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            return new ObservableCollection<CustomerShipment>(combinedProjList);
        }

        public static bool AddShippingHeader(ShippingHeader sh, int memoNum)
        {
            bool _cont = true;
            sh.MemoNumber = memoNum;
            using (ShippingHeaderDataContext dtCtx = new ShippingHeaderDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    sh.DateShipped = DateTime.Today;
                    sh.TimeShipped = DateTime.Now;
                    sh.UpdatingUser = Environment.UserName;
                    sh.UpdatingMachine = Environment.MachineName;
                    dtCtx.ShippingHeader.InsertOnSubmit(sh);
                    dtCtx.SubmitChanges();
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); _cont = false; }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; }
            }
            return _cont;
        }

        public static bool UpdateShippingHeader(ShippingHeader sh)
        {
            bool _cont = true;
            using (ShippingHeaderDataContext dtCtx = new ShippingHeaderDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.ShippingHeader.Attach(sh, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, sh);
                    dtCtx.SubmitChanges();
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); _cont = false; }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; }
            }
            return _cont;
        }

        public static int GetNextMemoNumber()
        {
            SqlConnection conn = new SqlConnection(GlobalVars.UcshConnectionString);
            string strQuery = "SELECT MAX(MemoNumber) FROM WHSHIPHEADER101";
            int memoNum = 0;

            try
            {
                SqlCommand comm = new SqlCommand(strQuery, conn);
                conn.Open();
                var dbVal = comm.ExecuteScalar();
                if (dbVal.GetType() == typeof(DBNull))
                    memoNum = 1;
                else
                    memoNum = (int)dbVal + 1;
            }
            catch (SqlException sqlEx)
            {
                MessageBox.Show(sqlEx.ToString());
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                if (conn != null)
                    conn.Close();
            }

            return memoNum;
        }
    }

    [Serializable]
    [mp.Table(Name = "[WHSHIPHEADER101]")]
    public class ShippingHeader : INotifyPropertyChanged
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private int _memoNumber;
        private int _headerType;
        private string _sopNumber;
        private string _customerNumber;
        private string _customerName;
        private string _jobNumber;
        private string _jobName;
        private string _stat;
        private string _courier;
        private string _shipper;
        private DateTime? _actualShipDate;
        private string _waybill;
        private DateTime? _reschedShipDate;
        private DateTime? _reqShipDate;
        private string _generatedBy;
        private string _requiredBy;
        private string _companyName;
        private string _address1;
        private string _attention;
        private string _address2;
        private string _city;
        private string _provState;
        private string _postalZip;
        private string _country;
        private string _phoneNumber;
        private string _faxNumber;
        private string _shipMethod;
        private string _comments;
        private string _concatenatedPos;
        private string _concatenatedItemDesc;
        private DateTime? _dateShipped;
        private DateTime? _timeShipped;
        private string _updatingUser;
        private string _updatingMachine;

        private ShippingHeader _foreignShippingHeader;
        private uc.DeferredPropertySetter _defPropSet;

        private bool _isModified;

        [mp.Column(Name = "MemoNumber", IsPrimaryKey=true)]
        public int MemoNumber
        {
            get { return _memoNumber; }
            set
            {
                _memoNumber = value;
                this.IsModified = true;
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.MemoNumber = x, value);
            }
        }

        [mp.Column(Name = "HeaderType")]
        public int HeaderType
        {
            get { return _headerType; }
            set
            {
                _headerType = value;
                this.IsModified = true;
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.HeaderType = x, value);
            }
        }

        [mp.Column(Name = "SOPNUMBER")]
        public string SopNumber
        {
            get { return _sopNumber; }
            set
            {
                _sopNumber = value;
                this.IsModified = true;
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.SopNumber = x, value);
            }
        }


        public string CustomerNumber
        {
            get { return _customerNumber; }
            set
            {
                _customerNumber = value;
                this.IsModified = true;
                OnPropertyChanged("CustomerNumber");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.CustomerNumber = x, value);
            }
        }


        public string CustomerName
        {
            get { return _customerName; }
            set
            {
                _customerName = value;
                this.IsModified = true;
                OnPropertyChanged("CustomerName");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.CustomerName = x, value);
            }
        }


        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set
            {
                _jobNumber = value;
                this.IsModified = true;
                OnPropertyChanged("JobNumber");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.JobNumber = x, value);
            }
        }

        [mp.Column(Name = "JobName")]
        public string JobName
        {
            get { return _jobName; }
            set
            {
                _jobName = value;
                this.IsModified = true;
                OnPropertyChanged("JobName");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.JobName = x, value);
            }
        }

        [mp.Column(Name = "Stat")]
        public string Stat
        {
            get { return _stat; }
            set
            {
                _stat = value;
                this.IsModified = true;
                OnPropertyChanged("Stat");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Stat = x, value);
            }
        }

        [mp.Column(Name = "Courier")]
        public string Courier
        {
            get { return _courier; }
            set
            {
                _courier = value;
                this.IsModified = true;
                OnPropertyChanged("Courier");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Courier = x, value);
            }
        }

        [mp.Column(Name = "Shipper")]
        public string Shipper
        {
            get { return _shipper; }
            set
            {
                _shipper = value;
                this.IsModified = true;
                OnPropertyChanged("Shipper");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Shipper = x, value);
            }
        }

        [mp.Column(Name = "ActualShipDate")]
        public DateTime? ActualShipDate
        {
            get { return _actualShipDate; }
            set
            {
                _actualShipDate = value;
                this.IsModified = true;
                OnPropertyChanged("ActualShipDate");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.ActualShipDate = x, value);
            }
        }

        [mp.Column(Name = "Waybill")]
        public string Waybill
        {
            get { return _waybill; }
            set
            {
                _waybill = value;
                this.IsModified = true;
                OnPropertyChanged("Waybill");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Waybill = x, value);
            }
        }

        [mp.Column(Name = "ReschedShipDate")]
        public DateTime? ReschedShipDate
        {
            get { return _reschedShipDate; }
            set
            {
                _reschedShipDate = value;
                this.IsModified = true;
                OnPropertyChanged("ReschedShipDate");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.ReschedShipDate = x, value);
            }
        }

        [mp.Column(Name = "ReqShipDate")]
        public DateTime? ReqShipDate
        {
            get { return _reqShipDate; }
            set
            {
                _reqShipDate = value;
                this.IsModified = true;
                OnPropertyChanged("ReqShipDate");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.ReqShipDate = x, value);
            }
        }

        [mp.Column(Name = "GeneratedBy")]
        public string GeneratedBy
        {
            get { return _generatedBy; }
            set
            {
                _generatedBy = value;
                this.IsModified = true;
                OnPropertyChanged("GeneratedBy");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.GeneratedBy = x, value);
            }
        }

        [mp.Column(Name = "RequiredBy")]
        public string RequiredBy
        {
            get { return _requiredBy; }
            set
            {
                _requiredBy = value;
                this.IsModified = true;
                OnPropertyChanged("RequiredBy");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.RequiredBy = x, value);
            }
        }

        [mp.Column(Name = "CompanyName")]
        public string CompanyName
        {
            get { return _companyName; }
            set
            {
                _companyName = value;
                this.IsModified = true;
                OnPropertyChanged("CompanyName");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.CompanyName = x, value);
            }
        }

        [mp.Column(Name = "Address1")]
        public string Address1
        {
            get { return _address1; }
            set
            {
                _address1 = value;
                this.IsModified = true;
                OnPropertyChanged("Address1");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Address1 = x, value);
            }
        }

        [mp.Column(Name = "Attention")]
        public string Attention
        {
            get { return _attention; }
            set
            {
                _attention = value;
                this.IsModified = true;
                OnPropertyChanged("Attention");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Attention = x, value);
            }
        }

        [mp.Column(Name = "Address2")]
        public string Address2
        {
            get { return _address2; }
            set
            {
                _address2 = value;
                this.IsModified = true;
                OnPropertyChanged("Address2");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Address2 = x, value);
            }
        }

        [mp.Column(Name = "City")]
        public string City
        {
            get { return _city; }
            set
            {
                _city = value;
                this.IsModified = true;
                OnPropertyChanged("City");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.City = x, value);
            }
        }

        [mp.Column(Name = "ProvState")]
        public string ProvState
        {
            get { return _provState; }
            set
            {
                _provState = value;
                this.IsModified = true;
                OnPropertyChanged("ProvState");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.ProvState = x, value);
            }
        }

        [mp.Column(Name = "PostalZip")]
        public string PostalZip
        {
            get { return _postalZip; }
            set
            {
                _postalZip = value;
                this.IsModified = true;
                OnPropertyChanged("PostalZip");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.PostalZip = x, value);
            }
        }

        [mp.Column(Name = "Country")]
        public string Country
        {
            get { return _country; }
            set
            {
                _country = value;
                this.IsModified = true;
                OnPropertyChanged("Country");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Country = x, value);
            }
        }

        [mp.Column(Name = "PhoneNumber")]
        public string PhoneNumber
        {
            get { return _phoneNumber; }
            set
            {
                _phoneNumber = value;
                this.IsModified = true;
                OnPropertyChanged("PhoneNumber");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.PhoneNumber = x, value);
            }
        }

        [mp.Column(Name = "FaxNumber")]
        public string FaxNumber
        {
            get { return _faxNumber; }
            set
            {
                _faxNumber = value;
                this.IsModified = true;
                OnPropertyChanged("FaxNumber");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.FaxNumber = x, value);
            }
        }

        [mp.Column(Name = "ShipMethod")]
        public string ShipMethod
        {
            get { return _shipMethod; }
            set
            {
                _shipMethod = value;
                this.IsModified = true;
                OnPropertyChanged("ShipMethod");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.ShipMethod = x, value);
            }
        }

        [mp.Column(Name = "Comments")]
        public string Comments
        {
            get { return _comments; }
            set
            {
                _comments = value;
                this.IsModified = true;
                OnPropertyChanged("Comments");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.Comments = x, value);
            }
        }

        //No decoration needed, derivative column from lines
        public string ConcatenatedPos
        {
            get { return _concatenatedPos; }
            set
            {
                _concatenatedPos = value;
                this.IsModified = true;
                OnPropertyChanged("ConcatenatedPos");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.ConcatenatedPos = x, value);
            }
        }

        public string ConcatednatedItemDesc
        {
            get { return _concatenatedItemDesc; }
            set
            {
                _concatenatedItemDesc = value;
                this.IsModified = true;
                OnPropertyChanged("ConcatenatedItemDesc");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.ConcatednatedItemDesc = x, value);
            }
        }

        [mp.Column(Name = "DateShipped")]
        public DateTime? DateShipped
        {
            get { return _dateShipped; }
            set
            {
                _dateShipped = value;
                this.IsModified = true;
                OnPropertyChanged("DateShipped");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.DateShipped = x, value);
            }
        }

        [mp.Column(Name = "TimeShipped", DbType = "Time", CanBeNull = true)]
        public DateTime? TimeShipped
        {
            get { return _timeShipped; }
            set
            {
                _timeShipped = value;
                this.IsModified = true;
                OnPropertyChanged("TimeShipped");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.TimeShipped = x, value);
            }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set
            {
                _updatingUser = value;
                this.IsModified = true;
                OnPropertyChanged("TimeShipped");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.UpdatingUser = x, value);
            }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set
            {
                _updatingMachine = value;
                this.IsModified = true;
                OnPropertyChanged("TimeShipped");
                if (_defPropSet != null)
                    _defPropSet.SetValue(x => ForeignShippingHeader.UpdatingMachine = x, value);
            }
        }

        public bool IsModified
        {
            get
            {
                return _isModified;
            }

            set
            {
                _isModified = value;
                OnPropertyChanged("IsModified");
                //Don't need to add deferall, that happens automatically
            }
        }

        public ShippingHeader ForeignShippingHeader
        {
            get
            {
                return _foreignShippingHeader;
            }

            set
            {
                _foreignShippingHeader = value;
            }
        }

        public void AssignForeignShippingHeader(ref ShippingHeader forSh) 
        {
            _foreignShippingHeader = forSh;
            _defPropSet = new uc.DeferredPropertySetter();
        }

        internal void ApplyDeferredShipHeadChanges()
        {
            if (_defPropSet != null)
                _defPropSet.ApplyChanges();
        }

        internal string ConcatenatePoList(List<string> pos)
        {
            string _poList = "";
            if (pos.Count > 0)
                _poList = pos[0].Trim();

            for (int i = 1; i < pos.Count; i++)
                _poList = _poList + ", " + pos[i].Trim();

            if (pos == null || pos.Count == 0)
                return "";
            else
                return _poList;
        }

        internal string ConcatedItemDescList(List<string> its)
        {
            string _poList = "";
            if (its.Count > 0)
                _poList = its[0].Trim();

            for (int i = 1; i < its.Count; i++)
                _poList = _poList + ", " + its[i].Trim();

            if (its == null || its.Count == 0)
                return "";
            else
                return _poList;
        }

        public ShippingHeader()
        {

        }

        //Constructor for creating a shipping header from a submittal header
        public ShippingHeader(pm.SubmittalHeader subHead, CombinedProject cp)
        {
            this._headerType = 1;
            this._jobNumber = subHead.JobNumber;
            this._jobName = subHead.JobName;
            this._companyName = subHead.ContractorName;
            this._customerNumber = cp.Jc00102.CustomerNumber;
            this._dateShipped = subHead.DateCreated;
            this._address1 = cp.Rm00101.Address;
            this._address2 = cp.Rm00101.Address2;
            this._city = cp.Rm00101.City;
            this._provState = cp.Rm00101.Province;
            this._country = cp.Rm00101.Country;
            this._postalZip = cp.Rm00101.PostalCode;
            this._phoneNumber = cp.Rm00101.PhoneNumber;
            this._faxNumber = cp.Rm00101.FaxNumber;
        }

        //Constructor for passing a combined project object through
        public ShippingHeader(CombinedProject cp)
        {
            this._headerType = 1;
            this._customerName = cp.Jc00102.CustomerName;
            this._customerNumber = cp.Jc00102.CustomerNumber;
            this._jobNumber = cp.Jc00102.JobNumber;
            this._jobName = cp.Jc00102.JobName;
            this._address1 = cp.Rm00101.Address;
            this._address2 = cp.Rm00101.Address2;
            this._city = cp.Rm00101.City;
            this._provState = cp.Rm00101.Province;
            this._country = cp.Rm00101.Country;
            this._postalZip = cp.Rm00101.PostalCode;
            this._phoneNumber = cp.Rm00101.PhoneNumber;
            this._faxNumber = cp.Rm00101.FaxNumber;
        }

        public ShippingHeader(CustomerShipment cp)
        {
            this._headerType = 2;
            this._sopNumber = cp.SopNumber;
            this._companyName = cp.CustomerName;
            this._customerNumber = cp.CustomerNumber;
            this._customerName = cp.CustomerName;
            this._address1 = cp.Rm00101.Address;
            this._address2 = cp.Rm00101.Address2;
            this._city = cp.Rm00101.City;
            this._provState = cp.Rm00101.Province;
            this._country = cp.Rm00101.Country;
            this._postalZip = cp.Rm00101.PostalCode;
            this._phoneNumber = cp.Rm00101.PhoneNumber;
            this._faxNumber = cp.Rm00101.FaxNumber;
        }

        public ShippingHeader(int memoNumber, int headerType, string sopNumber, string jobNumber, string jobName, string stat, string courier, 
                                string shipper, DateTime? actualShipDate, string waybill, DateTime? reschedShipDate, DateTime? reqShipDate, 
                                string generatedBy, string requiredBy, string companyName, string address1, string attention, 
                                string address2, string city, string provState, string postalZip, string country, 
                                string phoneNumber, string faxNumber, string shipMethod, string comments, DateTime? dateShipped, 
                                DateTime? timeShipped, string updatingUser, string updatingMachine,
                                string concatenatedPos,
                                string concatenatedItemDesc)
        {
            this._memoNumber = memoNumber;
            this._headerType = headerType;
            this._sopNumber = sopNumber == null ? string.Empty : sopNumber;
            this._jobNumber = jobNumber == null ? string.Empty : jobNumber;
            this._jobName = jobName == null ? string.Empty : jobName;
            this._stat = stat;
            this._courier = courier;
            this._shipper = shipper;
            this._actualShipDate = actualShipDate;
            this._waybill = waybill;
            this._reschedShipDate = reschedShipDate;
            this._reqShipDate = reqShipDate;
            this._generatedBy = generatedBy;
            this._requiredBy = requiredBy;
            this._companyName = companyName;
            this._address1 = address1;
            this._attention = attention;
            this._address2 = address2;
            this._city = city;
            this._provState = provState;
            this._postalZip = postalZip;
            this._country = country;
            this._phoneNumber = phoneNumber;
            this._faxNumber = faxNumber;
            this._shipMethod = shipMethod;
            this._comments = comments;
            this._dateShipped = dateShipped;
            this._timeShipped = timeShipped;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;

            this._concatenatedPos = concatenatedPos;
            this._concatenatedItemDesc = concatenatedItemDesc;
        }

        [field: NonSerializedAttribute()]
        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }
    }

    public class ShippingHeaderDataContext : lq.DataContext
    {
        public ShippingHeaderDataContext(string cs)
            : base(cs)
        {
        }

        public ShippingHeaderDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public lq.Table<ShippingHeader> ShippingHeader;
    }

    public class CustomerShipment
    {
        private string _sopNumber;
        private string _customerNumber;
        private string _customerName;
        private gp.Rm00101 _rm00101 = new gp.Rm00101();

        public string SopNumber
        {
            get { return _sopNumber; }
            set { _sopNumber = value; }
        }

        public string CustomerNumber
        {
            get { return _customerNumber; }
            set { _customerNumber = value; }
        }

        public string CustomerName
        {
            get { return _customerName; }
            set { _customerName = value; }
        }

        public gp.Rm00101 Rm00101
        {
            get { return _rm00101; }
            set { _rm00101 = value; }
        }

        public CustomerShipment()
        {
        }

        public CustomerShipment(string sopNumber, string customerNumber, string customerName, string address1, string address2, string city,
                               string province, string country, string postalCode, string phoneNumber, string faxNumber)
        {
            this._sopNumber = sopNumber;
            this._customerNumber = customerNumber;
            this._customerName = customerName;
            this._rm00101.Address = address1;
            this._rm00101.Address2 = address2;
            this._rm00101.City = city;
            this._rm00101.Province = province;
            this._rm00101.Country = country;
            this._rm00101.PostalCode = postalCode;
            this._rm00101.PhoneNumber = phoneNumber;
            this._rm00101.FaxNumber = faxNumber;
        }
    }
}
