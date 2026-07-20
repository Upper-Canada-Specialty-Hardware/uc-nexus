using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using System.Collections.ObjectModel;
using System.Windows;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;

namespace PM_Project_Tracking.DataClasses
{
    class PurchaseOrderHeaders
    {
        public static ObservableCollection<PurchaseOrderHeader> GetPoHeaders()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<PurchaseOrderHeader> purchOrderList = null;

            try
            {
                var purchOrdQuery = from poHead in dtCtx.GetTable<PurchaseOrderHeader>()
                                    join line in dtCtx.GetTable<gp.Pop10110>().Select(e => new { e.PoNumber, e.JobNumber}).Distinct() on poHead.PoNumber equals line.PoNumber
                                    into full
                                    from line in full.DefaultIfEmpty()
                                    join job in dtCtx.GetTable<gp.Jc00102>().Select(r => new { r.JobNumber, r.JobName}).Distinct() on line.JobNumber equals job.JobNumber 
                                    into fullx
                                    from job in fullx.DefaultIfEmpty()
                                    join ucHeader in dtCtx.GetTable<PoUcshHeaderComment>().Select(r => new { r.PoNumber, r.DoNotShipBeforeDate }).Distinct() on poHead.PoNumber equals ucHeader.PoNumber
                                    into fulla
                                    from ucHeader in fulla.DefaultIfEmpty()
                                    //join lineTwo in dtCtx.GetTable<gp.Pop10110>().Select(e => new { e.PoNumber, e.JobNumber, e.LocationCode }).Distinct() on poHead.PoNumber equals lineTwo.PoNumber
                                    //into fullz
                                    //from lineTwo in fullz.DefaultIfEmpty()
                                    where job.JobNumber != "" //&& poHead.PoNumber == "PO092160" //&& poHead.PoStatus < 4
                                    //where lineTwo.LocationCode.ToUpper() == "MARKHAM" && poHead.PoStatus < 4
                                    orderby poHead.PoNumber descending
                                    select new
                                    {
                                        PoNumber = poHead.PoNumber,
                                        JobNumber = line.JobNumber,
                                        JobName = job.JobName,
                                        BuyerId = poHead.BuyerId,
                                        DoNotShipBeforeDate = ucHeader.DoNotShipBeforeDate
                                        
                                    };

                purchOrderList = purchOrdQuery.AsEnumerable().Select(x => new PurchaseOrderHeader(x.PoNumber, x.JobNumber, x.JobName, x.BuyerId, x.DoNotShipBeforeDate)).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<PurchaseOrderHeader>(purchOrderList);
        }

        //public static ObservableCollection<PurchaseOrderHeader> GetPoHeadersWithSop()
        //{
        //    lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
        //    lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
        //    List<PurchaseOrderHeader> purchOrderList = null;

        //    try
        //    {
        //        var purchOrdQuery = from poHead in dtCtx.GetTable<PurchaseOrderHeader>()
        //                            join line in dtCtx.GetTable<gp.Pop10110>().Select(e => new { e.PoNumber, e.JobNumber }).Distinct() on poHead.PoNumber equals line.PoNumber
        //                            into full
        //                            from line in full.DefaultIfEmpty()
        //                            join job in dtCtx.GetTable<gp.Jc00102>().Select(r => new { r.JobNumber, r.JobName }).Distinct() on line.JobNumber equals job.JobNumber
        //                            into fullx
        //                            from job in fullx.DefaultIfEmpty()
        //                            where job.JobNumber != "" && poHead.PoStatus < 4
        //                            orderby poHead.PoNumber descending
        //                            select new
        //                            {
        //                                PoNumber = poHead.PoNumber,
        //                                JobNumber = line.JobNumber,
        //                                JobName = job.JobName
        //                            };

        //        purchOrderList = purchOrdQuery.AsEnumerable().Select(x => new PurchaseOrderHeader(x.PoNumber, x.JobNumber, x.JobName)).ToList();
        //    }
        //    catch (Exception ex)
        //    {
        //        MessageBox.Show(ex.ToString());
        //    }
        //    finally
        //    {
        //        dtCtx.Dispose();
        //    }

        //    return new ObservableCollection<PurchaseOrderHeader>(purchOrderList);
        //}

        public static ObservableCollection<PurchaseOrderHeader> GetPoHeadersUnusual()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<PurchaseOrderHeader> purchOrderList = null;

