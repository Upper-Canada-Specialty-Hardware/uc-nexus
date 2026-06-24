using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using wc = PM_Project_Tracking.WordConverters;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using pmw = PM_Project_Tracking.ProjectManagementWindows;
using pmuvm = PM_Project_Tracking.ProjectManagementClasses.ProjectManagementUtililtyClasses.CostCodeAggregateViewModel;
using olc = PM_Project_Tracking.OutlookConverters;
using xl = Microsoft.Office.Interop.Excel;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;

namespace PM_Project_Tracking.ProjectManagementWindows
{
    /// <summary>
    /// Interaction logic for ProjectManagementMain.xaml
    /// </summary>
    public partial class ProjectManagementMain : Window
    {
        private readonly string _jobNumber;
        private readonly string _division;
        List<ProjectManagementMain> _projWinList = null;
        dc.CombinedProject _combProj = null;
        pm.ChangeIndex _chIndex = null;
        string _userName = Environment.UserName;
        int _userId;
        dc.User _curUser = null;
        ObservableCollection<dc.User> _taskUserCol = null;
        ObservableCollection<pm.TaskEnum> _taskEnumCol = null;
        ObservableCollection<pm.TaskSchedulerItem> _taskListCol = null;
        ObservableCollection<dc.ShopDrawingLine> _sdAreaCol = null;
        ObservableCollection<pm.ProgressBillingHeader> _pbHeaderCol = null;
        ObservableCollection<pm.ChangeHeader> _changeHeaderCol = null;
        pm.SubmittalHeader _subHeader = null;
        dc.ShippingHeader _sampleShipmentHeader = null;
        ObservableCollection<dc.ShippingLine> _sampleShipLineCol = new ObservableCollection<dc.ShippingLine>();
        ObservableCollection<pm.SubmittalLine> _subCol = null;
        ObservableCollection<pm.RequestForInfo> _rfiCol = null;
        ObservableCollection<dc.PurchaseOrderLineItem> _poCol = null;
        ObservableCollection<dc.ReceivingLine> _whViewRecLineCol = null;
        ObservableCollection<dc.ShippingHeader> _whShipHeaderCol = null;

        DeferredAction _tiDa;
        DeferredAction _hwPoDa;
        DeferredAction _whRecDa;
        DeferredAction _whShDa;
        DeferredAction _coDa;

        public ProjectManagementMain()
        {
            InitializeComponent();
        }

        public ProjectManagementMain(dc.CombinedProject combProj, List<ProjectManagementMain> projWinList, dc.User curUser)
        {
            InitializeComponent();
            //Tab_TaskScheduler.IsSelected = true;
            _curUser = curUser;
            _jobNumber = combProj.MainProject.JobNumber;
            _division = combProj.Jc00102.Division;
            _combProj = combProj;
            _projWinList = projWinList;
            _chIndex = pm.ChangeIndexes.GetChangeIndexByJob(this.JobNumber);
            if (_chIndex == null)
                _chIndex = new pm.ChangeIndex(combProj);
        }

        private void Window_Loaded(object sender, RoutedEventArgs e)
        {

            _pbHeaderCol = pm.ProgressBillingHeaders.GetProgressBillingHeaders(this.JobNumber);
            _changeHeaderCol = pm.ChangeHeaders.GetChangeHeaders(this.JobNumber);
            _subHeader = pm.SubmittalHeaders.GetSingleSubmittalHeaderByJob(this.JobNumber);
            if (_subHeader == null)
                _subHeader = pm.SubmittalHeaders.GetNewSingleSubmittalHeaderByJob(this.JobNumber);

            _sampleShipmentHeader = new dc.ShippingHeader(_subHeader, _combProj);

            StckPan_SubmittalHeader.DataContext = _subHeader;

            //ObservableCollection<pm.ChangeLine> _testCL = new ObservableCollection<pm.ChangeLine>();
            //_chIndex.ChangeLineItems = _testCL;
            //_testCL.Add(new pm.ChangeLine());

            _taskUserCol = dc.Users.GetUsers();
            _userId = _taskUserCol.Where(r => r.DomainUserName == _userName).Select(x => x.Id).SingleOrDefault();
            _taskEnumCol = pm.TaskSchedulers.GetTaskEnums();
            _sdAreaCol = dc.HollowMetal.GetShopDrawingAreaList(_jobNumber); //20059
            _subCol = pm.SubmittalLines.GetSubmittalsByJobNumber(_jobNumber);
            _rfiCol = pm.RequestForInfos.GetRfisByJobNumber(_jobNumber);
            _taskListCol = pm.TaskSchedulers.GetTaskScheduleItemsByJobNum(_jobNumber);


            CBox_TaskScheduler_SelectAssignee.ItemsSource = _taskUserCol;
            CBox_TaskScheduler_SelectTask.ItemsSource = _taskEnumCol;
            CBox_TaskScheduler_SelectArea.ItemsSource = _sdAreaCol;

            Cbox_ProgressBillings_SelectProgressBilling.ItemsSource = _pbHeaderCol;

            DG_ChangeOrders_HeaderIndex.ItemsSource = _changeHeaderCol;
            CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Filter = ChangeIndexFilter;
            DG_Submittal_SubmittalList.ItemsSource = _subCol;
            DG_RequestForInfo_RfiList.ItemsSource = _rfiCol;
            DG_TaskScheduler_Tasks.ItemsSource = _taskListCol;
            CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Filter = TaskItemFilter;
            if (_pbHeaderCol.Count > 0)
                Grid_ProgressBilling.DataContext = _pbHeaderCol[0];

            this.Title = _combProj.MainProject.JobNumber + " - " + _combProj.Jc00102.JobName;
            //pmuvm.CostCodeViewModel vm = new pmuvm.CostCodeViewModel(this.JobNumber);
            //this.DataContext = vm;

            StckPan_ChangeOrders_ChangesSummary.DataContext = _chIndex;
        }

