using System;
using System.Collections.Generic;
using System.Linq;
using System.Data; // ADO.NET
using System.Data.SqlClient; // ADO.NET
using System.Text;
using System.Threading.Tasks;
using xl = Microsoft.Office.Interop.Excel;
using System.Windows;
using System.IO;
using dc = PM_Project_Tracking.DataClasses;

namespace PM_Project_Tracking.ExcelConverters
{
    public static class ExcelExporter
    {
        //https://www.add-in-express.com/creating-addins-blog/2013/11/05/release-excel-com-objects/
        //http://www.dotnetperls.com/excel

        //http://stackoverflow.com/questions/1041266/c-sharp-and-excel-automation-ending-the-running-instance
        //http://stackoverflow.com/questions/12530303/close-excel-application-process-after-data-has-been-fetched
        //http://stackoverflow.com/questions/158706/how-to-properly-clean-up-excel-interop-objects/159419#159419

        //https://blogs.msdn.microsoft.com/visualstudio/2010/03/01/marshal-releasecomobject-considered-dangerous/
        //http://stackoverflow.com/questions/9962157/safely-disposing-excel-interop-objects-in-c

        private static dc.User _user;

        public static void DatabaseToExcel(ReportName rn, dc.User user)
        {
            string[,] headerArr = null;
            object[,] objArr = null;
            string filePath = null;
            bool cont = false;
            _user = user;

            CheckFolder(GlobalVars.DefaultExcelSavePath);
            cont = ManageExcelFilepath(rn, out filePath);
            if (cont)
                cont = GetTableData(rn, out objArr, out headerArr);

            if (cont)
                CreateExcelFile(objArr, headerArr, filePath);
        }

        private static void CheckFolder(string pf)
        {
            if (!Directory.Exists(pf))
                System.IO.Directory.CreateDirectory(pf);
        }

        private static bool ManageExcelFilepath(ReportName rn, out string filePath)
        {
            filePath = null;
            string pathFolder = GlobalVars.DefaultExcelSavePath;
            string fileName = GetFileName(rn);
            string dateStr = DateTime.Now.ToString("dd-MMM-yyyy");
            //string timeStr = DateTime.Now.ToString("hh");
            string excelWbName = fileName + " - " + dateStr + ".xlsx";
            string finalPath = pathFolder + @"\" + excelWbName;
            //string finalPath = pathFolder + @"\" + fileName + dateStr + " time-" + timeStr + ".xlsx";

            if (File.Exists(finalPath))
            {
                try
                {
                    using (var stream = new FileStream(finalPath, FileMode.Open, FileAccess.Read)) { }
                }
                catch (IOException ex)
                {
                    MessageBox.Show("File with the same name is already open.  Please close the existing Excel file with the name '" + excelWbName + "' before attempting any more exports.");
                    MessageBox.Show(ex.ToString());
                    return false;
                }
            }
            
            //Excel already handles this
            if (File.Exists(finalPath))
            {
                File.Delete(finalPath);
                //if (MessageBox.Show("File '" + excelWbName + "' already exists.  Would you like to overwrite it?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                //{
                //    filePath = finalPath;
                //    return true;
                //}
                //else
                //{
                //    return false;
                //}
            }
            filePath = finalPath;
            return true;
        }

