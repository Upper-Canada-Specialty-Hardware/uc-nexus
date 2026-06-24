using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using ol = Microsoft.Office.Interop.Outlook;
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added

namespace PM_Project_Tracking.OutlookConverters
{
    //https://docs.microsoft.com/en-us/visualstudio/vsto/walkthrough-creating-your-first-vsto-add-in-for-outlook?view=vs-2017
    public class OutlookGenerator
    {
        //https://www.akadia.com/services/dotnet_delegates_and_events.html

        internal ol.Inspectors _inspecs;
        public delegate void UcMailSender(object a, ol.Application c);
        //public delegate void UcMailSenderExtended(object a, ol.Application c, T d);

        public OutlookGenerator()
        {

        }
        public OutlookGenerator(object ucObj)
        {
            ol.Application olIn = new ol.Application();
            _inspecs = olIn.Application.Inspectors;
            //_inspecs.NewInspector += new ol.InspectorsEvents_NewInspectorEventHandler(Inspectors_NewInspector);

            ol.MailItem _newMail = olIn.CreateItem(ol.OlItemType.olMailItem);

            UcMailSender _mailMethod = new UcMailSender(GetDel(ucObj));
            _mailMethod(ucObj, olIn);
        }

        void NewMailSingleDesignate()
        {

        }

        void NewMailDistributionList()
        {

        }

        internal UcMailSender GetDel(object obj)
        {
            if (obj is dc.Pursuit)
                return new UcMailSender(GeneratePursuitsNotification);

            else if (obj is dc.BidProject)
                return new UcMailSender(GenerateBidNotification);

            else if (obj is dc.ReceivingLine)
                return new UcMailSender(GenerateWarehouseReceiptNotification);

            else if (obj is pm.TaskSchedulerItem)
                return new UcMailSender(GenerateTaskSchedulerAssigneeNotification);

            else if (obj is dc.WhDeficiency)
                return new UcMailSender(GenerateWhReceiptDeficiencyNotification);

            else
                return null;
        }



        internal void GeneratePursuitsNotification(object obj, ol.Application olIn)
        {
            ol.MailItem mailItem = olIn.CreateItem(ol.OlItemType.olMailItem);
            mailItem.To = "mattn@ucsh.com";
            mailItem.Subject = "Connects Outlook Testing";
            mailItem.Body = "This delegate method was called using a UC Connects Pursuit object";
            mailItem.Display();
            //mailItem.Send();
        }

        internal void GenerateBidNotification(object obj, ol.Application olIn)
        {
            ol.MailItem mailItem = olIn.CreateItem(ol.OlItemType.olMailItem);
            mailItem.To = "mattn@ucsh.com";
            mailItem.Subject = "Connects Outlook Testing";
            mailItem.Body = "This delegate method was called using a UC Connects Bid object";
            mailItem.Display();
            //mailItem.Send();
        }

        internal void GenerateWarehouseReceiptNotification(object obj, ol.Application olIn)
        {
            ol.MailItem mailItem = olIn.CreateItem(ol.OlItemType.olMailItem);
            dc.ReceivingLine _recLine = (dc.ReceivingLine)obj;
            dc.User _selPm = null;
            dc.User _selHwCoord = null;
            dc.User _selProjCoord = null;

            GetPmCoordinatorAddressesFromJobNumberObject(_recLine, ref _selPm, ref _selHwCoord, ref _selProjCoord);

            if (_selPm != null && _selPm.Email != null)
            {
                if ((_selHwCoord != null && _selHwCoord.Email != null) && (_selProjCoord != null && _selProjCoord.Email != null))
                    mailItem.To = _selPm.Email + "; " + _selHwCoord.Email + "; " + _selProjCoord.Email;
                else if (_selHwCoord != null && _selHwCoord.Email != null)
                    mailItem.To = _selPm.Email + "; " + _selHwCoord.Email;
                else
                    mailItem.To = _selPm.Email;

                mailItem.Subject = "Warehouse Items Received - " + _recLine.JobName;
                mailItem.Body = "Hardware was received for " + _recLine.JobName + " on PO number: " + _recLine.PoNumber + ", with the receipt number " + _recLine.PopRctNum;
                mailItem.Send();
            }
            else
                MessageBox.Show("Either the PM's domain login does not match their PM name in GP or they don't have an e-mail address added in the database");

            if (NotifyTaggingBackorder(_recLine))
                GenerateTaggingBackorderFillNotification(_recLine, olIn);
        }