        public string JobNumber
        {
            get { return _jobNumber; }
        }

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            if (_subCol.Where(x => x.IsModified == true).Count() > 0)
            {
                if (MessageBox.Show("There are still unsaved submittals, would you like to keep this project window open?", "Prompt",
                                   MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                    e.Cancel = true;
            }
        }

        private void Window_Closed(object sender, EventArgs e)
        {
            _projWinList.Remove(this);
            if (_subHeader != null && _subHeader.IsModified)
            {
                try
                {
                    pm.SubmittalHeaders.InsertUpdateSubmittalHeader(_subHeader);
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                }                
            }

            try
            {
                if (_chIndex.Id == 0)
                    pm.ChangeIndexes.CreateIndex(_chIndex);
                else if (_chIndex.IsModified)
                    pm.ChangeIndexes.UpdateIndex(_chIndex);
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }   
        }

        #region Task Scheduler

        private void BTN_TaskScheduler_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            MessageBox.Show("Please Note: If you are deleting items, this can only be done on a line-by-line basis. 'Update Server' only adds or modifies items.");
            //List<pm.TaskSchedulerItem> newTaskList = _taskListCol.Where(x => x.IsNew == true).ToList();
            pm.TaskSchedulers.UpdateAddTaskSchedulerItems(ref _taskListCol);
            //if (pm.TaskSchedulers.UpdateAddTaskSchedulerItems(ref _taskListCol))
            //{
            //    foreach (pm.TaskSchedulerItem tsi in newTaskList)
            //    {
            //        OutlookConverters.OutlookGenerator _olGen = new olc(tsi);
            //    }
            //}
        }

        private void BTN_TaskScheduler_AddTask_Click(object sender, RoutedEventArgs e)
        {
            dc.User _selAssignee = (dc.User)CBox_TaskScheduler_SelectAssignee.SelectedItem;
            pm.TaskEnum _selTask = (pm.TaskEnum)CBox_TaskScheduler_SelectTask.SelectedItem;
            string _area;
            if (CBox_TaskScheduler_SelectArea.SelectedIndex == -1)
                _area = "";
            else
                _area = ((dc.ShopDrawingLine)CBox_TaskScheduler_SelectArea.SelectedItem).Area;
            
            if (_selAssignee == null || _selTask == null)
            {
                MessageBox.Show("There is either no user list or task list loaded. Please check the database to ensure that the tables SYSUCUSERS and PMTASKITEMLIST001 are populated.");
                return;
            }

            if (CBox_TaskScheduler_SelectAssignee.SelectedIndex == -1 ||
                CBox_TaskScheduler_SelectTask.SelectedIndex == -1)// ||
                //(_selTask.DerivateOperation == true && CBox_TaskScheduler_SelectArea.SelectedIndex == -1) ) 
            {
                MessageBox.Show("Must have an assignee, task and area selected (if the task requires an area). If the area list is empty, a skeletal shop drawing with openings and areas" +
                                " needs to be uploaded to SQL Server. This can be done via the UCSH plug-in in the hollow metal shop drawings.");
            }
            else
            {
                Dictionary<string, int> _userIdPairs = new Dictionary<string, int>(_taskUserCol.AsEnumerable().Select(x => new { x.DomainUserName, x.Id }).ToDictionary(x => x.DomainUserName, x => x.Id));
                pm.TaskSchedulerItem _newTaskItem = new pm.TaskSchedulerItem(_userIdPairs, this.JobNumber, _combProj.Jc00102.JobName, _userId, _userName, _selAssignee.Id
                                                                             , _selAssignee.DomainUserName, _selTask.Id, _selTask.TaskName, _area, this._division);

                _taskListCol.Add(_newTaskItem);
            }
        }