        private static bool GetTableData(ReportName rn, out object[,] objData, out string[,] headerData)
        {
            SqlConnection adoCon = new SqlConnection(GlobalVars.UcshConnectionString);
            SqlDataAdapter dscmd = null;
            DataSet ds = new DataSet();
            string readStr = null;
            int x = 0;
            int y = 0;
            //rn = ReportName.MainProjects;

            object[,] objArr = null;
            string[,] strArr = null;
            try
            {
                readStr = GetQueryReadString(rn);
                adoCon.Open();
                dscmd = new SqlDataAdapter(readStr, adoCon);
                dscmd.Fill(ds);
                objArr = new object[ds.Tables[0].Rows.Count, ds.Tables[0].Columns.Count]; 
                int colCount = ds.Tables[0].Columns.Count;

                for (x = 0; x <= ds.Tables[0].Rows.Count - 1; x++) //ds.Tables[0].Rows.Count
                {
                    for (y = 0; y <= ds.Tables[0].Columns.Count - 1; y++) //ds.Tables[0].Columns.Count
                    {
                        objArr[x, y] = ds.Tables[0].Rows[x].ItemArray[y].ToString();
                    }
                }

                strArr = new string[1, colCount];
                for (int n = 0; n <= colCount - 1; n++)
                {
                    strArr[0, n] = ds.Tables[0].Columns[n].ColumnName;
                }
            }
            catch (SqlException sqlEx)
            {
                headerData = strArr;
                objData = objArr;
                MessageBox.Show(sqlEx.ToString());
                return false;
            }
            catch (Exception ex)
            {
                headerData = strArr;
                objData = objArr;
                MessageBox.Show(ex.ToString());
                return false;
            }
            finally
            {
                adoCon.Close();
            }

            headerData = strArr;
            objData = objArr;
            return true;
        }

        private static bool GetTableDataStoredFucntion(ReportName rn, out object[,] objData, out string[,] headerData)
        {
            dc.PoListFunctionV1 objContext = null;
            List<dc.PurchaseOrderLineItem> asdf = null;
            objContext = new dc.PoListFunctionV1("Data Source=UCSHSQL2\\MSSQL2014; Initial Catalog=Avaware;Integrated Security=SSPI");
            asdf = objContext.ConnectsPoLineTestAllJobs().ToList();
            int x = 0;
            int y = 0;
            //rn = ReportName.MainProjects;

            object[,] objArr = null;
            string[,] strArr = null;

            var properties = from property in typeof(dc.PurchaseOrderLineItem).GetProperties()
                             where property.Name != "QuantityMatched"
                             where property.Name != "BackOrder"
                             let orderAttribute = property.GetCustomAttributes(typeof(dc.OrderAttribute), false).SingleOrDefault() as dc.OrderAttribute
                             orderby orderAttribute.Order
                             select property;

            try
            {




                //readStr = GetQueryReadString(rn);
                //adoCon.Open();
                //dscmd = new SqlDataAdapter(readStr, adoCon);
                //dscmd.Fill(ds);
                //objArr = new object[ds.Tables[0].Rows.Count, ds.Tables[0].Columns.Count];
                //int colCount = ds.Tables[0].Columns.Count;

                //for (x = 0; x <= ds.Tables[0].Rows.Count - 1; x++) //ds.Tables[0].Rows.Count
                //{
                //    for (y = 0; y <= ds.Tables[0].Columns.Count - 1; y++) //ds.Tables[0].Columns.Count
                //    {
                //        objArr[x, y] = ds.Tables[0].Rows[x].ItemArray[y].ToString();
                //    }
                //}

                //strArr = new string[1, colCount];
                //for (int n = 0; n <= colCount - 1; n++)
                //{
                //    strArr[0, n] = ds.Tables[0].Columns[n].ColumnName;
                //}
            }
            catch (SqlException sqlEx)
            {
                headerData = strArr;
                objData = objArr;
                MessageBox.Show(sqlEx.ToString());
                return false;
            }
            catch (Exception ex)
            {
                headerData = strArr;
                objData = objArr;
                MessageBox.Show(ex.ToString());
                return false;
            }
            finally
            {
                //adoCon.Close();
            }

            headerData = strArr;
            objData = objArr;
            return true;
        }