        internal void GenerateWhReceiptDeficiencyNotification(object obj, ol.Application olIn)
        {
            ol.MailItem mailItem = olIn.CreateItem(ol.OlItemType.olMailItem);
            dc.WhDeficiency _whDef = (dc.WhDeficiency)obj;
            dc.User _selPm = null;
            dc.User _selHwCoord = null;
            dc.User _selProjCoord = null;

            GetPmCoordinatorAddressesFromJobNumberObject(_whDef, ref _selPm, ref _selHwCoord, ref _selProjCoord);

            if (_selPm != null && _selPm.Email != null)
            {
                if ((_selHwCoord != null && _selHwCoord.Email != null) && (_selProjCoord != null && _selProjCoord.Email != null))
                    mailItem.To = _selPm.Email + "; " + _selHwCoord.Email + "; " + _selProjCoord.Email;
                else if (_selHwCoord != null && _selHwCoord.Email != null)
                    mailItem.To = _selPm.Email + "; " + _selHwCoord.Email;
                else
                    mailItem.To = _selPm.Email;

                mailItem.Subject = "Warehouse Receipt Deficiency - " + _whDef.JobNumber;
                mailItem.Body = "There is a new warehouse receiving issue that needs adressing for job " + _whDef.JobNumber + " on PO number: " + _whDef.PoNumber;
                mailItem.Send();
            }
            else
                MessageBox.Show("Either the PM's domain login does not match their PM name in GP or they don't have an e-mail address added in the database");

        }

        internal void GenerateTaggingBackorderFillNotification(dc.ReceivingLine rl, ol.Application olIn)
        {
            ol.MailItem mailItem = olIn.CreateItem(ol.OlItemType.olMailItem);
            mailItem.To = "vptagging@ucsh.com";
            mailItem.Subject = "BACKORDER: Warehouse Items Received - " + rl.JobName;
            mailItem.Body = "Backordered hardware was received for " + rl.JobName + " on PO number: " + rl.PoNumber + ", with the receipt number " + rl.PopRctNum;
            mailItem.Send();
        }

        internal void GenerateTaskSchedulerAssigneeNotification(object obj, ol.Application olIn)
        {
            ol.MailItem mailItem = olIn.CreateItem(ol.OlItemType.olMailItem);
            pm.TaskSchedulerItem _selTask = (pm.TaskSchedulerItem)obj;
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));

            dc.User pm = dtCtx.GetTable<dc.User>().Where(x => x.DomainUserName == _selTask.AssignedToName).SingleOrDefault();

