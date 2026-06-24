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
using System.Collections.ObjectModel;

namespace PM_Project_Tracking.ExcelConverters
{
    public static class ExportCommissionSheets
    {
        public static void GenerateCommSheets(int jobId)
        {
            string filePath = null;
            bool cont = false;
            object[,] _headersArr;
            List<object[,]> _rowsArr;
            int _pageBreakInc = 1000;
            List<ObservableCollection<dc.HardwareSchedule>> _arrList = new List<ObservableCollection<DataClasses.HardwareSchedule>>();

            CheckFolder(GlobalVars.DefaultExcelSavePath);
            cont = ManageExcelFilepath(out filePath);
            List<dc.HardwareSchedule> _hwList = dc.Hardware.GetHardwareSchedule(jobId).ToList();
            //List<string> _hmInfo = _hwList.OrderBy(i => new { i.OpeningNumber, i.ProductHash }).Select(x => x.HmInfoConcat).ToList();
            List<dc.HardwareSchedule> _asdf = _hwList.GroupBy(x => new { x.OpeningNumber, x.ProductHash }).Select(i => i.First()).ToList();

            _headersArr = GetHeadersArry();
            _rowsArr = ObjectArrFromListV2(_hwList, _pageBreakInc);
            CreateExcelFileV2(_rowsArr, _asdf, _headersArr, null);
            GC.Collect();  //https://stackoverflow.com/questions/22050384/excel-process-still-runs-in-background
        }   

        private static void CheckFolder(string pf)
        {
            if (!Directory.Exists(pf))
                System.IO.Directory.CreateDirectory(pf);
        }

        private static bool ManageExcelFilepath(out string filePath)
        {
            filePath = null;
            string pathFolder = GlobalVars.DefaultExcelSavePath;
            string fileName = "Commissioning Sheet - ";
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
                File.Delete(finalPath);
            
            filePath = finalPath;
            return true;
        }

