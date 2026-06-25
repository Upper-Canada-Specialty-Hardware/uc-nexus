using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.Collections.ObjectModel;
using System.Windows;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using System.Reflection;

namespace PM_Project_Tracking.DataClasses
{
    class Hardware
    {
        internal static ObservableCollection<HardwareSchedule> GetHardwareSchedule(int projId)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<HardwareSchedule> hardwareSchedList = null;

            try
            {
                var hardschedQuery = from matl in dtCtx.GetTable<AVA_APJ_D8_MaterialList>()
                                     join opn in dtCtx.GetTable<AVA_APJ_D8_OpeningsSchedules>() on new { a = matl.OsRowNum.GetValueOrDefault(0), b = matl.ProjectId } equals new { a = opn.RowNum.GetValueOrDefault(0), b = opn.ProjectId } into fOpen
                                     from opn in fOpen.DefaultIfEmpty()
                                     join hdwList in dtCtx.GetTable<AVA_APJ_D8_HardwareList>() on new { a = matl.ShortCode, b = matl.ProjectId } equals new { a = hdwList.ShortCode, b = hdwList.ProjectId } into a
                                     from hdwList in a.DefaultIfEmpty()
                                     join proj in dtCtx.GetTable<AVA_FUSION_FileList>() on matl.ProjectId equals proj.Id into fProj
                                     from proj in fProj.DefaultIfEmpty()
                                     join hm in dtCtx.GetTable<ShopDrawingLine>() on new { a = opn.OpeningNumber, b = proj.ProjectNumber } equals new { a = hm.OpeningNum, b = hm.JobNumber } into fHm
                                     from hm in fHm.DefaultIfEmpty()
                                     where matl.ProjectId == projId
                                     //orderby matl.ProductHash
                                     orderby opn.OpeningNumber, matl.ProductHash
                                     select new
                                     {
                                         OpeningNumber = opn.OpeningNumber,
                                         HgNum = matl.HgNum,
                                         HgRowNum = matl.HgRowNum,
                                         OsNum = matl.OsNum,
                                         OsRowNum = matl.OsRowNum,
                                         ShortCode = hdwList.ShortCode == null ? "" : hdwList.ShortCode,
                                         HwType = hdwList.HwType == null ? "" : hdwList.HwType,
                                         PrepList = matl.PrepList,
                                         ProductHash = matl.ProductHash == null ? "" : matl.ProductHash,
                                         ProductId = matl.ProductId == null ? "" : matl.ProductId,
                                         ProductLine = matl.ProductLine,
                                         Manufacturer = matl.Manufacturer == null ? "" : matl.Manufacturer,
                                         JobNumber = proj.ProjectNumber,
                                         OpeningCost = ParseDecimal(matl.OpeningCost),   //Has to be nullable because this column in SQL is sometimes left blank
                                         OpeningList = matl.OpeningList,   //Has to be nullable because this column in SQL is sometimes left blank
                                         Quantity = matl.Quantity,      //There is never a blank in this column, either 0 or above, so a regular Convert method works fine
                                         QuantityPerOpening = matl.QuantityPerOpening,
                                         NumberOfOpenings = matl.NumberOfOpenings,
                                        PriceBasis = ParseDecimal(matl.PriceBasis),
                                        Discount = matl.Discount,
                                        RowNum = Convert.ToInt32(matl.RowNum),
                                        Group = matl.Group,
                                        SdLine = hm,
                                        ImportDate = Convert.ToDateTime(proj.ImportedDate),
                                        ImportTime = Convert.ToDateTime(proj.ImportedTime)
                                    };

                hardwareSchedList = hardschedQuery.AsEnumerable().Select(x => new HardwareSchedule(x.OpeningNumber, x.HgNum, x.HgRowNum, x.OsNum, x.OsRowNum
                                                                                                   ,x.ShortCode
                                                                                                   ,x.HwType
                                                                                                   ,x.PrepList, x.ProductHash, x.ProductId, x.ProductLine 
                                                                                                   ,x.Manufacturer
                                                                                                   ,x.JobNumber
                                                                                                   ,x.OpeningCost, x.OpeningList 
                                                                                                   ,x.PriceBasis, x.Discount
                                                                                                   ,x.Quantity 
                                                                                                   ,x.QuantityPerOpening
                                                                                                   ,x.NumberOfOpenings
                                                                                                   ,x.RowNum, x.Group
                                                                                                   ,x.ImportDate, x.ImportTime
                                                                                                   ,x.SdLine)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<HardwareSchedule>(hardwareSchedList);
        }

        public static ObservableCollection<AVA_FUSION_FileList> GetHWSchedJobsList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<AVA_FUSION_FileList> hwJobList = null;

            try
            {
                var hardschedQuery = from proj in dtCtx.GetTable<AVA_FUSION_FileList>()
                                     orderby proj.ProjectName
                                     select new
                                     {
                                        Id = proj.Id,
                                        ProjectNumber = proj.ProjectNumber,
                                        ProjectName = proj.ProjectName,
                                        ImportedDate = proj.ImportedDate,
                                        ImportedTime = proj.ImportedTime
                                     };

                hwJobList = hardschedQuery.AsEnumerable().Select(x => new AVA_FUSION_FileList(x.Id, x.ProjectNumber, x.ProjectName, x.ImportedDate, x.ImportedTime)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<AVA_FUSION_FileList>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<AVA_FUSION_FileList>(hwJobList);
        }

        public static ObservableCollection<AVA_FUSION_FileList> GetHWSchedJobId(string jobNumber)
        {
            //might have to use a truncation on the jobnumber because some job avaware files are broken down by area, so their 'jobnumbers' are concats of 'jobnumber' and 'area' like HRRH level 14
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<AVA_FUSION_FileList> hwJobList = null;

            try
            {
                var hardschedQuery = from proj in dtCtx.GetTable<AVA_FUSION_FileList>()
                                     orderby proj.ProjectNumber
                                     where proj.ProjectNumber == jobNumber
                                     select new
                                     {
                                         Id = proj.Id,
                                         ProjectNumber = proj.ProjectNumber,
                                         ProjectName = proj.ProjectName,
                                         ImportedDate = proj.ImportedDate,
                                         ImportedTime = proj.ImportedTime
                                     };

                hwJobList = hardschedQuery.AsEnumerable().Select(x => new AVA_FUSION_FileList(x.Id, x.ProjectNumber, x.ProjectName, x.ImportedDate, x.ImportedTime)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<AVA_FUSION_FileList>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<AVA_FUSION_FileList>(hwJobList);
        }

        public static decimal? ParseDecimal(string s)
        {
            decimal d;
            if (decimal.TryParse(s, out d))
                return d;
            return null;
        }
    }

    [mp.Table]      //Should allow us to ignore non-decorated properties now: https://stackoverflow.com/questions/8412430/how-do-i-exclude-a-member-from-linq-to-sql-mapping
    public class HardwareSchedule
    {
        string _productDescription;
        int _projectId;
        int? _hgNum;
        string _shortCode;
        string _hwType;
        //door leaf truncation as last part of primary key
        string _primeKey;
        int _pkMultiples;
        string _hwgName;
        string _manufacturer;
        string _openingNumber;
        string _numberOfOpenings;
        string _openingType;
        string _quantityPerOpening;
        string _totalQuantity;  //QTY    // Avaware AVA_APJ_D8-MaterialList table stores these as string (varchar(255))
        string _jobNumber;
        decimal? _priceBasis;   //P01   Manufacturer list
        string _discount;     //PDS   Our company/project discount

        decimal? _totalCost;    //PTC   // Avaware AVA_APJ_D8-MaterialList table stores these as string (varchar(255))
        decimal? _totalList;
        decimal? _openingCost;  //PUC   // Avaware AVA_APJ_D8-MaterialList table stores these as string (varchar(255))
        string _openingList;  //PUL   // Avaware AVA_APJ_D8-MaterialList table stores these as string (varchar(255))

        int? _hgRowNum;
        int? _osNum;
        int? _osRowNum;
        string _prepList;
        string _productHash;
        string _productId;
        string _proudctLine;
        int _rowNum;
        string _group;

        private ShopDrawingLine _sdLine;
        string _hmInfoConcat;

        DateTime? _importDate;
        DateTime? _importTime;


        [mp.Column(DbType = "varchar(max)", Name = "D01")]
        public string ProductDescription
        {
            get { return _productDescription; }
            set { _productDescription = value; }
        }


        [mp.Column(Name = "[ProjectNumber]")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }


        [mp.Column(DbType = "int", Name = "[PROJECT_ID]")]
        public int ProjectId
        {
            get { return _projectId; }
            set { _projectId = value; }
        }

        [mp.Column(DbType = "int", Name = "[HG_Num]")]
        public int? HgNum
        {
            get { return _hgNum; }
            set { _hgNum = value; }
        }

        [mp.Column(DbType = "varchar(max)", Name = "[D02]")]
        public string ShortCode
        {
            get { return _shortCode; }
            set { _shortCode = value; }
        }

        [mp.Column(DbType = "varchar(255)", Name = "[HC2]")]
        public string HwType
        {
            get
            {
                return _hwType;
            }

            set
            {
                _hwType = value;
            }
        }

        [mp.Column(Name = "[PrimeKey]")]
        public string PrimeKey
        {
            get { return _primeKey; }
            set { _primeKey = value; }
        }

        [mp.Column(DbType = "int", Name = "[cnt]")]
        public int PkMultiples
        {
            get { return _pkMultiples; }
            set { _pkMultiples = value; }
        }

        //[mp.Column(Name = "[Name]")]
        //public string HwgName
        //{
        //    get { return _hwgName; }
        //    set { _hwgName = value; }
        //}

        [mp.Column(Name = "[MFG]")]
        public string Manufacturer
        {
            get { return _manufacturer; }
            set { _manufacturer = value; }
        }

        [mp.Column(Name = "[O01]")]
        public string OpeningNumber
        {
            get { return _openingNumber; }
            set { _openingNumber = value; }
        }

        [mp.Column(Name = "[O02]")]
        public string NumberOfOpenings
        {
            get { return _numberOfOpenings; }
            set { _numberOfOpenings = value; }
        }

        [mp.Column(Name = "[O03]")]
        public string OpeningType
        {
            get { return _openingType; }
            set { _openingType = value; }
        }

        [mp.Column(Name = "[Q01]")]
        public string QuantityPerOpening
        {
            get { return _quantityPerOpening; }
            set { _quantityPerOpening = value; }
        }

        [mp.Column(Name = "[QTY]")]
        public string TotalQuantity
        {
            get { return _totalQuantity; }
            set { _totalQuantity = value; }
        }

        [mp.Column(Name = "[P01]")]
        public decimal? PriceBasis
        {
            get { return _priceBasis; }
            set { _priceBasis = value; }
        }

        [mp.Column(Name = "[PDS]")]
        public string Discount
        {
            get { return _discount; }
            set { _discount = value; }
        }

        [mp.Column(Name = "[PTC]")]
        public decimal? TotalCost
        {
            get { return _totalCost; }
            set { _totalCost = value; }
        }

        [mp.Column(Name = "[PUC]")]
        public decimal? OpeningCost   // Avaware AVA_APJ_D8-MaterialList table stores these as string (varchar(255))
        {
            get { return _openingCost; }
            set { _openingCost = value; }
        }

        [mp.Column(Name = "[PUL]")]
        public string OpeningList   // Avaware AVA_APJ_D8-MaterialList table stores these as string (varchar(255))
        {
            get { return _openingList; }
            set { _openingList = value; }
        }


        //public int? HgRowNum
        //{
        //    get { return _hgRowNum; }
        //    set { _hgRowNum = value; }
        //}


        //public int? OsNum
        //{
        //    get { return _osNum; }
        //    set { _osNum = value; }
        //}


        //public int? OsRowNum
        //{
        //    get { return _osRowNum; }
        //    set { _osRowNum = value; }
        //}


        //public string PrepList
        //{
        //    get { return _prepList; }
        //    set { _prepList = value; }
        //}

        public string ProductHash
        {
            get { return _productHash; }
            set { _productHash = value; }
        }

        //[mp.Column(DbType = "varchar(255)", Name = "PRODUCT_ID")]
        public string ProductId
        {
            get { return _productId; }
            set { _productId = value; }
        }


        //public string ProudctLine
        //{
        //    get { return _proudctLine; }
        //    set { _proudctLine = value; }
        //}

        [mp.Column(Name = "[RowNum]", CanBeNull=true)]     //OS ROW NUM, NOT MAT LIST ROW NUM
        public int RowNum
        {
            get { return _rowNum; }
            set { _rowNum = value; }
        }

        public ShopDrawingLine SdLine
        {
            get { return _sdLine; }
            set
            {
                _sdLine = value;
            }
        }

        public string HmInfoConcat
        {
            get
            {
                return _hmInfoConcat;
            }

            set
            {
                _hmInfoConcat = value;
            }
        }

        [mp.Column(DbType = "date", Name = "[ImportedDate]")]
        public DateTime? ImportDate
        {
            get { return _importDate; }
            set { _importDate = value; }
        }

        [mp.Column(DbType = "time", Name = "[ImportedTime]")]
        public DateTime? ImportTime
        {
            get { return _importTime; }
            set { _importTime = value; }
        }


        public HardwareSchedule()
        {
        }

        public HardwareSchedule(string opn, int? hgN, int? hgRn, int? osN, int? osRn,
                                string shortCode, 
                                string hwType,
                                string prepL, string prodHash, string prodId, string prodLine, 
                                string manufacturer,
                                string jobNum,
                                decimal? openCost, string openList,
                                decimal? priceBasis, string discount,
                                string qty,
                                string qtyPerOpening,
                                string numberOfOpenings, 
                                int rowN, string grp,
                                DateTime? avaImportDate, DateTime? avaImportTime,
                                ShopDrawingLine sdLine)
        {
            this._openingNumber = opn;
            this._hgNum = hgN;
            this._hgRowNum = hgRn;
            this._osNum = osN;
            this._osRowNum = osRn;
            this._shortCode = shortCode;
            this._hwType = hwType;
            this._prepList = prepL;
            this._productHash = prodHash;
            this._productId = prodId;
            this._proudctLine = prodLine;
            this._manufacturer = manufacturer;
            this._jobNumber = jobNum;
            this._openingCost = openCost;
            this._openingList = openList;
            this._priceBasis = priceBasis;
            this._discount = discount;
            this._totalQuantity = qty;
            this._quantityPerOpening = qtyPerOpening;
            this._numberOfOpenings = numberOfOpenings;
            this._rowNum = rowN;
            this._group = grp;
            this._sdLine = sdLine;
            if (sdLine != null)
            {
                //If you ever change the first 4 characters to say anything other than "Area" then you need to update the export commission sheet
                //code that inserts page breaks. Same goes for below with "No shop drawing...".
                this._hmInfoConcat = "Area: " + _sdLine.Area +
                ", Hardware Heading: " + _sdLine.HardwareHeading +
                ", Partion: " + _sdLine.PartitionType +
                ", Frame Width: " + _sdLine.FrameWidth +
                ", Frame Height: " + _sdLine.FrameHeight +
                ", Frame Fire Rating: " + _sdLine.FrameFireRating +
                ", Door Series: " + _sdLine.DoorSeries +
                ", Door Finish: " + _sdLine.DoorFinish +
                ", Door Swing: " + _sdLine.DoorSwing +
                ", Remarks: " + _sdLine.Remarks;
            }
            else
            {
                //If this text gets changed, the commission sheet export code needs to be revisited at the part where page breaks are added.
                this._hmInfoConcat = "No shop drawing data uploaded to SQL Server";
            }
            this._importDate = avaImportDate;
            this._importTime = avaImportTime;
        }
    }


    [mp.Table(Name = "[Avaware].[dbo].[AVA_APJ_D8-MaterialList]")]
    public class AVA_APJ_D8_MaterialList
    {
        int? _hgNum;
        int? _hgRowNum;
        int? _osNum;
        int? _osRowNum;
        string _shortCode;
        string _prepList;
        string _productHash;
        string _productId;
        string _productLine;
        string _manufacturer;
        int _projectId;
        string _openingCost;  //PUC
        string _openingList;  //PUL
        //int _quantityPerOpening;  //Q01
        string _quantityPerOpening;
        string _quantity;  //QTY
        string _numberOfOpenings;
        string _priceBasis;   //PUL ALSO LIST
        string _discount;

        int _rowNum;
        string _group;

        [mp.Column(Name = "HG_Num")]
        public int? HgNum
        {
            get { return _hgNum; }
            set { _hgNum = value; }
        }

        [mp.Column(Name = "HG_RowNum")]
        public int? HgRowNum
        {
            get { return _hgRowNum; }
            set { _hgRowNum = value; }
        }

        [mp.Column(Name = "OS_Num")]
        public int? OsNum
        {
            get { return _osNum; }
            set { _osNum = value; }
        }

        [mp.Column(Name = "OS_RowNum")]
        public int? OsRowNum
        {
            get { return _osRowNum; }
            set { _osRowNum = value; }
        }

        [mp.Column(Name = "D02")]
        public string ShortCode
        {
            get
            {
                return _shortCode;
            }

            set
            {
                _shortCode = value;
            }
        }

        [mp.Column(Name = "PrepList_Abb")]
        public string PrepList
        {
            get { return _prepList; }
            set { _prepList = value; }
        }

        [mp.Column(Name = "Product_HASH")]
        public string ProductHash
        {
            get { return _productHash; }
            set { _productHash = value; }
        }

        [mp.Column(Name = "PRODUCT_ID")]
        public string ProductId
        {
            get { return _productId; }
            set { _productId = value; }
        }

        [mp.Column(Name = "ProductLine")]
        public string ProductLine
        {
            get { return _productLine; }
            set { _productLine = value; }
        }

        [mp.Column(Name = "MFG")]
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

        [mp.Column(Name = "PROJECT_ID")]
        public int ProjectId
        {
            get { return _projectId; }
            set { _projectId = value; }
        }

        [mp.Column(Name = "PUC")]
        public string OpeningCost
        {
            get { return _openingCost; }
            set { _openingCost = value; }
        }

        [mp.Column(Name = "PUL")]
        public string OpeningList
        {
            get { return _openingList; }
            set { _openingList = value; }
        }

        [mp.Column(Name = "QTY")]
        public string Quantity
        {
            get { return _quantity; }
            set { _quantity = value; }
        }

        [mp.Column(Name = "Q01")]
        public string QuantityPerOpening
        {
            get
            {
                return _quantityPerOpening;
            }

            set
            {
                _quantityPerOpening = value;
            }
        }

        [mp.Column(Name = "O02")]
        public string NumberOfOpenings
        {
            get
            {
                return _numberOfOpenings;
            }

            set
            {
                _numberOfOpenings = value;
            }
        }

        [mp.Column(Name = "PUL")]
        public string PriceBasis
        {
            get { return _priceBasis; }
            set { _priceBasis = value; }
        }

        [mp.Column(Name = "PDS")]
        public string Discount
        {
            get { return _discount; }
            set { _discount = value; }
        }

        [mp.Column(Name = "RowNum")]
        public int RowNum
        {
            get { return _rowNum; }
            set { _rowNum = value; }
        }

        [mp.Column(Name = "GRP")]
        public string Group
        {
            get { return _group; }
            set { _group = value; }
        }

    }

    [mp.Table(Name = "[Avaware].[dbo].[AVA_APJ_D8-OpeningsSchedules]")]
    public class AVA_APJ_D8_OpeningsSchedules
    {
        string _openingNumber;
        int _projectId;
        int? _rowNum;

        [mp.Column(Name = "O01")]
        public string OpeningNumber
        {
            get { return _openingNumber; }
            set { _openingNumber = value; }
        }

        [mp.Column(Name = "PROJECT_ID")]
        public int ProjectId
        {
            get { return _projectId; }
            set { _projectId = value; }
        }

        [mp.Column(Name = "RowNum")]
        public int? RowNum
        {
            get { return _rowNum; }
            set { _rowNum = value; }
        }

    }

    [mp.Table(Name = "[Avaware].[dbo].[AVA_APJ_D8-HardwareList]")]
    public class AVA_APJ_D8_HardwareList
    {
        int _projectId;
        int? _rowNum;
        string _shortCode;
        string _hwType;

        [mp.Column(Name = "PROJECT_ID")]
        public int ProjectId
        {
            get { return _projectId; }
            set { _projectId = value; }
        }

        [mp.Column(Name = "RowNum")]
        public int? RowNum
        {
            get { return _rowNum; }
            set { _rowNum = value; }
        }

        [mp.Column(Name = "H01")]
        public string ShortCode
        {
            get
            {
                return _shortCode;
            }

            set
            {
                _shortCode = value;
            }
        }

        [mp.Column(Name = "HC2")]
        public string HwType
        {
            get
            {
                return _hwType;
            }

            set
            {
                _hwType = value;
            }
        }
    }

    [mp.Table(Name = "[Avaware].[dbo].[AVA_APJ_D8_HardwareGroups]")]
    public class AVA_APJ_D8_HardwareGroups
    {
        int _projectId;
        int? _rowNum;
        string _shortCode;
        string _hwType;

        [mp.Column(Name = "PROJECT_ID")]
        public int ProjectId
        {
            get { return _projectId; }
            set { _projectId = value; }
        }

        [mp.Column(Name = "RowNum")]
        public int? RowNum
        {
            get { return _rowNum; }
            set { _rowNum = value; }
        }

        [mp.Column(Name = "H01")]
        public string ShortCode
        {
            get
            {
                return _shortCode;
            }

            set
            {
                _shortCode = value;
            }
        }

        [mp.Column(Name = "HC2")]
        public string HwType
        {
            get
            {
                return _hwType;
            }

            set
            {
                _hwType = value;
            }
        }

        public AVA_APJ_D8_HardwareGroups()
        {

        }
    }

    [mp.Table(Name = "[Avaware].[dbo].[AVA_FUSION_FileList]")]
    public class AVA_FUSION_FileList
    {
        int _id;
        string _projectNumber;
        string _projectName;
        string _fileLocation;
        string _fileName;
        string _importedDate;
        string _importedTime;

        [mp.Column(Name = "ID")]
        public int Id
        {
            get { return _id; }
            set { _id = value; }
        }

        [mp.Column(Name = "ProjectNumber")]
        public string ProjectNumber
        {
            get { return _projectNumber; }
            set { _projectNumber = value; }
        }

        [mp.Column(Name = "ProjectName")]
        public string ProjectName
        {
            get { return _projectName; }
            set { _projectName = value; }
        }

        [mp.Column(Name = "FileLocation")]
        public string FileLocation
        {
            get { return _fileLocation; }
            set { _fileLocation = value; }
        }

        [mp.Column(Name = "FileName")]
        public string FileName
        {
            get { return _fileName; }
            set { _fileName = value; }
        }

        [mp.Column(Name = "ImportedDate", CanBeNull=true)]
        public String ImportedDate
        {
            get { return _importedDate; }
            set { _importedDate = value; }
        }

        [mp.Column(Name = "ImportedTime", CanBeNull=true)]
        public String ImportedTime
        {
            get { return _importedTime; }
            set { _importedTime = value; }
        }

        public AVA_FUSION_FileList()
        {
        }

        public AVA_FUSION_FileList(int id, string projNumber, string projName, string importDate, string importTime)
        {
            this._id = id;
            this._projectNumber = projNumber;
            this._projectName = projName;
            this._importedDate = importDate;
            this._importedTime = importTime;
        }
    }

    public class matListContext : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\PrimaryHardwarePKQuery_16Mar2018.sql  //not the same as below, Mar 16, not 19. Stored procedure, not function.
        [mp.Function(Name = "[Avaware].[dbo].[PrimaryHardwarePKQuery16Mar2018]", IsComposable = false)]       //In SQL Server: Avaware/Programmability/Stored Procedures
        public lq.ISingleResult<HardwareSchedule> getMatListByProject([mp.Parameter(DbType = "int", Name = "@projectId")] int projNum) //[mp.Parameter(DbType="int")] int projNum
        {
            object[] _para = new object[1];
            _para[0] = projNum;
            lq.IExecuteResult objResult = this.ExecuteMethodCall(this, (MethodInfo)(MethodInfo.GetCurrentMethod()), projNum);

            lq.ISingleResult<HardwareSchedule> objresults =
                (lq.ISingleResult<HardwareSchedule>)objResult.ReturnValue;
            return objresults;
        }

        public matListContext(string connStr)
            : base(connStr)
        {
        }
    }


    public class matListFunctionV2 : lq.DataContext
    {
        //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Testing Avaware Hash Codes for Next Module\Stored Procedure Testing\UDF-PrimaryHardwarePKQuery_19Mar2018.sql
        [mp.Function(Name = "[Avaware].[dbo].[functionTestV2]", IsComposable = true)]       //In SQL Server: Avaware/Programmability/Functions/Table-vaued Functions
        public IQueryable<HardwareSchedule> getMatListByProjectv2([mp.Parameter(DbType = "int", Name = "@projectId")] int projNum)
        {
            return this.CreateMethodCallQuery<HardwareSchedule>(this, ((MethodInfo)(MethodInfo.GetCurrentMethod())), projNum);
        }

        public matListFunctionV2(string connStr)
            : base(connStr)
        {
        }
    }

    //public static class nothing
    //{
    //    [mp.Function(Name = "[dbo].[testV3]", IsComposable = false)]
    //    public lq.ISingleResult<matListContext> getCustomerAll()
    //    {
    //        lq.IExecuteResult objResult = this.ExecuteMethodCall(this, (MethodInfo)(MethodInfo.GetCurrentMethod()));

    //        lq.ISingleResult<matListContext> objresults =
    //            (lq.ISingleResult<matListContext>)objResult.ReturnValue;
    //        return objresults;
    //    }
    //}
}
