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

namespace PM_Project_Tracking.WordConverters
{
    class ExportSubmittal
    {
        public static void CreateSubmittalDocument(pm.SubmittalHeader subHeader, List<pm.SubmittalLine> subLines)
        {
            wd.Application wdIn = new wd.Application();
            wd.Document _doc = wdIn.Documents.Add();
            wdIn.Visible = true;

            wdIn.ActiveDocument.Content.Font.Name = "Trebuchet MS";
            wdIn.Selection.PageSetup.TopMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.BottomMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.LeftMargin = wdIn.CentimetersToPoints(1.27F);
            wdIn.Selection.PageSetup.RightMargin = wdIn.CentimetersToPoints(0.27F);

            _doc.PageSetup.TextColumns.Add();
            _doc.PageSetup.TextColumns.EvenlySpaced = 0;
            _doc.PageSetup.TextColumns[1].Width = wdIn.CentimetersToPoints(4.23F);
            _doc.PageSetup.TextColumns[1].SpaceAfter = wdIn.CentimetersToPoints(0.5F);
            _doc.PageSetup.TextColumns[2].Width = wdIn.CentimetersToPoints(14.32F);

            try
            {
                wdIn.Selection.InlineShapes.AddPicture(@"P:\Documents\Graphics\UCSH Excel PO Add-In Graphics\400x400.jpg");
            }
            catch (Exception e)
            {
                MessageBox.Show("Error with UCSH logo file: \r" + Convert.ToString(e));
                return;
            }

            for (int i = 0; i < 28; i++)
                wdIn.Selection.TypeParagraph();

            //wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 1);
            wd.Range hdRange = wdIn.Selection.Range;
            //wd.Range hdRange = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            //wd.Table wdTab1 = wdIn.ActiveDocument.Sections[1].Headers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range.Tables.Add(hdRange, 12, 3, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            wd.Table wdTab1 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, 12, 2, wd.WdDefaultTableBehavior.wdWord9TableBehavior);
            wdTab1.Range.Font.Name = "Swis721 BT";
            wdTab1.Range.Font.Size = 10;
            //wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekPrimaryHeader;

            wdTab1.Columns[1].Width = 280;
            wdTab1.Columns[2].Width = 120;

            wdTab1.Cell(1, 1).Range.Text = DateTime.Today.ToString();
            wdTab1.Cell(1, 2).Range.Text = "Submitted via email";
            wdTab1.Cell(1, 1).Range.Text = subHeader.DateCreated != null ? ((DateTime)subHeader.DateCreated).ToString("dd MMM yyyy") : "";
            wdTab1.Cell(3, 1).Range.Text = subHeader.ContractorName;
            wdTab1.Cell(4, 1).Range.Text = subHeader.ContractorAddress;
            wdTab1.Cell(7, 1).Range.Text = "Attention: " + subHeader.ContactName + ", " + subHeader.ContactTitle;
            wdTab1.Cell(8, 1).Range.Text = "Contact number: " + subHeader.ContactPhoneNumber;

            wdTab1.Cell(10, 1).Range.Text = "Re:    [USER DEFINED]";
            wdTab1.Cell(11, 1).Range.Text = "         " + subHeader.JobName;
            wdTab1.Cell(12, 1).Range.Text = "         " + subHeader.JobAddress;

            wdTab1.Cell(3, 1).Range.Font.Bold = 1;
            wdTab1.Cell(4, 1).Range.Font.Bold = 1;
            wdTab1.Cell(7, 1).Range.Select();
            //wdIn.Selection.Range.MoveStart(wd.WdUnits.wdCharacter);
            int _rangeDif = wdIn.Selection.Characters.Count - 11;
            wdIn.Selection.MoveLeft(wd.WdUnits.wdCharacter, wdIn.Selection.Characters.Count, wd.WdMovementType.wdExtend);
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 11, wd.WdMovementType.wdMove); //11 his how many characters are in "Attention: "
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, _rangeDif - 1, wd.WdMovementType.wdExtend);
            wdIn.Selection.Font.Bold = 1;

