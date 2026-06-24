using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using wd = Microsoft.Office.Interop.Word;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using dc = PM_Project_Tracking.DataClasses;
using System.Windows;
using System.Windows.Media;
using System.Runtime.InteropServices;
using System.Collections.ObjectModel;

namespace PM_Project_Tracking.WordConverters
{
    class ExportShipmentHeaderAndLines
    {
        public static void CreateShipmentDocument(dc.ShippingHeader shipHeader, ObservableCollection<dc.ShippingLine> shipLines, int shipSel = 0, string[,] shipArr = null,  params string[] vendAdd)
        {
            wd.Application wdIn = new wd.Application();
            wd.Document _doc = wdIn.Documents.Add(""); //wd.Document _doc = wdIn.Documents.Add() //No quotation marks in the constructor
            wdIn.Visible = true;

            // Remember to check for fileformat validation and that you're running this on an xml file
            int i;
            int o;

            // The beginning of the messy process of creating forms in Word procedurally instead of using a template
            wdIn.ActiveDocument.Content.Font.Name = "Trebuchet MS";
            wdIn.Selection.PageSetup.TopMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.BottomMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.LeftMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.RightMargin = wdIn.CentimetersToPoints(1.27F);
            // Table 1 formatting
            //
            wd.Range hdRange = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            hdRange.Fields.Add(hdRange, wd.WdFieldType.wdFieldPage);

            wd.Table wdTab1 = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range.Tables.Add(hdRange, 11, 3, wd.WdDefaultTableBehavior.wdWord9TableBehavior);
            foreach (wd.Border bd in wdTab1.Borders)
            {
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;
            }

            wdTab1.Range.Font.Size = 8.5F;
            wdTab1.Rows.Height = 8;
            wdTab1.Rows[1].Height = 25;
            wdTab1.Cell(1, 3).Range.Text = "SHIPPING MEMO";
            wdTab1.Cell(1, 3).Range.Bold = 1;
            wdTab1.Cell(1, 3).Range.Font.Size = 20;

            wdTab1.Cell(11, 3).Range.Text = "SHIP COMPLETE";
            wdTab1.Cell(11, 3).Range.Bold = 1;
            wdTab1.Cell(11, 3).Range.Font.Size = 16;
            //

            wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekPrimaryHeader;

            wdIn.Selection.SetRange(wdTab1.Cell(3, 3).Range.Start, wdTab1.Cell(10, 3).Range.End);
            wdIn.Selection.Cells.Split(1, 2);
            // wdTab1.Cell(1, 2).Range.Bold = 1;
            wdIn.Selection.Range.Bold = 1;
            // wdTab1.Cell(1, 2).Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            //

            wdIn.Selection.SetRange(wdTab1.Cell(3, 3).Range.Start, wdTab1.Cell(5, 3).Range.End);

            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.SetRange(wdTab1.Cell(7, 3).Range.Start, wdTab1.Cell(8, 3).Range.End);
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //
            wdIn.Selection.SetRange(wdTab1.Cell(3, 3).Range.Start, wdTab1.Cell(5, 4).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //
            wdIn.Selection.SetRange(wdTab1.Cell(7, 3).Range.Start, wdTab1.Cell(8, 4).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //
            wdIn.Selection.SetRange(wdTab1.Cell(2, 1).Range.Start, wdTab1.Cell(10, 1).Range.End);
            wdIn.Selection.Cells.Merge();

            //
            wdTab1.Cell(3, 3).Range.Text = "Shipping Memo No.";
            wdTab1.Cell(3, 4).Range.Text = shipHeader.MemoNumber.ToString();

            wdTab1.Cell(4, 3).Range.Text = "Exported Date";
            wdTab1.Cell(4, 4).Range.Text = Convert.ToString(DateTime.Today.ToString("dd-MMM-yyyy"));
            wdTab1.Cell(5, 3).Range.Text = "Page";
            wdTab1.Cell(7, 3).Range.Text = "Recording Date"; //DateShipped field aka date created
            wdTab1.Cell(7, 4).Range.Text = shipHeader.DateShipped.Value.ToString("dd-MMM-yyyy");
            wdTab1.Cell(8, 3).Range.Text = "Required By";
            wdTab1.Cell(8, 4).Range.Text = shipHeader.ReschedShipDate == null ? "" : shipHeader.ReschedShipDate.Value.ToString("dd-MMM-yyyy"); // headArr[8, 1].ToString();
            //wdTab1.Cell(9, 3).Range.Text = "Rev #";
            ///if (shipArr != null) wdTab1.Cell(9, 4).Range.Text = shipArr[0, 1];

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, wdTab1.Rows.Count);
            wdIn.Selection.TypeParagraph();

            // Add page numbers
            wdTab1.Cell(5, 4).Range.Select();
            wdTab1.Cell(5, 4).Range.Text = " ";
            wdTab1.Cell(5, 4).Range.Collapse(wd.WdCollapseDirection.wdCollapseEnd);
            wdIn.ActiveDocument.Fields.Add(wdIn.Selection.Range, wd.WdFieldType.wdFieldPage);

            wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekMainDocument;

            // Table 2 formatting
            //
            wd.Table wdTab2 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 17, 1, wd.WdDefaultTableBehavior.wdWord9TableBehavior);
            foreach (wd.Border bd in wdTab2.Borders)
            {
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;
            }
            wdTab2.Range.Font.Size = 8.5F;
            wdTab2.Rows.Height = 8.5F;
            wdTab2.Rows[2].Range.Font.Size = 12;
            wdTab2.Cell(2, 1).Range.Text = "Upper Canada Specialty Hardware";
            wdTab2.Cell(2, 1).Range.Bold = 1;
            wdTab2.Cell(3, 1).Range.Text = "7100 Warden Avenue";
            wdTab2.Cell(4, 1).Range.Text = "Unit 1";
            wdTab2.Cell(5, 1).Range.Text = "Markham, ON    L3R 8B5";
            //
            wdIn.Selection.SetRange(wdTab2.Cell(8, 1).Range.Start, wdTab2.Cell(11, 1).Range.End);
            wdIn.Selection.Cells.Split(1, 4);
            //
            wdIn.Selection.Range.Font.Size = 8.5F;
            wdIn.Selection.Range.Font.Name = "Trebuchet MS";
            //
            wdIn.Selection.SetRange(wdTab2.Cell(8, 1).Range.Start, wdTab2.Cell(11, 1).Range.End);
            wdIn.Selection.Cells.Width = 60;
            wdIn.Selection.SetRange(wdTab2.Cell(8, 2).Range.Start, wdTab2.Cell(11, 2).Range.End);
            wdIn.Selection.Cells.Width = 215.5F;
            wdIn.Selection.SetRange(wdTab2.Cell(8, 3).Range.Start, wdTab2.Cell(11, 3).Range.End);
            wdIn.Selection.Cells.Width = 60;
            wdIn.Selection.SetRange(wdTab2.Cell(8, 4).Range.Start, wdTab2.Cell(11, 4).Range.End);
            wdIn.Selection.Cells.Width = 215.5F;
            wdIn.Selection.SetRange(wdTab2.Cell(14, 1).Range.Start, wdTab2.Cell(15, 1).Range.End);
            wdIn.Selection.Cells.Split(1, 5);
            //
            wdIn.Selection.SetRange(wdTab2.Cell(15, 1).Range.Start, wdTab2.Cell(15, 5).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            //
            wdIn.Selection.SetRange(wdTab2.Cell(8, 1).Range.Start, wdTab2.Cell(14, 5).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdTab2.Cell(8, 1).Range.Text = "Contact";
            wdTab2.Cell(8, 1).Range.Bold = 1;
            wdIn.Selection.SetRange(wdTab2.Cell(8, 2).Range.Start, wdTab2.Cell(11, 2).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
            wdIn.Selection.SetRange(wdTab2.Cell(8, 4).Range.Start, wdTab2.Cell(11, 4).Range.End);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
            wdTab2.Rows[14].Cells.VerticalAlignment = wd.WdCellVerticalAlignment.wdCellAlignVerticalCenter;
            // Add optional vendor address info
            //if (vendAdd.Length > 0)
            //{
            wdTab2.Cell(8, 2).Range.Text = shipHeader.CompanyName;
            wdTab2.Cell(9, 2).Range.Text = shipHeader.PhoneNumber;
            //wdTab2.Cell(10, 2).Range.Text = vendAdd[2].ToString();
            //wdTab2.Cell(11, 2).Range.Text = vendAdd[3].ToString();
            //}
            wdTab2.Cell(8, 3).Range.Text = "Ship To:";
            wdTab2.Cell(8, 3).Range.Bold = 1;
            //if (shipArr != null && shipSel > 0)
            //{
            wdTab2.Cell(8, 4).Range.Text = shipHeader.JobName;
            wdTab2.Cell(10, 4).Range.Text = shipHeader.Address1;
            wdTab2.Cell(11, 4).Range.Text = shipHeader.City + ", " + shipHeader.ProvState + ", " + shipHeader.PostalZip;
            //}

            wdTab2.Cell(8, 3).Range.Borders[wd.WdBorderType.wdBorderLeft].LineStyle = wd.WdLineStyle.wdLineStyleNone;
            wdIn.Selection.SetRange(wdTab2.Cell(14, 1).Range.Start, wdTab2.Cell(14, 5).Range.End);
            wdIn.Selection.Range.Bold = 1;
            wdTab2.Cell(14, 1).Range.Text = "Project Number";
            wdTab2.Cell(15, 1).Range.Text = shipHeader.JobNumber;
            wdTab2.Cell(14, 2).Range.Text = "Shipping Method";
            wdTab2.Cell(15, 2).Range.Text = shipHeader.Courier; // "LOCAL DELIVERY";
            wdTab2.Cell(14, 3).Range.Text = "Attention To";
            wdTab2.Cell(15, 3).Range.Text = shipHeader.Attention;
            wdTab2.Cell(14, 4).Range.Text = "Requested By";
            wdTab2.Cell(15, 4).Range.Text = shipHeader.Shipper;
            wdTab2.Cell(14, 5).Range.Text = "Ship Date";    //ACTUAL ship date field used
            wdTab2.Cell(15, 5).Range.Text = shipHeader.ActualShipDate == null ? "" : shipHeader.ActualShipDate.Value.ToString("dd-MMM-yyyy");

            wdIn.Selection.SetRange(wdTab2.Cell(14, 1).Range.Start, wdTab2.Cell(15, 5).Range.End);
            wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdIn.Selection.SetRange(wdTab2.Cell(14, 1).Range.Start, wdTab2.Cell(14, 5).Range.End);
            wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;

            wdTab2.Rows[17].Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab2.Rows[17].Range.Text = shipHeader.Comments;

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 5);
            wdIn.Selection.TypeParagraph();

            //  Table 3 (6) formatting
            //
            wd.Table wdTab6 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, (shipLines.Count * 2) + 1, 4);
            wdTab6.Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;

            wdTab6.Columns[1].Width = 35;
            wdTab6.Columns[2].Width = 120;
            wdTab6.Columns[3].Width = 334;
            wdTab6.Columns[4].Width = 50;
            //wdTab6.Columns[5].Width = 50;
            //wdTab6.Columns[6].Width = 50;


            // Header titles
            //
            wdTab6.Cell(1, 1).Range.Text = "Line #";
            wdTab6.Cell(1, 2).Range.Text = "PO No.";
            wdTab6.Cell(1, 3).Range.Text = "Item Description";
            wdTab6.Cell(1, 4).Range.Text = "Quantity";
            //wdTab6.Cell(1, 6).Range.Text = "Total Cost";

            // Line data
            int n = 0;
            int ser = 1;
            for (i = 1; i <= (shipLines.Count * 2); i += 2)
            {
                for (o = 1; o <= wdTab6.Columns.Count; o++)
                {
                    switch (o)
                    {
                        case 1:
                            wdTab6.Cell(i + 1, o).Range.InsertAfter(Convert.ToString(ser));
                            ser++;
                            break;
                        case 2:
                            wdTab6.Cell(i + 1, o).Range.InsertAfter(shipLines[n].PoNumber);
                            break;
                        //case 3:
                        //    wdTab6.Cell(i + 1, o).Range.InsertAfter(shipLines[n].ItemNumber);
                        //    break;
                        case 3:
                            wdTab6.Cell(i + 1, o).Range.InsertAfter(shipLines[n].ItemDescription);
                            break;
                        case 4:
                            wdTab6.Cell(i + 1, o).Range.InsertAfter(shipLines[n].QuantityShipped.ToString());
                            wdIn.Selection.SetRange(wdTab6.Cell(i + 2, 1).Range.Start, wdTab6.Cell(i + 2, 4).Range.End);
                            wdIn.Selection.Cells.Merge();
                            wdTab6.Cell(i + 2, 1).Range.InsertAfter("\t" + shipLines[n].Comments);
                            wdTab6.Cell(i + 2, 1).VerticalAlignment = wd.WdCellVerticalAlignment.wdCellAlignVerticalTop;
                            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
                            break;
                        //case 6:
                        //    //wdTab6.Cell(i + 1, o).Range.InsertAfter("$" + "placeholder");
                        //    wdIn.Selection.SetRange(wdTab6.Cell(i + 2, 1).Range.Start, wdTab6.Cell(i + 2, 5).Range.End);
                        //    wdIn.Selection.Cells.Merge();
                        //    wdTab6.Cell(i + 2, 1).Range.InsertAfter("\t" + "placeholder");
                        //    wdTab6.Cell(i + 2, 1).VerticalAlignment = wd.WdCellVerticalAlignment.wdCellAlignVerticalTop;
                        //    wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
                        //    break;
                    }
                    if (o == 6) break;
                }
                n++;
            }
            // Formatting hardware order table
            wdTab6.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab6.Rows.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab6.Columns.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdTab6.Rows[1].Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab6.Rows[1].Cells.VerticalAlignment = wd.WdCellVerticalAlignment.wdCellAlignVerticalCenter;
            wdTab6.Select();
            wdIn.Selection.Font.Size = 8;
            wdIn.Selection.Paragraphs.SpaceBefore = 4;
            wdIn.Selection.Paragraphs.SpaceAfter = 4;
            wdTab6.Rows[1].Height = 20;
            wdTab6.Select();
            wdIn.Selection.Paragraphs.SpaceAfter = 0;
            /* This damn object DEMANDS an enumeration.  Casting as long (the enums actual type) doesn't work therefore you can see
            the arbitraty colour used (wdColorLightGreen) and then using subtraction to get the colour value that I want.
            wdTab6.Shading.BackgroundPatternColor = wd.WdColor.wdColorLightGreen - 727539;  */
            wdTab6.Rows[1].Shading.BackgroundPatternColor = wd.WdColor.wdColorGray15;
            wdTab6.Rows[1].Range.Bold = 1;

            for (i = 2; i <= wdTab6.Rows.Count; i += 4)
            {
                wdTab6.Rows[i].Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;
                wdTab6.Rows[i + 1].Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;
            }

            // Totals table formatting
            //
            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 5);
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.TypeParagraph();
            //wd.Table wdTab7 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 5, 2, wd.WdDefaultTableBehavior.wdWord9TableBehavior);
            //wdTab7.Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphRight;
            //wdTab7.Columns.Width = 90;
            //wdTab7.Range.Font.Size = 8.5F;
            //wdTab7.Rows.LeftIndent = wdIn.CentimetersToPoints(13.1F);
            //wdIn.Selection.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //wdIn.Selection.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            //wdTab7.Cell(1, 1).Range.Text = "Subtotal";
            //wdTab7.Cell(1, 2).Range.Text = "$" + "placeholder"; // totalCost.ToString("0.00");
            //wdTab7.Cell(2, 1).Range.Text = "Freight";
            //wdTab7.Cell(2, 2).Range.Text = "$0.00";
            //wdTab7.Cell(3, 1).Range.Text = "Miscellaneous";
            //wdTab7.Cell(3, 2).Range.Text = "$0.00";
            //wdTab7.Cell(4, 1).Range.Text = "HST";
            //wdTab7.Cell(4, 2).Range.Text = "$" + "placeholder"; // Math.Round(totalCost * 0.13, 2).ToString("0.00");
            //wdTab7.Cell(5, 1).Range.Text = "Order Total";
            //wdTab7.Cell(5, 2).Range.Text = "$" + "placeholder"; // (Math.Round(totalCost * 0.13, 2) + totalCost).ToString("0.00");

            //wdIn.Selection.SetRange(wdTab7.Cell(1, 1).Range.Start, wdTab7.Cell(5, 1).Range.End);
            //wdIn.Selection.Shading.BackgroundPatternColor = wd.WdColor.wdColorGray10;

            //  Create signature area
            //
            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 5);
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.ParagraphFormat.SpaceAfter = 0;

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 5);
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.ParagraphFormat.SpaceAfter = 0;
            wdIn.Selection.Font.Size = 8;
            wdIn.Selection.Range.Text = "________________________________________________\r" +
                                        "    Receiver Signature   \r" + //+ DateTime.Today.ToString("dd-MMM-yyyy") + "\r" +
                                        "\r";


