using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using System.ComponentModel;
using System.Data.SqlClient;
using System.Collections.ObjectModel;
using System.Windows;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using PM_Project_Tracking.DataClasses.Interfaces;

namespace PM_Project_Tracking.DataClasses
{
    class WhReceivingLines
    {
        internal static ObservableCollection<ReceivingLine> GetPoReceivingLineItemsByPoNum(string poNum, bool excludeComplete)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ReceivingLine> purchOrderList = null;

            try
            {
                //P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\Shipping, Hardware and Order Tracking Module\Hardware PO Retrieval\POP10110 annotated LEAN reconfig RTL col v5 - simplified version.sql
                var purchOrderQuery = from poLine in dtCtx.GetTable<gp.Pop10110>()
                                      join
                                      recs in dtCtx.GetTable<gp.Pop10500>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = recs.PoNumber, b = recs.Polnenum } into fulla
                                      from recs in fulla.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum, QtyPrevRecFromGp = fulla.Select(r => r.QuantityShipped).Sum() })
                                      join hdr in dtCtx.GetTable<gp.Pop10100>() on poLine.PoNumber equals hdr.PoNumber into fullb
                                      from hdr in fullb.DefaultIfEmpty()
                                      join jc in dtCtx.GetTable<gp.Jc00102>() on poLine.JobNumber equals jc.JobNumber into fullc
                                      from jc in fullc.DefaultIfEmpty()
                                      join pays in dtCtx.GetTable<gp.Pm00200>() on poLine.VendorId equals pays.VendorId into fulld
                                      from pays in fulld.DefaultIfEmpty()
                                      //join hdrCom in dtCtx.GetTable<dc.PoUcshHeaderComment>() on poLine.PoNumber equals hdrCom.PoNumber into fulle
                                      //from hdrCom in fulle.DefaultIfEmpty()

                                      where poLine.LocationCode != "SHOWROOM" && poLine.PoNumber == poNum
                                      orderby poLine.PoNumber descending, poLine.Order ascending
                                      select new
                                      {
                                          PoNumber = poLine.PoNumber.Trim(),
                                          Ord = poLine.Order,
                                          Polnesta = poLine.Polnesta,
                                          JobNumber = poLine.JobNumber == null ? "" : poLine.JobNumber.Trim(), //Will be null where the PO has been deleted from pop10110
                                          JobName = jc.JobName.Trim(),
                                          BuyerId = hdr.BuyerId.Trim(),
                                          ChangeId = hdr.AddressThree.Trim(),
                                          VendorId = poLine.VendorId.Trim(),
                                          VendorName = pays.VendorName.Trim(),
                                          LineNumber = poLine.LineNumber,
                                          ItemNumber = poLine.ItemNumber.Trim(),
                                          ItemDescription = poLine.ItemDescription.Trim(),
                                          UnitCost = poLine.UnitCost,
                                          QuantityOrdered = poLine.QtyOrder,
                                          QtyPrevRecFromGp = recs.Key.QtyPrevRecFromGp == null ? 0 : recs.Key.QtyPrevRecFromGp, //(recs.Key.QtyPrevRecFromGp == null) ? recs.Key.QtyPrevRecFromGp : 0, //new
                                          NonInventory = poLine.NonInventory,

                                          UcHeaderCommentText = dtCtx.GetTable<PoUcshHeaderComment>().Where(n => n.PoNumber == poLine.PoNumber).ToList(), //new List<string>(), // 
                                          UcLineCommentText = dtCtx.GetTable<PoUcshLineComment>().Where(n => n.PoNumber == poLine.PoNumber && n.Order == poLine.Order).ToList(),//
                                          //DoNotShipBeforeDate = dtCtx.GetTable<PoUcshHeaderComment>().Where(n => n.PoNumber == poLine.PoNumber).Select(x => x.DoNotShipBeforeDate), //Added 24 Feb 2024

                                          Locncode = poLine.LocationCode
                                      };

                if (excludeComplete)
                    purchOrderQuery = purchOrderQuery.Where(x => x.QtyPrevRecFromGp != x.QuantityOrdered);

                purchOrderList = purchOrderQuery.AsEnumerable().Select(x => new ReceivingLine(x.PoNumber, x.Ord, x.Polnesta, x.ItemNumber, x.ItemDescription,
                                                                                                x.JobNumber, x.JobName,
                                                                                                x.ChangeId,
                                                                                                Convert.ToInt32(x.QuantityOrdered), Convert.ToInt32(x.QtyPrevRecFromGp),
                                                                                                x.VendorId, x.VendorName,
                                                                                                x.NonInventory, x.UnitCost, 
                                                                                                x.UcHeaderCommentText, x.UcLineCommentText,
                                                                                                x.Locncode)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ReceivingLine>(purchOrderList);
        }

        //Used for VIEW of receivings
        internal static ObservableCollection<ReceivingLine> GetPoRecLinesWithUcshRecLines(string jobNumber, bool _maxOneYear)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ReceivingLine> purchOrderList = null;

            var sopUnion = (from c in dtCtx.GetTable<gp.Sop10100>() select new { c.SopNumber, c.SopType, c.OriginNumber, c.CustomerNumber, c.CustomerName }).Union(
                           (from d in dtCtx.GetTable<gp.Sop30200>() select new { d.SopNumber, d.SopType, d.OriginNumber, d.CustomerNumber, d.CustomerName }));

            try
            {
                var purchOrderQuery = from ucsh in dtCtx.GetTable<ReceivingLine>()
                                      join poRec in dtCtx.GetTable<gp.Pop10500>() on new { ucsh.PoNumber, ucsh.Polnenum, ucsh.PopRctNum, ucsh.RcptLnNm } equals new { poRec.PoNumber, poRec.Polnenum, poRec.PopRctNum, poRec.RcptLnNm }
                                      join poLine in dtCtx.GetTable<gp.Pop10110>() on new { a = ucsh.PoNumber, b = ucsh.Polnenum } equals new { a = poLine.PoNumber, b = poLine.Order } into fulla
                                      from poLine in fulla.DefaultIfEmpty()
                                      //join
                                      //recs in dtCtx.GetTable<gp.Pop10500>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = recs.PoNumber, b = recs.Polnenum } into fullx
                                      //from recs in fullx.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum, QtyPrevRecFromGp = fullx.Select(r => r.QuantityShipped).Sum() })
                                      join jc in dtCtx.GetTable<gp.Jc00102>() on poLine.JobNumber equals jc.JobNumber into fullb
                                      from jc in fullb.DefaultIfEmpty()
                                      join pays in dtCtx.GetTable<gp.Pm00200>() on poLine.VendorId equals pays.VendorId into fullc
                                      from pays in fullc.DefaultIfEmpty()
                                      join sop in dtCtx.GetTable<gp.Sop60100>() on poLine.PoNumber equals sop.PoNumber into fulle
                                      from sop in fulle.DefaultIfEmpty().GroupBy(x => new { SopNumber = x.SopNumber })
                                      join hdr in dtCtx.GetTable<gp.Pop10100>() on poLine.PoNumber equals hdr.PoNumber into fullf
                                      from hdr in fullf.DefaultIfEmpty()
                                      join mainRec in dtCtx.GetTable<gp.Pop30300>() on ucsh.PopRctNum equals mainRec.PopRctNum into fullg
                                      from mainRec in fullg.DefaultIfEmpty()
                                      join sopAll in sopUnion on sop.Key.SopNumber equals sopAll.SopNumber into fullthree
                                      from sopAll in fullthree.DefaultIfEmpty()
                                      //join shipLine in dtCtx.GetTable<ShippingLine>().Select(m => new { m.PoNumber, m.Polnenum, m.QuantityShipped })
                                      //.Where(f => f.QuantityShipped > 0) on new { a = ucsh.PoNumber, b = ucsh.Polnenum } equals new { a = shipLine.PoNumber, b = shipLine.Polnenum } into fullShip
                                      //from shipLine in fullShip.DefaultIfEmpty()
                                      join shipLine in dtCtx.GetTable<ShippingLine>() on new { a = ucsh.PoNumber, b = ucsh.Polnenum } equals new { a = shipLine.PoNumber, b = shipLine.Polnenum } into fullShip
                                      from shipLine in fullShip.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum, QuantityShipped = fullShip.Select(r => r.QuantityShipped).Sum() })
                                      join tagLine in dtCtx.GetTable<TaggingLine>() on new { a = ucsh.PopRctNum, b = ucsh.RcptLnNm } equals new { a = tagLine.PopRctNum, b = tagLine.RcptLnNm } into fullTag
                                      from tagLine in fullTag.DefaultIfEmpty().GroupBy( x => new { ReceiptNumber = x.PopRctNum, ReceiptLineNumber = x.RcptLnNm, TaggedQuantity = fullTag.Select(r => r.OrigTaggedQuantity).Sum() })
                                      //where ucsh.PoNumber == "PO032289" && ucsh.Polnenum == 16384
                                      select new
                                      {
                                          PoNumber = ucsh.PoNumber,
                                          Polnenum = ucsh.Polnenum,
                                          PopRctNum = ucsh.PopRctNum,
                                          PopRctLineNum = ucsh.RcptLnNm,
                                          JobNumber = poLine.JobNumber == null ? "" : poLine.JobNumber,     //Will be null where the PO has been deleted from pop10110
                                          JobName = jc.JobName,
                                          BuyerId = hdr.BuyerId,
                                          GlPostDate = mainRec.GlPostDate,
                                          SopNumber = sop.Key.SopNumber,
                                          VendorId = poLine.VendorId,
                                          VendorName = pays.VendorName,
                                          ItemNumber = poLine.ItemNumber,
                                          ItemDescription = poLine.ItemDescription,
                                          CustomerName = sopAll.CustomerName,           //Added 18 Jan 2017
                                          QtyOrdFromGp = poLine.QtyOrder == null ? 0 : poLine.QtyOrder,     //Will be null where the PO has been deleted from pop10110
                                          QtyRecForGp = poRec.QuantityShipped,
                                          QtyRemaining = ucsh.QtyRemainingOnRec,
                                          QuantityActualShippped = shipLine.Key.QuantityShipped == null ? 0 : shipLine.Key.QuantityShipped,
                                          QuantityTagged = tagLine.Key.TaggedQuantity == null ? 0 : tagLine.Key.TaggedQuantity,
                                          RevisionNumber = ucsh.RevisionNumber,
                                          Location = ucsh.Location,
                                          Comments = ucsh.Comments,
                                          DateReceived = ucsh.DateReceived,
                                          TimeReceived = ucsh.TimeReceived,
                                          UpdatingUser = ucsh.UpdatingUser,
                                          UpdatingMachine = ucsh.UpdatingMachine,
                                          Locncode = poLine.LocationCode
                                      };

                if (jobNumber != null)
                    purchOrderQuery = purchOrderQuery.Where(x => x.JobNumber == jobNumber);

                if (_maxOneYear == true)
                    purchOrderQuery = purchOrderQuery.Where(x => x.DateReceived > DateTime.Today.AddYears(-1));

                purchOrderList = purchOrderQuery.AsEnumerable().Select(x => new ReceivingLine(x.PoNumber 
                                                                                              ,x.Polnenum
                                                                                              ,x.PopRctNum
                                                                                              ,x.PopRctLineNum
                                                                                              ,x.ItemNumber
                                                                                              ,x.ItemDescription 
                                                                                              ,x.JobNumber
                                                                                              ,x.JobName 
                                                                                              ,x.BuyerId
                                                                                              ,x.GlPostDate
                                                                                              ,x.SopNumber
                                                                                              ,x.VendorId
                                                                                              ,x.VendorName
                                                                                              ,Convert.ToInt32(x.QtyOrdFromGp)
                                                                                              ,Convert.ToInt32(x.QtyRecForGp)
                                                                                              ,x.QtyRemaining
                                                                                              ,x.QuantityActualShippped
                                                                                              ,x.QuantityTagged
                                                                                              ,x.RevisionNumber
                                                                                              ,x.Location
                                                                                              ,x.Comments
                                                                                              , x.DateReceived
                                                                                              , x.TimeReceived
                                                                                              , x.UpdatingUser
                                                                                              , x.UpdatingMachine
                                                                                              , x.CustomerName
                                                                                              , x.Locncode)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ReceivingLine>(purchOrderList);
        }

        internal static ObservableCollection<gp.Sop60100> GetPoWithSopList()
        {
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.GpConnectionString);   //Instead of passing this through DatabaseSwitcher, changing to GlobalVars.GpConnectionString
            List<gp.Sop60100> poSopList = null;

            try
            {
                var poSopQuery = from sopLink in dtCtx.GetTable<gp.Sop60100>()
                                      where sopLink.Locncode != "SHOWROOM"
                                      group sopLink by new { sopLink.PoNumber, sopLink.Locncode, sopLink.SopNumber } into grp
                                      join hdr in dtCtx.GetTable<gp.Pop10100>() on grp.Key.PoNumber equals hdr.PoNumber into fullf
                                      from hdr in fullf.DefaultIfEmpty()
                                      orderby grp.Key.PoNumber descending
                                      select new
                                      {
                                          grp.Key.PoNumber,
                                          grp.Key.Locncode,
                                          grp.Key.SopNumber,
                                          hdr.BuyerId
                                      };

                poSopList = poSopQuery.AsEnumerable().Select(x => new gp.Sop60100(x.PoNumber, x.Locncode, x.SopNumber, x.BuyerId)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<gp.Sop60100>(poSopList);
        }

        internal static ObservableCollection<gp.Sop60100> GetPoWithSopListShowroom()
        {
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.GpConnectionString);   //Instead of passing this through DatabaseSwitcher, changing to GlobalVars.GpConnectionString
            List<gp.Sop60100> poSopList = null;

            try
            {
                var poSopQuery = from sopLink in dtCtx.GetTable<gp.Sop60100>()
                                 where sopLink.Locncode == "SHOWROOM"
                                 group sopLink by new { sopLink.PoNumber, sopLink.Locncode, sopLink.SopNumber } into grp
                                 join hdr in dtCtx.GetTable<gp.Pop10100>() on grp.Key.PoNumber equals hdr.PoNumber into fullf
                                 from hdr in fullf.DefaultIfEmpty()
                                 orderby grp.Key.PoNumber descending
                                 select new
                                 {
                                     grp.Key.PoNumber,
                                     grp.Key.Locncode,
                                     grp.Key.SopNumber,
                                     hdr.BuyerId
                                 };

                poSopList = poSopQuery.AsEnumerable().Select(x => new gp.Sop60100(x.PoNumber, x.Locncode, x.SopNumber, x.BuyerId)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<gp.Sop60100>(poSopList);
        }

        internal static ObservableCollection<ReceivingLine> GetPoLinesFromSop(string poNum, string sopNum, bool excludeComplete)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ReceivingLine> recLineList = null;

            try
            {
                var purchOrderQuery = from poLine in dtCtx.GetTable<gp.Pop10110>()
                                      join
                                      recs in dtCtx.GetTable<gp.Pop10500>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = recs.PoNumber, b = recs.Polnenum } into fulla
                                      from recs in fulla.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum, QtyPrevRecFromGp = fulla.Select(r => r.QuantityShipped).Sum() })
                                      join hdr in dtCtx.GetTable<gp.Pop10100>() on poLine.PoNumber equals hdr.PoNumber into fullb
                                      from hdr in fullb.DefaultIfEmpty()
                                      join jc in dtCtx.GetTable<gp.Jc00102>() on poLine.JobNumber equals jc.JobNumber into fullc
                                      from jc in fullc.DefaultIfEmpty()
                                      join pays in dtCtx.GetTable<gp.Pm00200>() on poLine.VendorId equals pays.VendorId into fulld
                                      from pays in fulld.DefaultIfEmpty()
                                      join sop in dtCtx.GetTable<gp.Sop60100>() on poLine.PoNumber equals sop.PoNumber into fulle
                                      from sop in fulle.DefaultIfEmpty().GroupBy(x => new {SopNumber = x.SopNumber})
                                      //where poLine.PoNumber == "PO032283"
                                      //where poLine.LocationCode != "SHOWROOM" && poLine.PoNumber == poNum
                                      where poLine.LocationCode != "SHOWROOM" && sop.Key.SopNumber == sopNum
                                      orderby poLine.PoNumber descending, poLine.Order ascending
                                      select new
                                      {
                                          PoNumber = poLine.PoNumber.Trim(),
                                          Ord = poLine.Order,
                                          Polnesta = poLine.Polnesta,
                                          JobNumber = poLine.JobNumber.Trim(),
                                          JobName = jc.JobName, // == null ? string.Empty : jc.JobName.Trim(),
                                          SopNumber = sop.Key.SopNumber.Trim(),
                                          BuyerId = hdr.BuyerId.Trim(),
                                          VendorId = poLine.VendorId.Trim(),
                                          VendorName = pays.VendorName.Trim(), // == null ? string.Empty : pays.VendorName.Trim(),
                                          LineNumber = poLine.LineNumber,
                                          ItemNumber = poLine.ItemNumber.Trim(),
                                          ItemDescription = poLine.ItemDescription.Trim(),
                                          QuantityOrdered = poLine.QtyOrder,
                                          QtyPrevRecFromGp = recs.Key.QtyPrevRecFromGp == null ? 0 : recs.Key.QtyPrevRecFromGp,
                                          NonInventory = poLine.NonInventory,
                                          Locncode = poLine.LocationCode
                                      };

                if (excludeComplete)
                    purchOrderQuery = purchOrderQuery.Where(x => x.QtyPrevRecFromGp != x.QuantityOrdered);

                recLineList = purchOrderQuery.AsEnumerable().Select(x => new ReceivingLine(x.PoNumber, x.Ord, x.Polnesta, x.ItemNumber, x.ItemDescription,
                                                                                                x.SopNumber,
                                                                                                x.JobNumber, x.JobName,
                                                                                                Convert.ToInt32(x.QuantityOrdered), Convert.ToInt32(x.QtyPrevRecFromGp),
                                                                                                x.VendorId, x.VendorName,
                                                                                                x.NonInventory, x.BuyerId, x.Locncode)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ReceivingLine>(recLineList);
        }


        internal static ObservableCollection<ReceivingLine> GetPoLinesFromSopShowroom(string poNum, string sopNum, bool excludeComplete)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<ReceivingLine> recLineList = null;

            try
            {
                var purchOrderQuery = from poLine in dtCtx.GetTable<gp.Pop10110>()
                                      join
                                      recs in dtCtx.GetTable<gp.Pop10500>() on new { a = poLine.PoNumber, b = poLine.Order } equals new { a = recs.PoNumber, b = recs.Polnenum } into fulla
                                      from recs in fulla.DefaultIfEmpty().GroupBy(x => new { PoNumber = x.PoNumber, Polnenum = x.Polnenum, QtyPrevRecFromGp = fulla.Select(r => r.QuantityShipped).Sum() })
                                      join hdr in dtCtx.GetTable<gp.Pop10100>() on poLine.PoNumber equals hdr.PoNumber into fullb
                                      from hdr in fullb.DefaultIfEmpty()
                                      join jc in dtCtx.GetTable<gp.Jc00102>() on poLine.JobNumber equals jc.JobNumber into fullc
                                      from jc in fullc.DefaultIfEmpty()
                                      join pays in dtCtx.GetTable<gp.Pm00200>() on poLine.VendorId equals pays.VendorId into fulld
                                      from pays in fulld.DefaultIfEmpty()
                                      join sop in dtCtx.GetTable<gp.Sop60100>() on poLine.PoNumber equals sop.PoNumber into fulle
                                      from sop in fulle.DefaultIfEmpty().GroupBy(x => new { SopNumber = x.SopNumber })
                                          //where poLine.PoNumber == "PO032283"
                                          //where poLine.LocationCode != "SHOWROOM" && poLine.PoNumber == poNum
                                      where poLine.LocationCode == "SHOWROOM" && sop.Key.SopNumber == sopNum
                                      orderby poLine.PoNumber descending, poLine.Order ascending
                                      select new
                                      {
                                          PoNumber = poLine.PoNumber.Trim(),
                                          Ord = poLine.Order,
                                          Polnesta = poLine.Polnesta,
                                          JobNumber = poLine.JobNumber.Trim(),
                                          JobName = jc.JobName, // == null ? string.Empty : jc.JobName.Trim(),
                                          SopNumber = sop.Key.SopNumber.Trim(),
                                          BuyerId = hdr.BuyerId.Trim(),
                                          VendorId = poLine.VendorId.Trim(),
                                          VendorName = pays.VendorName.Trim(), // == null ? string.Empty : pays.VendorName.Trim(),
                                          LineNumber = poLine.LineNumber,
                                          ItemNumber = poLine.ItemNumber.Trim(),
                                          ItemDescription = poLine.ItemDescription.Trim(),
                                          QuantityOrdered = poLine.QtyOrder,
                                          QtyPrevRecFromGp = recs.Key.QtyPrevRecFromGp == null ? 0 : recs.Key.QtyPrevRecFromGp,
                                          NonInventory = poLine.NonInventory,
                                          Locncode = poLine.LocationCode
                                      };

                if (excludeComplete)
                    purchOrderQuery = purchOrderQuery.Where(x => x.QtyPrevRecFromGp != x.QuantityOrdered);

                recLineList = purchOrderQuery.AsEnumerable().Select(x => new ReceivingLine(x.PoNumber, x.Ord, x.Polnesta, x.ItemNumber, x.ItemDescription,
                                                                                                x.SopNumber,
                                                                                                x.JobNumber, x.JobName,
                                                                                                Convert.ToInt32(x.QuantityOrdered), Convert.ToInt32(x.QtyPrevRecFromGp),
                                                                                                x.VendorId, x.VendorName,
                                                                                                x.NonInventory, x.BuyerId, x.Locncode)).ToList();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            return new ObservableCollection<ReceivingLine>(recLineList);
        }

        public static void AddReceivingLine(ReceivingLine rl)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));

            using(ReceivingLineDataContext dtCtx = new ReceivingLineDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.ReceivingLine.InsertOnSubmit(rl);
                    dtCtx.SubmitChanges();
                }
                catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); }
            }
        }

        public static bool AddReceivingLines(ObservableCollection<ReceivingLine> rlCol)
        {
            System.Security.Permissions.EnvironmentPermission _envPerm = new System.Security.Permissions.EnvironmentPermission(System.Security.Permissions.EnvironmentPermissionAccess.Read, "UserName");
            
            bool _cont = true;
            using (ReceivingLineDataContext dtCtx = new ReceivingLineDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ReceivingLine rl in rlCol)
                {
                    //if (!_cont) return _cont;
                    //if (rl.Polnesta < 4 && rl.QtyRecForGp > 0)
                    if (rl.QtyRecForGp > 0)
                    {
                        try
                        {
                            rl.QtyRemainingOnRec = rl.QtyRecForGp;
                            rl.DateReceived = DateTime.Today;
                            //rl.TimeReceived = TimeSpan.FromTicks(DateTime.Now.Ticks);
                            rl.TimeReceived = DateTime.Now;
                            //rl.UpdatingUser = Environment.UserName;
                            rl.UpdatingUser = System.Security.Principal.WindowsIdentity.GetCurrent().Name;
                            rl.UpdatingMachine = Environment.MachineName;
                            dtCtx.ReceivingLine.InsertOnSubmit(rl);
                            dtCtx.SubmitChanges();
                            rl.InsertedToDb = true;
                        }
                        catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); _cont = false; break; }
                        catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; break; }
                    }
                }
            }
            if (!_cont) DeleteReceivingLines(rlCol);
            return _cont;
        }

        public static bool UpdateReceivingLine(ReceivingLine rl)
        {
            bool _cont = true;
            using (ReceivingLineDataContext dtCtx = new ReceivingLineDataContext(GlobalVars.UcshConnectionString))
            {
                try
                {
                    dtCtx.ReceivingLine.Attach(rl, false);
                    dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, rl);
                }
                catch (Exception ex) { MessageBox.Show(ex.ToString()); _cont = false; }
                dtCtx.SubmitChanges();
            }
            return _cont;
        }

        public static void UpdateReceivingLines(ObservableCollection<ReceivingLine> rlCol)
        {
            using (ReceivingLineDataContext dtCtx = new ReceivingLineDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ReceivingLine rl in rlCol)
                {
                    try
                    {
                        dtCtx.ReceivingLine.Attach(rl, false);
                        dtCtx.Refresh(lq.RefreshMode.KeepCurrentValues, rl);
                    }
                    catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                }
                dtCtx.SubmitChanges();
            }
        }

        public static void DeleteReceivingLines(ObservableCollection<ReceivingLine> rlCol)
        {
            using (ReceivingLineDataContext dtCtx = new ReceivingLineDataContext(GlobalVars.UcshConnectionString))
            {
                foreach (ReceivingLine rl in rlCol)
                {
                    //if (!_cont) return _cont;
                    if (rl.InsertedToDb)
                    {
                        try
                        {
                            dtCtx.ReceivingLine.DeleteOnSubmit(rl);
                            dtCtx.SubmitChanges();
                        }
                        catch (SqlException sqlEx) { MessageBox.Show(sqlEx.ToString()); }
                        catch (Exception ex) { MessageBox.Show(ex.ToString()); }
                    }
                }
            }
        }
    }

    [mp.Table(Name = "[WHRECLINE101]")]
    public class ReceivingLine : IJobNumberHaver, INotifyPropertyChanged
    {
        //This class is dual-purpose:  It's nominally decorated in LINQ for the WHRECLINE101 table in the PMUCSH database however it has two extra properties called
        //"QtyRecForGp" and "VendorDatagridDispOnly." "VendorDatagridDispOnly" is the vendor name field for the datagrid but is not used for passing data to the WHRECLINE101 table.
        //"QtyRecForGp" is used for storing the actual quantity received so that this class can be re-used for passing to the "PopReceivingType" class that has the PO receipt eConnect procedure.
        //The whole reason this class exists is just for capturing the "RevisionNumber" and "Location" (not the same as POP10110 LOCNCODE) fields that GP doesn't have.  The other fields
        //are simply there so that the ReceivingLine class can be joined to existing PO receipts in GP.

        public static Enum TableFamily = uc.EnumTableFamily.UCSH;

        private string _poNumber;
        private int _polnenum;
        private short _polnesta;    //line status, very important because they can't be passed into GP for receipts
        private string _sopNumber;

        private string _popRctNum; 
        private int _rcptLnNm;
        private string _itemNumber;
        private string _itemDescription;
        private string _customerName;
        private string _vendorId;
        private string _vendorName;
        private string _jobNumber;
        private string _jobName;
        private string _buyerId;
        private string _changeId;

        private DateTime? _glPostDate;
        private string _revisionNumber;
        private string _location;   //Rack
        private string _locnCode;   //GP location code
        private string _comments;
        private DateTime? _dateReceived;
        private DateTime? _timeReceived;
        private string _updatingUser;
        private string _updatingMachine;

        private short _nonInventory;

        private int _qtyOrdFromGp;      //Original quantity ordered for the line in GP
        private int _qtyCumulativeRecFromGp;  //Aggregate of other receipts, synthetic column
        private int _qtyRecForGp;       //Specific to the receiving line itself.  This is basically the 'QTYSHPPD' columnn in POP10500
        private int _qtyRemainingOnRec; //The remaining draw-down quantity used for UCSH shipments
        private int _qtyActualShip;
        private string _vendorDatagridDispOnly;

        private int _taggedQuantityCumulative;    //Added 31 Aug 2017

        private decimal _unitCost;

        private int _uiQuantityToTransfer;

        private bool _insertedToDb;

        private TaggingLine _taggingLine;

        private string _ucHeaderCommentText;
        private string _ucLineCommentText;
        private DateTime _doNotShipBeforeDate;

        private ObservableCollection<PoUcshHeaderComment> _ucHeaderCommentCol = new ObservableCollection<PoUcshHeaderComment>();
        private ObservableCollection<PoUcshLineComment> _ucLineCommentCol = new ObservableCollection<PoUcshLineComment>();


        [mp.Column(Name = "PONUMBER", IsPrimaryKey=true)]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "POLNENUM", IsPrimaryKey = true)]
        public int Polnenum
        {
            get { return _polnenum; }
            set { _polnenum = value; }
        }

        public short Polnesta
        {
            get { return _polnesta; }
            set { _polnesta = value; }
        }

        [mp.Column(Name = "SopNumber")]
        public string SopNumber
        {
            get { return _sopNumber; }
            set { _sopNumber = value; }
        }

        [mp.Column(Name = "POPRCTNM", IsPrimaryKey = true)]
        public string PopRctNum
        {
            get { return _popRctNum; }
            set { _popRctNum = value; }
        }

        [mp.Column(Name = "RCPTLNNM", IsPrimaryKey = true)]
        public int RcptLnNm
        {
            get { return _rcptLnNm; }
            set { _rcptLnNm = value; }
        }

        [mp.Column(Name = "ITEMNMBR")]
        public string ItemNumber
        {
            get { return _itemNumber; }
            set { _itemNumber = value; }
        }

        [mp.Column(Name = "ITEMDESC")]
        public string ItemDescription
        {
            get { return _itemDescription; }
            set { _itemDescription = value; }
        }

        public string CustomerName        //Added 18 Jan 2017 - No decoration needed since it's only needed to be seen by the UI but not stored in the UCSH tables
        {
            get { return _customerName; }
            set { _customerName = value; }
        }

        [mp.Column(Name = "VENDORID")]
        public string VendorId
        {
            get { return _vendorId; }
            set { _vendorId = value; }
        }

        [mp.Column(Name = "VENDNAME")]
        public string VendorName
        {
            get { return _vendorName; }
            set { _vendorName = value; }
        }

        [mp.Column(Name = "JobNumber")]
        public string JobNumber
        {
            get { return _jobNumber; }
            set { _jobNumber = value; }
        }

        [mp.Column(Name = "JobName")]
        public string JobName
        {
            get { return _jobName; }
            set { _jobName = value; }
        }

        public string BuyerId
        {
            get { return _buyerId; }
            set { _buyerId = value; }
        }

        public string ChangeId
        {
            get { return _changeId; }
            set { _changeId = value; }
        }

        public DateTime? GlPostDate
        {
            get { return _glPostDate; }
            set { _glPostDate = value; }
        }

        [mp.Column(Name = "RevisionNumber")]
        public string RevisionNumber
        {
            get { return _revisionNumber; }
            set { _revisionNumber = value; }
        }

        [mp.Column(Name = "Location")]
        public string Location
        {
            get { return _location; }
            set 
            { 
                _location = value;
                //OnPropertyChanged("Location");
            }
        }

        //NOT STORED IN CONNECTS WHRECLINE101 TABLE.  ADDED TO CHANGE LOCATION TO REFLECT PO LOCATION AFTER VANCOUVER COULDN'T RECEIVE POs.
        public string LocnCode
        {
            get
            {
                return _locnCode;
            }

            set
            {
                _locnCode = value;
            }
        }

        [mp.Column(Name = "Comments")]
        public string Comments
        {
            get { return _comments; }
            set { _comments = value; }
        }

        [mp.Column(Name = "DateReceived")]
        public DateTime? DateReceived
        {
            get { return _dateReceived; }
            set { _dateReceived = value; }
        } 

        [mp.Column(Name = "TimeReceived", DbType="Time", CanBeNull=true)]
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

        public short NonInventory
        {
            get { return _nonInventory; }
            set { _nonInventory = value; }
        }

        //Using this so that it can be bound to the datagrid and useable both for the eConnect procedure and WHRECLINE101 without making a separate class
        [mp.Column(Name = "QuantityOrdered")] 
        public int QtyOrdFromGp
        {
            get { return _qtyOrdFromGp; }
            set { _qtyOrdFromGp = value; }
        }

        //Using this so that it can be bound to the datagrid and useable both for the eConnect procedure and WHRECLINE101 without making a separate class
        public int QtyCumulativePrevRecFromGp
        {
            get { return _qtyCumulativeRecFromGp; }
            set { _qtyCumulativeRecFromGp = value; }
        }

        //Using this so that it can be bound to the datagrid and useable both for the eConnect procedure and WHRECLINE101 without making a separate class
        [mp.Column(Name = "QuantityReceived")]  //This is basically the 'QTYSHPPD' columnn in POP10500
        public int QtyRecForGp
        {
            get { return _qtyRecForGp; }
            set 
            { 
                _qtyRecForGp = value;
                OnPropertyChanged("QtyRecForGp");
            }
        }

        [mp.Column(Name = "QuantityRemainingOnRack")]
        public int QtyRemainingOnRec
        {
            get { return _qtyRemainingOnRec; }
            set { _qtyRemainingOnRec = value; }
        }

        public int QtyActualShip
        {
            get { return _qtyActualShip; }
            set { _qtyActualShip = value; }
        }

        //Using this so that it can be bound to the datagrid and displayed even though it's not entered into the WHRECLINE101 table
        public string VendorDatagridDispOnly
        {
            get { return _vendorDatagridDispOnly; }
            set { _vendorDatagridDispOnly = value; }
        }

        //Derived from the tagging table, quantity alraedy tagged, not an entry field.  Read only.
        public int TaggedQuantityCumulative
        {
            get { return _taggedQuantityCumulative; }
            set 
            { 
                _taggedQuantityCumulative = value;
                OnPropertyChanged("TaggedQuantityCumulative");
            }
        }

        public decimal UnitCost
        {
            get { return _unitCost; }
            set { _unitCost = value; }
        }

        //Using this as the user field to transfer quantity to shipping line.  UI only.
        public int UiQuantityToTransfer
        {
            get { return _uiQuantityToTransfer; }
            set { _uiQuantityToTransfer = value; }
        }

        //Using this so that it can be used to determine which lines need to be rolled back from the SQL database in case some inserts of the eConnect procedure fails
        public bool InsertedToDb
        {
            get { return _insertedToDb; }
            set { _insertedToDb = value; }
        }

        public TaggingLine TaggingLine
        {
            get { return _taggingLine; }
            set { _taggingLine = value; }
        }
            
        public string UcHeaderCommentText
        {
            get { return _ucHeaderCommentText; }
            set { _ucHeaderCommentText = value; }
        }

        public string UcLineCommentText
        {
            get { return _ucLineCommentText; }
            set { _ucLineCommentText = value; }
        }

        public ObservableCollection<PoUcshHeaderComment> UcHeaderCommentCol
        {
            get { return _ucHeaderCommentCol; }
            set
            {
                _ucHeaderCommentCol = value;
            }
        }

        public ObservableCollection<PoUcshLineComment> UcLineCommentCol
        {
            get { return _ucLineCommentCol; }
            set
            {
                _ucLineCommentCol = value;
            }
        }

        public DateTime DoNotShipBeforeDate
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

        public ReceivingLine()
        {
        }

        public ReceivingLine(string poNumber, int polnenum,
                             int quantityOrdered,
                             int quantityReceived, int quantityRemaining,
                             string popRctNm, int rcptLnNum,
                             string sopNumber, 
                             string itemNumber, string itemDescription,
                             string vendorId, string vendorName, 
                             string jobNumber, string jobName,
                             string revisionNumber, string location, string comments,
                             DateTime? dateReceived, DateTime? timeReceived)
        {
            this._poNumber = poNumber;
            this._polnenum = polnenum;

            this._qtyOrdFromGp = quantityOrdered;
            this._qtyRecForGp = quantityReceived;
            this._qtyRemainingOnRec = quantityRemaining;
            this._popRctNum = popRctNm;
            this._rcptLnNm = rcptLnNum;
            this._sopNumber = sopNumber ?? string.Empty;

            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._vendorId = vendorId;
            this._vendorName = vendorName;
            this._jobNumber = jobNumber;
            this._jobName = jobName;
            this._revisionNumber = revisionNumber;
            this._location = location;
            this._comments = comments;
            this._dateReceived = dateReceived;
            this._timeReceived = timeReceived;

            this._taggingLine = new TaggingLine(); //no ref to parent receiving line object
            this._taggingLine.OrigReceiptQuantity = _qtyRecForGp;
        }

        //GetPoReceivingLineItemsByPoNum(string poNum)
        public ReceivingLine(string poNumber, int order, short polnesta, string itemNumber, string itemDescription,
            string jobNumber, string jobName,
            string changeId,
            int quantityOrdered, int quantityPrevOrderedGp,
            string vendorId, string vendorName,
            short nonInventory,
            decimal unitCost,
            List<PoUcshHeaderComment> _headerList,
            List<PoUcshLineComment> _lineList,
            string locnCode
            )
        {
            this._poNumber = poNumber;
            this._polnenum = order;
            this._polnesta = polnesta;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._jobNumber = jobNumber;
            this._jobName = jobName ?? string.Empty;
            this._changeId = changeId;
            this._sopNumber = string.Empty;
            this._qtyCumulativeRecFromGp = quantityPrevOrderedGp;
            this._qtyOrdFromGp = quantityOrdered;
            this._qtyRecForGp = 0;  //quantityOrdered - quantityPrevOrderedGp; //11 Nov 2016 - Changing this back to 0.  Warehouse is accidentally fully receiving POs when they shouldn't be.
            this._qtyRemainingOnRec = quantityOrdered - quantityPrevOrderedGp;
            this._vendorId = vendorId;
            this._vendorName = vendorName;
            this._vendorDatagridDispOnly = vendorName;
            this._nonInventory = nonInventory;
            this._unitCost = unitCost;

            this._ucHeaderCommentCol = new ObservableCollection<PoUcshHeaderComment>(_headerList);
            this._ucLineCommentCol = new ObservableCollection<PoUcshLineComment>(_lineList);
            this._ucHeaderCommentText = ConcatPoComment(_headerList);
            this._ucLineCommentText = ConcatPoComment(_lineList);

            this._locnCode = locnCode;
        }

        //GetPoLinesFromSop(string poNum)
        public ReceivingLine(string poNumber, int order, short polnesta, string itemNumber, string itemDescription,
            string sopnumber, 
            string jobNumber, string jobName, 
            int quantityOrdered, int quantityPrevOrderedGp,
            string vendorId, string vendorName,
            short nonInventory, string buyerId,
            string locnCode)
        {
            this._poNumber = poNumber;
            this._polnenum = order;
            this._polnesta = polnesta;
            this._itemNumber = itemNumber;
            this._itemDescription = itemDescription;
            this._sopNumber = sopnumber ?? string.Empty;
            this._jobNumber = jobNumber;
            this._jobName = jobName ?? string.Empty;
            this._qtyCumulativeRecFromGp = quantityPrevOrderedGp;
            this._qtyOrdFromGp = quantityOrdered;
            this._qtyRecForGp = quantityOrdered - quantityPrevOrderedGp;
            this._qtyRemainingOnRec = quantityOrdered - quantityPrevOrderedGp;
            this._vendorId = vendorId;
            this._vendorName = vendorName;
            this._vendorDatagridDispOnly = vendorName;
            this._nonInventory = nonInventory;
            this._buyerId = buyerId;
            this._locnCode = locnCode;
        }

        //GetPoRecLinesWithUcshRecLines()
        public ReceivingLine(string poNumber, int order, string popRctNum, int rcptLnNm, string itemNumber, 
                             string itemDescription, string jobNumber, string jobName, 
                             string buyerId,
                             DateTime? glPostDate,
                             string sopNumber,
                             string vendorId, string vendorname,
                             int qtyOrdFromGp, int qtyRecForGp, int qtyRemainingOnRec,
                             int qtyActualShip,
                             int qtyTagged,
                             string revisionNumber, string location, string comments
                             , DateTime? dateReceived
                             , DateTime? timeReceived
                             , string updatingUser
                             , string updatingMachine
                             , string customerName
                             , string locnCode
            )
        {
            try
            {
                this._poNumber = poNumber;
                this._polnenum = order;
                this._popRctNum = popRctNum;
                this._rcptLnNm = rcptLnNm;
                this._itemNumber = itemNumber;
                this._itemDescription = itemDescription;
                this._jobNumber = jobNumber;
                this._jobName = jobName ?? string.Empty;
                this._buyerId = buyerId ?? string.Empty;
                this._glPostDate = glPostDate;
                this._sopNumber = sopNumber ?? string.Empty;
                this._vendorId = vendorId;
                this._vendorName = vendorname;
                this._qtyOrdFromGp = qtyOrdFromGp;
                this._qtyRecForGp = qtyRecForGp;
                this._qtyRemainingOnRec = qtyRemainingOnRec;
                this._qtyActualShip = qtyActualShip;

                this._taggedQuantityCumulative = qtyTagged;           //new - CUMULATIVE quantity tagged

                this._revisionNumber = revisionNumber;
                this._location = location;
                this._comments = comments;
                this._dateReceived = dateReceived;
                this._timeReceived = timeReceived;
                this._updatingUser = updatingUser;
                this._updatingMachine = updatingMachine;
                this._customerName = customerName;

                //There can be many tag lines for a receiving line, but we only create one tag at a time, so for purposes of binding to the UI in the datagrid, a
                //1-to-1 relationship works.
                this._taggingLine = new TaggingLine(this);
                //this._taggingLine.TaggedQuantity = qtyTagged;
                this._locnCode = locnCode;
            }
            catch (Exception ex)
            {
                MessageBox.Show(this._poNumber);
            }
        }

        public event PropertyChangedEventHandler PropertyChanged;
        private void OnPropertyChanged(string propertyName)
        {
            if (PropertyChanged != null)
                PropertyChanged(this, new PropertyChangedEventArgs(propertyName));
        }

        private string ConcatPoComment(object _genCol)
        {
            if (_genCol.GetType() == typeof(List<PoUcshHeaderComment>))
                return this.UcHeaderCommentText = string.Join(", ", ((List<PoUcshHeaderComment>)_genCol).Select(x => x.CommentText).ToList());
            else
                return this.UcLineCommentText = string.Join(", ", ((List<PoUcshLineComment>)_genCol).Select(x => x.CommentText).ToList());
        }
    }

    public class ReceivingLineDataContext : lq.DataContext
    {
        public ReceivingLineDataContext(string cs)
            : base(cs)
        {

        }

        public ReceivingLineDataContext(SqlConnection conn)
            : base(conn)
        {
        }

        public ReceivingLineDataContext(string cs, lq.Mapping.MappingSource ms)
            : base(cs, ms)
        {
        }

        public lq.Table<ReceivingLine> ReceivingLine;
    }
}
