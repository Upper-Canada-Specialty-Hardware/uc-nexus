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
using gp = PM_Project_Tracking.DataClasses.GpObjects;

namespace PM_Project_Tracking.DataClasses
{
    public static class HollowMetal 
    {
        internal static ObservableCollection<ShopDrawingLine> GetShopDrawing(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ShopDrawingLine> shopDrawList = null;

            System.Diagnostics.Stopwatch a = new System.Diagnostics.Stopwatch();
            a.Start();

            try
            {
                var shopDrawQuery = from sdraw in dtCtx.GetTable<ShopDrawingLine>()
                                    where sdraw.JobNumber == jobNumber
                                    orderby sdraw.SerialOrder ascending
                                    select new
                                    {
                                        JobNumber = sdraw.JobNumber,
                                        Area = sdraw.Area,
                                        OpeningNum = sdraw.OpeningNum,
                                        OpenFrom = sdraw.OpenFrom,
                                        SwingTo = sdraw.SwingTo,
                                        PartitionType = sdraw.PartitionType,
                                        Construction = sdraw.Construction,
                                        FrameQuantity = sdraw.FrameQuantity,
                                        ReorderRework = sdraw.ReorderRework,
                                        DoorQuantity = sdraw.DoorQuantity,
                                        //DoorReorder = sdraw.DoorReorder,
                                        FrameWorkOrderNum = sdraw.FrameWorkOrderNum,
                                        FrameShipDate = sdraw.FrameShipDate,
                                        FramePO = sdraw.FramePo,
                                        FramePODate = sdraw.FramePoDate,
                                        FrameManufacturer = sdraw.FrameManufacturer,
                                        DoorWorkOrderNum = sdraw.DoorWorkOrderNum,
                                        DoorShipDate = sdraw.DoorShipDate,
                                        DoorPO = sdraw.DoorPo,
                                        DoorPODate = sdraw.DoorPoDate,
                                        DoorManufacturer = sdraw.DoorManufacturer,
                                        Reworks = sdraw.Reworks,
                                        ShipRemarks = sdraw.ShipRemarks,
                                        FrameSeries = sdraw.FrameSeries,
                                        FrameJambDepth = sdraw.FrameJambDepth,
                                        FrameElevNum = sdraw.FrameElevNum,
                                        FrameArchElevNum = sdraw.FrameArchElevNum,
                                        FrameElevSheetNum = sdraw.FrameElevSheetNum,
                                        FrameSectNum = sdraw.FrameSectNum,
                                        FrameSectSheetNum = sdraw.FrameSectSheetNum,
                                        FrameWidth = sdraw.FrameWidth,
                                        FrameHeight = sdraw.FrameHeight,
                                        FrameDoorThickness = sdraw.FrameDoorThickness,
                                        FrameSwing = sdraw.FrameSwing,
                                        FrameAnchor = sdraw.FrameAnchor,
                                        FrameFireRating = sdraw.FrameFireRating,
                                        HardwareHeading = sdraw.HardwareHeading,
                                        HardwareHinges = sdraw.HardwareHinges,
                                        HardwareLockNum = sdraw.HardwareLockNum,
                                        HardwareStrikeType = sdraw.HardwareStrikeType,
                                        HardwareNonStdStrike = sdraw.HardwareNonStdStrike,
                                        HardwareCloser = sdraw.HardwareCloser,
                                        HardwareCloserTop = sdraw.HardwareCloserTop,
                                        HardwareCloserBot = sdraw.HardwareCloserBot,
                                        HardwareDoorPosSwitch = sdraw.HardwareDoorPosSwitch,
                                        HardwareConcOverStop = sdraw.HardwareConcOverStop,
                                        HardwareFrDrEdge = sdraw.HardwareFrDrEdge,
                                        HardwareConcDoorBot = sdraw.HardwareConcDoorBot,
                                        HardwarePowerTrans = sdraw.HardwarePowerTrans,
                                        HardwareMisc = sdraw.HardwareMisc,
                                        DoorSeries = sdraw.DoorSeries,
                                        DoorFinish = sdraw.DoorFinish,
                                        DoorSwing = sdraw.DoorSwing,
                                        DoorPanelType = sdraw.DoorPanelType,
                                        DoorPanelSheetNum = sdraw.DoorPanelSheetNum,
                                        DoorGlassThick = sdraw.DoorGlassThick,
                                        DoorGlazingKitType = sdraw.DoorGlazingKitType,
                                        DoorLabel = sdraw.DoorLabel,
                                        DoorSteelCap = sdraw.DoorSteelCap,
                                        Remarks = sdraw.Remarks,
                                        LightKitPoNumber = sdraw.LightKitPoNumber,
                                        LightKitPoDate = sdraw.LightKitPoDate,
                                        LightKidTagId = sdraw.LightKitTagId,
                                        Flex01 = sdraw.Flex01,
                                        Flex02 = sdraw.Flex02,
                                        Flex03 = sdraw.Flex03,
                                        Flex04 = sdraw.Flex04,
                                        Flex05 = sdraw.Flex05,
                                        Flex06 = sdraw.Flex06,
                                        Flex07 = sdraw.Flex07,
                                        Flex08 = sdraw.Flex08,
                                        SerialOrder = sdraw.SerialOrder,
                                        LastUpdate = sdraw.LastUpdate,
                                        LastUpdateTime = sdraw.LastUpdateTime,
                                        UpdatingUser = sdraw.UpdatingUser,
                                        UpdatingMachine = sdraw.UpdatingMachine


            };

                shopDrawList = shopDrawQuery.AsEnumerable().Select(x => new ShopDrawingLine(x.JobNumber, x.Area, x.OpeningNum, x.OpenFrom, x.SwingTo,
                                                                                    x.PartitionType, x.Construction, x.FrameQuantity, x.ReorderRework, x.DoorQuantity,
                                                                                    x.FrameWorkOrderNum, x.FrameShipDate, x.FramePO, x.FramePODate, x.FrameManufacturer,
                                                                                    x.DoorWorkOrderNum, x.DoorShipDate, x.DoorPO, x.DoorPODate, x.DoorManufacturer, 
                                                                                    x.Reworks, x.ShipRemarks, x.FrameSeries, x.FrameJambDepth, x.FrameElevNum, x.FrameArchElevNum,
                                                                                    x.FrameElevSheetNum, x.FrameSectNum, x.FrameSectSheetNum, x.FrameWidth, x.FrameHeight,
                                                                                    x.FrameDoorThickness,
                                                                                    x.FrameSwing, x.FrameAnchor, x.FrameFireRating, x.HardwareHeading, x.HardwareHinges,
                                                                                    x.HardwareLockNum, x.HardwareStrikeType, x.HardwareNonStdStrike, x.HardwareCloser, x.HardwareCloserTop,
                                                                                    x.HardwareCloserBot, x.HardwareDoorPosSwitch, x.HardwareConcOverStop, x.HardwareFrDrEdge, x.HardwareConcDoorBot,
                                                                                    x.HardwarePowerTrans, x.HardwareMisc, x.DoorSeries, x.DoorFinish, x.DoorSwing,
                                                                                    x.DoorPanelType, x.DoorPanelSheetNum, x.DoorGlassThick, x.DoorGlazingKitType, x.DoorLabel,
                                                                                    x.DoorSteelCap, x.Remarks, 
                                                                                    x.LightKitPoNumber, x.LightKitPoDate, x.LightKidTagId,
                                                                                    x.Flex01, x.Flex02, x.Flex03,
                                                                                    x.Flex04, x.Flex05, x.Flex06, x.Flex07, x.Flex08,
                                                                                    x.SerialOrder, x.LastUpdate, x.LastUpdateTime, x.UpdatingUser, x.UpdatingMachine)).ToList();
                a.Stop();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ShopDrawingLine>(shopDrawList);
        }

        public static ObservableCollection<ShopDrawingLine> GetShopDrawingAreaList(string jobNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ShopDrawingLine> shopDrawList = null;

            try
            {
                var shopDrawQuery = from sdraw in dtCtx.GetTable<ShopDrawingLine>()
                                    group sdraw by new { sdraw.JobNumber, sdraw.Area } into grp
                                    where grp.Key.JobNumber == jobNumber
                                    orderby grp.Key.Area
                                    select new
                                    {
                                        JobNumber = grp.Key.JobNumber,
                                        Area = grp.Key.Area
                                    };

                shopDrawList = shopDrawQuery.AsEnumerable().Select(x => new ShopDrawingLine(x.JobNumber, x.Area, null)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<ShopDrawingLine>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ShopDrawingLine>(shopDrawList);
        }

        public static ObservableCollection<ShopDrawingLine> GetShopDrawingJobsList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ShopDrawingLine> shopDrawList = null;

            try
            {
                var shopDrawQuery = from sdraw in dtCtx.GetTable<ShopDrawingLine>()
                                    group sdraw by new { sdraw.JobNumber } into grp
                                    join jobs in dtCtx.GetTable<gp.Jc00102>() on grp.Key.JobNumber equals jobs.JobNumber into full
                                    from jobs in full.DefaultIfEmpty()
                                    orderby grp.Key.JobNumber
                                    select new
                                    {
                                        JobNumber = grp.Key.JobNumber,
                                        JobName = jobs.JobName == null ? "" : jobs.JobName
                                    };

                shopDrawList = shopDrawQuery.AsEnumerable().Select(x => new ShopDrawingLine(x.JobNumber, x.JobName)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                return new ObservableCollection<ShopDrawingLine>();
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ShopDrawingLine>(shopDrawList);
        }
    }

    [mp.Table(Name = "[HMSHOPDRAW101]")]
    public class ShopDrawingLine
    {
        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private string _jobNumber;
        private string _jobName;        //NOT ACTUALLY PART OF THE TABLE SCHEMA AND NOT FOUND IN THE UCSH HM SQL ADD-IN FOR THIS CLASS
        private string _area;
        private string _openingNum;
        private string _openFrom;
        private string _swingTo;
        private string _partitionType;
        private string _construction;
        private int? _frameQuantity;
        private int? _reorderRework;
        private int? _doorQuantity;
        //private int? _doorReorder;
        private string _frameWorkOrderNum;
        private DateTime? _frameShipDate;
        private string _framePo;
        private DateTime? _framePoDate;
        private string _frameManufacturer;
        private string _doorWorkOrderNum;        
        private DateTime? _doorShipDate;
        private string _doorPo;
        private DateTime? _doorPoDate;
        private string _doorManufacturer;
        private string _reworks;
        private string _shipRemarks;
        private string _frameSeries;
        private string _frameJambDepth;
        private string _frameElevNum;
        private string _frameArchElevNum;
        private string _frameElevSheetNum;
        private string _frameSectNum;
        private string _frameSectSheetNum;
        private string _frameWidth;
        private string _frameHeight;
        private string _frameDoorThickness;
        private string _frameSwing;
        private string _frameAnchor;
        private string _frameFireRating;
        private string _hardwareHeading;
        private string _hardwareHinges;
        private string _hardwareLockNum;
        private string _hardwareStrikeType;
        private string _hardwareNonStdStrike;
        private string _hardwareCloser;
        private string _hardwareCloserTop;
        private string _hardwareCloserBot;
        private string _hardwareDoorPosSwitch;
        private string _hardwareConcOverStop;
        private string _hardwareFrDrEdge;
        private string _hardwareConcDoorBot;
        private string _hardwarePowerTrans;
        private string _hardwareMisc;
        private string _doorSeries;
        private string _doorFinish;
        private string _doorSwing;
        private string _doorPanelType;
        private string _doorPanelSheetNum;
        private string _doorGlassThick;
        private string _doorGlazingKitType;
        private string _doorLabel;
        private string _doorSteelCap;
        private string _remarks;
        private string _lightKitPoNumber;
        private DateTime? _lightKitPoDate;
        private string _lightKitTagId;
        private string _flex01;
        private string _flex02;
        private string _flex03;
        private string _flex04;
        private string _flex05;
        private string _flex06;
        private string _flex07;
        private string _flex08;
        private int? _serialOrder;
        private DateTime? _lastUpdate;
        private DateTime? _lastUpdateTime;
        private string _updatingUser;
        private string _updatingMachine;

        private List<HardwareSchedule> _hwList;

        [mp.Column(Name = "JobNumber", IsPrimaryKey=true)]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        public string JobName
        {
            get { return _jobName; }
            set { _jobName = value; }
        }

        [mp.Column(Name = "Area")]
        public string Area
        {
            get { return _area; }
            set { _area = value; }
        }

        [mp.Column(Name = "OpeningNum", IsPrimaryKey=true)]
        public string OpeningNum
        {
            get { return _openingNum; }
            set { _openingNum = value; }
        }

        [mp.Column(Name = "OpenFrom")]
        public string OpenFrom
        {
            get { return _openFrom; }
            set { _openFrom = value; }
        }

        [mp.Column(Name = "SwingTo")]
        public string SwingTo
        {
            get { return _swingTo; }
            set { _swingTo = value; }
        }

        [mp.Column(Name = "PartitionType")]
        public string PartitionType
        {
            get { return _partitionType; }
            set { _partitionType = value; }
        }

        [mp.Column(Name = "Const")]
        public string Construction
        {
            get { return _construction; }
            set { _construction = value; }
        }

        [mp.Column(Name = "FrameQuantity")]
        public int? FrameQuantity
        {
            get { return _frameQuantity; }
            set { _frameQuantity = value; }
        }

        [mp.Column(Name = "ReorderRework")]
        public int? ReorderRework
        {
            get { return _reorderRework; }
            set { _reorderRework = value; }
        }

        [mp.Column(Name = "DoorQuantity")]
        public int? DoorQuantity
        {
            get { return _doorQuantity; }
            set { _doorQuantity = value; }
        }

        [mp.Column(Name = "FrameWorkOrderNum")]
        public string FrameWorkOrderNum
        {
            get { return _frameWorkOrderNum; }
            set { _frameWorkOrderNum = value; }
        }

        [mp.Column(Name = "FrameShipDate")]
        public DateTime? FrameShipDate
        {
            get { return _frameShipDate; }
            set { _frameShipDate = value; }
        }

        [mp.Column(Name = "FramePo")]
        public string FramePo
        {
            get { return _framePo; }
            set { _framePo = value; }
        }

        [mp.Column(Name = "FramePoDate")]
        public DateTime? FramePoDate
        {
            get { return _framePoDate; }
            set { _framePoDate = value; }
        }


        [mp.Column(Name = "FrameManufacturer")]
        public string FrameManufacturer
        {
            get { return _frameManufacturer; }
            set { _frameManufacturer = value; }
        }

        [mp.Column(Name = "DoorWorkOrderNum")]
        public string DoorWorkOrderNum
        {
            get { return _doorWorkOrderNum; }
            set { _doorWorkOrderNum = value; }
        }

        [mp.Column(Name = "DoorShipDate")]
        public DateTime? DoorShipDate
        {
            get { return _doorShipDate; }
            set { _doorShipDate = value; }
        }

        [mp.Column(Name = "DoorPo")]
        public string DoorPo
        {
            get { return _doorPo; }
            set { _doorPo = value; }
        }

        [mp.Column(Name = "DoorPoDate")]
        public DateTime? DoorPoDate
        {
            get { return _doorPoDate; }
            set { _doorPoDate = value; }
        }

        [mp.Column(Name = "DoorManufacturer")]
        public string DoorManufacturer
        {
            get { return _doorManufacturer; }
            set { _doorManufacturer = value; }
        }

        [mp.Column(Name = "Reworks")]
        public string Reworks
        {
            get { return _reworks; }
            set { _reworks = value; }
        }

        [mp.Column(Name = "ShipRemarks")]
        public string ShipRemarks
        {
            get { return _shipRemarks; }
            set { _shipRemarks = value; }
        }

        [mp.Column(Name = "FrameSeries")]
        public string FrameSeries
        {
            get { return _frameSeries; }
            set { _frameSeries = value; }
        }

        [mp.Column(Name = "FrameJambDepth")]
        public string FrameJambDepth
        {
            get { return _frameJambDepth; }
            set { _frameJambDepth = value; }
        }

        [mp.Column(Name = "FrameElevNum")]
        public string FrameElevNum
        {
            get { return _frameElevNum; }
            set { _frameElevNum = value; }
        }

        [mp.Column(Name = "FrameArchElevNum")]
        public string FrameArchElevNum
        {
            get { return _frameArchElevNum; }
            set { _frameArchElevNum = value; }
        }

        [mp.Column(Name = "FrameElevSheetNum")]
        public string FrameElevSheetNum
        {
            get { return _frameElevSheetNum; }
            set { _frameElevSheetNum = value; }
        }

        [mp.Column(Name = "FrameSectNum")]
        public string FrameSectNum
        {
            get { return _frameSectNum; }
            set { _frameSectNum = value; }
        }

        [mp.Column(Name = "FrameSectSheetNum")]
        public string FrameSectSheetNum
        {
            get { return _frameSectSheetNum; }
            set { _frameSectSheetNum = value; }
        }

        [mp.Column(Name = "FrameWidth")]
        public string FrameWidth
        {
            get { return _frameWidth; }
            set { _frameWidth = value; }
        }

        [mp.Column(Name = "FrameHeight")]
        public string FrameHeight
        {
            get { return _frameHeight; }
            set { _frameHeight = value; }
        }

        [mp.Column(Name = "FrameDoorThickness")]
        public string FrameDoorThickness
        {
            get { return _frameDoorThickness; }
            set { _frameDoorThickness = value; }
        }

        [mp.Column(Name = "FrameSwing")]
        public string FrameSwing
        {
            get { return _frameSwing; }
            set { _frameSwing = value; }
        }

        [mp.Column(Name = "FrameAnchor")]
        public string FrameAnchor
        {
            get { return _frameAnchor; }
            set { _frameAnchor = value; }
        }

        [mp.Column(Name = "FrameFireRating")]
        public string FrameFireRating
        {
            get { return _frameFireRating; }
            set { _frameFireRating = value; }
        }

        [mp.Column(Name = "HardwareHeading")]
        public string HardwareHeading
        {
            get { return _hardwareHeading; }
            set { _hardwareHeading = value; }
        }

        [mp.Column(Name = "HardwareHinges")]
        public string HardwareHinges
        {
            get { return _hardwareHinges; }
            set { _hardwareHinges = value; }
        }

        [mp.Column(Name = "HardwareLockNum")]
        public string HardwareLockNum
        {
            get { return _hardwareLockNum; }
            set { _hardwareLockNum = value; }
        }

        [mp.Column(Name = "HardwareStrikeType")]
        public string HardwareStrikeType
        {
            get { return _hardwareStrikeType; }
            set { _hardwareStrikeType = value; }
        }

        [mp.Column(Name = "HardwareNonStdStrike")]
        public string HardwareNonStdStrike
        {
            get { return _hardwareNonStdStrike; }
            set { _hardwareNonStdStrike = value; }
        }

        [mp.Column(Name = "HardwareCloser")]
        public string HardwareCloser
        {
            get { return _hardwareCloser; }
            set { _hardwareCloser = value; }
        }

        [mp.Column(Name = "HardwareCloserTop")]
        public string HardwareCloserTop
        {
            get { return _hardwareCloserTop; }
            set { _hardwareCloserTop = value; }
        }

        [mp.Column(Name = "HardwareCloserBot")]
        public string HardwareCloserBot
        {
            get { return _hardwareCloserBot; }
            set { _hardwareCloserBot = value; }
        }

        [mp.Column(Name = "HardwareDoorPosSwitch")]
        public string HardwareDoorPosSwitch
        {
            get { return _hardwareDoorPosSwitch; }
            set { _hardwareDoorPosSwitch = value; }
        }

        [mp.Column(Name = "HardwareConcOverStop")]
        public string HardwareConcOverStop
        {
            get { return _hardwareConcOverStop; }
            set { _hardwareConcOverStop = value; }
        }

        [mp.Column(Name = "HardwareFrDrEdge")]
        public string HardwareFrDrEdge
        {
            get { return _hardwareFrDrEdge; }
            set { _hardwareFrDrEdge = value; }
        }

        [mp.Column(Name = "HardwareConcDoorBot")]
        public string HardwareConcDoorBot
        {
            get { return _hardwareConcDoorBot; }
            set { _hardwareConcDoorBot = value; }
        }

        [mp.Column(Name = "HardwarePowerTrans")]
        public string HardwarePowerTrans
        {
            get { return _hardwarePowerTrans; }
            set { _hardwarePowerTrans = value; }
        }

        [mp.Column(Name = "HardwareMisc")]
        public string HardwareMisc
        {
            get { return _hardwareMisc; }
            set { _hardwareMisc = value; }
        }

        [mp.Column(Name = "DoorSeries")]
        public string DoorSeries
        {
            get { return _doorSeries; }
            set { _doorSeries = value; }
        }

        [mp.Column(Name = "DoorFinish")]
        public string DoorFinish
        {
            get { return _doorFinish; }
            set { _doorFinish = value; }
        }

        [mp.Column(Name = "DoorSwing")]
        public string DoorSwing
        {
            get { return _doorSwing; }
            set { _doorSwing = value; }
        }

        [mp.Column(Name = "DoorPanelType")]
        public string DoorPanelType
        {
            get { return _doorPanelType; }
            set { _doorPanelType = value; }
        }

        [mp.Column(Name = "DoorPanelSheetNum")]
        public string DoorPanelSheetNum
        {
            get { return _doorPanelSheetNum; }
            set { _doorPanelSheetNum = value; }
        }

        [mp.Column(Name = "DoorGlassThick")]
        public string DoorGlassThick
        {
            get { return _doorGlassThick; }
            set { _doorGlassThick = value; }
        }

        [mp.Column(Name = "DoorGlazingKitType")]
        public string DoorGlazingKitType
        {
            get { return _doorGlazingKitType; }
            set { _doorGlazingKitType = value; }
        }

        [mp.Column(Name = "DoorLabel")]
        public string DoorLabel
        {
            get { return _doorLabel; }
            set { _doorLabel = value; }
        }

        [mp.Column(Name = "DoorSteelCap")]
        public string DoorSteelCap
        {
            get { return _doorSteelCap; }
            set { _doorSteelCap = value; }
        }

        [mp.Column(Name = "Remarks")]
        public string Remarks
        {
            get { return _remarks; }
            set { _remarks = value; }
        }

        [mp.Column(Name = "LightKitPoNumber")]
        public string LightKitPoNumber
        {
            get { return _lightKitPoNumber; }
            set { _lightKitPoNumber = value; }
        }

        [mp.Column(Name = "LightKitPoDate")]
        public DateTime? LightKitPoDate
        {
            get { return _lightKitPoDate; }
            set { _lightKitPoDate = value; }
        }

        [mp.Column(Name = "LightKitTagId")]
        public string LightKitTagId
        {
            get { return _lightKitTagId; }
            set { _lightKitTagId = value; }
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

        [mp.Column(Name = "Flex03")]
        public string Flex03
        {
            get { return _flex03; }
            set { _flex03 = value; }
        }

        [mp.Column(Name = "Flex04")]
        public string Flex04
        {
            get { return _flex04; }
            set { _flex04 = value; }
        }

        [mp.Column(Name = "Flex05")]
        public string Flex05
        {
            get { return _flex05; }
            set { _flex05 = value; }
        }

        [mp.Column(Name = "Flex06")]
        public string Flex06
        {
            get { return _flex06; }
            set { _flex06 = value; }
        }

        [mp.Column(Name = "Flex07")]
        public string Flex07
        {
            get { return _flex07; }
            set { _flex07 = value; }
        }

        [mp.Column(Name = "Flex08")]
        public string Flex08
        {
            get { return _flex08; }
            set { _flex08 = value; }
        }

        [mp.Column(Name = "SerialOrder")]
        public int? SerialOrder
        {
            get { return _serialOrder; }
            set { _serialOrder = value; }
        }

        [mp.Column(Name = "LastUpdate")]
        public DateTime? LastUpdate
        {
            get { return _lastUpdate; }
            set { _lastUpdate = value; }
        }

        [mp.Column(Name = "LastUpdateTime", DbType = "Time", CanBeNull = true)]
        public DateTime? LastUpdateTime
        {
            get { return _lastUpdateTime; }
            set { _lastUpdateTime = value; }
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

        public List<HardwareSchedule> HwList
        {
            get
            {
                return _hwList;
            }

            set
            {
                _hwList = value;
            }
        }

        public ShopDrawingLine()
        {
        }

        public ShopDrawingLine(string jobNum, string JobName)
        {
            this._jobNumber = jobNum;
            this._jobName = JobName;
        }

        public ShopDrawingLine(string jobNum, string area, object asdf)
        {
            this._jobNumber = jobNum;
            this._area = area;
        }

        public ShopDrawingLine(string jobNum, string area, string openNum, string openFrom, string swingTo, string partType, string construc, int? frameQty, 
                           int? reorderRework, int? doorQty, 
                           string frameWorkOrderNum, DateTime? frameShipDate, string framePo, DateTime? framePoDate, string frameManufac, 
                           string doorWorkOrderNum,  DateTime? doorShipDate, string doorPo, DateTime? doorPoDate, string doorManufac, 
                           string reworks, string shipRem, string frameSer, string frameJambDep, string frameElevNum,
                           string frameArchElevNum, string frameElevSheetNum, string frameSectNum, string frameSectSheetNum, string frameWid, string frameHeight, string frameDoorThickness,
                           string frameSw, string frameAnch,
                           string frameFireRating, string hardHead, string hardHing, string hardLockNum, string hardStrType, string hardNonStdStr, string hardCloser, string hardCloserTop,
                           string hardCloserBot, string hardDoorPosSw, string hardConcOverStop, string hardFrDrEdge, string hardConcDoorBot, string hardPowerTran, string hardMisc, string doorSer,
                           string doorfin, string doorSw, string doorPanTyp, string doorPanShNum, string doorGlassTh, string doorGlazeKitTy, string doorLab, string doorSteelCap,
                           string rem, 
                           string lightKitPoNumber, DateTime? lightKitPoDate, string lightKitTagId,
                           string flex1, string flex2, string flex3, string flex4, string flex5, string flex6, string flex7,
                           string flex8, int? serOrd, DateTime? lastUpd, DateTime? lastUpdTime, string updUser, string updMach)
        {
            this._jobNumber = jobNum;
            this._area = area;
            this._openingNum = openNum;
            this._openFrom = openFrom;
            this._swingTo = swingTo;
            this._partitionType = partType;
            this._construction = construc;
            this._frameQuantity = frameQty;
            this._reorderRework = reorderRework;
            this._doorQuantity = doorQty;
            //this._doorReorder = doorRe;
            this._frameWorkOrderNum = frameWorkOrderNum;
            this._frameShipDate = frameShipDate;
            this._framePo = framePo;
            this._framePoDate = framePoDate;
            this._frameManufacturer = frameManufac;
            this._doorWorkOrderNum = doorWorkOrderNum;
            this._doorShipDate = doorShipDate;
            this._doorPo = doorPo;
            this._doorPoDate = doorPoDate;
            this._doorManufacturer = doorManufac;

            this._reworks = reworks;
            this._shipRemarks = shipRem;
            this._frameSeries = frameSer;
            this._frameJambDepth = frameJambDep;
            this._frameElevNum = frameElevNum;

            this._frameArchElevNum = frameArchElevNum;
            this._frameElevSheetNum = frameElevSheetNum;
            this._frameSectNum = frameSectNum;
            this._frameSectSheetNum = frameSectSheetNum;
            this._frameWidth = frameWid;
            this._frameHeight = frameHeight;
            this._frameDoorThickness = frameDoorThickness;
            this._frameSwing = frameSw;
            this._frameAnchor = frameAnch;

            this._frameFireRating = frameFireRating;
            this._hardwareHeading = hardHead;
            this._hardwareHinges = hardHing;
            this._hardwareLockNum = hardLockNum;
            this._hardwareStrikeType = hardStrType;
            this._hardwareNonStdStrike = hardNonStdStr;
            this._hardwareCloser = hardCloser;
            this._hardwareCloserTop = hardCloserTop;
            this._hardwareCloserBot = hardCloserBot;
            this._hardwareDoorPosSwitch = hardDoorPosSw;
            this._hardwareConcOverStop = hardConcOverStop;
            this._hardwareFrDrEdge = hardFrDrEdge;
            this._hardwareConcDoorBot = hardConcDoorBot;
            this._hardwarePowerTrans = hardPowerTran;
            this._hardwareMisc = hardMisc;
            this._doorSeries = doorSer;
            this._doorFinish = doorfin;
            this._doorSwing = doorSw;
            this._doorPanelType = doorPanTyp;
            this._doorPanelSheetNum = doorPanShNum;
            this._doorGlassThick = doorGlassTh;
            this._doorGlazingKitType = doorGlazeKitTy;
            this._doorLabel = doorLab;
            this._doorSteelCap = doorSteelCap;
            this._remarks = rem;
            this._lightKitPoNumber = lightKitPoNumber;
            this._lightKitPoDate = lightKitPoDate;
            this._lightKitTagId = lightKitTagId;
            this._flex01 = flex1;
            this._flex02 = flex2;
            this._flex03 = flex3;
            this._flex04 = flex4;
            this._flex05 = flex5;
            this._flex06 = flex6;
            this._flex07 = flex7;
            this._flex08 = flex8;
            this._serialOrder = serOrd;
            this._lastUpdate = lastUpd;
            this._lastUpdateTime = lastUpdTime;
            this._updatingUser = updUser;
            this._updatingMachine = updMach;
        }
    }

    public class ProjectsByShopDraw
    {
        private string _jobNumber;
        private string _jobName;
    }
}
