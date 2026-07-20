using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Collections.ObjectModel;
using System.Data.SqlClient;
using System.Windows;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.DataClasses
{
    class PROC_PoConfirmations
    {
        internal static ObservableCollection<PoConfirmation> GetProcPoReceipts()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<PoConfirmation> poConfList = null;

            try
            {
                var poRecQuery = from recLine in dtCtx.GetTable<PoConfirmation>()
                                orderby recLine.PoNumber descending
                                select new
                                {
                                    PoNumber = recLine.PoNumber,
                                    JobNumber = recLine.JobNumber,
                                    EmailToSupplier = recLine.EmailToSupplier,
                                    ShipToLocation = recLine.ShipToLocation,
                                    AcknowReceived = recLine.AcknowReceived,
                                    AnticiShipDate = recLine.AnticiShipDate,
                                    Notes = recLine.Notes,
                                    Flex01 = recLine.Flex01,
                                    Flex02 = recLine.Flex02,
                                    FileLocation = recLine.FileLocation,
                                    DateReceived = recLine.DateReceived,
                                    TimeReceived = recLine.TimeReceived,
                                    UpdatingUser = recLine.UpdatingUser,
                                    UpdatingMachine = recLine.UpdatingMachine,
                                };

                poConfList = poRecQuery.AsEnumerable().Select(x => new PoConfirmation(x.PoNumber, x.JobNumber, x.EmailToSupplier, x.ShipToLocation, x.AcknowReceived, 
                                                                                x.AnticiShipDate, x.Notes, x.Flex01, x.Flex02, x.FileLocation, 
                                                                                x.DateReceived, x.TimeReceived, x.UpdatingUser, x.UpdatingMachine 
                                                                                )).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
                if (poConfList.Count == 0)
                    MessageBox.Show("PO confirmations returned no entries from the database.");
            }

            return new ObservableCollection<PoConfirmation>(poConfList);
        }
    }

    [mp.Table(Name = "[PROCPOCONF101]")]
    public class PoConfirmation
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private string _poNumber;
        private string _jobNumber;
        private bool _emailToSupplier;
        private string _shipToLocation;
        private bool _acknowReceived;
        private DateTime? _anticiShipDate;
        private string _notes;
        private string _flex01;
        private string _flex02;
        private string _fileLocation;
        private DateTime? _dateReceived;
        private DateTime? _timeReceived;
        private string _updatingUser;
        private string _updatingMachine;

        [mp.Column(Name = "PONUMBER", IsPrimaryKey = true)]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "EmailToSupplier")]
        public bool EmailToSupplier
        {
            get { return _emailToSupplier; }
            set { _emailToSupplier = value; }
        }

        [mp.Column(Name = "ShipToLocation")]
        public string ShipToLocation
        {
            get { return _shipToLocation; }
            set { _shipToLocation = value; }
        }

        [mp.Column(Name = "AcknowReceived")]
        public bool AcknowReceived
        {
            get { return _acknowReceived; }
            set { _acknowReceived = value; }
        }

        [mp.Column(Name = "AnticiShipDate")]
        public DateTime? AnticiShipDate
        {
            get { return _anticiShipDate; }
            set { _anticiShipDate = value; }
        }

        [mp.Column(Name = "Notes")]
        public string Notes
        {
            get { return _notes; }
            set { _notes = value; }
        }

        [mp.Column(Name = "Flex01")]
        public string Flex01
        {
            get { return _flex01; }
            set { _flex01 = value; }
        }

        [mp.Column(Name = "Flex02")]
        public string Flex02
        {
            get { return _flex02; }
            set { _flex02 = value; }
        }

        [mp.Column(Name = "FileLocation")]
        public string FileLocation
        {
            get { return _fileLocation; }
            set { _fileLocation = value; }
        }

        [mp.Column(Name = "DateReceived")]
        public DateTime? DateReceived
        {
            get { return _dateReceived; }
            set { _dateReceived = value; }
        }

        [mp.Column(Name = "TimeReceived")]
        public DateTime? TimeReceived
        {
            get { return _timeReceived; }
            set { _timeReceived = value; }
        }

        [mp.Column(Name = "UpdatingUser")]
        public string UpdatingUser
        {
            get { return _updatingUser; }
            set { _updatingUser = value; }
        }

        [mp.Column(Name = "UpdatingMachine")]
        public string UpdatingMachine
        {
            get { return _updatingMachine; }
            set { _updatingMachine = value; }
        }

        public PoConfirmation()
        {
        }

        public PoConfirmation(string poNumber, string jobNumber, bool emailToSupplier, string shipToLocation, bool acknowReceived,
                         DateTime? anticiShipDate, string notes, string flex01, string flex02, string fileLocation,
                         DateTime? dateReceived, DateTime? timeReceived, string updatingUser, string updatingMachine)
        {
            this._poNumber = poNumber;
            this._jobNumber = jobNumber;
            this._emailToSupplier = emailToSupplier;
            this._shipToLocation = shipToLocation;
            this._acknowReceived = acknowReceived;
            this._anticiShipDate = anticiShipDate;
            this._notes = notes;
            this._flex01 = flex01;
            this._flex02 = flex02;
            this._fileLocation = fileLocation;
            this._dateReceived = dateReceived;
            this._timeReceived = timeReceived;
            this._updatingUser = updatingUser;
            this._updatingMachine = updatingMachine;
        }

        public class PoReceiptDataContext : lq.DataContext
        {
            public PoReceiptDataContext(string cs)
                : base(cs)
            {

            }

            public PoReceiptDataContext(SqlConnection conn)
                : base(conn)
            {
            }

            public lq.Table<PoConfirmation> PoReceipt;
        }
    }
}