        private static void CreateExcelFile(object[,] dataArr, string[,] headerArr, string filePath)
        {
            string[,] headers = headerArr;
            object[,] rows = dataArr;
            xl.Application _app = new xl.Application();
            xl.Workbook _wb = _app.Workbooks.Add();
            _app.Visible = true;

            xl.Worksheet xlSh = _wb.Worksheets[1];
            string colLet = ColumnIndexToColumnLetter(rows.GetLength(1));
            xl.Range headerRange = xlSh.Range["A1", colLet + "1"];
            xl.Range targetRange = xlSh.Range["A2", colLet + (rows.GetLength(0) + 1)];
            xl.Range autoFitRange = xlSh.Range["A1", colLet + (rows.GetLength(0) + 1)];
            headerRange.Value2 = headers;
            targetRange.Value2 = rows;
            headerRange.Style = "Accent2";
            headerRange.AutoFilter(1);
            autoFitRange.Columns.AutoFit();
            _wb.SaveAs(filePath);
            headers = null;
            rows = null;

            System.Runtime.InteropServices.Marshal.ReleaseComObject(autoFitRange);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(headerRange);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(targetRange);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(xlSh);

            //_wb.Close(false);
            //_app.Quit();
            System.Runtime.InteropServices.Marshal.ReleaseComObject(_wb);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(_app);
            GC.Collect();
        }

        static string ColumnIndexToColumnLetter(int colIndex)
        {
            int div = colIndex;
            string colLetter = String.Empty;
            int mod = 0;

            while (div > 0)
            {
                mod = (div - 1) % 26;
                colLetter = (char)(65 + mod) + colLetter;
                div = (int)((div - mod) / 26);
            }
            return colLetter;
        }

        private static string GetFileName(ReportName rn)
        {
            switch (rn)
            {
                case ReportName.Pursuits:
                    return "Pursuits";
                case ReportName.OffersToTender:
                    return "Offers to Tender";
                case ReportName.Bids:
                    return "Bidding Projects";
                case ReportName.AwardedContracts:
                    return "Awarded Contracts";
                case ReportName.MainProjects:
                    return "Main Projects";
                case ReportName.MainProjectsPmOnly:
                    return "Main Projects - " + Environment.UserDomainName;
                case ReportName.WarehouseReceiptsAll:
                    return "Warehouse Receiving - ";
                case ReportName.WarehouseShipHeaderAll:
                    return "Warehouse Shipping Headers - ";
                case ReportName.WarehouseShipLineAll:
                    return "Warehouse Shipping Lines - ";
                default:
                    return null;
            }
        }