            if (pm != null && pm.Email != null)
            {
                mailItem.To = pm.Email;
                mailItem.Subject = "Task Item Created - " + _selTask.JobName;
                mailItem.Body = "Task: " + _selTask.TaskTypeName + "\r"
                                + "Start Date: " + _selTask.StartDate.ToString() + "\r"
                                + "Duration: " + _selTask.Duration + "\r"
                                + "Assigned By: " + _selTask.AssignedByName;
                mailItem.Send();
            }
            else
                MessageBox.Show("Either the assignee's domain login does not exist or they don't have an e-mail address added in the database");
        }

        internal void Inspectors_NewInspector(Microsoft.Office.Interop.Outlook.Inspector Inspector)
        {
            ol.MailItem mailItem = Inspector.CurrentItem as ol.MailItem;
            if (mailItem != null)
            {
                if (mailItem.EntryID == null)
                {
                    mailItem.To = "davep@ucsh.com";
                    mailItem.Subject = "Connects Outlook Testing";
                    mailItem.Body = "This text was automatically generated by Connects";
                }

            }
        }

        public void GetPmCoordinatorAddressesFromJobNumberObject(dc.Interfaces.IJobNumberHaver jnOb, ref dc.User pm, ref dc.User hwCoord, ref dc.User projCoord)
        {

            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));

            try
            {

                pm = dtCtx.GetTable<dc.MainProject>().Join(dtCtx.GetTable<dc.User>(), mainp => mainp.ProjectManager.ToLower(), us => us.DomainUserName.ToLower(), (mainp, us) => new { mainp, us })
                                .Where(n => n.mainp.JobNumber == jnOb.JobNumber).Select(i => i.us).SingleOrDefault();

                hwCoord = dtCtx.GetTable<dc.MainProject>().Join(dtCtx.GetTable<dc.User>(), mainp => mainp.HardwareCoordinator.ToLower(), us => us.DomainUserName.ToLower(), (mainp, us) => new { mainp, us })
                                .Where(n => n.mainp.JobNumber == jnOb.JobNumber).Select(i => i.us).SingleOrDefault();

                projCoord = dtCtx.GetTable<dc.MainProject>().Join(dtCtx.GetTable<dc.User>(), mainp => mainp.ProjectCoordinator.ToLower(), us => us.DomainUserName.ToLower(), (mainp, us) => new { mainp, us })
                                .Where(n => n.mainp.JobNumber == jnOb.JobNumber).Select(i => i.us).SingleOrDefault();

            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
        }

        internal bool NotifyTaggingBackorder(dc.ReceivingLine rl)
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            int _recCount = 0;

            try
            {
                _recCount = dtCtx.GetTable<dc.ReceivingLine>().GroupBy(x => new { x.PoNumber, x.PopRctNum }).Where(r => r.Key.PoNumber == rl.PoNumber).Count();
            }
            catch(Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }

            if (_recCount > 1)
                return true;
            else
                return false;
        }

    }

    public class OutlookGenerator<T> : OutlookGenerator
    {
        public delegate void UcMailSenderExtended(object a, ol.Application c, T d);
        public OutlookGenerator(object ucObj, T objList)
        {
            ol.Application olIn = new ol.Application();
            _inspecs = olIn.Application.Inspectors;
            //_inspecs.NewInspector += new ol.InspectorsEvents_NewInspectorEventHandler(Inspectors_NewInspector);

            ol.MailItem _newMail = olIn.CreateItem(ol.OlItemType.olMailItem);

            UcMailSenderExtended _mailMethod = new UcMailSenderExtended(GetDelExtended(ucObj));
            _mailMethod(ucObj, olIn, objList);
        }

        private UcMailSenderExtended GetDelExtended(object obj)
        {
            if (obj is dc.WhDeficiency)
                return new UcMailSenderExtended(GenerateWhReceiptDeficiencyListNotification);

            return null;
        }

        internal void GenerateWhReceiptDeficiencyListNotification(object obj, ol.Application olIn, T whDefs)
        {
            ol.MailItem mailItem = olIn.CreateItem(ol.OlItemType.olMailItem);
            dc.WhDeficiency _whDef = (dc.WhDeficiency)obj;
            dc.User _selPm = null;
            dc.User _selHwCoord = null;
            dc.User _selProjCoord = null;

            GetPmCoordinatorAddressesFromJobNumberObject(_whDef, ref _selPm, ref _selHwCoord, ref _selProjCoord);

            if (_selPm != null && _selPm.Email != null)
            {
                if ((_selHwCoord != null && _selHwCoord.Email != null) && (_selProjCoord != null && _selProjCoord.Email != null))
                    mailItem.To = _selPm.Email + "; " + _selHwCoord.Email + "; " + _selProjCoord.Email;
                else if (_selHwCoord != null && _selHwCoord.Email != null)
                    mailItem.To = _selPm.Email + "; " + _selHwCoord.Email;
                else
                    mailItem.To = _selPm.Email;

                mailItem.Subject = "Warehouse Receipt Deficiency - " + _whDef.JobNumber;
                mailItem.Body = "There is a new warehouse receiving issue that needs adressing for job " + _whDef.JobNumber.Trim() + " on PO number: " + _whDef.PoNumber;
                mailItem.Body = mailItem.Body + String.Join("\r", (whDefs as List<dc.WhDeficiency>).Select(x => x.Remarks));

                mailItem.Send();
            }
            else
                MessageBox.Show("Either the PM's domain login does not match their PM name in GP or they don't have an e-mail address added in the database");
        }
    }
}
