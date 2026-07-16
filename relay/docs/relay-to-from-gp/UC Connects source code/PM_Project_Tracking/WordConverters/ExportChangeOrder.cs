using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using wd = Microsoft.Office.Interop.Word;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using System.Windows;
using System.Windows.Media;
using System.Runtime.InteropServices;
using System.Collections.ObjectModel;
using System.Drawing;
using System.IO;

namespace PM_Project_Tracking.WordConverters
{
    class ExportChangeOrder
    {
        public static void CreateChangeOrderDocument(pm.ChangeHeader ch, ObservableCollection<pm.ChangeLine> cLines, pm.ChangeIndex chIndex, bool isItemized)
        {
            List<CostCodeGroup> _ccGrp = GetGroupedCostCodeSums(cLines);
            if (isItemized)
                CreateItemizedChangeOrderDocument(ch, _ccGrp, chIndex, cLines);
            else
                CreateChangeOrderDocument(ch, _ccGrp, chIndex);
        }

        private static void CreateChangeOrderDocument(pm.ChangeHeader ch, List<CostCodeGroup> ccGrp, pm.ChangeIndex chIndex)
        {
            wd.Application wdIn = new wd.Application();
            wd.Document _doc = wdIn.Documents.Add();
            wdIn.Visible = true;
            
            
            //ch.OverheadPercentage = 5.5m;
            //ch.ProfitPercentage = 10m;

            string ohPer = String.Format("{0:0.00}", ch.OverheadPercentage); //"";//Format(overheadPercentH40, "Percent")
            string profPer = String.Format("{0:0.00}", ch.ProfitPercentage); // "";//Format(ovProfitD41, "Percent")
            decimal ohDecTotal = (ch.OverheadPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum();
            string ohTotal = String.Format("{0:C}", ((ch.OverheadPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum()));  // "";//Format(ovValue, "Currency")
            decimal profDecTotal = (ch.ProfitPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum();
            string profTotal = String.Format("{0:C}", ((ch.ProfitPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum())); // "";//Format(profValue, "Currency")
            string totalAmount = String.Format("{0:C}", ohDecTotal + profDecTotal + ccGrp.Select(n => n.CostCustomer).Sum());

            wdIn.Selection.PageSetup.TopMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.BottomMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.LeftMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.RightMargin = wdIn.CentimetersToPoints(1.27F);

            wd.Range hdRange = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            wd.Table wdTab1 = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range.Tables.Add(hdRange, 1, 3, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            wdTab1.Columns[1].Width = 110;
            wdTab1.Columns[2].Width = 340.8F;
            //wdTab1.Columns[3].Width = 10;

            wdTab1.Cell(1, 2).Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdTab1.Cell(1, 2).Range.Font.Size = 24;
            wdTab1.Cell(1, 2).Range.Font.Bold = 1;
            wdTab1.Cell(1, 2).Range.Text = "\rQUOTATION";

            wdTab1.Cell(1, 1).Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
            
            try
            {
                if (File.Exists(@"P:\Documents\Graphics\UCSH Excel PO Add-In Graphics\400x400.jpg"))
                    wdTab1.Cell(1, 1).Range.InlineShapes.AddPicture(@"P:\Documents\Graphics\UCSH Excel PO Add-In Graphics\400x400.jpg");
                else
                    wdTab1.Cell(1, 1).Range.InlineShapes.AddPicture(@"X:\UCConnects Graphics\400x400.jpg");

            }
            catch (Exception e)
            {
                MessageBox.Show("Error with UCSH logo file: \r" + Convert.ToString(e));
                return;
            }

            wdTab1.Cell(1, 3).Range.Font.Size = 10;
            wdTab1.Cell(1, 3).Range.Text = "Head Office\r" +
                                            "7100 Warden Avenue\r" +
                                            "Unit 1\r" +
                                            "Markham, Ontario\r" +
                                            "L3R 8B5\r" +
                                            "PH:  905-940-8358\r" +
                                            "FAX:  905-940-8362";

            wdTab1.Cell(1, 3).Range.Paragraphs.SpaceAfter = 0;

            wd.Table wdTab2 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 8, 5, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

//wdTab2.Range.Font.Color = 2500134;
            wdTab2.Range.Font.Size = 10;
            wdTab2.Range.Paragraphs.SpaceAfter = 0;

            wdTab2.Columns[1].Width = 60;
            wdTab2.Columns[2].Width = 180;
            wdTab2.Columns[3].Width = 146.8F;
            wdTab2.Columns[4].Width = 84;
            wdTab2.Columns[5].Width = 80;
            
            wdIn.Selection.SetRange(wdTab2.Cell(1, 1).Range.Start, wdTab2.Cell(8, 1).Range.End);
            wdIn.Selection.Font.Bold = 1;
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;

            foreach (wd.Border bd in wdTab1.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            //
            //wdIn.Selection.SetRange Start:=wdTab2.Cell(1, 2).Range.Start, End:=wdTab2.Cell(1, 2).Range.End 'wdTab1.Cell(3, 3).Range.Start, wdTab1.Cell(9, 3).Range.End);
            wdTab2.Cell(1, 2).Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            //wdIn.Selection.Borders.OutsideLineStyle = wdLineStyleDot;
            //wdIn.Selection.Shading.BackgroundPatternColor = wdColorGray05;
            //wdIn.Selection.Font.Size = 12;
            //wdIn.Selection.Font.Bold = 1;
            //wdIn.Selection.Cells.Merge();
            //
            foreach (wd.Border bd in wdTab2.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab2.Cell(1, 1).Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab2.Cell(1, 1).Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                  //
            wdTab2.Cell(1, 1).Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            //
            wdIn.Selection.SetRange(wdTab2.Cell(8, 1).Range.Start, wdTab2.Cell(8, 5).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            //
            wdIn.Selection.SetRange(wdTab2.Cell(7, 1).Range.Start, wdTab2.Cell(7, 2).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.Font.Bold = 1;
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                   //
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            //
            wdIn.Selection.SetRange(wdTab2.Cell(3, 2).Range.Start, wdTab2.Cell(5, 2).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.SetRange(wdTab2.Cell(3, 1).Range.Start, wdTab2.Cell(5, 1).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //wdIn.Selection.SetRange Start:=wdTab2.Cell(3, 1).Range.Start, End:=wdTab2.Cell(6, 1).Range.End;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                    //
            wdIn.Selection.Borders.InsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                     //
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            wdIn.Selection.SetRange(wdTab2.Cell(3, 5).Range.Start, wdTab2.Cell(5, 5).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.SetRange(wdTab2.Cell(3, 4).Range.Start, wdTab2.Cell(5, 4).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //wdIn.Selection.SetRange Start:=wdTab2.Cell(3, 4).Range.Start, End:=wdTab2.Cell(5, 4).Range.End;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                   //
            wdIn.Selection.Borders.InsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                    //
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            wdIn.Selection.Font.Bold = 1;

            wdTab2.Cell(1, 1).Range.Text = "Project";
            wdTab2.Cell(1, 2).Range.Font.Bold = 0;
            //wdTab2.Rows(2).Range.Font.Size = 3;
            //wdTab2.Rows(2).Height = 10;

            wdTab2.Cell(3, 1).Range.Text = "Contractor";
            wdTab2.Cell(4, 1).Range.Text = "Contact";
            wdTab2.Cell(5, 1).Range.Text = "E-mail";
            //
            wdTab2.Cell(3, 4).Range.Text = "Date";
            wdTab2.Cell(4, 4).Range.Text = "UCSH Quote No.";
            wdTab2.Cell(5, 4).Range.Text = "Contractor ID No.";
            wdTab2.Cell(5, 5).Range.Text = ch.ContractorChangeId;
            //
            wdTab2.Cell(7, 1).Range.Text = "UCSH Projected of Scope-of-Work";
            wdTab2.Cell(8, 1).Range.Text = ch.HeaderDescription;
            //
            wdTab2.Cell(1, 2).Range.Text = chIndex.JobName;

            wdTab2.Cell(3, 2).Range.Text = ch.Contractor;
            wdTab2.Cell(4, 2).Range.Text = chIndex.ContactName;
            wdTab2.Cell(5, 2).Range.Text = chIndex.ContactEmail;
            //
//wdTab2.Cell(3, 5).Range.Text = Format(Date, "dd-mmm-yy")
            wdTab2.Cell(3, 5).Range.Text = DateTime.Today.ToString("dd MMM yyyy");
            wdTab2.Cell(4, 5).Range.Text = ch.QuoteNumber;
            //wdTab2.Cell(8, 1).Range.Text = "";

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);
            wdIn.Selection.TypeParagraph();

            wd.Table wdTab3 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, (ccGrp.Count * 2) + 1, 3, wd.WdDefaultTableBehavior.wdWord9TableBehavior);    //Add 2 extra lines if there are IsLabour lines
            
            foreach (wd.Border bd in wdTab3.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab3.Range.Font.Color = (Microsoft.Office.Interop.Word.WdColor)(38 + 0x100 * 38 + 0x10000 * 38);
            wdTab3.Range.Font.Size = 10;
            wdTab3.Range.Paragraphs.SpaceAfter = 0;
            wdTab3.Columns[1].Width = 420.8F;
            wdTab3.Columns[2].Width = 50;
            wdTab3.Columns[3].Width = 80;
            //wdIn.Selection.SetRange(wdTab3.Cell(2, 3).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 3).Range.End);
            //wdIn.Selection.Range.Font.Size = 12;

            wdIn.Selection.SetRange(wdTab3.Cell(1, 1).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 3).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
            wdIn.Selection.SetRange(wdTab3.Cell(1, 2).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 2).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.SetRange(wdTab3.Cell(1, 3).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 3).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;

            wdIn.Selection.SetRange(wdTab3.Cell(1, 1).Range.Start, wdTab3.Cell(1, 3).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.Font.Bold = 1;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdTab3.Cell(1, 1).Range.Text = "Supply Subcontract";

            wdTab3.Columns.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleNone;
            wdTab3.Rows.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdTab3.Rows[1].Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab3.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;  //RGB(217, 229, 193)
            wdTab3.Rows[1].Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10; //RGB(195, 214, 155)

            //fill in the rows with change line data
            //when getting the change lines, need to filter out the individual IsLabour/Gen Condition lines and just provide them as a one line sum

            int i = -1;
            for (int x = 1; x < (ccGrp.Count * 2); x += 2)
            {
                i += 1;
                wdTab3.Cell(x + 1, 1).Range.Text = ccGrp[i].CostCode + " " + ccGrp[i].CostCodeName;
                wdTab3.Cell(x + 2, 2).Range.Text = "Sub-total";
                wdTab3.Cell(x + 2, 3).Range.Text = String.Format("{0:C}", ccGrp[i].CostCustomer);
                wdIn.Selection.SetRange(wdTab3.Cell(x + 2, 2).Range.Start, wdTab3.Cell(x + 2, 3).Range.End);
                wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
                if (ccGrp[i].CostCustomer < 0)
                    wdTab3.Cell(x + 2, 3).Range.Font.Color = (Microsoft.Office.Interop.Word.WdColor)(255 + 0x100 * 0 + 0x10000 * 0);

                if ((i + 2) % 2 != 0)
                {
                    wdIn.Selection.SetRange(wdTab3.Cell(x + 1, 1).Range.Start, wdTab3.Cell(x + 2, 3).Range.End);
                    wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
                    wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;
                }
            }

            wdTab3.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab3.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);
            wdIn.Selection.TypeParagraph();

            wd.Table wdTab4 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 4, 4, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            foreach (wd.Border bd in wdTab4.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab4.Range.Font.Color = (Microsoft.Office.Interop.Word.WdColor)(38 + 0x100 * 38 + 0x10000 * 38);
            wdTab4.Range.Font.Size = 10;
            wdTab4.Range.Paragraphs.SpaceAfter = 0;
            wdTab4.Columns[1].Width = 280.8F;
            wdTab4.Columns[2].Width = 130;
            wdTab4.Columns[3].Width = 50;
            wdTab4.Columns[4].Width = 90;
            wdIn.Selection.SetRange(wdTab4.Cell(1, 2).Range.Start, wdTab4.Cell(3, 4).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);
            wdIn.Selection.Borders.InsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);
            wdIn.Selection.SetRange(wdTab4.Cell(1, 2).Range.Start, wdTab4.Cell(3, 2).Range.End);
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10; // 'RGB(195, 214, 155)
            wdIn.Selection.Range.Font.Bold = 1;
            wdTab4.Cell(1, 2).Range.Text = "Overhead";
            //wdTab4.Cell(1, 3).Range.Text = ""; //Not actually a percentage, just carrying over the variable name
            wdTab4.Cell(2, 2).Range.Text = "Profit";
            //wdTab4.Cell(2, 3).Range.Text = "";        //Old variable, name not entirely accurate
            wdTab4.Cell(3, 2).Range.Text = "Total Contract Price Change";
            wdTab4.Cell(1, 3).Range.Text = ohPer + "%";  // ch.OverheadPercentage.ToString(); //"";//Format(overheadPercentH40, "Percent")
            wdTab4.Cell(2, 3).Range.Text = profPer + "%";  // "";//Format(ovProfitD41, "Percent")
            wdTab4.Cell(1, 4).Range.Text = ohTotal;  // (ch.OverheadPercentage * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum()).ToString();  // "";//Format(ovValue, "Currency")
            wdTab4.Cell(2, 4).Range.Text = profTotal;  // (ch.ProfitPercentage * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum()).ToString(); // "";//Format(profValue, "Currency")
            wdTab4.Cell(3, 4).Range.Text = totalAmount;  // "";//Format(TotalH42, "Currency");
            wdIn.Selection.SetRange(wdTab4.Cell(3, 4).Range.Start, wdTab4.Cell(1, 4).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.Range.Font.Bold = 0;
            wdTab4.Cell(3, 2).Range.Font.Bold = 1;  //I shouldn't even have to use this one, but something is messed up
            wdTab4.Cell(4, 4).Range.Text = "*HST not included";
            wdIn.Selection.SetRange(wdTab4.Cell(3, 3).Range.Start, wdTab4.Cell(3, 4).Range.End);
            wdIn.Selection.Cells.Merge();

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);
            wdIn.Selection.TypeParagraph();

            wd.Table wdTab5 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 7, 3, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            foreach (wd.Border bd in wdTab5.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab5.Columns[2].Width = 143.6F;
            wdTab5.Columns[3].Width = 223.6F;
            wdTab5.Rows[4].Height = 25;
            wdTab5.Rows[5].Height = 25;
            wdTab5.Rows[6].Height = 25;
            //MsgBox wdTab5.Columns(2).Width & " - " & wdTab5.Columns(3).Width
            wdTab5.Range.Font.Color = (Microsoft.Office.Interop.Word.WdColor)(38 + 0x100 * 38 + 0x10000 * 38);
            wdTab5.Range.Font.Size = 10;
            wdTab5.Range.Paragraphs.SpaceAfter = 0;
            wdIn.Selection.SetRange(wdTab5.Cell(1, 3).Range.Start, wdTab5.Cell(1, 3).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.Range.Font.Size = 12;
            wdIn.Selection.Range.Font.Bold = 1;
            wdIn.Selection.SetRange(wdTab5.Cell(1, 2).Range.Start, wdTab5.Cell(6, 2).Range.End);
            wdIn.Selection.SetRange(wdTab5.Cell(1, 2).Range.Start, wdTab5.Cell(6, 2).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.SetRange(wdTab5.Cell(4, 3).Range.Start, wdTab5.Cell(7, 3).Range.End);
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;

            wdIn.Selection.SetRange(wdTab5.Cell(3, 2).Range.Start, wdTab5.Cell(3, 3).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;

            wdTab5.Cell(1, 3).Range.Text = "Upper Canada Specialty Hardware";
            wdTab5.Cell(3, 2).Range.Text = "Written authorization required to proceed with the above";
            wdTab5.Cell(4, 2).Range.Text = "Print Signature";
            wdTab5.Cell(5, 2).Range.Text = "Signature";
            wdTab5.Cell(6, 2).Range.Text = "Authorization Date";

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);

            wd.Range ftRange = null;
            ftRange = _doc.Sections[1].Footers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            _doc.Sections[1].Footers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range.Text = "Exclusions and Optional Pricing.\r" +
                             "    -  Work not specifically stated above.\r" +
                             "    -  Costs shown herein are good for 30 days from the date shown above.  We will proceed with the work upon written authorization.";

            ftRange.Font.Size = 8;

            //https://stackoverflow.com/questions/13628622/how-to-set-the-file-name-of-a-word-document-without-saving-it-from-c-sharp-and-a
            dynamic dialog = wdIn.Dialogs[wd.WdWordDialog.wdDialogFileSummaryInfo];
            dialog.Title = ch.JobNumber + "  " + ch.QuoteNumber 
                                                + "  " + DateTime.Today.ToString("dd")
                                                + " " + DateTime.Today.ToString("MMM")
                                                + " " + DateTime.Today.ToString("yyyy"); ;
            dialog.Execute();

            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdTab1);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdTab2);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(_doc);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdIn);
            GC.Collect();
        }

        private static void CreateItemizedChangeOrderDocument(pm.ChangeHeader ch, List<CostCodeGroup> ccGrp, pm.ChangeIndex chIndex, ObservableCollection<pm.ChangeLine> cLines)
        {
            wd.Application wdIn = new wd.Application();
            wd.Document _doc = wdIn.Documents.Add();
            wdIn.Visible = true;


            //ch.OverheadPercentage = 5.5m;
            //ch.ProfitPercentage = 10m;

            string ohPer = String.Format("{0:0.00}", ch.OverheadPercentage); //"";//Format(overheadPercentH40, "Percent")
            string profPer = String.Format("{0:0.00}", ch.ProfitPercentage); // "";//Format(ovProfitD41, "Percent")
            decimal ohDecTotal = (ch.OverheadPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum();
            string ohTotal = String.Format("{0:C}", ((ch.OverheadPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum()));  // "";//Format(ovValue, "Currency")
            decimal profDecTotal = (ch.ProfitPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum();
            string profTotal = String.Format("{0:C}", ((ch.ProfitPercentage / 100) * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum())); // "";//Format(profValue, "Currency")
            string totalAmount = String.Format("{0:C}", ohDecTotal + profDecTotal + ccGrp.Select(n => n.CostCustomer).Sum());

            wdIn.Selection.PageSetup.TopMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.BottomMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.LeftMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.RightMargin = wdIn.CentimetersToPoints(1.27F);

            wd.Range hdRange = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            wd.Table wdTab1 = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range.Tables.Add(hdRange, 1, 3, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            wdTab1.Columns[1].Width = 110;
            wdTab1.Columns[2].Width = 340.8F;
            //wdTab1.Columns[3].Width = 10;

            wdTab1.Cell(1, 2).Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdTab1.Cell(1, 2).Range.Font.Size = 24;
            wdTab1.Cell(1, 2).Range.Font.Bold = 1;
            wdTab1.Cell(1, 2).Range.Text = "\rQUOTATION";

            wdTab1.Cell(1, 1).Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;

            try
            {
                if (File.Exists(@"P:\Documents\Graphics\UCSH Excel PO Add-In Graphics\400x400.jpg"))
                    wdTab1.Cell(1, 1).Range.InlineShapes.AddPicture(@"P:\Documents\Graphics\UCSH Excel PO Add-In Graphics\400x400.jpg");
                else
                    wdTab1.Cell(1, 1).Range.InlineShapes.AddPicture(@"X:\UCConnects Graphics\400x400.jpg");
            }
            catch (Exception e)
            {
                MessageBox.Show("Error with UCSH logo file: \r" + Convert.ToString(e));
                return;
            }

            wdTab1.Cell(1, 3).Range.Font.Size = 10;
            wdTab1.Cell(1, 3).Range.Text = "Head Office\r" +
                                            "7100 Warden Avenue\r" +
                                            "Unit 1\r" +
                                            "Markham, Ontario\r" +
                                            "L3R 8B5\r" +
                                            "PH:  905-940-8358\r" +
                                            "FAX:  905-940-8362";

            wdTab1.Cell(1, 3).Range.Paragraphs.SpaceAfter = 0;

            wd.Table wdTab2 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 8, 5, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            //wdTab2.Range.Font.Color = 2500134;
            wdTab2.Range.Font.Size = 10;
            wdTab2.Range.Paragraphs.SpaceAfter = 0;

            wdTab2.Columns[1].Width = 60;
            wdTab2.Columns[2].Width = 180;
            wdTab2.Columns[3].Width = 146.8F;
            wdTab2.Columns[4].Width = 84;
            wdTab2.Columns[5].Width = 80;

            wdIn.Selection.SetRange(wdTab2.Cell(1, 1).Range.Start, wdTab2.Cell(8, 1).Range.End);
            wdIn.Selection.Font.Bold = 1;
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;

            foreach (wd.Border bd in wdTab1.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            //
            //wdIn.Selection.SetRange Start:=wdTab2.Cell(1, 2).Range.Start, End:=wdTab2.Cell(1, 2).Range.End 'wdTab1.Cell(3, 3).Range.Start, wdTab1.Cell(9, 3).Range.End);
            wdTab2.Cell(1, 2).Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            //wdIn.Selection.Borders.OutsideLineStyle = wdLineStyleDot;
            //wdIn.Selection.Shading.BackgroundPatternColor = wdColorGray05;
            //wdIn.Selection.Font.Size = 12;
            //wdIn.Selection.Font.Bold = 1;
            //wdIn.Selection.Cells.Merge();
            //
            foreach (wd.Border bd in wdTab2.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab2.Cell(1, 1).Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab2.Cell(1, 1).Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                  //
            wdTab2.Cell(1, 1).Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            //
            wdIn.Selection.SetRange(wdTab2.Cell(8, 1).Range.Start, wdTab2.Cell(8, 5).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            //
            wdIn.Selection.SetRange(wdTab2.Cell(7, 1).Range.Start, wdTab2.Cell(7, 2).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.Font.Bold = 1;
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                   //
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            //
            wdIn.Selection.SetRange(wdTab2.Cell(3, 2).Range.Start, wdTab2.Cell(5, 2).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.SetRange(wdTab2.Cell(3, 1).Range.Start, wdTab2.Cell(5, 1).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //wdIn.Selection.SetRange Start:=wdTab2.Cell(3, 1).Range.Start, End:=wdTab2.Cell(6, 1).Range.End;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                    //
            wdIn.Selection.Borders.InsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                     //
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            wdIn.Selection.SetRange(wdTab2.Cell(3, 5).Range.Start, wdTab2.Cell(5, 5).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdIn.Selection.SetRange(wdTab2.Cell(3, 4).Range.Start, wdTab2.Cell(5, 4).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //wdIn.Selection.SetRange Start:=wdTab2.Cell(3, 4).Range.Start, End:=wdTab2.Cell(5, 4).Range.End;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                   //
            wdIn.Selection.Borders.InsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);                                    //
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;
            wdIn.Selection.Font.Bold = 1;

            wdTab2.Cell(1, 1).Range.Text = "Project";
            wdTab2.Cell(1, 2).Range.Font.Bold = 0;
            //wdTab2.Rows(2).Range.Font.Size = 3;
            //wdTab2.Rows(2).Height = 10;

            wdTab2.Cell(3, 1).Range.Text = "Contractor";
            wdTab2.Cell(4, 1).Range.Text = "Contact";
            wdTab2.Cell(5, 1).Range.Text = "E-mail";
            //
            wdTab2.Cell(3, 4).Range.Text = "Date";
            wdTab2.Cell(4, 4).Range.Text = "UCSH Quote No.";
            wdTab2.Cell(5, 4).Range.Text = "Contractor ID No.";
            wdTab2.Cell(5, 5).Range.Text = ch.ContractorChangeId;
            //
            wdTab2.Cell(7, 1).Range.Text = "UCSH Projected of Scope-of-Work";
            wdTab2.Cell(8, 1).Range.Text = ch.HeaderDescription;
            //
            wdTab2.Cell(1, 2).Range.Text = chIndex.JobName;

            wdTab2.Cell(3, 2).Range.Text = ch.Contractor;
            wdTab2.Cell(4, 2).Range.Text = chIndex.ContactName;
            wdTab2.Cell(5, 2).Range.Text = chIndex.ContactEmail;
            //
            //wdTab2.Cell(3, 5).Range.Text = Format(Date, "dd-mmm-yy")
            wdTab2.Cell(3, 5).Range.Text = DateTime.Today.ToString("dd MMM yyyy");
            wdTab2.Cell(4, 5).Range.Text = ch.QuoteNumber;
            //wdTab2.Cell(8, 1).Range.Text = "";

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);
            wdIn.Selection.TypeParagraph();

            wd.Table wdTab3 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, (ccGrp.Count + (cLines.Count * 2)) + 1, 4, wd.WdDefaultTableBehavior.wdWord9TableBehavior);    //Add 2 extra lines if there are IsLabour lines

            foreach (wd.Border bd in wdTab3.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab3.Range.Font.Color = (Microsoft.Office.Interop.Word.WdColor)(38 + 0x100 * 38 + 0x10000 * 38);
            wdTab3.Range.Font.Size = 10;
            wdTab3.Range.Paragraphs.SpaceAfter = 0;
            wdTab3.Columns[1].Width = 400.8F;
            wdTab3.Columns[2].Width = 50;
            wdTab3.Columns[3].Width = 20;
            wdTab3.Columns[4].Width = 80;
            //wdIn.Selection.SetRange(wdTab3.Cell(2, 3).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 3).Range.End);
            //wdIn.Selection.Range.Font.Size = 12;

            wdIn.Selection.SetRange(wdTab3.Cell(1, 1).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 4).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
            wdIn.Selection.SetRange(wdTab3.Cell(1, 2).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 3).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.SetRange(wdTab3.Cell(1, 3).Range.Start, wdTab3.Cell(wdTab3.Rows.Count, 4).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;

            wdIn.Selection.SetRange(wdTab3.Cell(1, 1).Range.Start, wdTab3.Cell(1, 4).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.Font.Bold = 1;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdTab3.Cell(1, 1).Range.Text = "Supply Subcontract";

            wdTab3.Columns.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleNone;
            wdTab3.Rows.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdTab3.Rows[1].Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab3.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray05;  //RGB(217, 229, 193)
            wdTab3.Rows[1].Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10; //RGB(195, 214, 155)

            //fill in the rows with change line data
            //when getting the change lines, need to filter out the individual IsLabour/Gen Condition lines and just provide them as a one line sum

            int i = 0;
            int curRow = 2;
            wdIn.Selection.SetRange(wdTab3.Cell(curRow, 1).Range.Start, wdTab3.Cell(curRow, 4).Range.End);
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray25;

            foreach (CostCodeGroup ccg in ccGrp)
            {
                List<pm.ChangeLine> curLines;

                if (ccg.CostCodeName != "LABOUR")
                    curLines = cLines.Where(x => x.CostCode == ccg.CostCode && x.IsLabour == false).OrderBy(r => r.Id).ToList();
                else
                    curLines = cLines.Where(x => x.IsLabour == true).OrderBy(r => r.Id).ToList();

                wdTab3.Cell(curRow, 1).Range.Text = ccGrp[i].CostCode + " " + ccGrp[i].CostCodeName + " - TOTAL: $" + String.Format("{0:0.00}", ccGrp[i].CostCustomer);
                wdTab3.Cell(curRow, 1).Range.Font.Bold = 1;
                for (int x = 0; x < curLines.Count; x++)
                {
                    curRow++;
                    wdTab3.Cell(curRow, 1).Range.Text = curLines[x].LineDescription;
                    wdTab3.Cell(curRow, 3).Range.Text = String.Format("{0:0.00}", curLines[x].Quantity);
                    wdTab3.Cell(curRow, 4).Range.Text = "$" + String.Format("{0:0.00}", curLines[x].ExtendedSellPrice); 
                    if (x % 2 != 0)
                    {
                        wdIn.Selection.SetRange(wdTab3.Cell(curRow, 1).Range.Start, wdTab3.Cell(curRow, 4).Range.End);    
                        wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
                        wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;
                    }
                }
                curRow++;
                i++;
                wdIn.Selection.SetRange(wdTab3.Cell(curRow, 1).Range.Start, wdTab3.Cell(curRow, 4).Range.End);
                wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray25;
            }

            wdTab3.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab3.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);
            wdIn.Selection.TypeParagraph();

            wd.Table wdTab4 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 4, 4, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            foreach (wd.Border bd in wdTab4.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab4.Range.Font.Color = (Microsoft.Office.Interop.Word.WdColor)(38 + 0x100 * 38 + 0x10000 * 38);
            wdTab4.Range.Font.Size = 10;
            wdTab4.Range.Paragraphs.SpaceAfter = 0;
            wdTab4.Columns[1].Width = 280.8F;
            wdTab4.Columns[2].Width = 130;
            wdTab4.Columns[3].Width = 50;
            wdTab4.Columns[4].Width = 90;
            wdIn.Selection.SetRange(wdTab4.Cell(1, 2).Range.Start, wdTab4.Cell(3, 4).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.OutsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);
            wdIn.Selection.Borders.InsideColor = (Microsoft.Office.Interop.Word.WdColor)(191 + 0x100 * 191 + 0x10000 * 191);
            wdIn.Selection.SetRange(wdTab4.Cell(1, 2).Range.Start, wdTab4.Cell(3, 2).Range.End);
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10; // 'RGB(195, 214, 155)
            wdIn.Selection.Range.Font.Bold = 1;
            wdTab4.Cell(1, 2).Range.Text = "Overhead";
            //wdTab4.Cell(1, 3).Range.Text = ""; //Not actually a percentage, just carrying over the variable name
            wdTab4.Cell(2, 2).Range.Text = "Profit";
            //wdTab4.Cell(2, 3).Range.Text = "";        //Old variable, name not entirely accurate
            wdTab4.Cell(3, 2).Range.Text = "Total Contract Price Change";
            wdTab4.Cell(1, 3).Range.Text = ohPer + "%"; // ch.OverheadPercentage.ToString(); //"";//Format(overheadPercentH40, "Percent")
            wdTab4.Cell(2, 3).Range.Text = profPer + "%";  // ch.ProfitPercentage.ToString(); // "";//Format(ovProfitD41, "Percent")
            wdTab4.Cell(1, 4).Range.Text = ohTotal;   // (ch.OverheadPercentage * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum()).ToString();  // "";//Format(ovValue, "Currency")
            wdTab4.Cell(2, 4).Range.Text = profTotal;  // (ch.ProfitPercentage * ccGrp.Where(x => x.CostCode != "").Select(n => n.CostCustomer).Sum()).ToString(); // "";//Format(profValue, "Currency")
            wdTab4.Cell(3, 4).Range.Text = totalAmount;  // "";//Format(TotalH42, "Currency");
            wdIn.Selection.SetRange(wdTab4.Cell(3, 4).Range.Start, wdTab4.Cell(1, 4).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.Range.Font.Bold = 0;
            wdTab4.Cell(3, 2).Range.Font.Bold = 1;  //I shouldn't even have to use this one, but something is messed up
            wdTab4.Cell(4, 4).Range.Text = "*HST not included";
            wdIn.Selection.SetRange(wdTab4.Cell(3, 3).Range.Start, wdTab4.Cell(3, 4).Range.End);
            wdIn.Selection.Cells.Merge();

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);
            wdIn.Selection.TypeParagraph();

            wd.Table wdTab5 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 7, 3, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            foreach (wd.Border bd in wdTab5.Borders)
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;

            wdTab5.Columns[2].Width = 143.6F;
            wdTab5.Columns[3].Width = 223.6F;
            wdTab5.Rows[4].Height = 25;
            wdTab5.Rows[5].Height = 25;
            wdTab5.Rows[6].Height = 25;
            //MsgBox wdTab5.Columns(2).Width & " - " & wdTab5.Columns(3).Width
            wdTab5.Range.Font.Color = (Microsoft.Office.Interop.Word.WdColor)(38 + 0x100 * 38 + 0x10000 * 38);
            wdTab5.Range.Font.Size = 10;
            wdTab5.Range.Paragraphs.SpaceAfter = 0;
            wdIn.Selection.SetRange(wdTab5.Cell(1, 3).Range.Start, wdTab5.Cell(1, 3).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.Range.Font.Size = 12;
            wdIn.Selection.Range.Font.Bold = 1;
            wdIn.Selection.SetRange(wdTab5.Cell(1, 2).Range.Start, wdTab5.Cell(6, 2).Range.End);
            wdIn.Selection.SetRange(wdTab5.Cell(1, 2).Range.Start, wdTab5.Cell(6, 2).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.SetRange(wdTab5.Cell(4, 3).Range.Start, wdTab5.Cell(7, 3).Range.End);
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;

            wdIn.Selection.SetRange(wdTab5.Cell(3, 2).Range.Start, wdTab5.Cell(3, 3).Range.End);
            wdIn.Selection.Cells.Merge();
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;

            wdTab5.Cell(1, 3).Range.Text = "Upper Canada Specialty Hardware";
            wdTab5.Cell(3, 2).Range.Text = "Written authorization required to proceed with the above";
            wdTab5.Cell(4, 2).Range.Text = "Print Signature";
            wdTab5.Cell(5, 2).Range.Text = "Signature";
            wdTab5.Cell(6, 2).Range.Text = "Authorization Date";

            wdIn.Selection.EndKey(wd.WdUnits.wdStory);

            wd.Range ftRange = null;
            ftRange = _doc.Sections[1].Footers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            _doc.Sections[1].Footers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range.Text = "Exclusions and Optional Pricing.\r" +
                             "    -  Work not specifically stated above.\r" +
                             "    -  Costs shown herein are good for 30 days from the date shown above.  We will proceed with the work upon written authorization.";

            ftRange.Font.Size = 8;

            dynamic dialog = wdIn.Dialogs[wd.WdWordDialog.wdDialogFileSummaryInfo];
            dialog.Title = ch.JobNumber + " " + ch.QuoteNumber;
            dialog.Execute();

            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdTab1);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdTab2);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(_doc);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdIn);
            GC.Collect();
        }

        private static List<CostCodeGroup> GetGroupedCostCodeSums(ObservableCollection<pm.ChangeLine> cls)
        {
            List<CostCodeGroup> _ccgList = new List<CostCodeGroup>();
            _ccgList.Add(new CostCodeGroup() { CostCode = "", CostCodeName= "General Conditions"});        //IsLabour
            foreach (pm.ChangeLine cl in cls)
            {
                CostCodeGroup _selCcg = _ccgList.Where(x => x.CostCode == cl.CostCode).FirstOrDefault();
                if (cl.IsLabour == true)
                    _ccgList[0].CostCustomer += cl.ExtendedSellPrice;
                else if (_selCcg == null)
                    _ccgList.Add(new CostCodeGroup() { CostCustomer = cl.ExtendedSellPrice, CostCode = cl.CostCode, CostCodeName = cl.CostCodeName });
                else
                    _selCcg.CostCustomer += cl.ExtendedSellPrice;
            }
            if (_ccgList[0].CostCustomer == 0)      //Remove IsLabour group it if it doesn't have any value
                _ccgList.RemoveAt(0);
            else                                    //Move to the back if it does
            {
                CostCodeGroup _isLabour = _ccgList[0];
                _isLabour.CostCodeName = "LABOUR";
                _ccgList.RemoveAt(0);
                _ccgList.Add(_isLabour);
            }

            return _ccgList;
        }

        private class CostCodeGroup
        {
            public decimal CostCustomer { get; set; }
            public string CostCode { get; set; }
            public string CostCodeName { get; set; }
        }
    }
}