            wdTab1.Cell(10, 1).Range.Select();
            //wdIn.Selection.Range.MoveStart(wd.WdUnits.wdCharacter);
            _rangeDif = wdIn.Selection.Characters.Count - 7;
            wdIn.Selection.MoveLeft(wd.WdUnits.wdCharacter, wdIn.Selection.Characters.Count, wd.WdMovementType.wdExtend);
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 7, wd.WdMovementType.wdMove); //7 is how many characters are in "Re:    "
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, _rangeDif - 1, wd.WdMovementType.wdExtend);
            wdIn.Selection.Font.Bold = 1;
             
            wdIn.Selection.MoveLeft(wd.WdUnits.wdCharacter, 1, wd.WdMovementType.wdMove);
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 1, wd.WdMovementType.wdMove);
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 12, wd.WdMovementType.wdExtend); //12 is how many characters are in "USER DEFINED"
            //Color fontColorOne = Color.FromRgb(255, 0, 0);
            //wd.WdColor wdfontColorOne = (Microsoft.Office.Interop.Word.WdColor)(fontColorOne.R + 0x100 * fontColorOne.G + 0x10000 * fontColorOne.B);
            wdIn.Selection.Font.ColorIndex = wd.WdColorIndex.wdRed;

            //wdIn.Selection.SetRange(wdTab1.Cell(1, 1).Range.Start, wdTab1.Cell(12, 1).Range.End);
            //wdIn.Selection.Cells.Merge();


            foreach (wd.Border bd in wdTab1.Borders)
            {
                bd.LineStyle = wd.WdLineStyle.wdLineStyleNone;
            }

            //wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekMainDocument;

            //wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 13);
            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3);

            wdIn.Selection.TypeParagraph();
            wdIn.Selection.ParagraphFormat.SpaceAfter = 0;
            wdIn.Selection.Font.Name = "Swis721 BT";
            wdIn.Selection.Font.Size = 10;

            wdIn.Selection.Range.Text = "Transmittal\r" +
                                        "We enclose herewith the following drawings and documents for your review, use,\r" +
                                        "comment, and approval:\r";

            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;

            //wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 2);
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 12, wd.WdMovementType.wdExtend);
            wdIn.Selection.Range.Bold = 1;
            wdIn.Selection.Font.Size = 12;
            wdIn.Selection.Range.Underline = wd.WdUnderline.wdUnderlineSingle;
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3);

            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 1, wd.WdMovementType.wdMove);
            wdIn.Selection.TypeParagraph();
            //wdIn.Selection.TypeParagraph();
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.ParagraphFormat.SpaceAfter = 0;
            wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 1);
            //wdIn.Selection.ParagraphFormat.SpaceAfter = 0;

            wd.Table wdTab2 = wdIn.ActiveDocument.Tables.Add(wdIn.Selection.Range, subLines.Count + 1, 5, wd.WdDefaultTableBehavior.wdWord9TableBehavior);

            wdTab2.Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab2.Rows.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab2.Columns.Borders.InsideLineStyle = wd.WdLineStyle.wdLineStyleDot;
            wdTab2.Rows[1].Borders.OutsideLineStyle = wd.WdLineStyle.wdLineStyleSingle;
            wdTab2.Select();
            wdIn.Selection.Font.Size = 8;
            wdIn.Selection.Paragraphs.SpaceBefore = 4;
            wdIn.Selection.Paragraphs.SpaceAfter = 4;
            wdTab2.Rows[1].Height = 20;
            wdTab2.Rows[1].Select();
            wdIn.Selection.Paragraphs.SpaceAfter = 0;
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;
            //Column widths
            wdTab2.Columns[1].Width = 42;
            wdTab2.Columns[2].Width = 50;
            wdTab2.Columns[3].Width = 42;
            wdTab2.Columns[4].Width = 160;
            wdTab2.Columns[5].Width = 120;
            //Header values
            wdTab2.Cell(1, 1).Range.Text = "Copies";
            wdTab2.Cell(1, 2).Range.Text = "Page / Quantity";
            wdTab2.Cell(1, 3).Range.Text = "Section No.";
            wdTab2.Cell(1, 4).Range.Text = "Description"; 
            wdTab2.Cell(1, 5).Range.Text = "Remarks";
            //Populate cells
            for (int i = 2; i <= wdTab2.Rows.Count; i++)    //Word uses base 1, not 0
            {
                int x = i - 2;
                wdTab2.Cell(i, 1).Range.Text = subLines[x].Copies.ToString();
                wdTab2.Cell(i, 2).Range.Text = subLines[x].QuantityPerPage.ToString();
                wdTab2.Cell(i, 3).Range.Text = subLines[x].SpecSection;
                wdTab2.Cell(i, 4).Range.Text = subLines[x].Reference;
                wdTab2.Cell(i, 5).Range.Text = subLines[x].Remarks;
            }

            //Colouring cells

            Color bkColor = Color.FromRgb(217, 229, 193);
            wd.WdColor wdColorBack = (Microsoft.Office.Interop.Word.WdColor)(bkColor.R + 0x100 * bkColor.G + 0x10000 * bkColor.B);
            wdTab2.Shading.BackgroundPatternColor = wdColorBack;
            Color headColor = Color.FromRgb(195, 214, 155);
            wd.WdColor wdColorHead = (Microsoft.Office.Interop.Word.WdColor)(headColor.R + 0x100 * headColor.G + 0x10000 * headColor.B);
            wdTab2.Rows[1].Shading.BackgroundPatternColor = wdColorHead;
            //wdTab2.Range.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, wdTab2.Rows.Count + 1, wd.WdMovementType.wdMove);
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.ParagraphFormat.SpaceAfter = 0;

            //wdIn.Selection.MoveEnd(wd.WdUnits.wdStory, wd.WdMovementType.wdMove);
            //wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 2);
            //wdIn.Selection.TypeParagraph();
            wdIn.Selection.ParagraphFormat.SpaceAfter = 0;
            wdIn.Selection.Font.Size = 10;
            wdIn.Selection.Font.Name = "Swis721 BT";

            wdIn.Selection.Range.Text = "In accordance with the requirements of the Contract Documents we will not proceed with\r" +
                                        "the Work unless authorized to do so.   Should you require information or clarification on\r" +
                                        "the enclosed information, please do not hesitate to contact our office. \r" +
                                        "\r" +
                                        "With kind regards,";

            //wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphLeft;
            //wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 14);
            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 1);
            wdIn.Selection.MoveEnd(wd.WdUnits.wdLine, 100);
            wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 1, wd.WdMovementType.wdMove);
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.ParagraphFormat.SpaceAfter = 0;

            wdIn.Selection.Font.Bold = 0;
            wdIn.Selection.Font.Name = "Swis721 BT";
            wdIn.Selection.Font.Size = 10;
            wdIn.Selection.Text = subHeader.UcshContactName + ", " + subHeader.UcshContactTitle;
            //wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 1);
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.TypeParagraph();

            wdIn.Selection.Text = "UPPER CANADA SPECIALTY HARDWARE LIMITED";
            wdIn.Selection.Font.Name = "Times New Roman";
            wdIn.Selection.Font.Size = 10;
            wdIn.Selection.Font.Bold = 1;

            //wdIn.Selection.MoveEnd(wd.WdUnits.wdLine, 1000);
            //wdIn.Selection.MoveRight(wd.WdUnits.wdCharacter, 1, wd.WdMovementType.wdMove);
            //wdIn.Selection.TypeParagraph();
            //wdIn.Selection.TypeParagraph();
            //wdIn.Selection.ParagraphFormat.SpaceAfter = 0;


            wd.Range ftRange = wdIn.ActiveDocument.Sections[1].Footers[wd.WdHeaderFooterIndex.wdHeaderFooterPrimary].Range;
            ftRange.Fields.Add(ftRange, wd.WdFieldType.wdFieldPage);
            wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekPrimaryFooter;


            wdIn.Selection.MoveDown(wd.WdUnits.wdLine);
            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3, wd.WdMovementType.wdExtend);
            wdIn.Selection.Font.Size = 7;

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3);
            //wdIn.Selection.TypeParagraph();
            wdIn.Selection.TypeParagraph();
            wdIn.Selection.Range.Text = "Head Office:  7100 Warden Ave. Unit 1, Markham, ON L3R 8B5, PH: 905-940-8358, FX: 905-940-8362\r" +
                                        "Ottawa Office:  159 Colonnade Rd. Unit 2, Ottawa, ON K2E 7J4, PH: 613-226-2268, FX: 613-226-7224\r" +
                                        "www.ucsh.com";

            wdIn.Selection.MoveDown(wd.WdUnits.wdLine, 3, wd.WdMovementType.wdExtend);
            wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;

            //Getting rid of the page number in footer
            wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 1);
            wdIn.Selection.MoveLeft(wd.WdUnits.wdCharacter, 1, wd.WdMovementType.wdExtend);
            wdIn.Selection.Delete();

            wdIn.ActiveDocument.ActiveWindow.ActivePane.View.SeekView = wd.WdSeekView.wdSeekMainDocument;
            //wdIn.Selection.MoveEnd(wd.WdUnits.wdStory);
            //wdIn.Selection.ParagraphFormat.Alignment = wd.WdParagraphAlignment.wdAlignParagraphCenter;

            //this is where the header image gets deleted
            //wdTab1.Select();
            //wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 1);
            //wdIn.Selection.Delete();
            //wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 1);
            //wdIn.Selection.Delete();
            //wdIn.Selection.MoveUp(wd.WdUnits.wdLine, 1);
            //wdIn.Selection.Delete();

            dynamic dialog = wdIn.Dialogs[wd.WdWordDialog.wdDialogFileSummaryInfo];
            dialog.Title = subHeader.JobNumber.Trim() + "  Transmittal  " + DateTime.Today.ToString("dd") 
                                                + " " + DateTime.Today.ToString("MMM") 
                                                + " " + DateTime.Today.ToString("yyyy");
            dialog.Execute();

            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdTab1);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdTab2);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(_doc);
            System.Runtime.InteropServices.Marshal.ReleaseComObject(wdIn);
            GC.Collect();
        }

        public static void testTwo()
        {
            Microsoft.Office.Interop.Word.Application app = new Microsoft.Office.Interop.Word.Application();
            wd.Documents docs = app.Documents;
            wd.Document doc = docs.Add();
            app.Visible = true;
            wd.Table t = app.ActiveDocument.Tables.Add(app.Selection.Range, 3, 5, wd.WdDefaultTableBehavior.wdWord9TableBehavior);
            double b1 = t.BottomPadding;
            double t1 = t.TopPadding;
            double r1 = t.RightPadding;
            double l1 = t.LeftPadding;

            wd.Range r = t.Range;
            wd.Cells cells = r.Cells;
            for (int i = 1; i <= cells.Count; i++)
            {
                wd.Cell cell = cells[i];
                double b2 = cell.BottomPadding;
                double t2 = cell.TopPadding;
                double r2 = cell.RightPadding;
                double l2 = cell.LeftPadding;

                // e.g. Here is the edit:
                cell.TopPadding = 21.6f;
                cell.BottomPadding = 28.8f;

                wd.Range r2b = cell.Range;
                String txt = r2b.Text;
                Marshal.ReleaseComObject(cell);
                Marshal.ReleaseComObject(r2b);
            }

            //doc.Close(false);
            //app.Quit(false);

            Marshal.ReleaseComObject(cells);
            Marshal.ReleaseComObject(r);
            Marshal.ReleaseComObject(t);
            Marshal.ReleaseComObject(doc);
            Marshal.ReleaseComObject(docs);
            Marshal.ReleaseComObject(app);
        }
    }

}