        private static void CreateExcelFileV2(List<object[,]> dataArr, List<dc.HardwareSchedule> hwList, object[,] headerArr, string filePath)
        {
            object[,] headers = headerArr;
            //object[,] rows = dataArr;
            string _curOpen;
            int _sheetIter = 0;
            xl.Application _app = new xl.Application();
            _app.Visible = false;
            xl.Workbook _wb = _app.Workbooks.Add();

            if (dataArr.Count > 3)
                for (int i = 0; i <= dataArr.Count - 3; i++) { _wb.Sheets.Add(); }

            xl.Worksheet xlSh = null;
            xl.Range colRange = null;
            xl.Range headerRange = null;
            xl.Range targetRange = null;
            xl.Range autoFitRange = null;
            xl.Range xlRange = null;
            xl.Range _xlLine = null;
            xl.Range _formatOpenColumn = null;

            try
            {
                foreach (object[,] rows in dataArr)
                {
                    _sheetIter++;
                    xlSh = _wb.Worksheets[_sheetIter];
                    xlSh.Activate();
                    _formatOpenColumn = xlSh.Range["A1", "A" + (rows.GetLength(0) + 1)];
                    _formatOpenColumn.NumberFormat = "@";
                    string colLet = ColumnIndexToColumnLetter(rows.GetLength(1));
                    headerRange = xlSh.Range["A1", colLet + "1"];
                    targetRange = xlSh.Range["A2", colLet + (rows.GetLength(0) + 1)];
                    autoFitRange = xlSh.Range["A1", colLet + (rows.GetLength(0) + 1)];
                    headerRange.Value2 = headers;
                    targetRange.Value2 = rows;
                    headerRange.Style = "Accent2";
                    headerRange.RowHeight = 40;
                    headerRange.WrapText = true;
                    headerRange.AutoFilter(1);
                    //autoFitRange.Columns.AutoFit();
                    //_wb.SaveAs(filePath);
                    xlRange = xlSh.UsedRange;
                    _xlLine = null;

                    for (int i = 1; i < rows.GetLength(0) - 1; i++)
                    {
                        _curOpen = rows[i, 0].ToString();
                        //this will crash if you have an opening number that's less than two characters because getting .Substring(0, 2) from a 1 char string = crash
                        if (_curOpen != rows[i - 1, 0].ToString() && _curOpen.Substring(0, 2) != "Ar" && _curOpen.Substring(0, 2).ToLower() != "no")
                        {
                            _xlLine = (xl.Range)xlSh.Rows[i];
                            xlSh.HPageBreaks.Add((xlSh.Cells[i + 1, 1] as xl.Range));
                            xlSh.Range["A" + (i + 1)].VerticalAlignment = Microsoft.Office.Interop.Excel.XlVAlign.xlVAlignTop;
                            xlSh.Range["A" + (i + 1), "C" + (i + 1)].Merge();
                            ((xl.Range)xlSh.Rows[i + 1]).RowHeight = 80;
                            xlSh.Range["A" + (i + 1), "C" + (i + 1)].WrapText = true; //DOESN'T FUCKING WORK

                            System.Runtime.InteropServices.Marshal.ReleaseComObject(_xlLine);

                        }
                        _curOpen = null;
                    }
                    autoFitRange.Columns.AutoFit();
                    xlSh.PageSetup.PrintArea = "$A$1:$G$" + rows.GetLength(0) + 1;
                    if (xlSh.VPageBreaks.Count > 0)
                    {
                        _app.ActiveWindow.View = Microsoft.Office.Interop.Excel.XlWindowView.xlPageBreakPreview;
                        xlSh.VPageBreaks[1].DragOff(Microsoft.Office.Interop.Excel.XlDirection.xlToRight, 1);
                    }
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                if (colRange != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(colRange);
                if (xlRange != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(xlRange);
                if (_xlLine != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(_xlLine);
                if (autoFitRange != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(autoFitRange);
                if (headerRange != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(headerRange);
                if (targetRange != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(targetRange);
                if (xlSh != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(xlSh);
                if (_formatOpenColumn != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(_formatOpenColumn);
                _app.Visible = true;
            }

            hwList = null;
            headers = null;
            dataArr = null;

            System.Runtime.InteropServices.Marshal.ReleaseComObject(_wb);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(_app);
            _wb = null;
            _app = null;

            GC.Collect();
            GC.WaitForPendingFinalizers();
            GC.Collect();
            GC.WaitForPendingFinalizers();
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

        public static List<object[,]> ObjectArrFromList(List<dc.HardwareSchedule> _hwList, int pageBreakInc)
        {
            List<object[,]> _listOfArrays = new List<object[,]>();
            //List<string> _intervalOpenings = _hwList.Select(x => x.OpeningNumber).Distinct().Skip(1).Where((x, i) => i % 1024 == 0).ToList();
            //Thanks to .FindLastIndex we don't need to .Skip(1)
            List<string> _intervalOpenings = _hwList.Select(x => x.OpeningNumber).Distinct().Where((x, i) => i % pageBreakInc == 0).ToList();
            _intervalOpenings.RemoveAt(0);      //The above LINQ method also returns the very first opening, so we just remove it to reduce confusion.
            _intervalOpenings.Add(_hwList[_hwList.Count - 1].OpeningNumber); //Add the very last opening number in
            //make sure _hwList is sorted by opening and hw row item row as it appears in the HW schedule so that you don't have to do any sorting when transferring values from the list to the array
            int _iterator = 0;
            int _endRow;

            foreach (string open in _intervalOpenings)
            {
                _endRow = _hwList.FindLastIndex(x => x.OpeningNumber == open);
                int _startRow = _iterator;
                object[,] _rowsArr = new object[_endRow - _iterator + 1, 7]; //rows, columns (setting 5 now for arbitrary)
                for (int i = 0; i <= _endRow - _startRow; i++)
                {
                    _rowsArr[i, 0] = _hwList[_iterator].OpeningNumber.ToString();
                    _rowsArr[i, 1] = _hwList[_iterator].ProductHash == null ? "" : _hwList[_iterator].ProductHash.ToString();
                    _rowsArr[i, 2] = _hwList[_iterator].HwType == null ? "" : _hwList[_iterator].HwType.ToString();
                    _rowsArr[i, 3] = _hwList[_iterator].ShortCode == null ? "" : _hwList[_iterator].ShortCode.ToString();
                    _rowsArr[i, 4] = _hwList[_iterator].NumberOfOpenings == null ? "" : _hwList[_iterator].NumberOfOpenings.ToString();
                    _rowsArr[i, 5] = _hwList[_iterator].QuantityPerOpening == null ? "" : _hwList[_iterator].QuantityPerOpening.ToString();
                    _rowsArr[i, 6] = _hwList[_iterator].HmInfoConcat == null ? "" : _hwList[_iterator].HmInfoConcat.ToString();

                    _iterator++;
                }
                _listOfArrays.Add(_rowsArr);
            }

            //return _rowsArr;
            return _listOfArrays;
        }



        public static List<object[,]> ObjectArrFromListV2(List<dc.HardwareSchedule> _hwList, int pageBreakInc)
        {
            List<object[,]> _listOfArrays = new List<object[,]>();
            //List<string> _intervalOpenings = _hwList.Select(x => x.OpeningNumber).Distinct().Skip(1).Where((x, i) => i % 1024 == 0).ToList();
            //Thanks to .FindLastIndex we don't need to .Skip(1)
            List<string> _intervalOpenings = _hwList.Select(x => x.OpeningNumber).Distinct().Where((x, i) => i % pageBreakInc == 0).ToList();
            _intervalOpenings.RemoveAt(0);      //The above LINQ method also returns the very first opening, so we just remove it to reduce confusion.
            _intervalOpenings.Add(_hwList[_hwList.Count - 1].OpeningNumber); //Add the very last opening number in
            //make sure _hwList is sorted by opening and hw row item row as it appears in the HW schedule so that you don't have to do any sorting when transferring values from the list to the array

            int _startRow = 0;
            int _endRow = 0;
            int r;
            string _curOpen = "";

            foreach (string terminalOpen in _intervalOpenings)
            {
                List<dc.HardwareSchedule> _hwListPage = new List<dc.HardwareSchedule>();
                //_hwListPage.Add(new dc.HardwareSchedule() { OpeningNumber = _hwList[_startRow].HmInfoConcat }); //Adding a HM info header line to the opening number property to start prior to the loop
                _endRow = _hwList.FindLastIndex(x => x.OpeningNumber == terminalOpen);

                for (r = _startRow; r <= _endRow; r++)
                {
                    if (_curOpen != _hwList[r].OpeningNumber)
                        _hwListPage.Add(new dc.HardwareSchedule() { OpeningNumber = _hwList[r].HmInfoConcat.Trim() });

                    _curOpen = _hwList[r].OpeningNumber;
                    _hwListPage.Add(_hwList[r]);
                }

                _startRow = r++;
                _listOfArrays.Add(ToExcelObjectArray(_hwListPage));
            }

            return _listOfArrays;
        }

        private static object[,] ToExcelObjectArray(List<dc.HardwareSchedule> hwList)
        {
            object[,] _rowsArr = new object[hwList.Count, 6];
            int i = 0;
            foreach (dc.HardwareSchedule hw in hwList)
            {
                _rowsArr[i, 0] = hw.OpeningNumber.ToString();
                _rowsArr[i, 1] = hw.ProductHash == null ? "" : hw.ProductHash.ToString();
                _rowsArr[i, 2] = hw.HwType == null ? "" : hw.HwType.ToString();
                _rowsArr[i, 3] = hw.ShortCode == null ? "" : hw.ShortCode.ToString();
                _rowsArr[i, 4] = hw.NumberOfOpenings == null ? "" : hw.NumberOfOpenings.ToString();
                _rowsArr[i, 5] = hw.QuantityPerOpening == null ? "" : hw.QuantityPerOpening.ToString();
                i++;
            }
            return _rowsArr;
        }

        private static object[,] GetHeadersArry()
        {
            object[,] _headers = new object[1, 7];
            _headers[0, 0] = "Opening Number(s)";
            _headers[0, 1] = "Product Code";
            _headers[0, 2] = "Category";
            _headers[0, 3] = "Group Number";
            _headers[0, 4] = "Number of Openings";
            _headers[0, 5] = "QTY Per Opening";
            _headers[0, 6] = "Checked";

            return _headers;
        }

        //public static object[,] ObjectArrFromList(List<dc.HardwareSchedule> _hwList)
        //{
        //    object[,] _rowsArr = new object[_hwList.Count, 6]; //rows, columns (setting 5 now for arbitrary)
        //    List<string> _hwInfo = new List<string>();
        //    //make sure _hwList is sorted by opening and hw row item row as it appears in the HW schedule so that you don't have to do any sorting when transferring values from the list to the array
        //    string _curOpen = _hwList[0].OpeningNumber;
        //    _hwInfo.Add(_hwList[0].HmInfoConcat);

        //    for (int i = 0; i < _hwList.Count; i++)
        //    {
        //        _rowsArr[i, 0] = _hwList[i].OpeningNumber.ToString();
        //        _rowsArr[i, 1] = _hwList[i].ProductHash == null ? "" : _hwList[i].ProductHash.ToString();
        //        _rowsArr[i, 2] = _hwList[i].HwType == null ? "" : _hwList[i].HwType.ToString();
        //        _rowsArr[i, 3] = _hwList[i].ShortCode == null ? "" : _hwList[i].ShortCode.ToString();
        //        _rowsArr[i, 4] = _hwList[i].NumberOfOpenings == null ? "" : _hwList[i].NumberOfOpenings.ToString();
        //        _rowsArr[i, 5] = _hwList[i].QuantityPerOpening == null ? "" : _hwList[i].QuantityPerOpening.ToString();
        //        //_rowsArr[i, 2] = _hwList[i].
        //        if (_rowsArr[i, 0] != _curOpen)
        //        {
        //            _hwInfo.Add(_hwList[i].HmInfoConcat);
        //            _curOpen = _rowsArr[i, 0].ToString();
        //        }
        //    }

        //    return _rowsArr;
        //}
    }
}