            wd.Range ftRange = wdIn.ActiveDocument.Sections[1].Footers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            ftRange.Fields.Add(ftRange, wd.WdFieldType.wdFieldPage);
            wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekPrimaryFooter;


            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3);
            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3, wd.WdMovementType.wdExtend);
            wdIn.Selection.Font.Size = 7;

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3);
            //wdIn.Selection.TypeParagraph();
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.Range.Text = "Head Office:  7100 Warden Ave. Unit 1, Markham, ON L3R 8B5, PH: 905-940-8358, FX: 905-940-8362\r" +
                                        "Showroom Office:  10 Brentcliffe Rd. Unit 14, Toronto, ON M4G 3Y2, PH: 416-696-8358, FX: 416-696-8362\r" +
                                        "Ottawa Office:  159 Colonnade Rd. Unit 2, Ottawa, ON K2E 7J4, PH: 613-226-2268, FX: 613-226-7224\r" +
                                        "Vancouver Office:  1850 Hartley Avenue Unit 1 & 2, Coquitlam, BC V3K 7A1, PH: 604-235-2609";

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 4, wd.WdMovementType.wdExtend);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            wdIn.Selection.Range.Font.Size = 8;

            //Getting rid of the page number in footer
            wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 1);
            wdIn.Selection.MoveLeft(wd.WdUnits.wdCharacter, 1, wd.WdMovementType.wdExtend);
            wdIn.Selection.Delete();

            wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekMainDocument;


            try
            {
                wdTab1.Cell(2, 1).Range.InlineShapes.AddPicture(@"P:\Documents\Graphics\UCSH Excel PO Add-In Graphics\400x400.jpg");
            }
            catch (Exception e)
            {

                wdIn = null;
                wdIn = null;
                MessageBox.Show("Error with UCSH logo:\r" + Convert.ToString(e));
                return;
            }

            wdIn = null;
            wdIn = null;
        }
    }
}