            try
            {
                var purchOrdQuery = from poHead in dtCtx.GetTable<PurchaseOrderHeader>()
                                    join line in dtCtx.GetTable<gp.Pop10110>().Select(e => new { e.PoNumber, e.JobNumber }).Distinct() on poHead.PoNumber equals line.PoNumber
                                    into full
                                    from line in full.DefaultIfEmpty()
                                    join job in dtCtx.GetTable<gp.Jc00102>().Select(r => new { r.JobNumber, r.JobName }).Distinct() on line.JobNumber equals job.JobNumber
                                    into fullx
                                    from job in fullx.DefaultIfEmpty()
                                    join lineTwo in dtCtx.GetTable<gp.Pop10110>().Select(e => new { e.PoNumber, e.JobNumber, e.LocationCode }).Distinct() on poHead.PoNumber equals lineTwo.PoNumber
                                    into fullz
                                    from lineTwo in fullz.DefaultIfEmpty()
                                    join ucHeader in dtCtx.GetTable<PoUcshHeaderComment>().Select(r => new { r.PoNumber, r.DoNotShipBeforeDate }).Distinct() on poHead.PoNumber equals ucHeader.PoNumber
                                    into fulla
                                    from ucHeader in fulla.DefaultIfEmpty()
                                    join sopLink in dtCtx.GetTable<gp.Sop60100>() on poHead.PoNumber equals sopLink.PoNumber
                                    into fully
                                    from sopLink in fully.DefaultIfEmpty()
                                    where line.JobNumber.Trim() == "" && lineTwo.LocationCode != "SHOWROOM" && sopLink.SopNumber == null
                                    //where lineTwo.LocationCode.ToUpper() == "MARKHAM" && poHead.PoStatus < 4
                                    //where poHead.PoNumber == "PO034633"
                                    orderby poHead.PoNumber descending
                                    select new
                                    {
                                        PoNumber = poHead.PoNumber,
                                        PoStatus = poHead.PoStatus,
                                        JobNumber = line.JobNumber,
                                        LocationCode = lineTwo.LocationCode,
                                        BuyerId = poHead.BuyerId,
                                        DoNotShipBeforeDate = ucHeader.DoNotShipBeforeDate
                                    };

                purchOrderList = purchOrdQuery.AsEnumerable().Select(x => new PurchaseOrderHeader(x.PoNumber, x.PoStatus, x.JobNumber, x.LocationCode, x.BuyerId, x.DoNotShipBeforeDate)).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<PurchaseOrderHeader>(purchOrderList);
        }

        public static PurchaseOrderHeader GetPoHeaderSingle(string poNumber)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            PurchaseOrderHeader poHeader = null;

            try
            {
                var purchOrdQuery = from poHead in dtCtx.GetTable<PurchaseOrderHeader>()
                                    join line in dtCtx.GetTable<gp.Pop10110>().Select(e => new { e.PoNumber, e.JobNumber }).Distinct() on poHead.PoNumber equals line.PoNumber
                                    into full
                                    from line in full.DefaultIfEmpty()
                                    join job in dtCtx.GetTable<gp.Jc00102>().Select(r => new { r.JobNumber, r.JobName }).Distinct() on line.JobNumber equals job.JobNumber
                                    into fullx
                                    from job in fullx.DefaultIfEmpty()
                                        //join lineTwo in dtCtx.GetTable<gp.Pop10110>().Select(e => new { e.PoNumber, e.JobNumber, e.LocationCode }).Distinct() on poHead.PoNumber equals lineTwo.PoNumber
                                        //into fullz
                                        //from lineTwo in fullz.DefaultIfEmpty()
                                    where poHead.PoNumber == poNumber
                                    //where lineTwo.LocationCode.ToUpper() == "MARKHAM" && poHead.PoStatus < 4
                                    orderby poHead.PoNumber descending
                                    select new
                                    {
                                        PoNumber = poHead.PoNumber,
                                        JobNumber = line.JobNumber,
                                        JobName = job.JobName,
                                        BuyerId = poHead.BuyerId
                                    };

                //poHeader = purchOrdQuery.AsEnumerable().Select(x => new PurchaseOrderHeader(x.PoNumber, x.JobNumber, x.JobName, x.BuyerId)).FirstOrDefault();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return poHeader;
        }
    }

    [mp.Table(Name = "[POP10100]")]
    public class PurchaseOrderHeader
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _poNumber;
        private short _poStatus;
        private string _jobNumber;
        private string _jobName;
        private string _locationCode;
        private string _buyerId;
        private DateTime? _doNotShipBeforeDate;

        [mp.Column(Name = "PONUMBER")]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "POSTATUS")]
        public short PoStatus
        {
            get { return _poStatus; }
            set { _poStatus = value; }
        }

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

        public string LocationCode          //Taken from PO line
        {
            get { return _locationCode; }
            set { _locationCode = value; }
        }

        [mp.Column(Name = "BUYERID")]
        public string BuyerId
        {
            get { return _buyerId; }
            set { _buyerId = value; }
        }

        public DateTime? DoNotShipBeforeDate
        {
            get
            {
                return _doNotShipBeforeDate;
            }

            set
            {
                _doNotShipBeforeDate = value;
            }
        }

        public PurchaseOrderHeader()
        {
        }

        public PurchaseOrderHeader(string poNumber)
        {
            this._poNumber = poNumber;
        }

        public PurchaseOrderHeader(string poNumber, string jobNumber, string jobName, string buyerId, DateTime? doNotShipBeforeDate)
        {
            this._poNumber = poNumber;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._buyerId = buyerId;
            this._doNotShipBeforeDate = doNotShipBeforeDate;
        }

        public PurchaseOrderHeader(string poNumber, short poStatus, string jobNumber, string locationCode, string buyerId, DateTime? doNotShipBeforeDate)
        {
            this._poNumber = poNumber;
            this._poStatus = poStatus;
            this._jobNumber = jobNumber.Trim();
            this._locationCode = locationCode;
            this._buyerId = buyerId;
            this._doNotShipBeforeDate = doNotShipBeforeDate;
        }
    }


}