        private static string GetQueryReadString(ReportName rn)
        {
            //NOTE THESE QUERIES WILL NOT WORK ON THE TEST DATABASE, THEY ONLY POINT TO LIVE ONES
            switch (rn)
            {
                case ReportName.Pursuits:
                    return "SELECT * FROM UTPMPURSUIT101";
                case ReportName.QuoteSummaries:
                    return "SELECT a.JobNumber, a.JobName, a.QuoteNumber, a.Contractor, a.ClosingDate, b.Consultant, b.ProjectStatus, b.Division, a.OriginatingDocumentNumber, a.OriginatingRevisionNumber,  " +
                            "a.RevisionIteration, a.FieldInstall, a.FrameInstall, a.AutoOperatorInstall, a.NumberOfDoorLeafs, a.RevenuePerDoor, a.Cc2102002Cost, a.Cc2102002Sell,  " +
                            "a.Cc2102002Mu, a.Cc2200002Cost, a.Cc2200002Sell, a.Cc2200002Mu, a.Cc3100003Cost, a.Cc3100003Sell, a.Cc3100003Mu, a.Cc3200003Cost, a.Cc3200003Sell,  " +
                            "a.Cc3200003Mu, a.Cc3300003Cost, a.Cc3300003Sell, a.Cc3300003Mu, a.Cc3400003Cost, a.Cc3400003Sell, a.Cc3400003Mu, a.Cc3500003Cost, a.Cc3500003Sell,  " +
                            "a.Cc3500003Mu, a.Cc4100004Cost, a.Cc4100004Sell, a.Cc4100004Mu, a.Cc4400004Cost, a.Cc4400004Sell, a.Cc4400004Mu, a.Cc4500004Cost, a.Cc4500004Sell,  " +
                            "a.Cc4500004Mu, a.Cc4600004Cost, a.Cc4600004Sell, a.Cc4600004Mu, a.Cc5100005Cost, a.Cc5100005Sell, a.Cc5100005Mu, a.Cc5200005Cost, a.Cc5200005Sell,  " +
                            "a.Cc5200005Mu, a.Cc9000009Cost, a.Cc9000009Sell, a.Cc9000009Mu, a.DateCreated, a.UpdatingUser " +
                            "FROM UTPMQUOTESUMMARY101 as a " +
                            "left join " +
                            "(SELECT DISTINCT JobNumber, Consultant, ProjectStatus, Division from[UTPMBIDPROJ101]) as b " +
                            "ON a.JobNumber = b.JobNumber ";
                case ReportName.OffersToTender:
                    return "SELECT * FROM UTPMOFFERTOTENDER101";
                case ReportName.Bids:
                    return "SELECT * FROM UTPMBIDPROJ101";
                case ReportName.AwardedContracts:
                    return "SELECT * FROM UTPMAWCONTRACTS101";
                case ReportName.MainProjects:
                    return "select proj.JobNumber, jc.WS_Job_Name, jc.Divisions, proj.SubstantialCompletionDate, jc.WS_Manager_ID, jc.Estimator_ID, proj.ProjectCoordinator, proj.HardwareCoordinator, " +
                                "rm.CUSTNAME, proj.ProjectStatus, proj.DateModified, proj.EstStartDate, " +
                                "proj.EstEndDate, jc.Contract_to_Date, " +
                                "jc.Billed_Amount_TTD, " +
                                "(jc.Contract_to_Date- jc.Billed_Amount_TTD) as Backlog, " +
                                "(CONVERT(decimal(8,4),((jc.Contract_to_Date - (jc.Contract_to_Date- jc.Billed_Amount_TTD)) / nullif(jc.Contract_to_Date, 0))) * 100)  as PercentageBilled, " +
                                "cs.TotalActualCostTTD, " +
                                "(CONVERT(decimal(8,4),((jc.Billed_Amount_TTD - cs.TotalActualCostTTD) / nullif(jc.Billed_Amount_TTD, 0))) * 100)  as CurrentMargin, " +
                                "ac.ContractStatus, " +
                                "ac.PreMobStatus, proj.SupplyCompletionPer, proj.Hardware, proj.DoorsAndFrames, proj.UCAccess, " +
                                "proj.PickeringInstall, proj.PickeringInstallPer, proj.SiteInstall, " +
                                "proj.SiteInstallPer, proj.ChangeOrders, proj.ChangeOrderComments, proj.PMComments " +
                                "from [UTPMMAINAWPROJ101] as proj " +
                                "left join (select distinct JobNumber, ContractStatus, PreMobStatus from [UTPMAWCONTRACTS101]) as ac " +
                                "on proj.JobNumber=ac.JobNumber " +
                                "left join (select distinct WS_Job_Number, WS_Job_Name, Divisions, WS_Manager_ID, " +
                                "Estimator_ID, CUSTNMBR, Contract_to_Date, Billed_Amount_TTD from [UCSH].[dbo].[JC00102]) as jc " +
                                "on proj.JobNumber=jc.WS_Job_Number " +
                                "left join (select distinct CUSTNMBR, CUSTNAME  from [UCSH].[dbo].[RM00101]) as rm " +
                                "on jc.CUSTNMBR=rm.CUSTNMBR " +
                                "left join (select distinct WS_Job_Number, WS_Inactive from [UCSH].[dbo].[JC00901]) as acj " +
                                "on proj.JobNumber=acj.WS_Job_Number " +
                                "left join (select WS_Job_Number, SUM(Cost_Code_Act_Cost_TTD) as TotalActualCostTTD from [UCSH].[dbo].[JC20001] group by WS_Job_Number) as cs " +
                                "on proj.JobNumber = cs.WS_Job_Number " +
                                "where acj.WS_Inactive=0 " +
                                "order by proj.JobNumber desc";
                case ReportName.MainProjectsPmOnly:
                    return "select proj.JobNumber, jc.WS_Job_Name, jc.Divisions, proj.SubstantialCompletionDate, jc.WS_Manager_ID, jc.Estimator_ID,  proj.ProjectCoordinator, proj.HardwareCoordinator, " +
                                "rm.CUSTNAME, proj.ProjectStatus, proj.DateModified, proj.EstStartDate, " +
                                "proj.EstEndDate, jc.Contract_to_Date, " +
                                "jc.Billed_Amount_TTD, " +
                                "(jc.Contract_to_Date- jc.Billed_Amount_TTD) as Backlog, " +
                                "(CONVERT(decimal(8,4),((jc.Contract_to_Date - (jc.Contract_to_Date- jc.Billed_Amount_TTD)) / nullif(jc.Contract_to_Date, 0))) * 100)  as PercentageBilled, " +
                                "cs.TotalActualCostTTD, " +
                                "(CONVERT(decimal(8,4),((jc.Billed_Amount_TTD - cs.TotalActualCostTTD) / nullif(jc.Billed_Amount_TTD, 0))) * 100)  as CurrentMargin, " +
                                "ac.ContractStatus, " +
                                "ac.PreMobStatus, proj.SupplyCompletionPer, proj.Hardware, proj.DoorsAndFrames, proj.UCAccess, " +
                                "proj.PickeringInstall, proj.PickeringInstallPer, proj.SiteInstall, " +
                                "proj.SiteInstallPer, proj.ChangeOrders, proj.ChangeOrderComments, proj.PMComments " +
                                "from [UTPMMAINAWPROJ101] as proj " +
                                "left join (select distinct JobNumber, ContractStatus, PreMobStatus from [UTPMAWCONTRACTS101]) as ac " +
                                "on proj.JobNumber=ac.JobNumber " +
                                "left join (select distinct WS_Job_Number, WS_Job_Name, Divisions, WS_Manager_ID, " +
                                "Estimator_ID, CUSTNMBR, Contract_to_Date, Billed_Amount_TTD from [UCSH].[dbo].[JC00102]) as jc " +
                                "on proj.JobNumber=jc.WS_Job_Number " +
                                "left join (select distinct CUSTNMBR, CUSTNAME  from [UCSH].[dbo].[RM00101]) as rm " +
                                "on jc.CUSTNMBR=rm.CUSTNMBR " +
                                "left join (select distinct WS_Job_Number, WS_Inactive from [UCSH].[dbo].[JC00901]) as acj " +
                                "on proj.JobNumber=acj.WS_Job_Number " +
                                "left join (select WS_Job_Number, SUM(Cost_Code_Act_Cost_TTD) as TotalActualCostTTD from [UCSH].[dbo].[JC20001] group by WS_Job_Number) as cs " +
                                "on proj.JobNumber = cs.WS_Job_Number " +
                                //"where jc.Estimator_ID='" + _user.GpEstimatorId + "' AND acj.WS_Inactive=0 " +
                                "order by proj.JobNumber desc";
                case ReportName.WarehouseReceiptsAll:
                    return "select * from [WHRECLINE101]";
                case ReportName.TaskSchedulerItemsAll:
                    return @"SELECT a.[ID]
                            ,a.[Completed]
                            ,a.[JobNumber]
                            ,b.[ProjectManager]
                            ,a.[JobName]
                            ,a.[AssignedById]
                            ,a.[AssignedByName]
                            ,a.[AssignedToId]
                            ,a.[AssignedToName]
                            ,a.[TaskTypeInt]
                            ,a.[TaskTypeName]
                            ,a.[Area]
                            ,a.[Duration]
                            ,a.[Division]
                            ,a.[StartDate]
                            ,a.[EndDate]
                            ,a.[TimeRemaining]
                            ,a.[BaselineStartDate]
                            ,a.[BaselineEndDate]
                            ,a.[VarianceDuration]
                            ,a.[TotalQuantity]
                            ,a.[CompletedQuantity]
                            ,a.[Comment]
                            ,a.[DateCreated]
                            ,a.[TimeCreated]
                            ,a.[UpdatingUser]
                            ,a.[UpdatingMachine]
                            ,a.[EditingUser]
                            ,a.[EditedDate]
                            ,a.[EditedTime]
                            FROM[PMUCSH].[dbo].[PMTASKSCHEDULER101] as a
                            left join (select JobNumber, ProjectManager from [PMUCSH].[dbo].[UTPMMAINAWPROJ101]) AS b
                            on a.JobNumber = b.JobNumber";
                case ReportName.WarehouseShipHeaderAll:
                    return "select * from [WHSHIPHEADER101]";
                case ReportName.WarehouseShipLineAll:
                    return "select * from [WHSHIPLINE101]";
                case ReportName.PurchaseOrderAll:
                    return @"SELECT * FROM(SELECT RTRIM(a.[PONUMBER]) AS PONUMBER-- 1
                              , a.[ORD]-- 2
                              , CAST(ISNULL(a.[JOBNUMBR], '') as varchar(255)) AS JOBNUMBR-- 3
                              , CAST(ISNULL(c.[WS_Job_Name], '') as varchar(255)) AS WS_Job_Name-- 4
                              , i.[SOPNUMBE]-- 5
                              , b.[BUYERID]-- 6
                              , a.[ADDRESS3] AS ChangeId
                              , a.[VENDORID]-- 7
                              , d.[VENDNAME]-- 8
                              , a.[LineNumber]-- 9
                              , a.[POLNESTA]-- 10
                              --,case a.[POLNESTA]--
                              --when 1 THEN 'New'
                              --when 2 then 'Released'
                              --when 3 then 'Change Order'
                              --when 4 THEN 'Received'
                              --when 5 then 'Closed'
                              --when 6 then 'Cancelled'
                              --end as 'PO LINE STATUS'
                              ,a.[ITEMNMBR]-- 11
	                          ,a.[ITEMDESC]-- 12
	                          ,a.[QTYORDER]-- 13
	                          ,CAST(ISNULL(f.QTYREC, 0) AS int) AS QTYREC   --14
	                          --,ISNULL(e.[QTYINVCD], 0) AS QTYINVCD          --15
	                          ,a.[QTYORDER] - CAST(ISNULL(f.QTYREC, 0) AS int) as BACKORDER
                              ,a.[UNITCOST]
                              ,a.[EXTDCOST]
                              --,r.[PO Total EXTD Cost]
                              --,r.TotalCost
	                          ,CAST(ISNULL(g.QTYSHIP, 0) AS int) AS QTYSHIP --16
	                          --,hdrComms.[CMMTTEXT] AS HEADERCMMTTEXT
                           --   , lineComms.[CMMTTEXT] as LINECMMTTEXT
	                          --,comJoin2.[UcHeaderCommentsConcat]			-- 23
                           --   ,comJoin.[UcLineCommentsConcat]				-- 24
	                          ,b.[DOCDATE] as 'PO Creation Date'
	                          
	                          --,h.DateReceived
	                          
	                          --,k.EarliestRecDate
	                          
	                          ,r.mrec
	                          
	                          ,a.[LSTRCPTDT]			-- 18
	                          ,a.[LOCNCODE]				-- 19
	                          ,a.[COSTCODE]				-- 20
                              ,a.[REQDATE]				-- 21
                              ,a.[PRMSHPDTE]			-- 22
      
                              --,(a.QTYORDER - CONVERT(numeric, ISNULL(g.QTYSHIP, 0))) as QTYORDER
                          FROM[UCSH].[dbo].[POP10110]
                                AS a
                          LEFT JOIN
                          [UCSH].[dbo].[POP10100]
                                AS b
                          ON a.PONUMBER=b.PONUMBER
                          LEFT JOIN
                          [UCSH].[dbo].[JC00102] AS c
                          ON a.JOBNUMBR= c.WS_Job_Number
                          LEFT JOIN
                          [UCSH].[dbo].[PM00200] AS d
                          ON a.VENDORID= d.VENDORID
                          LEFT JOIN
                          [UCSH].[dbo].[WS10101] AS e
                          ON a.PONUMBER= e.PONUMBER AND a.ORD= e.ORD
                          LEFT JOIN 
                          ( select PONUMBER, POLNENUM, sum(QTYSHPPD) as QTYREC FROM[UCSH].[dbo].[POP10500]
                                GROUP BY PONUMBER, POLNENUM ) AS f
                          ON a.PONUMBER=f.PONUMBER AND a.ORD= f.POLNENUM
                           LEFT JOIN 
                          ( select PONUMBER, POLNENUM, sum(QuantityShipped) as QTYSHIP FROM[PMUCSH].[dbo].[WHSHIPLINE101]
                                GROUP BY PONUMBER, POLNENUM ) AS g
                          ON a.PONUMBER=g.PONUMBER AND a.ORD= g.POLNENUM
							
						LEFT JOIN 
                          ( select PONUMBER, POLNENUM, MIN(DateReceived) AS mrec FROM [PMUCSH].[dbo].[WHRECLINE101]
                                GROUP BY PONUMBER, POLNENUM ) AS r
                          ON a.PONUMBER=r.PONUMBER AND a.ORD= r.POLNENUM
                          
                        --LEFT JOIN
                        --  (
                        --  SELECT
                        --  [PONUMBER], SUM([EXTDCOST]) AS 'PO Total EXTD Cost' FROM[UCSH].[dbo].[POP10110] 
                        --  GROUP BY PONUMBER
                        --  ) AS r
                        --  ON a.PONUMBER=r.PONUMBER
                          LEFT JOIN
                         (SELECT DISTINCT SOPNUMBE, PONUMBER, ORD FROM [UCSH].[dbo].[SOP60100]) AS i
                          ON a.PONUMBER=i.PONUMBER AND a.ORD= i.ORD
                        --  Left Join (SELECT POPNUMBE, CMMTTEXT from [UCSH].[dbo].[POP10150] ) AS hdrComms
                        --  on a.PONUMBER=hdrComms.POPNUMBE
                        --  Left Join (SELECT POPNUMBE, ORD, CMMTTEXT from [UCSH].[dbo].[POP10550] ) AS lineComms
                        --  on a.PONUMBER=lineComms.POPNUMBE and a.ORD= lineComms.ORD
                        --  LEFT JOIN
	                       -- (SELECT DISTINCT com3.PONUMBER,
	                       -- ( 
                        --    SELECT com4.CommentText + CHAR(10) as [text()]
                        --    from [PMUCSH].[dbo].[POUCSHHEADERCOMMENT101] as com4
                        --    where com3.PONUMBER= com4.PONUMBER
                        --    FOR XML PATH('')
	                       -- ) as [UcHeaderCommentsConcat]
                        --        from[PMUCSH].[dbo].[POUCSHHEADERCOMMENT101] as com3 ) as comJoin2
                        --on a.PONUMBER=comJoin2.PONUMBER
                        --LEFT JOIN
                        --(SELECT DISTINCT com1.PONUMBER, com1.ORD,
	                       -- ( 
                        --    SELECT com2.CommentText + CHAR(10) as [text()]
                        --    from [PMUCSH].[dbo].[POUCSHLINECOMMENT101] as com2
                        --where com1.PONUMBER= com2.PONUMBER and com1.ORD= com2.ORD
                        --    FOR XML PATH('')
	                       -- ) as [UcLineCommentsConcat]
                        --        from[PMUCSH].[dbo].[POUCSHLINECOMMENT101] as com1 ) as comJoin
                        --on a.PONUMBER=comJoin.PONUMBER and a.ORD=comJoin.ORD
                        ) AS retQuery";
                default:
                    return null;
            }
        }

        public enum ReportName
        {
            Pursuits = 1,
            QuoteSummaries,
            OffersToTender,
            Bids,
            AwardedContracts,
            MainProjects,
            MainProjectsPmOnly,
            WarehouseReceiptsAll,
            TaskSchedulerItemsAll,
            WarehouseShipHeaderAll,
            WarehouseShipLineAll,
            PurchaseOrderAll
        }
    }
}