        private void BTN_TaskScheduler_UpdateTask_Click(object sender, RoutedEventArgs e)
        {

            bool _update = false;
            pm.TaskSchedulerItem _selTask = (pm.TaskSchedulerItem)((Button)e.Source).DataContext;
            if (_selTask.IsDeleted && _selTask.IsNew)
            {
                _taskListCol.Remove(_selTask);
                return;
            }
            else if (_selTask.IsDeleted)
            {
                if (pm.TaskSchedulers.DeleteTaskSchedulerItem(_selTask))
                    _taskListCol.Remove(_selTask);
                    
                return;
            }

            if ((_selTask.IsNew || _selTask.IsModified))             //REMOVED:  && (_selTask.StartDate != null && _selTask.EndDate != null)
            {
                if (MessageBox.Show("Would you like to save/update this new task?", "Prompt",
                   MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                {
                    if (_selTask.IsNew)
                        _update = pm.TaskSchedulers.AddTaskSchedulerItem(_selTask);
                    else if (_selTask.IsModified)
                        _update = pm.TaskSchedulers.UpdateTaskSchedulerItem(_selTask, _taskUserCol);
                    if (!_update)
                        MessageBox.Show("Adding of task item failed");
                    else if (_update)
                    {
                        if (_selTask.IsNew)
                        {
                            _selTask.IsNew = false;
                            _selTask.IsModified = false;
                            //OutlookConverters.OutlookGenerator _olGen = new olc(_selTask);
                        }
                        else if (_selTask.IsModified)
                        {
                            _selTask.IsModified = false;
                            MessageBox.Show("Task item updated");
                        }
                    }
                }
            }
            else
                MessageBox.Show("Task already updated."); //MessageBox.Show("Task must have both a start and end date as well either be new or edited in order to be updated");
        }

        private void TB_TaskScheduler_AssignedFromFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            if (_taskListCol != null)
                this._tiDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_TaskScheduler_AssignedToFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            if (_taskListCol != null)
                this._tiDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_TaskScheduler_TaskFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            if (_taskListCol != null)
                this._tiDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_TaskScheduler_AreaFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            if (_taskListCol != null)
                this._tiDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private bool TaskItemFilter(object tsi)
        {
            var _taskSchedulerItem = (pm.TaskSchedulerItem)tsi;

            return (_taskSchedulerItem.AssignedByName.IndexOf(TB_TaskScheduler_AssignedFromFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _taskSchedulerItem.AssignedToName.IndexOf(TB_TaskScheduler_AssignedToFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _taskSchedulerItem.TaskTypeName.IndexOf(TB_TaskScheduler_TaskFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _taskSchedulerItem.Area.IndexOf(TB_TaskScheduler_AreaFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }


        #endregion

        #region Submittals

        private void BTN_Submittals_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                pm.SubmittalLines.UpdateSubmittals(_subCol, this.JobNumber);
                _subCol = pm.SubmittalLines.GetSubmittalsByJobNumber(this.JobNumber);
                DG_Submittal_SubmittalList.ItemsSource = _subCol;
                //CollectionViewSource.GetDefaultView(OfferToTenderTab_DG_PreProj.ItemsSource).Filter = OttItemFilter;
            }
            catch (Exception ex)
            {
                MessageBox.Show("BTN_OfferToTender_UpdateServer_Click \r\n" + ex.ToString());
            }
        }

        private void BTN_Submittals_AddNewSubmittal_Click(object sender, RoutedEventArgs e)
        {
            pm.SubmittalLine _newSubmittal = new pm.SubmittalLine();
            _newSubmittal.JobNumber = this.JobNumber;
            _newSubmittal.IsModified = false;
            _subCol.Add(_newSubmittal);
        }

        private void BTN_Submittal_ExportToWord_Click(object sender, RoutedEventArgs e)
        {
            //pm.SubmittalLine _selSubmit = (pm.SubmittalLine)((Button)e.Source).DataContext;
            List<pm.SubmittalLine> _subLines = ((ObservableCollection<pm.SubmittalLine>)DG_Submittal_SubmittalList.ItemsSource).Where(x => x.SelForExport == true).ToList();
            wc.ExportSubmittal.CreateSubmittalDocument(_subHeader, _subLines);
        }



        private void BTN_SubmittalShipmentDocument_ExportToWord_Click(object sender, RoutedEventArgs e) 
        {
            List<pm.SubmittalLine> _subLines = ((ObservableCollection<pm.SubmittalLine>)DG_Submittal_SubmittalList.ItemsSource).Where(x => x.SelForExport == true).ToList();
            if (_subLines == null || _subLines.Count == 0)
                return;

            int _memoNum = 0;
            ObservableCollection<dc.ShippingLine> _shipLines = new ObservableCollection<dc.ShippingLine>(ConvertSubmittalLineToShipLine(_subLines));
            try
            {
                _memoNum = dc.WhShippingHeaders.GetNextMemoNumber();
                dc.WhShippingHeaders.AddShippingHeader(_sampleShipmentHeader, _memoNum);
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                //dc.WhShippingLines.RollbackShippingHeader(_memoNum);  //Redundant, since if the add ship header
            }
            finally
            {
                WordConverters.ExportShipmentHeaderAndLines.CreateShipmentDocument(_sampleShipmentHeader, _shipLines, 0, null, null);
                MessageBox.Show("Shipping header memo number is " + _memoNum.ToString());
            }
        }


        //OLD
        //private void BTN_SubmittalShipmentDocument_ExportToWord_Click(object sender, RoutedEventArgs e)
        //{


        //    SubmittalShipmentLineQtyPopupForm _subPopupForm = new SubmittalShipmentLineQtyPopupForm(_sampleShipmentHeader, _combProj);
        //    _subPopupForm.Owner = this;
        //    _subPopupForm.ShowDialog();
        //    if (_subPopupForm.ContWindow)
        //    {
        //        int _memoNum = 0;
        //        try
        //        {
        //            WordConverters.ExportShipmentHeaderAndLines.CreateShipmentDocument(_subPopupForm.ShipHeader, _subPopupForm.ShipLines, 0, null, null);
        //            _memoNum = dc.WhShippingHeaders.GetNextMemoNumber();
        //        }
        //        catch
        //        {
        //            MessageBox.Show("Unable to fully launch Word document or generate shipping memo number.");
        //        }
        //        finally
        //        {
        //            if (_memoNum > 0)
        //            {
        //                //Only create shipping headers for samples sent out the door, no shipping lines due to complications with generating primary keys for shipping lines
        //                dc.WhShippingHeaders.AddShippingHeader(_subPopupForm.ShipHeader, _memoNum); BTN_Submittal_ExportToWord_Click

        //                //if (dc.WhShippingHeaders.AddShippingHeader(_subPopupForm.ShipHeader, _memoNum))
        //                //    dc.WhShippingLines.AddShippingLine(_subPopupForm.ShipLines, _memoNum);
        //            }
        //        }
        //    }

        //}

        #endregion

        #region RFIs

        private void BTN_Rfis_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                pm.RequestForInfos.UpdateRfis(_rfiCol);
                _rfiCol = pm.RequestForInfos.GetRfisByJobNumber(this.JobNumber);
                DG_RequestForInfo_RfiList.ItemsSource = _rfiCol;
                //CollectionViewSource.GetDefaultView(OfferToTenderTab_DG_PreProj.ItemsSource).Filter = OttItemFilter;
            }
            catch (Exception ex)
            {
                MessageBox.Show("BTN_OfferToTender_UpdateServer_Click \r\n" + ex.ToString());
            }
        }

        private void BTN_Rfis_AddNewRfi_Click(object sender, RoutedEventArgs e)
        {
            pm.RequestForInfo _newRfi = new pm.RequestForInfo();
            _newRfi.JobNumber = this.JobNumber;
            _newRfi.IsModified = false;
            _rfiCol.Add(_newRfi);
        }

        #endregion

        #region Purchase Orders

        private void BTN_PurchaseOrders_GetPurchaseOrders_Click(object sender, RoutedEventArgs e)
        {
            _poCol = dc.PurchaseOrderLineItems.GetAllPurchaseOrderLinesByProject(this.JobNumber);
            PurchaseOrders_DG_HardwarePos.ItemsSource = _poCol;
        }

        private void TB_HW_PurchaseOrders_PoNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private bool HwPurchaseOrderFilter(object po)
        {
            var _poObject = (dc.PurchaseOrderLineItem)po;
            return (_poObject.PoNumber.IndexOf(TB_PO_PurchaseOrders_PoNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }

 

        #endregion

        #region Progress Billings

        private void Cbox_ProgressBillings_SelectProgressBilling_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (Cbox_ProgressBillings_SelectProgressBilling.HasItems && Cbox_ProgressBillings_SelectProgressBilling.SelectedItem != null)
            {
                pm.ProgressBillingHeader _selPbHeader = (pm.ProgressBillingHeader)Cbox_ProgressBillings_SelectProgressBilling.SelectedItem;
                Grid_ProgressBilling.DataContext = _selPbHeader;
                Grid_ProgressBilling_HeaderSubs.DataContext = _selPbHeader.HeaderSubs;
            }
        }

        private void BTN_ProgressBillings_OpenSelectedBillingWindow_Click(object sender, RoutedEventArgs e)
        {
            if (Cbox_ProgressBillings_SelectProgressBilling.SelectedIndex != -1)
            {
                pm.ProgressBillingHeader _selPbHeader = (pm.ProgressBillingHeader)Cbox_ProgressBillings_SelectProgressBilling.SelectedItem;
                pm.ProgressBillSession _session = pm.ProgressBillSessions.CheckSession(_selPbHeader.JobNumber, _selPbHeader.Iteration, _selPbHeader.Revision);
                if (_session == null)
                {
                    pm.ProgressBillSessions.CreateSession(_selPbHeader.JobNumber, _selPbHeader.Iteration, _selPbHeader.Revision);
                    ProgressBillingWindow _pbWin = new ProgressBillingWindow(ref _selPbHeader, false);
                    _pbWin.Show();
                    //Disable 'create' button while these are open.
                }
                else
                {
                    MessageBox.Show("Progress billing currently in use by " + _session.DomainUserName + " since " + _session.SessionTime.Value.ToString("HH:mm")
                                    + " on " + _session.SessionDate.Value.ToString("dd-MMM-yyyy"));

                    if (MessageBox.Show("Would you like to view this progress billing in read-only mode?", "Prompt",
                                       MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    {
                        ProgressBillingWindow _pbw = new ProgressBillingWindow(ref _selPbHeader, true);
                        _pbw.Show();
                        //this.Focus();
                    }

                }
            }
        }

        private void BTN_ProgressBillings_CreateRevisionProgressBilling_Click(object sender, RoutedEventArgs e)
        {
            pm.ProgressBillingHeader _pmHeader = null;

            if (Cbox_ProgressBillings_SelectProgressBilling.SelectedIndex != -1)
            {
                _pmHeader = new pm.ProgressBillingHeader(_pbHeaderCol[_pbHeaderCol.Count - 1]);
                _pmHeader.Revision++;
                _pmHeader.BillingName = "Client Breakdown " + DateTime.Today.ToString("dd") + "-" + DateTime.Today.ToString("MMM").ToUpper() + "-" + DateTime.Today.ToString("yyyy") + "r" + _pmHeader.Revision;
                um.CreatingNewProgressBilling.CreateNewProgressBilling(_combProj, true, _pmHeader.BillingName, _pmHeader.HstNumber, _pmHeader.ContractNumber);
                _pbHeaderCol = pm.ProgressBillingHeaders.GetProgressBillingHeaders(this.JobNumber);
                Cbox_ProgressBillings_SelectProgressBilling.ItemsSource = _pbHeaderCol;
            }
            else
                MessageBox.Show("No Progress Billing was selected.");

        }

        private void BTN_ProgressBillings_NewProgressBilling_Click(object sender, RoutedEventArgs e)
        {
            //Check to see if other progress billing windows for this job are open because we don't want to create a new one then someone save changes on an older existing one.
            //Check to see if the combo box list is empty, if so, prompt for hst number and contrat number.
            //Check change line sessions before creating new progress billing
            pm.ProgressBillingHeader _pmHeader = null;
            //_pbHeader = new ObservableCollection<pm.ProgressBillingHeader>();

            if (_pbHeaderCol != null && _pbHeaderCol.Count == 0)
                _pmHeader = new pm.ProgressBillingHeader(); 
            else if (_pbHeaderCol.Count > 0)
                _pmHeader = _pbHeaderCol[_pbHeaderCol.Count - 1];
           
            pmw.NewProgressBillingWindow _newPbWindow = new pmw.NewProgressBillingWindow(ref _pmHeader);
            _newPbWindow.Owner = this;
            _newPbWindow.ShowDialog();

            um.CreatingNewProgressBilling.CreateNewProgressBilling(_combProj, false, _pmHeader.BillingName, _pmHeader.HstNumber, _pmHeader.ContractNumber);
            _pbHeaderCol = pm.ProgressBillingHeaders.GetProgressBillingHeaders(this.JobNumber);
            Cbox_ProgressBillings_SelectProgressBilling.ItemsSource = _pbHeaderCol;
        }

        #endregion

        private void DG_ChangeOrders_HeaderIndex_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_ChangeOrders_HeaderIndex.SelectedIndex != -1)
            {
                pm.ChangeHeader _changeHeader = (pm.ChangeHeader)DG_ChangeOrders_HeaderIndex.SelectedItem;
                pm.ChangeQuoteSession _session = pm.ChangeQuoteSessions.CheckSession(_changeHeader.JobNumber, _changeHeader.QuoteNumber);
                
                if (_changeHeader.Approved)
                {
                    if (MessageBox.Show("This change order has been approved and can no longer be edited.  Would you like to view this change order in read-only mode?", "Prompt",
                                       MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    {
                        ChangeOrderQuoteWindow _coqw = new ChangeOrderQuoteWindow(ref _changeHeader, ref _chIndex, true, _curUser, ref _changeHeaderCol);
                        //_coqw.Owner = this;
                        _coqw.Show();
                    }
                }
                else if (_session != null)  
                {
                    MessageBox.Show("Quote currently in use by " + _session.DomainUserName + " since " + _session.SessionTime.Value.ToString("HH:mm")
                                    + " on " + _session.SessionDate.Value.ToString("dd-MMM-yyyy"));

                    if (MessageBox.Show("Would you like to view this change order in read-only mode?", "Prompt",
                                       MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    {
                        ChangeOrderQuoteWindow _coqw = new ChangeOrderQuoteWindow(ref _changeHeader, ref _chIndex, true, _curUser, ref _changeHeaderCol);
                        //_coqw.Owner = this;
                        _coqw.Show();
                    }
                }   
                else if (_session == null)
                {
                    pm.ChangeQuoteSessions.CreateSession(_changeHeader.JobNumber, _changeHeader.QuoteNumber);
                    ChangeOrderQuoteWindow _coqw = new ChangeOrderQuoteWindow(ref _changeHeader, ref _chIndex, false, _curUser, ref _changeHeaderCol);
                    //_coqw.Owner = this;
                    _coqw.Show();
                    //pm.ChangeHeaders.UpdateHeader(_changeHeader);
                }


            }
        }

        private void BTN_ChangeOrders_NewQuoteHeader_Click(object sender, RoutedEventArgs e)
        {
            ChangeOrderQuoteAheadWindow _coqaw = new ChangeOrderQuoteAheadWindow();

            if (_changeHeaderCol.Count == 0)
            {
                if (MessageBox.Show("Would you like to start a quote number beyond Q001? This is for instances when the project has already had quotes made in the Excel change index already.", "Prompt",
                        MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                {
                    _coqaw.Owner = this;
                    _coqaw.ShowDialog();

                    if (!_coqaw.ContinueBool)
                        return;
                }
            }

            pm.ChangeHeader _prevHeader = _changeHeaderCol.Count == 0 ? null : _changeHeaderCol[0];   //Grabs contract number info from the quote Q001
            pm.ChangeHeader _chHeader = new pm.ChangeHeader(_combProj, _changeHeaderCol, _prevHeader, _coqaw.QuoteStartNumber);
            try
            {
                if (pm.ChangeHeaders.CreateHeader(_chHeader))   //Constructor now returns a bool and if it's false, a new header won't be added to the _changeHeaderCol collection
                    _changeHeaderCol.Add(_chHeader);
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
            }
        }

        private void BTN_ChangeOrders_CreateRevisionQuote_Click(object sender, RoutedEventArgs e)
        {
            pm.ChangeHeader _selPrevHeader = ((FrameworkElement)sender).DataContext as pm.ChangeHeader;
            if (_selPrevHeader.Cancelled)
            {
                MessageBox.Show("Cannot create a revision from a cancelled quote.");
                return;
            }
            else
            {
                if (_selPrevHeader.RevisionIteration == 0)
                {
                    //_selPrevHeader.Cancelled = true;
                    pm.ChangeHeader _newHeader = new pm.ChangeHeader(_selPrevHeader);
                    _newHeader.Revision = true;
                    if (pm.ChangeHeaders.CreateHeader(_newHeader))
                        _changeHeaderCol.Add(_newHeader);
                    else
                        return;

                    List<pm.ChangeLine> _newQuoteLines = new List<pm.ChangeLine>(pm.ChangeLines.GetChangeLinesByQuote(_selPrevHeader.JobNumber, _selPrevHeader.QuoteNumber));
                    _newQuoteLines.Select(x => { x.QuoteNumber = _newHeader.QuoteNumber; return x; }).ToList();
                    pm.ChangeLines.AddRevisionChangeLines(new ObservableCollection<pm.ChangeLine>(_newQuoteLines));
                    return;
                }
                else //This whole process is redundant since any prior revision quote gets cancelled, but if it changes and prior revisions will NOT be auto-cancelled, this is here.
                {    //Which will be important because it looks like entries 3 and 19 on the bugs list relate to 'uncancelling'
                    int maxRevisionIter = _changeHeaderCol.Where(x => x.QuoteNumber.Substring(0, 4) == _selPrevHeader.QuoteNumber.Substring(0, 4))
                                                .Select(y => y.RevisionIteration).Max();
                    if (_selPrevHeader.RevisionIteration < maxRevisionIter)
                    {
                        MessageBox.Show("Cannot create revision off of this quote because it is not the latest revision quote for " + _selPrevHeader.QuoteNumber.Substring(0, 4) + ".");
                        return;
                    }

                    //_selPrevHeader.Cancelled = true;
                    pm.ChangeHeader _newHeader = new pm.ChangeHeader(_selPrevHeader);
                    if (pm.ChangeHeaders.CreateHeader(_newHeader))
                    {
                        _changeHeaderCol.Add(_newHeader);
                        List<pm.ChangeLine> _newQuoteLines = new List<pm.ChangeLine>(pm.ChangeLines.GetChangeLinesByQuote(_selPrevHeader.JobNumber, _selPrevHeader.QuoteNumber));
                        _newQuoteLines.Select(x => { x.QuoteNumber = _newHeader.QuoteNumber; return x; }).ToList();
                        pm.ChangeLines.AddRevisionChangeLines(new ObservableCollection<pm.ChangeLine>(_newQuoteLines));
                    }
                    else
                        MessageBox.Show("Creation of change quote in the database was unsuccessful");
                    
                }
            }

            //pm.ChangeHeader _header = ((FrameworkElement)sender).DataContext as pm.ChangeHeader;
            //if (_header.Cancelled)
            //{
            //    MessageBox.Show("Cannot create a revision from a cancelled quote.");
            //    return;
            //}
            //else
            //{
            //    if (_header.RevisionIteration == 0)
            //    {
            //        _header.Cancelled = true;
            //        pm.ChangeHeader _newHeader = new pm.ChangeHeader(_header);
            //        _changeHeaderCol.Add(_newHeader);
            //        return;
            //    }
            //    else //This whole process is redundant since any prior revision quote gets cancelled, but if it changes and prior revisions will NOT be auto-cancelled, this is here.
            //    {
            //        bool _canCreate = true;
            //        foreach (pm.ChangeHeader ch in _changeHeaderCol)
            //        {
            //            if (_header.OriginatingDocumentNumber == ch.OriginatingDocumentNumber)
            //            {
            //                if (_header.RevisionIteration < ch.RevisionIteration)
            //                {
            //                    _canCreate = false;
            //                    MessageBox.Show("Cannot create revision off of this quote because it is not the latest revision quote for " + ch.OriginatingDocumentNumber + ".");
            //                    return;
            //                }
            //            }
            //        }
            //        if (_canCreate)
            //        {
            //            _header.Cancelled = true;
            //            pm.ChangeHeader _newHeader = new pm.ChangeHeader(_header);
            //            _changeHeaderCol.Add(_newHeader);
            //        }
            //    }
            //}
        }

        private void BTN_ChangeOrders_CancelQuote_Click(object sender, RoutedEventArgs e)
        {
            pm.ChangeHeader _header = ((FrameworkElement)sender).DataContext as pm.ChangeHeader;
            if (_header.Approved)
            {
                MessageBox.Show("Cannot cancel approved changes.");
            }
            else if (!_header.Cancelled && !_header.Approved)
            {
                _header.Cancelled = true;   //Don't have to check through all the quotes bec
                pm.ChangeHeaders.UpdateHeader(_header);
            }
            else  
            {
                _header.Cancelled = false;
                pm.ChangeHeaders.UpdateHeader(_header);
                //If its status already says cancelled, check all the revision quotes to make sure it wasn't cancelled because a revision was made of it.
                //foreach (pm.ChangeHeader ch in _changeHeaderCol)
                //{
                //    if (_header.QuoteNumber == ch.OriginatingRevisionNumber)
                //    {
                //        MessageBox.Show("This quote cannot be cancelled because revision(s) of it have been made.");
                //        return;
                //    }
                //}
                //_header.Cancelled = true;
            }
        }

        //ChangeOrderCellLostFocus
        void ChangeOrderCellLostFocus(object sender, RoutedEventArgs e)
        {
            DataGridCell cell = sender as DataGridCell;
            if(cell.Column.DisplayIndex == 6)
            {
                MessageBox.Show("sup");
            }
        }

        private void DatePickerDateChanged(object sender, SelectionChangedEventArgs e)
        {
            pm.ChangeHeader _selHeader = ((DatePicker)(sender)).DataContext as pm.ChangeHeader;
            pm.ChangeHeaders.UpdateHeader(_selHeader);
        }

        #region Purchase Orders

        private void BTN_PO_PurchaseOrders_GetAllPoLines_Click(object sender, RoutedEventArgs e)
        {
            //System.Diagnostics.Stopwatch asdf = new System.Diagnostics.Stopwatch();
            //asdf.Start();
            this.IsEnabled = false;
            try
            {

                dc.PoListFunctionByJob objContext = null;
                objContext = new dc.PoListFunctionByJob("Data Source=UCSHSQL2\\MSSQL2014; Initial Catalog=Avaware;Integrated Security=SSPI");
                List<dc.PurchaseOrderLineItem> _poList = objContext.ConnectsPoLineTestAllJobs(this.JobNumber).ToList();
                _poCol = new ObservableCollection<dc.PurchaseOrderLineItem>(_poList);

                //_poCol = dc.PurchaseOrderLineItems.GetAllPurchaseOrdersWithReceipts();
                PurchaseOrders_DG_HardwarePos.ItemsSource = _poCol;
                CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Filter = PoPurchaseOrderFilter;
            }
            catch (Exception ex)
            {
                this.IsEnabled = true;
                MessageBox.Show(ex.ToString());
            }
            this.IsEnabled = true;
            //asdf.Stop();
            //MessageBox.Show(asdf.Elapsed.Seconds.ToString());
        }

        private void BTN_PO_PurchaseOrders_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.PurchaseOrderAll, _curUser);
        }

        private void TB_PO_PurchaseOrders_PoNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_PO_PurchaseOrders_JobNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null && _poCol != null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_PO_PurchaseOrders_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }


        private void TB_PO_PurchaseOrders_SopNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_PO_PurchaseOrders_ItemDescriptionFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_PO_PurchaseOrders_ChangeOrderFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_PO_PurchaseOrders_BuyerIdFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null && _poCol != null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }


        private void TB_PO_PurchaseOrders_VendorNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwPoDa == null && _poCol != null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_PO_PurchaseOrders_AndOr_Checked(object sender, RoutedEventArgs e)
        {
            if (this._hwPoDa == null && _poCol != null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_PO_PurchaseOrders_AndOr_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._hwPoDa == null && _poCol != null)
            {
                this._hwPoDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Refresh());
            }
            if (_poCol != null)
                this._hwPoDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void BTN_PO_PurchaseOrders_ClearFilters_Click(object sender, RoutedEventArgs e)
        {
            CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Filter = null;
            TB_PO_PurchaseOrders_PoNumberFilter.Text = null;
            TB_PO_PurchaseOrders_JobNumberFilter.Text = null;
            TB_PO_PurchaseOrders_JobNameFilter.Text = null;
            TB_PO_PurchaseOrders_SopNumberFilter.Text = null;
            TB_PO_PurchaseOrders_ItemDescriptionFilter.Text = null;
            TB_PO_PurchaseOrders_ChangeOrderFilter.Text = null;
            TB_PO_PurchaseOrders_BuyerIdFilter.Text = null;
            TB_PO_PurchaseOrders_VendorNameFilter.Text = null;
            CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Filter = PoPurchaseOrderFilter;
        }

        private void BTN_PO_PurchaseOrders_AddUcshLineComment(object sender, RoutedEventArgs e)
        {

        }


        private void BTN_PO_PurchaseOrders_AddUcshHeaderComment(object sender, RoutedEventArgs e)
        {

        }

        private void BTN_PO_PurchaseOrders_LaunchJobFolder(object sender, MouseButtonEventArgs e)
        {
            dc.PurchaseOrderLineItem _selPoLine = (dc.PurchaseOrderLineItem)((ContentPresenter)e.Source).DataContext;
            if (Directory.Exists(_selPoLine.JobFolder))
            {
                ProcessStartInfo startInfo = new ProcessStartInfo
                {
                    Arguments = _selPoLine.JobFolder,
                    FileName = "explorer.exe"
                };
                Process.Start(startInfo);
            }
            else
            {
                MessageBox.Show(string.Format("{0} Directory does not exist or job has not been assigned its main project directory in Links yet.", _selPoLine.JobFolder));
            }
        }
        private bool PoPurchaseOrderFilter(object po)
        {
            var _poObject = (dc.PurchaseOrderLineItem)po;

            if (ChkBox_PO_PurchaseOrders_AndOr.IsChecked == true)
            {
                return (_poObject.PoNumber.IndexOf(TB_PO_PurchaseOrders_PoNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _poObject.JobNumber.IndexOf(TB_PO_PurchaseOrders_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _poObject.JobName.IndexOf(TB_PO_PurchaseOrders_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _poObject.ChangeId.IndexOf(TB_PO_PurchaseOrders_ChangeOrderFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _poObject.BuyerId.IndexOf(TB_PO_PurchaseOrders_BuyerIdFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _poObject.SopNumber.IndexOf(TB_PO_PurchaseOrders_SopNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _poObject.ItemDescription.IndexOf(TB_PO_PurchaseOrders_ItemDescriptionFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _poObject.VendorName.IndexOf(TB_PO_PurchaseOrders_VendorNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        );
            }
            else
            {
                return (_poObject.PoNumber.IndexOf(TB_PO_PurchaseOrders_PoNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _poObject.JobNumber.IndexOf(TB_PO_PurchaseOrders_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _poObject.JobName.IndexOf(TB_PO_PurchaseOrders_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _poObject.ChangeId.IndexOf(TB_PO_PurchaseOrders_ChangeOrderFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _poObject.BuyerId.IndexOf(TB_PO_PurchaseOrders_BuyerIdFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _poObject.SopNumber.IndexOf(TB_PO_PurchaseOrders_SopNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _poObject.ItemDescription.IndexOf(TB_PO_PurchaseOrders_ItemDescriptionFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _poObject.VendorName.IndexOf(TB_PO_PurchaseOrders_VendorNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        );
            }
        }

        private void PurchaseOrders_DG_HardwarePos_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            DataGridCell cell = sender as DataGridCell;
            if (cell.Column.DisplayIndex == 1)
            {
                BTN_PO_PurchaseOrders_LaunchJobFolder(sender, e);
                return;
            }
            if (cell != null && !cell.IsEditing)        //(cell != null && !cell.IsEditing && !cell.IsReadOnly) - old, remvoed the negation check on the readonly property of the cell
            {
                if (!cell.IsFocused)
                {
                    cell.Focus();
                }
                DataGrid dataGrid = FindVisualParent<DataGrid>(cell);
                if (dataGrid != null)
                {
                    if (dataGrid.SelectionUnit != DataGridSelectionUnit.FullRow)
                    {
                        if (!cell.IsSelected)
                            cell.IsSelected = true;
                    }
                    else
                    {
                        DataGridRow row = FindVisualParent<DataGridRow>(cell);
                        if (row != null && !row.IsSelected)
                        {
                            if (cell.Column.DisplayIndex == 24)
                            {

                                dc.PurchaseOrderLineItem _selItem = (dc.PurchaseOrderLineItem)row.Item;
                                if (_selItem.UcHeaderHasComments)
                                    _selItem.UcHeaderCommentCol = dc.PoUcshHeaderComments.GetPoUcshHeaderComments(_selItem.PoNumber);
                                else
                                    _selItem.UcHeaderCommentCol = new ObservableCollection<DataClasses.PoUcshHeaderComment>();//This is to bind the collection changed event so that the datagrid updates if a comment is being added for the first time

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(ref _selItem, true, ref _poCol);
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 24)
                            {

                                dc.PurchaseOrderLineItem _selItem = (dc.PurchaseOrderLineItem)row.Item;
                                if (_selItem.UcHeaderHasComments)
                                    _selItem.UcHeaderCommentCol = dc.PoUcshHeaderComments.GetPoUcshHeaderComments(_selItem.PoNumber);
                                else
                                    _selItem.UcHeaderCommentCol = new ObservableCollection<DataClasses.PoUcshHeaderComment>();//This is to bind the collection changed event so that the datagrid updates if a comment is being added for the first time

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(ref _selItem, true, ref _poCol);
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                        }

                        if (row != null && !row.IsSelected)
                        {
                            if (cell.Column.DisplayIndex == 25)
                            {

                                dc.PurchaseOrderLineItem _selItem = (dc.PurchaseOrderLineItem)row.Item;
                                if (_selItem.UcLineHasComments)
                                    _selItem.UcLineCommentCol = dc.PoUcshLineComments.GetPoUcshLineComments(_selItem.PoNumber, _selItem.Order);
                                else
                                    _selItem.UcLineCommentCol = new ObservableCollection<DataClasses.PoUcshLineComment>();//This is to bind the collection changed event so that the datagrid updates if a comment is being added for the first time

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(ref _selItem, false, ref _poCol);
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 25)
                            {

                                dc.PurchaseOrderLineItem _selItem = (dc.PurchaseOrderLineItem)row.Item;
                                if (_selItem.UcLineHasComments)
                                    _selItem.UcLineCommentCol = dc.PoUcshLineComments.GetPoUcshLineComments(_selItem.PoNumber, _selItem.Order);
                                else
                                    _selItem.UcLineCommentCol = new ObservableCollection<DataClasses.PoUcshLineComment>();//This is to bind the collection changed event so that the datagrid updates if a comment is being added for the first time

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(ref _selItem, false, ref _poCol);
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                        }
                    }
                }
            }

        }

        #endregion

        private void ComboBox_Loaded(object sender, RoutedEventArgs e)
        {
            if (_curUser.DomainUserName.ToUpper() != _combProj.MainProject.ProjectManager.ToUpper() && _curUser.PermissionTier > 2 )
                ((ComboBox)sender).IsEnabled = false;
        }

        private List<dc.ShippingLine> ConvertSubmittalLineToShipLine(List<pm.SubmittalLine> submitLines)
        {
            List<dc.ShippingLine> _shipLines = new List<dc.ShippingLine>();
            for (int i = 0; i < submitLines.Count; i++)
            {
                _shipLines.Add(new dc.ShippingLine() { ItemDescription = submitLines[i].Reference, QuantityShipped = submitLines[i].Copies });
            }
            return _shipLines;
        }

        static T FindVisualParent<T>(UIElement element) where T : UIElement
        {
            UIElement parent = element;
            while (parent != null)
            {
                T correctlyTyped = parent as T;
                if (correctlyTyped != null)
                {
                    return correctlyTyped;
                }

                parent = VisualTreeHelper.GetParent(parent) as UIElement;
            }
            return null;
        }

        private void TB_ChangeOrders_QuoteNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_ChangeOrders_ContactChangeId_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_ChangeOrders_TotalValue_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_ChangeOrders_Description_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_ChangeOrders_Manager_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void DP_ChangeOrders_DateCreated_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void DP_ChangeOrders_DateSubmitted_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_ChangeOrders_DateCreated_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_ChangeOrders_DateSubmitted_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_Cancelled_Checked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_Cancelled_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_TentativeApproval_Checked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_TentativeApproval_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_Approved_Checked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_Approved_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_ChangeOrders_ApprovalNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_Billed_Checked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_ChangeOrders_Billed_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._coDa == null)
            {
                this._coDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_ChangeOrders_HeaderIndex.ItemsSource).Refresh());
            }
            this._coDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private bool ChangeIndexFilter(object ch)
        {
            var _changeHeaderObj = (pm.ChangeHeader)ch;
            string headerDesc = _changeHeaderObj.HeaderDescription ?? "";
            string contChangeId = _changeHeaderObj.ContractorChangeId ?? "";
            string authNum = _changeHeaderObj.AuthorizationNumber ?? "";
            //DateTime dtC = _changeHeaderObj.DateCreated ?? DateTime.

            return (_changeHeaderObj.QuoteNumber.IndexOf(TB_ChangeOrders_QuoteNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && contChangeId.IndexOf(TB_ChangeOrders_ContactChangeId.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _changeHeaderObj.TotalQuoteValue.ToString().IndexOf(TB_ChangeOrders_TotalValue.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && headerDesc.IndexOf(TB_ChangeOrders_Description.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _changeHeaderObj.Manager.IndexOf(TB_ChangeOrders_Manager.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    //&& dtC == Convert.ToDateTime(DP_ChangeOrders_DateCreated.Text)
                    //&& dtS == Convert.ToDateTime(DP_ChangeOrders_DateSubmitted.Text)
                    && (ChkBox_ChangeOrders_Cancelled.IsChecked == true ? Convert.ToInt32(_changeHeaderObj.Cancelled.Equals(ChkBox_ChangeOrders_Cancelled.IsChecked)) > 0 : Convert.ToInt32(_changeHeaderObj.Cancelled.Equals(ChkBox_ChangeOrders_Cancelled.IsChecked)) > -1)
                    && (ChkBox_ChangeOrders_TentativeApproval.IsChecked == true ? Convert.ToInt32(_changeHeaderObj.TentativeApproval.Equals(ChkBox_ChangeOrders_TentativeApproval.IsChecked)) > 0 : Convert.ToInt32(_changeHeaderObj.TentativeApproval.Equals(ChkBox_ChangeOrders_TentativeApproval.IsChecked)) > -1)
                    && (ChkBox_ChangeOrders_Approved.IsChecked == true ? Convert.ToInt32(_changeHeaderObj.Approved.Equals(ChkBox_ChangeOrders_Approved.IsChecked)) > 0 : Convert.ToInt32(_changeHeaderObj.Approved.Equals(ChkBox_ChangeOrders_Approved.IsChecked)) > -1)
                    && authNum.IndexOf(TB_ChangeOrders_ApprovalNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && (ChkBox_ChangeOrders_Billed.IsChecked == true ? Convert.ToInt32(_changeHeaderObj.Billed.Equals(ChkBox_ChangeOrders_Billed.IsChecked)) > 0 : Convert.ToInt32(_changeHeaderObj.Billed.Equals(ChkBox_ChangeOrders_Billed.IsChecked)) > -1)
                    );
        }

    }

    internal class DeferredAction : IDisposable
    {
        private System.Threading.Timer timer;

        public static DeferredAction Create(Action action)
        {
            if (action == null)
            {
                throw new ArgumentNullException("action");
            }

            return new DeferredAction(action);
        }

        private DeferredAction(Action action)
        {
            this.timer = new System.Threading.Timer(new System.Threading.TimerCallback(delegate { Application.Current.Dispatcher.Invoke(action); }));
        }

        public void Defer(TimeSpan delay)
        {
            this.timer.Change(delay, TimeSpan.FromMilliseconds(-1));
        }

        public void Dispose()
        { 

        }
    }

    internal class StatusToColorPm : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((bool)value)
            {
                //retColor.Color = System.Windows.Media.Color.FromRgb(255, 0, 0);
                retColor.Color = (Color)ColorConverter.ConvertFromString("Orange");
            }
            else
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
                //retColor.Color = System.Windows.Media.Color.FromRgb(0, 128, 0);
            }
            return retColor;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    internal class ChangeOrderIsCancelled : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((bool)value)
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("Yellow");
            }
            else
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
            }
            return retColor;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    internal class ChangeOrderIsApproved : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((bool)value)
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("Green");
            }
            else
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
            }
            return retColor;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    internal class ChangeOrderIsTentativeApproved : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((bool)value)
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("Green");
            }
            else
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
            }
            return retColor;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    internal class ChangeOrderIsBilled : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((bool)value)
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("Green");
            }
            else
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("#FF575555");
            }
            return retColor;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    internal class PopLinePolnestaStatusConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            string _stat = "";
            if ((short)value == 1)
                _stat = "New";
            else if ((short)value == 2)
                _stat = "Released";
            else if ((short)value == 3)
                _stat = "Change Order";
            else if ((short)value == 4)
                _stat = "Received";
            else if ((short)value == 5)
                _stat = "Closed";
            else if ((short)value == 6)
                _stat = "Cancelled";

            return _stat;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

}
