using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Navigation;
using System.Windows.Shapes;
using dc = PM_Project_Tracking.DataClasses;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using pmw = PM_Project_Tracking.ProjectManagementWindows;
using exc = PM_Project_Tracking.ExcelConverters.ExcelExporter;
using xl = Microsoft.Office.Interop.Excel;
using olc = PM_Project_Tracking.OutlookConverters;
using lq = System.Data.Linq; //Added
using System.Data;
using System.Reflection;
using System.Diagnostics;
using System.ComponentModel;
using System.Resources;
using System.Net.Http;
using PM_Project_Tracking.TitanApi;
using ti = PM_Project_Tracking.DataClasses.TitanObjects;

namespace PM_Project_Tracking
{
    /// <summary>
    /// Interaction logic for MainWindow.xaml
    /// </summary>
    public partial class MainWindow : Window
    {
        //private dc.QsInstaller _qsInstallType;

        //public dc.QsInstaller SelectedInstall
        //{
        //    get { return _qsInstallType; }
        //    set
        //    {
        //        if (_qsInstallType != value)
        //        {
        //            _qsInstallType = value;
        //            OnPropertyChanged(nameof(SelectedInstall));
        //        }
        //    }
        //}




        ObservableCollection<dc.Pursuit> _ptObCol = null;
        ObservableCollection<dc.QuoteSummary> _qsCol = new ObservableCollection<dc.QuoteSummary>();
        ObservableCollection<dc.OfferToTender> _otProjObCol = null;
        ObservableCollection<dc.BidProject> _bidProjObCol = null;
        ObservableCollection<dc.AwardedContract> _awContrObCol = null;
        ObservableCollection<dc.CombinedProject> _combProjObCol = null;
        //
        ObservableCollection<dc.User> _userObCol = null;
        //dc.User _curUser = null;
        dc.User _curUserTwo = null;
        //Task Items
        ObservableCollection<pm.TaskSchedulerItem> _taskListCol = null;
        DateTime _taskItemsToggleMonth = DateTime.Now;
        //Ordering - Hardware
        ObservableCollection<dc.HardwareSchedule> _hdwSchedOrderList = null;

        //Purchase Orders
        ObservableCollection<dc.ShopDrawingLine> _hmShopDraw = null;
        ObservableCollection<dc.HardwareSchedule> _hwSchedule = null;
        ObservableCollection<dc.PurchaseOrderLineItem> _poCol = null;
        //
        //Hardware
        ListCollectionView _hwOpenView = null;
        CollectionView cv = null;
        internal int _hwSelectedJobNum = 0;
        // SOP / POP Link
        ObservableCollection <dc.SopLinkV2> _sopPopList = null;
        DateTime _sopLinkToggleMonth = DateTime.Now;
        private bool _sopLinkItemEdit;
        //Warehouse
        //Create receipts
        internal ObservableCollection<dc.ReceivingLine> _whPoRecCol = new ObservableCollection<dc.ReceivingLine>();
        WarehouseReceiptType _whType = new WarehouseReceiptType();
        //View receipts
        internal ObservableCollection<dc.ReceivingLine> _whViewRecLineCol = null;
        //View tags
        internal ObservableCollection<dc.TaggingLine> _whTagViewEditCol = null;
        //View shipments
        ObservableCollection<dc.ShippingHeader> _whShipHeaderCol = null;
        //Create Shipments
        internal ObservableCollection<dc.ReceivingLine> _whShipRecCol = new ObservableCollection<dc.ReceivingLine>();
        internal ObservableCollection<dc.ShippingLine> _whShipLinesCol = new ObservableCollection<dc.ShippingLine>();
        internal dc.ShippingHeader _whShipHeader = new dc.ShippingHeader();
        internal uc.ReceiptLineRackQuantityTracker _whShipRlDataTrack = new uc.ReceiptLineRackQuantityTracker();

        //Deferred action filters
        //Projects
        DeferredAction _pursuitDa;
        DeferredAction _ottDa;
        DeferredAction _bidDa;
        DeferredAction _acDa;
        DeferredAction _mpDa;
    //Task Items
        DeferredAction _tiDa;
    //Purchase Orders
        DeferredAction _hwPoDa;
        //SOP POP Link
        DeferredAction _sopLinkDa;
    //Hollow Metal
        DeferredAction _hmSdDa;
    //Hardware
        DeferredAction _hwHsDa;
    //Warehouse
        //ViewReceipts
        DeferredAction _whRecDa;
        //ViewEditTags
        DeferredAction _tagVeDa;
        //ViewShipments
        DeferredAction _whShDa;

        //Permission Exception Booleans

        //Project Window Collection
        List<string> _projWinJobNumList = new List<string>();
        List<pmw.ProjectManagementMain> _projWinList = new List<pmw.ProjectManagementMain>();

        //Receipt Draw Down/Ship line create window collection.  This is to stop people from opening multiple windows.
        List<WhShipGetPoReceiptLines> _poRecLinesCreateShipWinList = new List<WhShipGetPoReceiptLines>();

        public MainWindow()
        {

            InitializeComponent();
            
            //change this later in the actual XAML settings
                    Tab_Pursuits_Main.Visibility = System.Windows.Visibility.Collapsed;
                    Tab_OfferToTender_Main.Visibility = System.Windows.Visibility.Collapsed;
                        Tab_QuoteSummary_Main.Visibility = System.Windows.Visibility.Visible;
                    Tab_Bidding_Main.Visibility = System.Windows.Visibility.Collapsed;
                    Tab_AwardedContracts_Main.Visibility = System.Windows.Visibility.Collapsed; 
                    Tab_Users_Main.Visibility = System.Windows.Visibility.Collapsed;

                    Tab_Warehouse_CreateReceipts.Visibility = System.Windows.Visibility.Collapsed;
                    Tab_Warehouse_CreateShipments.Visibility = System.Windows.Visibility.Collapsed;
                    StckPan_Warehouse_ViewReceipts_UpdateRackLocation.Visibility = System.Windows.Visibility.Visible;
            //

            _curUserTwo = dc.Users.GetCurrentUser();
            //_curUserTwo = dc.Users.GetDummyUser();
            if (_curUserTwo == null) { this.Close(); return; }
            if (_curUserTwo.CompanyId == 2)
            {
                GlobalVars.CurrentPmDatabaseName = "PMUBC";
                GlobalVars.CurrentGpDatabaseName = "UBC";
            }

            Tab_MainProject_Main.IsSelected = true;
            ChkBox_PO_PurchaseOrders_MaxOneYear.IsChecked = true;
            ChkBox_Warehouse_CreateReceipts_HideFullReceivedLines.IsChecked = false;
            ChkBox_Warehouse_ViewReceipts_MaxOneYear.IsChecked = false;

            //Setting default tab sliders in the warehouse shipment creation component
            StckPan_Warehouse_CreateShipments_CustomerButtons.Visibility = System.Windows.Visibility.Hidden;
            StckPan_Warehouse_CreateShipments_JobProperties.Visibility = System.Windows.Visibility.Visible;
            StckPan_Warehouse_CreateShipments_CustProperties.Visibility = System.Windows.Visibility.Hidden;
            //Debug.Print("test");
        }
         
        private void Window_Loaded(object sender, RoutedEventArgs e)
        {
            //ChkBox_Pursuits_IgnoreCompleted.IsChecked = true;
            ChkBox_Pursuits_IgnoreCompleted.IsChecked = false;  //TESTING FOR NOW, REVERT TO 'TRUE' LATER
            ChkBox_Bidding_IgnoreCompleted.IsChecked = true;
            //Insert check here to set to UCSH or BC based on user company ID
            SetModulesAccess(_curUserTwo);  //gotta work on this one
            //
            LBL_DisplayDatabase.Content = GlobalVars.CurrentPmDatabaseName;
            LBL_DisplayUsername.Content = _curUserTwo.DomainUserName;

        }

        #region MainWindow Utility Methods

        internal void SetModulesAccess(dc.User _user)
        {
            //Pursuits
            if (_user.PermissionTier < 4 | ViewsOverrideChecker("Tab_OfferToTender_Main"))   //This assumes that anything under curator will never see these tabs.  If we make exceptions for people below curator, we'll have to change this
            {
                Tab_Pursuits_Main.Visibility = System.Windows.Visibility.Visible;
                _ptObCol = dc.Pursuits.GetPursuits((bool)ChkBox_Pursuits_IgnoreCompleted.IsChecked);
                DG_Pursuits_PursuitList.ItemsSource = _ptObCol;
                if (_ptObCol != null)
                    CollectionViewSource.GetDefaultView(DG_Pursuits_PursuitList.ItemsSource).Filter = PtItemFilter;
                    if (_user.PermissionTier > 2 & (AccessOverrideChecker("OfferToTender_UpdateCreateTransfer") == false)) //Notice the comparison symbol goes the other way ">"
                    {
                        BTN_Pursuits_AddNewPursuit.IsEnabled = false;
                        BTN_Pursuits_UpdateServer.IsEnabled = false;
                        BTN_Pursuits_TransferPursuit.IsEnabled = false;
                    }
            }

            //Offer to tender
            if (_user.PermissionTier < 4 | ViewsOverrideChecker("Tab_OfferToTender_Main"))   //This assumes that anything under curator will never see these tabs.  If we make exceptions for people below curator, we'll have to change this
            {
                Tab_OfferToTender_Main.Visibility = System.Windows.Visibility.Visible;
                _otProjObCol = dc.OfferToTenders.GetOfferToTenderProjects();
                DG_OfferToTender_TenderList.ItemsSource = _otProjObCol;
                CollectionViewSource.GetDefaultView(DG_OfferToTender_TenderList.ItemsSource).Filter = OttItemFilter;
                if (_user.PermissionTier > 2 & (AccessOverrideChecker("OfferToTender_UpdateCreateTransfer") == false)) //Notice the comparison symbol goes the other way ">"
                {
                    BTN_OfferToTender_AddNewProj.IsEnabled = false;
                    BTN_OfferToTender_UpdateServer.IsEnabled = false;
                    BTN_OfferToTender_TransferProjects.IsEnabled = false;
                }
            }

            //Bidding
            if (_user.PermissionTier < 4 | ViewsOverrideChecker("Tab_Bidding_Main"))
            {
                Tab_Bidding_Main.Visibility = System.Windows.Visibility.Visible;
                _bidProjObCol = dc.BidProjects.GetBidProjects((bool)ChkBox_Bidding_IgnoreCompleted.IsChecked);
                DG_Bidding_PreProj.ItemsSource = _bidProjObCol;
                CollectionViewSource.GetDefaultView(DG_Bidding_PreProj.ItemsSource).Filter = BidItemFilter;  //5 Jan 2017 - Somehow an entry made it into the Awarded Contract table with no job number (null), causing this BidItemFilter to silently crash when it iterated over the null value
                if (_user.PermissionTier > 2 & (AccessOverrideChecker("Bidding_UpdateCreateTransfer") == false)) //Notice the comparison symbol goes the other way ">"
                {
                    BTN_Bidding_AddNewProj.IsEnabled = false;
                    BTN_Bidding_UpdateServer.IsEnabled = false;
                    BTN_Bidding_TransferProjects.IsEnabled = false;
                }
            }

            //Quote Summary
            if (_user.PermissionTier < 4 | ViewsOverrideChecker("Tab_QuoteSummary_Main"))
            {





                ////Tab_QuoteSummary_Main.Visibility = System.Windows.Visibility.Visible;
                //dc.QuoteSummary asdf = new dc.QuoteSummary() { JobNumber = "99999", Cc2102002Cost = 500, Cc2102002Sell = 1000 };
                ////StckPan_QuoteSummary_ExpandersGroup.DataContext = asdf;
                //Tab_QuoteSummary_Main.DataContext = asdf;

                //IEnumerable<Expander> xcol = StckPan_QuoteSummary_ExpandersGroup.Children.OfType<Expander>();
                ////https://stackoverflow.com/questions/46034722/how-to-find-wpf-expander-children-programmatically

                //try
                //{

                //    foreach (Expander exp in QuoteSummaryFindLogicalChildren<Expander>(StckPan_QuoteSummary_ExpandersGroup))
                //    {
                //        StackPanel _selStackPan = null;
                //        if (exp.Content.GetType() == typeof(StackPanel))
                //            _selStackPan = exp.Content as StackPanel;

                //        //var stckpan_name = _selStackPan.Name;

                //        foreach (StackPanel sp in QuoteSummaryFindLogicalChildren<StackPanel>(_selStackPan))
                //        {
                //            Debug.Print(sp.Name);
                //            foreach (DependencyObject ct in LogicalTreeHelper.GetChildren(sp))
                //            {
                //                if (ct is TextBox == true)
                //                {
                //                    //var aasdfdsfs = (ct as TextBox).GetBindingExpression(TextBox.TextProperty);
                //                    var bbbb = (ct as TextBox).Text;
                //                }

                //            }
                //        }
                //    }
                //}
                //catch(Exception ex)
                //{
                //    MessageBox.Show(ex.ToString());
                //}

            }

            //Awarded Contracts
            if (_user.PermissionTier < 4 | ViewsOverrideChecker("Tab_AwardedContracts_Main"))
            {
                Tab_AwardedContracts_Main.Visibility = System.Windows.Visibility.Visible;
                _awContrObCol = dc.AwardedContracts.GetAwardedContracts();
                DG_AwardedContracts_ContrList.ItemsSource = _awContrObCol;
                CollectionViewSource.GetDefaultView(DG_AwardedContracts_ContrList.ItemsSource).Filter = AwContrFilter;
                if (_user.PermissionTier > 2 & (AccessOverrideChecker("AwardedContracts_UpdateCreateTransfer") == false)) //Notice the comparison symbol goes the other way ">"
                {
                    BTN_AwardedAndContracts_UpdateServer.IsEnabled = false;
                }
            }

            //Main Project
            if (_user.PermissionTier < 4 | ViewsOverrideChecker("Tab_MainProject_Main"))
            {
                Tab_MainProject_Main.Visibility = System.Windows.Visibility.Visible;
                _combProjObCol = dc.MainProjects.GetCombinedProject();
                DG_MainProject_ProjectList.ItemsSource = _combProjObCol;
                CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Filter = MainProjFilter;
            }
            else
            {
                Tab_MainProject_Main.Visibility = System.Windows.Visibility.Visible;
                _combProjObCol = dc.MainProjects.GetLimitedUsers(_curUserTwo);
                DG_MainProject_ProjectList.ItemsSource = _combProjObCol;
                CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Filter = MainProjFilter;
            }

            //Users
            if (_user.PermissionTier < 3)   //Only developers and admins
            {
                _userObCol = dc.Users.GetUsers();
                UsersTab_DG_Users.ItemsSource = _userObCol;
                Tab_Users_Main.Visibility = System.Windows.Visibility.Visible;
            }

            //Task Items


            //Hollow Metal
            //_hmShopDraw = dc.HollowMetal.GetShopDrawing();
            //HollowMetal_DG_ShopDrawings.ItemsSource = _hmShopDraw;

            //Hardware
                //Hardware Schedule
            //_hwSchedule = dc.Hardware.GetHardwareSchedule();
            //Hardware_DG_HardwareSchedule.ItemsSource = _hwSchedule;

                //Hardware Purchase Orders
            //_poCol = dc.PurchaseOrderLineItems.GetAllPurchaseOrdersWithReceipts();
            //PurchaseOrders_DG_HardwarePos.ItemsSource = _poCol;
            //CollectionViewSource.GetDefaultView(PurchaseOrders_DG_HardwarePos.ItemsSource).Filter = PoPurchaseOrderFilter;

            //Warehouse
                //Create Receipts
            if (_user.PermissionTier < 3 | ViewsOverrideChecker("Tab_Warehouse_CreateReceipts"))   //This assumes that anything under curator will never see these tabs.  If we make exceptions for people below curator, we'll have to change this
            {
                Tab_Warehouse_CreateReceipts.Visibility = System.Windows.Visibility.Visible;
                StckPan_Warehouse_ViewReceipts_UpdateRackLocation.Visibility = System.Windows.Visibility.Visible;
            }
                //Create Shipments
            if (_user.PermissionTier < 3 | ViewsOverrideChecker("Tab_Warehouse_CreateShipments"))   //This assumes that anything under curator will never see these tabs.  If we make exceptions for people below curator, we'll have to change this
            {
                Tab_Warehouse_CreateShipments.Visibility = System.Windows.Visibility.Visible;
                DG_Warehouse_CreateShipments_ShipLines.ItemsSource = _whShipLinesCol;   
            }

        }


        internal void RefreshPursuits()
        {
            _ptObCol = dc.Pursuits.GetPursuits((bool)ChkBox_Pursuits_IgnoreCompleted.IsChecked);
            DG_Pursuits_PursuitList.ItemsSource = _ptObCol;
            CollectionViewSource.GetDefaultView(DG_Pursuits_PursuitList.ItemsSource).Filter = PtItemFilter;
        }

        internal void RefreshOfferToTenders()
        {
            _otProjObCol = dc.OfferToTenders.GetOfferToTenderProjects();
            DG_OfferToTender_TenderList.ItemsSource = _otProjObCol;
            CollectionViewSource.GetDefaultView(DG_OfferToTender_TenderList.ItemsSource).Filter = OttItemFilter;
        }

        internal void RefreshBidProjects()
        {
            _bidProjObCol = dc.BidProjects.GetBidProjects((bool)ChkBox_Bidding_IgnoreCompleted.IsChecked);
            DG_Bidding_PreProj.ItemsSource = _bidProjObCol;
            CollectionViewSource.GetDefaultView(DG_Bidding_PreProj.ItemsSource).Filter = BidItemFilter;
        }

        #endregion

        #region Quote Summary Events


        private void BTN_QuoteSummary_SelectJob_Click(object sender, RoutedEventArgs e)
        {   
            QsSelectJob _selJobWin = new QsSelectJob(this);
            _selJobWin.Owner = this;
            _selJobWin.ShowDialog();
            if (_selJobWin.ReturnQuoteList)
                _qsCol = _selJobWin.QuoteList;

            //Grid_QuoteSummary_Main.DataContext = _qsCol[0];
                //CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged -= CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
            CBox_QuoteSummary_SelectQuoteNumber.ItemsSource = _qsCol;
        }

        private void BTN_QuoteSummary_NewJob_Click(object sender, RoutedEventArgs e)
        {
            QsNewJobQuote _newJobWin = new QsNewJobQuote(this);
            _newJobWin.Owner = this;
            _newJobWin.ShowDialog();

            CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged -= CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
            _qsCol.Clear();
            _qsCol.Add(_newJobWin.NewQs);
            CBox_QuoteSummary_SelectQuoteNumber.ItemsSource = _qsCol;
            CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged += CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
            CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex = 0;
        }


        private void BTN_QuoteSummary_ExportToWord_Click(object sender, RoutedEventArgs e)
        {
            if (Grid_QuoteSummary_Main.DataContext != null)
                WordConverters.ExportQuoteSummary.CreateQuoteSummaryDocument((dc.QuoteSummary)Grid_QuoteSummary_Main.DataContext);
        }

        private void BTN_QuoteSummary_UpdateBid_Click(object sender, RoutedEventArgs e)
        {

            if (CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex != -1)
            {
                dc.QuoteSummary _selQuote = (dc.QuoteSummary)CBox_QuoteSummary_SelectQuoteNumber.SelectedItem;
                if (MessageBox.Show("Do you wish to update job " + _selQuote.JobNumber + "'s bid value using " + _selQuote.QuoteNumber + "?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    dc.QuoteSummaries.UpdateRelatedBidObject(_selQuote);
            }
        }

        private void BTN_QuoteSummary_test_Click(object sender, RoutedEventArgs e)
        {
            dc.QuoteSummary qs = new dc.QuoteSummary() { Cc2102002SellTax = 20, Cc3100003SellTax = 45, Cc5100005SellTax = 71 };
            //The casting of (decimal) to "i.Getvalue(qs)" works without error because the attribute "CostCodeSellWithTax" has ONLY been applied to properties that are of type decimal
            List<PropertyInfo> sellTaxPropInfo = qs.GetType().GetProperties().Where(x => x.CustomAttributes.Any(y => y.AttributeType == typeof(dc.CostCodeSellWithTax))).Where(i => (decimal)i.GetValue(qs) > 0).ToList();
            //dc.CostCodeSellWithTax ccAttr = (dc.CostCodeSellWithTax)sellTaxPropInfo[1].GetCustomAttribute(typeof(dc.CostCodeSellWithTax));

            //MessageBox.Show(sellTaxPropInfo[0].GetValue(qs).ToString());
            var total = sellTaxPropInfo.Select(x => (decimal)x.GetValue(qs)).Sum();
        }

        private void CBox_QuoteSummary_SelectQuoteNumber_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            dc.QuoteSummary _selQs = (dc.QuoteSummary)CBox_QuoteSummary_SelectQuoteNumber.SelectedItem;
            if (CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex != -1)
            {
                int _qsIndex = CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex;
                //Setting the Datacontext to null for the quote number combobox in the XAML stopped this datacontext reset from also resetting the selected item in the combobox
                Grid_QuoteSummary_Main.DataContext = _qsCol[_qsIndex];
            }
        }

        private void BTN_QuoteSummary_NewQuote_Click(object sender, RoutedEventArgs e)
        {
            dc.QuoteSummary _newQuote = new dc.QuoteSummary();
            if (_qsCol != null)
                _newQuote = _qsCol.OrderByDescending(x => x.Iteration).ThenByDescending(i => i.RevisionIteration).First();

            _qsCol.Add(new dc.QuoteSummary(_newQuote, false));
            Grid_QuoteSummary_Main.DataContext = _qsCol[_qsCol.Count - 1];
            CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged -= CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
            CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex = _qsCol.Count - 1;
            CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged += CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
        }

        private void BTN_QuoteSummary_NewRevision_Click(object sender, RoutedEventArgs e)
        {
            dc.QuoteSummary _selQuote = null;
            dc.QuoteSummary _newQuote = new dc.QuoteSummary();
            if (CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex != -1)
            {
                _selQuote = (dc.QuoteSummary)CBox_QuoteSummary_SelectQuoteNumber.SelectedItem;
                //Grabs whatever quote number base was taken from the selected item on the quote drop down and finds the latest revision for it and passes that version to the QuoteSummary constructor so that it simplifies what gets passed through
                _newQuote = _qsCol.Where(x => x.Iteration == _selQuote.Iteration).OrderByDescending(i => i.RevisionIteration).First();
                if (MessageBox.Show("Do you wish to make a revision based off of" + _newQuote.QuoteNumber + "?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.No)
                    return;
            }
            else
            {
                MessageBox.Show("A base quote must be selected from the drop-down before a revision can be created.");
                return;
            }

            _qsCol.Add(new dc.QuoteSummary(_newQuote, true));
            Grid_QuoteSummary_Main.DataContext = _qsCol[_qsCol.Count - 1];
            CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged -= CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
            CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex = _qsCol.Count - 1;
            CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged += CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
        }


        private void CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
        {
            var asdf = "sdfds";
            //if (CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex != -1)
            //{
            //    int _qsIndex = CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex;
            //    CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged -= CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
            //    CBox_QuoteSummary_SelectQuoteNumber.SelectedIndex = _qsIndex;
            //    CBox_QuoteSummary_SelectQuoteNumber.DataContextChanged += CBox_QuoteSummary_SelectQuoteNumber_DataContextChanged;
            //}
        }

        private void BTN_QuoteSummary_CommitChanges_Click(object sender, RoutedEventArgs e)
        {
            dc.QuoteSummary _selQs = (dc.QuoteSummary)Grid_QuoteSummary_Main.DataContext;

            if (_selQs.Id == 0)
                dc.QuoteSummaries.CreateQuoteSummary(_selQs);
            else
                dc.QuoteSummaries.UpdateQuoteSummary(_selQs);
        }

        private void BTN_QuoteSummary_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.QuoteSummaries, _curUserTwo);
        }

        #endregion

        #region Pursuit Events

        private void BTN_Pursuits_UpdateServer_Click(object sender, RoutedEventArgs e)
        {

            try
            {
                bool _cont = dc.Pursuits.UpdatePursuitProjects(_ptObCol);
                if (_cont)
                {
                    _ptObCol = dc.Pursuits.GetPursuits((bool)ChkBox_Pursuits_IgnoreCompleted.IsChecked);
                    DG_Pursuits_PursuitList.ItemsSource = _ptObCol;
                    CollectionViewSource.GetDefaultView(DG_Pursuits_PursuitList.ItemsSource).Filter = PtItemFilter;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show("BTN_Pursuits_UpdateServer_Click \r\n" + ex.ToString());
            }
        }
            
        private void BTN_Pursuits_AddNewPursuit_Click(object sender, RoutedEventArgs e)
        {
            dc.Pursuit _newPt = new dc.Pursuit();
            //_newPt.PursuitStatus = "PENDING";
            _newPt.JobName = ""; 
            _newPt.Contractor = "";
            _newPt.IsModified = false;
            _ptObCol.Add(_newPt);
        }

        private void BTN_Pursuits_TransferPursuit_Click(object sender, RoutedEventArgs e)
        {
            TransferPursuitMenu _transPtMenu = new TransferPursuitMenu(this, this.DG_Pursuits_PursuitList, _ptObCol);
            _transPtMenu.Owner = this;
            _transPtMenu.ShowDialog();

        }

        private void TB_Pursuits_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._pursuitDa == null)
            {
                this._pursuitDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Pursuits_PursuitList.ItemsSource).Refresh());
            }
            this._pursuitDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_Pursuits_AndOr_Checked(object sender, RoutedEventArgs e)
        {

        }

        private void TB_Pursuits_CustomerNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._pursuitDa == null)
            {
                this._pursuitDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Pursuits_PursuitList.ItemsSource).Refresh());
            }
            this._pursuitDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void BTN_Pursuits_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.Pursuits, _curUserTwo);
        }

        private bool PtItemFilter(object pt)
        {
            var _ptObject = (dc.Pursuit)pt;

            if (ChkBox_Pursuits_AndOr.IsChecked == true)
            {
                return (_ptObject.JobName.IndexOf(TB_Pursuits_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _ptObject.Contractor.IndexOf(TB_Pursuits_CustomerNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
            else
            {
                return (_ptObject.JobName.IndexOf(TB_Pursuits_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _ptObject.Contractor.IndexOf(TB_Pursuits_CustomerNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
        }

        #endregion

        #region OfferToTender Events

        private void BTN_OfferToTender_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                dc.OfferToTenders.UpdateOfferToTenderProjects(_otProjObCol);
                _otProjObCol = dc.OfferToTenders.GetOfferToTenderProjects();
                DG_OfferToTender_TenderList.ItemsSource = _otProjObCol;
                CollectionViewSource.GetDefaultView(DG_OfferToTender_TenderList.ItemsSource).Filter = OttItemFilter;
            }
            catch (Exception ex)
            {
                MessageBox.Show("BTN_OfferToTender_UpdateServer_Click \r\n" + ex.ToString());
            }
        }

        private void BTN_OfferToTender_AddNewProj_Click(object sender, RoutedEventArgs e)
        {
            dc.OfferToTender _newOtt = new dc.OfferToTender();
            _newOtt.JobName = "";
            _newOtt.CustomerName = "";
            _newOtt.IsModified = false;
            _otProjObCol.Add(_newOtt);
        }

        private void BTN_OfferToTender_TransferProjects_Click(object sender, RoutedEventArgs e)
        {
            TransferTenderMenu _transOttMenu = new TransferTenderMenu(this, this.DG_OfferToTender_TenderList, _otProjObCol);
            _transOttMenu.Owner = this;
            _transOttMenu.ShowDialog();
        }

        private void BTN_OfferToTender_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.OffersToTender, _curUserTwo);
        }

        private void TB_OfferToTender_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            //http://www.codeproject.com/Articles/32426/Deferring-ListCollectionView-filter-updates-for-a

            if (this._ottDa == null)
            {
                this._ottDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_OfferToTender_TenderList.ItemsSource).Refresh());
            }
            this._ottDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_OfferToTender_CustomerNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._ottDa == null)
            {
                this._ottDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_OfferToTender_TenderList.ItemsSource).Refresh());
            }
            this._ottDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_OfferToTender_AndOr_Checked(object sender, RoutedEventArgs e)
        {
            if (this._ottDa == null)
            {
                this._ottDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_OfferToTender_TenderList.ItemsSource).Refresh());
            }
            this._ottDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void ChkBox_OfferToTender_AndOr_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._ottDa == null)
            {
                this._ottDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_OfferToTender_TenderList.ItemsSource).Refresh());
            }
            this._ottDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private bool OttItemFilter(object hw)
        {
            var _ottObject = (dc.OfferToTender)hw;

            if (ChkBox_OfferToTender_AndOr.IsChecked == true)
            {
                return (_ottObject.JobName.IndexOf(TB_OfferToTender_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _ottObject.CustomerName.IndexOf(TB_OfferToTender_CustomerNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
            else
            {
                return (_ottObject.JobName.IndexOf(TB_OfferToTender_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _ottObject.CustomerName.IndexOf(TB_OfferToTender_CustomerNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
        }

        #endregion

        #region Biddding Events

        private void BTN_Bidding_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            try
            {
               bool _cont = dc.BidProjects.UpdateBidProjects(_bidProjObCol);
                if (_cont)
                {
                    _bidProjObCol = dc.BidProjects.GetBidProjects((bool)ChkBox_Bidding_IgnoreCompleted.IsChecked);
                    DG_Bidding_PreProj.ItemsSource = _bidProjObCol;
                    CollectionViewSource.GetDefaultView(DG_Bidding_PreProj.ItemsSource).Filter = BidItemFilter;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show("BTN_Bidding_UpdateServer_Click \r\n" + ex.ToString());
            }
        }

        private void BTN_Bidding_AddNewProj_Click(object sender, RoutedEventArgs e)
        {
            dc.BidProject _newBid = new dc.BidProject();
            _newBid.DateModified = DateTime.Today; //DateTime.Today;
            _newBid.IsModified = false;
            _newBid.JobNumber = "";
            _newBid.JobName = "";
            _bidProjObCol.Add(_newBid);
        }

        private void BTN_Bidding_TransferProjects_Click(object sender, RoutedEventArgs e)
        {
            TransferBidMenu _transProjsMenu = new TransferBidMenu(this, this.DG_Bidding_PreProj, _bidProjObCol, _curUserTwo);
            _transProjsMenu.Owner = this;
            _transProjsMenu.ShowDialog();
        }

        private void BTN_Bidding_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.Bids, _curUserTwo);
        }

        private void TB_Bidding_JobNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._bidDa == null)
            {
                this._bidDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Bidding_PreProj.ItemsSource).Refresh());
            }
            this._bidDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_Bidding_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._bidDa == null)
            {
                this._bidDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Bidding_PreProj.ItemsSource).Refresh());
            }
            this._bidDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_Bidding_AndOr_Checked(object sender, RoutedEventArgs e)
        {
            if (this._bidDa == null)
            {
                this._bidDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Bidding_PreProj.ItemsSource).Refresh());
            }
            this._bidDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void ChkBox_Bidding_AndOr_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._bidDa == null)
            {
                this._bidDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Bidding_PreProj.ItemsSource).Refresh());
            }
            this._bidDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private bool BidItemFilter(object bid)
        {
            var _bidObject = (dc.BidProject)bid;

            if (ChkBox_Bidding_AndOr.IsChecked == true)
            {
                return (_bidObject.JobNumber.IndexOf(TB_Bidding_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _bidObject.JobName.IndexOf(TB_Bidding_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
            else
            {
                return (_bidObject.JobNumber.IndexOf(TB_Bidding_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _bidObject.JobName.IndexOf(TB_Bidding_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
        }

        #endregion

        #region AwardAndContract Events

        private void BTN_AwardedContracts_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                dc.AwardedContracts.UpdateAwardedContracts(_awContrObCol);
                _awContrObCol = dc.AwardedContracts.GetAwardedContracts();
                DG_AwardedContracts_ContrList.ItemsSource = _awContrObCol;
                CollectionViewSource.GetDefaultView(DG_AwardedContracts_ContrList.ItemsSource).Filter = AwContrFilter;
            }
            catch (Exception ex)
            {
                MessageBox.Show("BTN_Bidding_UpdateServer_Click \r\n" + ex.ToString());
            }
        }

        private void BTN_AwardedContracts_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.AwardedContracts, _curUserTwo);
        }

        private void TB_AwardedContracts_JobNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._acDa == null)
            {
                this._acDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_AwardedContracts_ContrList.ItemsSource).Refresh());
            }
            this._acDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_AwardedContracts_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._acDa == null)
            {
                this._acDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_AwardedContracts_ContrList.ItemsSource).Refresh());
            }
            this._acDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_AwardedContracts_AndOr_Checked(object sender, RoutedEventArgs e)
        {
            if (this._acDa == null)
            {
                this._acDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_AwardedContracts_ContrList.ItemsSource).Refresh());
            }
            this._acDa.Defer(new TimeSpan(0, 0, 0, 1, 200));
        }

        private void ChkBox_AwardedContracts_AndOr_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._acDa == null)
            {
                this._acDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_AwardedContracts_ContrList.ItemsSource).Refresh());
            }
            this._acDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private bool AwContrFilter(object awContr)
        {
            var _awContrObject = (dc.AwardedContract)awContr;

            if (ChkBox_AwardAndContracts_AndOr.IsChecked == true)
            {
                return (_awContrObject.JobNumber.IndexOf(TB_AwardedContracts_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _awContrObject.JobName.IndexOf(TB_AwardedContracts_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
            else
            {
                return (_awContrObject.JobNumber.IndexOf(TB_AwardedContracts_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _awContrObject.JobName.IndexOf(TB_AwardedContracts_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
        }

        #endregion

        #region MainProjects Events

        private void BTN_MainProject_UpdateServer_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                //Need to extract all the main projects into a collection from the CombinedProject observable collection
                List<dc.MainProject> _mpList = new List<dc.MainProject>();
                foreach (dc.CombinedProject cp in _combProjObCol)
                {
                    _mpList.Add(cp.MainProject);
                }
                dc.MainProjects.UpdateMainProjects(_mpList);

                //_combProjObCol = dc.MainProjects.GetCombinedProject();
                SetModulesAccess(_curUserTwo);
                //RefreshDataGrids();
                //MainProjTab_DG_MainProjects.ItemsSource = _combProjObCol;
                //CollectionViewSource.GetDefaultView(MainProjTab_DG_MainProjects.ItemsSource).Filter = MainProjFilter;
            }
            catch (Exception ex)
            {
                MessageBox.Show("BTN_MainProjects_UpdateServer_Click \r\n" + ex.ToString());
            }
        }

        private void BTN_MainProject_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
                if (_curUserTwo.PermissionTier < 4)
                {
                    ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.MainProjects, _curUserTwo);
                }
                else
                {
                    ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.MainProjects, _curUserTwo);
                }
        }

        private void TB_MainProject_JobNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_MainProject_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {            
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_MainProject_ProjectManagerFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_MainProject_ConsultantFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_MainProject_CoordinatorFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_MainProject_HardwareCoordinatorFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void ChkBox_MainProject_AndOr_Checked(object sender, RoutedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void ChkBox_MainProject_AndOr_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }


        private void ChkBox_MainProject_FilterUca_Checked(object sender, RoutedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }


        private void ChkBox_MainProject_FilterUca_Unchecked(object sender, RoutedEventArgs e)
        {
            if (this._mpDa == null)
            {
                this._mpDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Refresh());
            }
            this._mpDa.Defer(new TimeSpan(0, 0, 0, 0, 200));
        }

        private void BTN_MainProject_ClearFilters_Click(object sender, RoutedEventArgs e)
        {
            CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Filter = null;
            TB_MainProject_JobNumberFilter.Text = null;
            TB_MainProject_JobNameFilter.Text = null;
            TB_MainProject_ProjectManagerFilter.Text = null;
            TB_MainProject_CoordinatorFilter.Text = null;
            TB_MainProject_HardwareCoordinatorFilter.Text = null;
            TB_MainProject_ConsultantFilter.Text = null;
            ChkBox_MainProject_FilterUca.IsChecked = false;
            CollectionViewSource.GetDefaultView(DG_MainProject_ProjectList.ItemsSource).Filter = MainProjFilter;
        }

        private void MainProject_LaunchProjectWindow(object sender, RoutedEventArgs e)
        {
            dc.CombinedProject _selProj = (dc.CombinedProject)((Button)e.Source).DataContext;

            for (int i = _projWinList.Count - 1; i >= 0; i--)   //Remove closed and ctrl+alt+deleted windows from the collection
            {
                if (_projWinList[i].IsLoaded == false)
                    _projWinList.RemoveAt(i); 
            }

            foreach (pmw.ProjectManagementMain pw in _projWinList)
            {
                if (pw.JobNumber == _selProj.MainProject.JobNumber)
                {
                    MessageBox.Show("There is already a window open for that project.");
                    return;
                }
            }

            pmw.ProjectManagementMain _projWindow = new pmw.ProjectManagementMain(_selProj, _projWinList, _curUserTwo);
            _projWinList.Add(_projWindow);
            _projWindow.Owner = this;
            _projWindow.Show();
            //this.Focus();
        }

        private bool MainProjFilter(object mp)
        {
            var _mainProjObject = (dc.CombinedProject)mp;

            if (ChkBox_MainProject_AndOr.IsChecked == true)
            {
                return (_mainProjObject.MainProject.JobNumber.IndexOf(TB_MainProject_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _mainProjObject.Jc00102.JobName.IndexOf(TB_MainProject_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _mainProjObject.MainProject.ProjectManager.IndexOf(TB_MainProject_ProjectManagerFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _mainProjObject.Jc00102.Consultant.IndexOf(TB_MainProject_ConsultantFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _mainProjObject.MainProject.ProjectCoordinator.IndexOf(TB_MainProject_CoordinatorFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || _mainProjObject.MainProject.HardwareCoordinator.IndexOf(TB_MainProject_HardwareCoordinatorFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        || (ChkBox_MainProject_FilterUca.IsChecked == true ? Convert.ToInt32(_mainProjObject.MainProject.IsUca.Equals(ChkBox_MainProject_FilterUca.IsChecked)) > 0 : Convert.ToInt32(_mainProjObject.MainProject.IsUca.Equals(ChkBox_MainProject_FilterUca.IsChecked)) > -1)
                        );
            }
            else
            {
                return (_mainProjObject.MainProject.JobNumber.IndexOf(TB_MainProject_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _mainProjObject.Jc00102.JobName.IndexOf(TB_MainProject_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _mainProjObject.MainProject.ProjectManager.IndexOf(TB_MainProject_ProjectManagerFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _mainProjObject.Jc00102.Consultant.IndexOf(TB_MainProject_ConsultantFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _mainProjObject.MainProject.ProjectCoordinator.IndexOf(TB_MainProject_CoordinatorFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _mainProjObject.MainProject.HardwareCoordinator.IndexOf(TB_MainProject_HardwareCoordinatorFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && (ChkBox_MainProject_FilterUca.IsChecked == true ? Convert.ToInt32(_mainProjObject.MainProject.IsUca.Equals(ChkBox_MainProject_FilterUca.IsChecked)) > 0 : Convert.ToInt32(_mainProjObject.MainProject.IsUca.Equals(ChkBox_MainProject_FilterUca.IsChecked)) > -1)
                        );
            }
        }

        #endregion 

        #region Task Items

        private void BTN_TaskScheduler_RefreshList_Click(object sender, RoutedEventArgs e)
        {
            //bool _ignoreCompl = (bool)ChkBox_TaskScheduler_IgnoreCompleted.IsChecked;
            _taskListCol = pm.TaskSchedulers.GetTaskScheduleItemsAll((bool)ChkBox_TaskScheduler_IgnoreCompleted.IsChecked);
            DG_TaskScheduler_Tasks.ItemsSource = _taskListCol;
            CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Filter = TaskItemFilter;
        }

        private void TB_TaskScheduler_JobNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            if (_taskListCol != null)
                this._tiDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_TaskScheduler_JobNameFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            if (_taskListCol != null)
                this._tiDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
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

        private void BTN_TaskScheduler_AssignYourselfButton_Click(object sender, RoutedEventArgs e)
        {
            TB_TaskScheduler_AssignedToFilter.Text = _curUserTwo.DomainUserName;
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

        private void BTN_TaskScheduler_DateFilterDateLeft_Click(object sender, RoutedEventArgs e)
        {
            if (TB_TaskScheduler_MonthDisplay.Text != "")
                _taskItemsToggleMonth = _taskItemsToggleMonth.AddMonths(-1);

            DateTime _startDay = new DateTime(_taskItemsToggleMonth.Year, _taskItemsToggleMonth.Month, 1);
            DateTime _endDay = _startDay.AddMonths(1).AddDays(-1);

            TB_TaskScheduler_MonthDisplay.Text = _taskItemsToggleMonth.ToString("MMMM yyyy");
            DP_TaskScheduler_DateFilter_StartDate.Text = _startDay.ToString();
            DP_TaskScheduler_DateFilter_EndDate.Text = _endDay.ToString();

            if (DG_TaskScheduler_Tasks.ItemsSource == null) return;
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            this._tiDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void BTN_TaskScheduler_DateFilterDateRight_Click(object sender, RoutedEventArgs e)
        {
            if (TB_TaskScheduler_MonthDisplay.Text != "")
                _taskItemsToggleMonth = _taskItemsToggleMonth.AddMonths(1);

            DateTime _startDay = new DateTime(_taskItemsToggleMonth.Year, _taskItemsToggleMonth.Month, 1);
            DateTime _endDay = _startDay.AddMonths(1).AddDays(-1);

            TB_TaskScheduler_MonthDisplay.Text = _taskItemsToggleMonth.ToString("MMMM yyyy");
            DP_TaskScheduler_DateFilter_StartDate.Text = _startDay.ToString();
            DP_TaskScheduler_DateFilter_EndDate.Text = _endDay.ToString();

            if (DG_TaskScheduler_Tasks.ItemsSource == null) return;
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            this._tiDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void DP_TaskScheduler_DateFilter_StartDate_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (DG_TaskScheduler_Tasks.ItemsSource == null) return;
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            this._tiDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void DP_TaskScheduler_DateFilter_EndDate_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (DG_TaskScheduler_Tasks.ItemsSource == null) return;
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            this._tiDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_TaskScheduler_DivisionFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_TaskScheduler_Tasks.ItemsSource == null) return;
            if (this._tiDa == null)
            {
                this._tiDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Refresh());
            }
            this._tiDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void BTN_TaskScheduler_ClearSearch_Click(object sender, RoutedEventArgs e)
        {
            if (DG_TaskScheduler_Tasks.ItemsSource != null)
            {
                CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Filter = null;
            }
            TB_TaskScheduler_JobNumberFilter.Text = "";
            TB_TaskScheduler_JobNameFilter.Text = "";
            TB_TaskScheduler_AssignedFromFilter.Text = "";
            TB_TaskScheduler_AssignedToFilter.Text = "";
            TB_TaskScheduler_TaskFilter.Text = "";
            TB_TaskScheduler_AreaFilter.Text = "";
            TB_TaskScheduler_MonthDisplay.Text = "";
            DP_TaskScheduler_DateFilter_StartDate.Text = "";
            DP_TaskScheduler_DateFilter_EndDate.Text = "";
            TB_TaskScheduler_DivisionFilter.Text = "";
            _taskItemsToggleMonth = DateTime.Now;
            if (DG_TaskScheduler_Tasks.ItemsSource != null)
                CollectionViewSource.GetDefaultView(DG_TaskScheduler_Tasks.ItemsSource).Filter = TaskItemFilter;
        }

        private bool TaskItemFilter(object tsi)
        {
            var _taskSchedulerItem = (pm.TaskSchedulerItem)tsi;
            DateTime? dt = _taskSchedulerItem.StartDate;

            if (DP_TaskScheduler_DateFilter_StartDate.Text == "" || DP_TaskScheduler_DateFilter_EndDate.Text == "")
            {
                return (_taskSchedulerItem.JobNumber.IndexOf(TB_TaskScheduler_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.JobName.IndexOf(TB_TaskScheduler_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.AssignedByName.IndexOf(TB_TaskScheduler_AssignedFromFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.AssignedToName.IndexOf(TB_TaskScheduler_AssignedToFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.TaskTypeName.IndexOf(TB_TaskScheduler_TaskFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.Area.IndexOf(TB_TaskScheduler_AreaFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.Division.IndexOf(TB_TaskScheduler_DivisionFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0);
            }
            else
            {
                return (_taskSchedulerItem.JobNumber.IndexOf(TB_TaskScheduler_JobNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.JobName.IndexOf(TB_TaskScheduler_JobNameFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.AssignedByName.IndexOf(TB_TaskScheduler_AssignedFromFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.AssignedToName.IndexOf(TB_TaskScheduler_AssignedToFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.TaskTypeName.IndexOf(TB_TaskScheduler_TaskFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _taskSchedulerItem.Area.IndexOf(TB_TaskScheduler_AreaFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0)
                        && _taskSchedulerItem.Division.IndexOf(TB_TaskScheduler_DivisionFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && dt >= Convert.ToDateTime(DP_TaskScheduler_DateFilter_StartDate.Text)
                        && dt <= Convert.ToDateTime(DP_TaskScheduler_DateFilter_EndDate.Text);
            }
        }

        private void BTN_TaskScheduler_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            //ExcelConverters.ExcelExporter.DatabaseToExcel(exc.ReportName.WarehouseReceiptsAll, _curUserTwo);
            ExcelConverters.ExcelExporter.DatabaseToExcel(exc.ReportName.TaskSchedulerItemsAll, _curUserTwo);
        }

        //private void _calendar_DisplayModeChanged(object sender, CalendarModeChangedEventArgs e)
        //{
        //    if (CDR_TaskScheduler_SelectMonth.DisplayMode == CalendarMode.Month)
        //        CDR_TaskScheduler_SelectMonth.DisplayMode = CalendarMode.Year;
        //}


        #endregion

        #region Ordering


        private void BTN_Ordering_Hardware_GetJobList_Click(object sender, RoutedEventArgs e)
        {
            OrderingHwByJobSelect _orderJobSelWin = new OrderingHwByJobSelect(this, DG_Ordering_HardwareOrdering_SelectableHardwareList);
            _orderJobSelWin.Owner = this;
            _orderJobSelWin.ShowDialog();
        }


        private void BTN_Ordering_Hardware_GetJobList_Titan_Click(object sender, RoutedEventArgs e)
        {
            OrderingSelectJobHardwareTitan _orderJobSelWin = new OrderingSelectJobHardwareTitan(this, DG_Ordering_HardwareOrdering_SelectableHardwareList, HdwDoorFrameSelect.Hardware);
            _orderJobSelWin.Owner = this;
            _orderJobSelWin.ShowDialog();
        }

        private void BTN_Ordering_Frames_GetJobList_Titan_Click(object sender, RoutedEventArgs e)
        {
            OrderingSelectJobHardwareTitan _orderJobSelWin = new OrderingSelectJobHardwareTitan(this, DG_Ordering_HardwareOrdering_SelectableHardwareList, HdwDoorFrameSelect.Frame);
            _orderJobSelWin.Owner = this;
            _orderJobSelWin.ShowDialog();
        }

        private void BTN_Ordering_Doors_GetJobList_Titan_Click(object sender, RoutedEventArgs e)
        {
            OrderingSelectJobHardwareTitan _orderJobSelWin = new OrderingSelectJobHardwareTitan(this, DG_Ordering_HardwareOrdering_SelectableHardwareList, HdwDoorFrameSelect.Door);
            _orderJobSelWin.Owner = this;
            _orderJobSelWin.ShowDialog();
        }

        #endregion


        #region Purchase Orders

        private void BTN_PO_PurchaseOrders_GetAllPoLines_Click(object sender, RoutedEventArgs e)
        {
            //System.Diagnostics.Stopwatch asdf = new System.Diagnostics.Stopwatch();
            //asdf.Start();
            this.IsEnabled = false;
            try
            {
                List<dc.PurchaseOrderLineItem> _poList = null;
                if ((bool)ChkBox_PO_PurchaseOrders_MaxOneYear.IsChecked)
                {
                    if (GlobalVars.CurrentGpDatabaseName == "UCSH")
                    {
                        dc.PoListFunctionLimitYear objContext = new dc.PoListFunctionLimitYear(GlobalVars.GpConnectionString);
                        _poList = objContext.ConnectsPoLineTestAllJobs().ToList();
                    }
                    else if (GlobalVars.CurrentGpDatabaseName == "UBC")
                    {
                        dc.PoListFunctionLimitYearUBC objContext = new dc.PoListFunctionLimitYearUBC(GlobalVars.GpConnectionString);
                        _poList = objContext.ConnectsPoLineTestAllJobs().ToList();
                    }
                    //Add in logic for test UCSH later

                }
                else
                {
                    if (GlobalVars.CurrentGpDatabaseName == "UCSH")
                    {
                        dc.PoListFunctionV1 objContext = new dc.PoListFunctionV1(GlobalVars.GpConnectionString);
                        _poList = objContext.ConnectsPoLineTestAllJobs().ToList();
                    }
                    else if (GlobalVars.CurrentGpDatabaseName == "UBC")
                    {
                        dc.PoListFunctionV1UBC objContext = new dc.PoListFunctionV1UBC(GlobalVars.GpConnectionString);
                        _poList = objContext.ConnectsPoLineTestAllJobs().ToList();
                    }

                }

                _poCol = new ObservableCollection<dc.PurchaseOrderLineItem>(_poList);
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
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.PurchaseOrderAll, _curUserTwo);
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

        private void BTN_PO_PurchaseOrders_LaunchJobFolder(object sender,  MouseButtonEventArgs e)
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
            if (cell != null && !cell.IsEditing )        //(cell != null && !cell.IsEditing && !cell.IsReadOnly) - old, remvoed the negation check on the readonly property of the cell
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
                            if (cell.Column.DisplayIndex == 25)
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
                            if (cell.Column.DisplayIndex == 25)
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
                            if (cell.Column.DisplayIndex == 26)
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
                            if (cell.Column.DisplayIndex == 26)
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

        #region SOP POP Link

        private void BTN_SopLink_RefreshList_Click(object sender, RoutedEventArgs e)
        {
            if ((bool)ChkBox_SopLink_IncludeHistorical.IsChecked)
                _sopPopList = dc.SopLinksV2s.GetAllSopLinkV2Lines();
            else
                _sopPopList = dc.SopLinksV2s.GetOpenSopLinkV2Lines();
            SopLink_DG_SopPopLinkLines.ItemsSource = _sopPopList;
            CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Filter = SopLinkFilter;

        }

        private void BTN_SopLink_ClearSearch_Click(object sender, RoutedEventArgs e)
        {
            CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Filter = null;
            TB_SopLink_PoFilter.Text = null;
            TB_SopLink_SopFilter.Text = null;
            TB_SopLink_ItemDescription.Text = null;
            TB_SopLink_BuyerId.Text = null;
            TB_SopLink_CustomerName.Text = null;
            TB_SopLink_RackLocation.Text = null;
            TB_SopLink_PhoneNumberFilter.Text = null;
            CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Filter = SopLinkFilter;
        }

        private void TB_SopLink_PoFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_SopLink_SopFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_SopLink_ItemDescription_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_SopLink_BuyerId_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_SopLink_CustomerName_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_SopLink_RackLocation_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void BTN_SopLink_AssignYourselfButton_Click(object sender, RoutedEventArgs e)
        {
            TB_SopLink_BuyerId.Text = _curUserTwo.DomainUserName;
        }

        private void BTN_SopLink_DateFilterDateLeft_Click(object sender, RoutedEventArgs e)
        {
            //_sopLinkToggleMonth
            if (TB_SopLink_MonthDisplay.Text != "")
                _sopLinkToggleMonth = _sopLinkToggleMonth.AddMonths(-1);

            DateTime _startDay = new DateTime(_sopLinkToggleMonth.Year, _sopLinkToggleMonth.Month, 1);
            DateTime _endDay = _startDay.AddMonths(1).AddDays(-1);

            TB_SopLink_MonthDisplay.Text = _sopLinkToggleMonth.ToString("MMMM yyyy");
            DP_SopLink_DateFilter_StartDate.Text = _startDay.ToString();
            DP_SopLink_DateFilter_EndDate.Text = _endDay.ToString();

            if (SopLink_DG_SopPopLinkLines.ItemsSource == null) return;
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void BTN_SopLink_DateFilterDateRight_Click(object sender, RoutedEventArgs e)
        {
            if (TB_SopLink_MonthDisplay.Text != "")
                _sopLinkToggleMonth = _sopLinkToggleMonth.AddMonths(1);

            DateTime _startDay = new DateTime(_sopLinkToggleMonth.Year, _sopLinkToggleMonth.Month, 1);
            DateTime _endDay = _startDay.AddMonths(1).AddDays(-1);

            TB_SopLink_MonthDisplay.Text = _sopLinkToggleMonth.ToString("MMMM yyyy");
            DP_SopLink_DateFilter_StartDate.Text = _startDay.ToString();
            DP_SopLink_DateFilter_EndDate.Text = _endDay.ToString();

            if (SopLink_DG_SopPopLinkLines.ItemsSource == null) return;
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void DP_SopLink_DateFilter_StartDate_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {   
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void DP_SopLink_DateFilter_EndDate_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_SopLink_PhoneNumberFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._sopLinkDa == null)
            {
                this._sopLinkDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(SopLink_DG_SopPopLinkLines.ItemsSource).Refresh());
            }
            if (_sopPopList != null)
                this._sopLinkDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private bool SopLinkFilter(object sopLinkLine)
        {
            var _sopObj = (dc.SopLinkV2)sopLinkLine;
            //DateTime? dt = _sopObj.DateCreated; //THIS FIELD CANNOT BE NULL

            return (_sopObj.PoNumber.IndexOf(TB_SopLink_PoFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                && _sopObj.SopNumber.IndexOf(TB_SopLink_SopFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                && _sopObj.ItemDescription.IndexOf(TB_SopLink_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
                && _sopObj.BuyerId.IndexOf(TB_SopLink_BuyerId.Text, StringComparison.OrdinalIgnoreCase) >= 0
                && _sopObj.CustomerName.IndexOf(TB_SopLink_CustomerName.Text, StringComparison.OrdinalIgnoreCase) >= 0
                && _sopObj.RackLocation.IndexOf(TB_SopLink_RackLocation.Text, StringComparison.OrdinalIgnoreCase) >= 0
                && _sopObj.PhoneNumber.IndexOf(TB_SopLink_PhoneNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                );

            //if (DP_SopLink_DateFilter_StartDate.Text == "" || DP_SopLink_DateFilter_EndDate.Text == "")
            //{
            //    return (_sopObj.PoNumber.IndexOf(TB_SopLink_PoFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.SopNumber.IndexOf(TB_SopLink_SopFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.ItemDescription.IndexOf(TB_SopLink_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.BuyerId.IndexOf(TB_SopLink_BuyerId.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.CustomerName.IndexOf(TB_SopLink_CustomerName.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.RackLocation.IndexOf(TB_SopLink_RackLocation.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.PhoneNumber.IndexOf(TB_SopLink_PhoneNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        );
            //}
            //else
            //{

            //    return (_sopObj.PoNumber.IndexOf(TB_SopLink_PoFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.SopNumber.IndexOf(TB_SopLink_SopFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.ItemDescription.IndexOf(TB_SopLink_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.BuyerId.IndexOf(TB_SopLink_BuyerId.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.CustomerName.IndexOf(TB_SopLink_CustomerName.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.RackLocation.IndexOf(TB_SopLink_RackLocation.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && _sopObj.PhoneNumber.IndexOf(TB_SopLink_PhoneNumberFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
            //        && dt >= Convert.ToDateTime(DP_SopLink_DateFilter_StartDate.Text)
            //        && dt <= Convert.ToDateTime(DP_SopLink_DateFilter_EndDate.Text)
            //        );
                
            //}

        }

        private void SopLink_DG_SopPopLinkLines_CellEditEnding(object sender, DataGridCellEditEndingEventArgs e)
        {
            dc.SopLinkV2 _selItem = (dc.SopLinkV2)e.Row.Item;
            if (!_selItem.HasLinkTableLines)
            {
                if (!dc.SopLinksV2s.AddSopLink(_selItem))
                    MessageBox.Show("Add new link line information failed.");
                else
                {
                    _selItem.HasLinkTableLines = true;
                    _selItem.LinkTableDataEdited = false;
                }
            }
            else if (_selItem.HasLinkTableLines && _selItem.LinkTableDataEdited)
            {
                if (!dc.SopLinksV2s.UpdateSopLink(_selItem))
                    MessageBox.Show("Updating of line failed.");
                else
                    _selItem.LinkTableDataEdited = false;
            }
        }

        private void Cbox_SopList_ItemStatus_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            dc.SopLinkV2 _selItem = (dc.SopLinkV2)((ComboBox)sender).DataContext;
            if (!_selItem.HasLinkTableLines)
            {
                if (!dc.SopLinksV2s.AddSopLink(_selItem))
                    MessageBox.Show("Add new link line information failed.");
                else
                {
                    _selItem.HasLinkTableLines = true;
                    _selItem.LinkTableDataEdited = false;
                }
            }
            else if (_selItem.HasLinkTableLines && _selItem.LinkTableDataEdited)
            {
                if (!dc.SopLinksV2s.UpdateSopLink(_selItem))
                    MessageBox.Show("Updating of line failed.");
                else
                    _selItem.LinkTableDataEdited = false;
            }
        }

        #endregion

        #region Users Events

        private void UsersTab_DG_Users_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (UsersTab_DG_Users.SelectedIndex != -1)
            {
                dc.User _selUser = (dc.User)UsersTab_DG_Users.SelectedItem;
                TransferModifyUserMenu _transUser = new TransferModifyUserMenu(UsersTab_DG_Users, _selUser, _userObCol);
                _transUser.Owner = this;
                _transUser.ShowDialog();
            }
        }

        private void BTN_Users_AddUser_Click(object sender, RoutedEventArgs e)
        {
            TransferAddUserMenu _transUser = new TransferAddUserMenu(UsersTab_DG_Users, _userObCol);
            _transUser.Owner = this;
            _transUser.ShowDialog();
        }

        private void BTN_RefreshJobFolderLinks_Click(object sender, RoutedEventArgs e)
        {
            dc.UtilityMethods.CheckLinksJobFolders.GetFolders();
        }

        private void BTN_Users_ChangeOrderSessions_Click(object sender, RoutedEventArgs e)
        {
            UsersChangeSessions _sessionWin = new UsersChangeSessions();
            _sessionWin.Owner = this;
            _sessionWin.ShowDialog();
        }

        private void BTN_Users_TestApi_Click(object sender, RoutedEventArgs e)
        {
            //RestClient rClient = new RestClient();
            //rClient.endPoint = "https://ucsh.protechtitan.com/titan/api";
            //rClient.authTech = autheticationTechnique.RollYourOwn;
            //rClient.authType = authenticationType.Basic;
            //rClient.userName = "davep@ucsh.com";
            //rClient.userPassword = "Warden7100";

            ////debugOutput("Rest Client Created");

            //string strResponse = string.Empty;

            //strResponse = rClient.makeRequest();

            //debugOutput(strResponse);

            //HttpClient client = new HttpClient();
            //client.BaseAddress = new Uri("https://ucsh.protechtitan.com/titan/api");
            //HttpResponseMessage response = client.GetAsync("serverlist.php").Result;
            //if (response.IsSuccessStatusCode)
            //{
            //    string result = response.Content.ReadAsStringAsync().Result;
            //    //var obj = System.Text.Json.JsonSerializer.Deserialize<ServerModel>(result);
            //}
            //client.Dispose();
        }

        private async void BTN_Users_TestApiTwo_Click(object sender, RoutedEventArgs e)
        {
            //TestAccess _testAccess = new TestAccess();
            //TitanProject tp = new TitanProject();
            //object asdf = await _testAccess.TestMethod(tp);
            //^this works, leave it alone


            //EConnect.PopTransaction.RunPoCreate();

            TitanApi.GetProject.GetProjectById(20);
        }

        #endregion

        #region Hollow Metal Events


        private void BTN_HollowMetal_OpeningHwWindow_Click(object sender, RoutedEventArgs e)
        {

        }

        private void TB_HW_ShopDrawings_OpeningNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hmSdDa == null)
            {
                this._hmSdDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(HollowMetal_DG_ShopDrawings.ItemsSource).Refresh());
            }
            this._hmSdDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void BTN_HollowMetal_ShopDrawings_RetrieveJob_Click(object sender, RoutedEventArgs e)
        {
            HmGetShopDrawByJobPopUp _hmPopUp = new HmGetShopDrawByJobPopUp(this, HollowMetal_DG_ShopDrawings);
            _hmPopUp.Owner = this;
            _hmPopUp.ShowDialog();
            if (HollowMetal_DG_ShopDrawings.ItemsSource != null)
            {
                _hmShopDraw = (ObservableCollection<dc.ShopDrawingLine>)HollowMetal_DG_ShopDrawings.ItemsSource;
                CollectionViewSource.GetDefaultView(HollowMetal_DG_ShopDrawings.ItemsSource).Filter = ShopDrawingFilter;
            }
        }

        private bool ShopDrawingFilter(object sd)
        {
            var _sdObject = (dc.ShopDrawingLine)sd;
            return (_sdObject.OpeningNum.IndexOf(TB_HW_ShopDrawings_OpeningNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0);
        }

        #endregion



        #region Hardware Events

        //---------- Hardware Schedule

        private void BTN_Hardware_HardwareSchedules_ClearFilters_Click(object sender, RoutedEventArgs e)
        {
            CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource).Filter = null;
            CollectionView cv = (CollectionView)CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource);
            //cv.GroupDescriptions.Clear();
            //PropertyGroupDescription pgd = new PropertyGroupDescription("OpeningNumber");
            //cv.GroupDescriptions.Add(pgd);

            TB_HW_HardwareSchedules_OpeningNumber.Text = null;
            TB_HW_HardwareSchedules_ItemDescription.Text = null;
            TB_HW_HardwareSchedules_Vendor.Text = null;
            CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource).Filter = MainProjFilter;
        }

        private void TB_HW_HardwareSchedules_OpeningNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwHsDa == null)
            {
                this._hwHsDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource).Refresh());
            }
            this._hwHsDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }


        private void TB_HW_HardwareSchedules_ItemDescription_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwHsDa == null)
            {
                this._hwHsDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource).Refresh());
            }
            this._hwHsDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        private void TB_HW_HardwareSchedules_Vendor_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (this._hwHsDa == null)
            {
                this._hwHsDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource).Refresh());
            }
            this._hwHsDa.Defer(new TimeSpan(0, 0, 0, 1, 100));
        }

        //private void BTN_Hardware_HardwareSchedules_RetrieveJob_Click(object sender, RoutedEventArgs e)
        //{
        //    //_hwSchedule
        //    HwGetHardwareSchedByJobPopUp _hwPopUp = new HwGetHardwareSchedByJobPopUp(this, Hardware_DG_HardwareSchedule);
        //    _hwPopUp.Owner = this;  
        //    _hwPopUp.ShowDialog();
        //    if (Hardware_DG_HardwareSchedule.ItemsSource != null)
        //    {
        //        _hwSchedule = (ObservableCollection<dc.HardwareSchedule>)Hardware_DG_HardwareSchedule.ItemsSource;
        //        //cv = (CollectionView)CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource);
        //        //cv.GroupDescriptions.Clear();
        //        //PropertyGroupDescription pgd = new PropertyGroupDescription("OpeningNumber");
        //        //cv.GroupDescriptions.Add(pgd);

        //        _hwOpenView = new ListCollectionView(_hwSchedule);
        //        _hwOpenView.GroupDescriptions.Add(new PropertyGroupDescription("OpeningNumber"));

        //        CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource).Filter = HardwareScheduleOrderFilter;
        //    }
        //}

        private void BTN_Hardware_ExportCommissionSheetsToExcel_Click(object sender, RoutedEventArgs e)
        {
            if (_hwSelectedJobNum < 1)
                MessageBox.Show("No job selected.");
            else
            {
                if (MessageBox.Show("This process may take several minutes, do you wish to proceed?", "Prompt",  MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    ExcelConverters.ExportCommissionSheets.GenerateCommSheets(_hwSelectedJobNum);
            }
        }

        private void BTN_Hardware_HardwareSchedules_RetrieveJob_Click(object sender, RoutedEventArgs e)
        {
            HwGetHardwareSchedByJobPopUp _hwPopUp = new HwGetHardwareSchedByJobPopUp(this, ref _hwSchedule);
            _hwPopUp.Owner = this;
            _hwPopUp.ShowDialog();
            _hwSchedule = _hwPopUp.HwSchedule;
            if (_hwSchedule != null)
            {
                Hardware_DG_HardwareSchedule.ItemsSource = _hwSchedule;
                CollectionView cv = (CollectionView)CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource);
                cv.GroupDescriptions.Clear();
                PropertyGroupDescription pgd = new PropertyGroupDescription("OpeningNumber");
                cv.GroupDescriptions.Add(pgd);
                //pgd = new PropertyGroupDescription("Manufacturer");
                //cv.GroupDescriptions.Add(pgd);    

                CollectionViewSource.GetDefaultView(Hardware_DG_HardwareSchedule.ItemsSource).Filter = HardwareScheduleOrderFilter;
            }
        }

        private bool HardwareScheduleOrderFilter(object hw)
        {
            var _hwObject = (dc.HardwareSchedule)hw;
            string _openNum = _hwObject.OpeningNumber ?? "";

            return (_openNum.IndexOf(TB_HW_HardwareSchedules_OpeningNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _hwObject.ProductHash.IndexOf(TB_HW_HardwareSchedules_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    && _hwObject.Manufacturer.IndexOf(TB_HW_HardwareSchedules_Vendor.Text, StringComparison.OrdinalIgnoreCase) >= 0
                    );
        }

        //----------

        #endregion

        #region Warehouse Events

        #region Receiving View

        private void BTN_Warehouse_ViewReceipts_RefreshList_Click(object sender, RoutedEventArgs e)
        {
            TB_Warehouse_ViewReceipts_RackLocationFilter.Text = "";
            TB_Warehouse_ViewReceipts_JobNumber.Text = "";
            TB_Warehouse_ViewReceipts_JobName.Text = "";
            TB_Warehouse_ViewReceipts_ItemDescription.Text = "";
            TB_Warehouse_ViewReceipts_PoNumber.Text = "";
            TB_Warehouse_ViewReceipts_SopNumber.Text = "";
            TB_Warehouse_ViewReceipts_BuyerId.Text = "";
            DP_Warehouse_ViewReceipts_ReceiveDate.Text = "";
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource != null)
            {
                CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Filter = null;
            }
            
            _whViewRecLineCol = dc.WhReceivingLines.GetPoRecLinesWithUcshRecLines(null, (bool)ChkBox_Warehouse_ViewReceipts_MaxOneYear.IsChecked);
            DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource = _whViewRecLineCol;
            CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Filter = WhReceivingsViewFilter;
        }

        private void BTN_Warehouse_ViewReceipts_GeneratePreShipmentDocument(object sender, RoutedEventArgs e)
        {
            dc.ReceivingLine _selRec = (dc.ReceivingLine)((Button)e.Source).DataContext;
            dc.CombinedProject _selProj = dc.MainProjects.GetSingleProject(_selRec.JobNumber);
            dc.PurchaseOrderHeader _poHeader = dc.PurchaseOrderHeaders.GetPoHeaderSingle(_selRec.PoNumber);
            ObservableCollection<dc.ReceivingLine> _recLines = dc.WhReceivingLines.GetPoReceivingLineItemsByPoNum(_selRec.PoNumber, false);

            WhRecsBlankLinesShippingMemo _recShipMemoWin = new WhRecsBlankLinesShippingMemo();
            _recShipMemoWin.ShowDialog();
            _recShipMemoWin.Owner = this;

            if (_recShipMemoWin.CanProceed)
                WordConverters.ExportReceiptsPoHeaderBlankLines.CreateShipmentDocument(_poHeader, _selProj, _recShipMemoWin.LineCount);



        }

        private void BTN_Warehouse_ViewReceipts_UpdateRackLocations_Click(object sender, RoutedEventArgs e)
        {
            if (TB_Warehouse_ViewReceipts_RackLocationFilter.Text == "" ||
                TB_Warehouse_ViewReceipts_PoNumber.Text.Length < 5 ||
                TB_Warehouse_ViewReceipts_UpdateRackLocations.Text == "")
            { 
                MessageBox.Show("Must have a purchase order filter with at least 5 characters entered, and old rack location filter entered and a new rack location" +
                                "set before a rack location renaming operation can be done.");
            }
            else
            {
                ICollectionView _colView = CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource);
                List<dc.ReceivingLine> _filteredItems = _colView.Cast<dc.ReceivingLine>().ToList();
                string _newRackLocation = TB_Warehouse_ViewReceipts_UpdateRackLocations.Text.Trim();
                for (int i = 0; i < _filteredItems.Count(); i++)
                {
                    _filteredItems[i].Location = _newRackLocation;
                }
                dc.WhReceivingLines.UpdateReceivingLines(new ObservableCollection<dc.ReceivingLine>(_filteredItems));
                DG_Warehouse_ViewReceipts_ReceiptList.Items.Refresh();
            }
        }

        private void BTN_Warehouse_ViewReceipts_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(exc.ReportName.WarehouseReceiptsAll, _curUserTwo);
        }

        private void BTN_Warehouse_ViewReceipts_ClearSearch_Click(object sender, RoutedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource != null)
            {
                CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Filter = null;
            }
            TB_Warehouse_ViewReceipts_RackLocationFilter.Text = "";
            TB_Warehouse_ViewReceipts_JobNumber.Text = "";
            TB_Warehouse_ViewReceipts_JobName.Text = "";
            TB_Warehouse_ViewReceipts_ItemDescription.Text = "";
            TB_Warehouse_ViewReceipts_PoNumber.Text = "";
            TB_Warehouse_ViewReceipts_SopNumber.Text = "";
            TB_Warehouse_ViewReceipts_BuyerId.Text = "";
            DP_Warehouse_ViewReceipts_ReceiveDate.Text = "";
            CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Filter = WhReceivingsViewFilter;
        }


        private void TB_Warehouse_ViewReceipts_RackLocationFilter_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewReceipts_JobNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewReceipts_JobName_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewReceipts_ItemDescription_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewReceipts_PoNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewReceipts_SopNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewReceipts_BuyerId_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void DP_Warehouse_ViewReceipts_ReceiveDate_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource == null) return;
            if (this._whRecDa == null)
            {
                this._whRecDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewReceipts_ReceiptList.ItemsSource).Refresh());
            }
            this._whRecDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private bool WhReceivingsViewFilter(object recLine)
        {
            var _recLineObject = (dc.ReceivingLine)recLine;
            DateTime? dt = _recLineObject.DateReceived;

            if (DP_Warehouse_ViewReceipts_ReceiveDate.Text == "")
            {
                return (_recLineObject.JobNumber.IndexOf(TB_Warehouse_ViewReceipts_JobNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.JobName.IndexOf(TB_Warehouse_ViewReceipts_JobName.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.PoNumber.IndexOf(TB_Warehouse_ViewReceipts_PoNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.SopNumber.IndexOf(TB_Warehouse_ViewReceipts_SopNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.BuyerId.IndexOf(TB_Warehouse_ViewReceipts_BuyerId.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.ItemDescription.IndexOf(TB_Warehouse_ViewReceipts_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.Location.IndexOf(TB_Warehouse_ViewReceipts_RackLocationFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        );
            }
            else
            {
                return (_recLineObject.JobNumber.IndexOf(TB_Warehouse_ViewReceipts_JobNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.JobName.IndexOf(TB_Warehouse_ViewReceipts_JobName.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.PoNumber.IndexOf(TB_Warehouse_ViewReceipts_PoNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.SopNumber.IndexOf(TB_Warehouse_ViewReceipts_SopNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.BuyerId.IndexOf(TB_Warehouse_ViewReceipts_BuyerId.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.ItemDescription.IndexOf(TB_Warehouse_ViewReceipts_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.Location.IndexOf(TB_Warehouse_ViewReceipts_RackLocationFilter.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && String.Format("{0:M/dd/yy}", dt) == DP_Warehouse_ViewReceipts_ReceiveDate.Text
                        );
            }
        }

        private void DG_Warehouse_ViewReceipts_ReceiptList_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_Warehouse_ViewReceipts_ReceiptList.SelectedIndex != -1)
            {
                dc.ReceivingLine _selLine = (dc.ReceivingLine)DG_Warehouse_ViewReceipts_ReceiptList.SelectedItem;
                WhRecLinesPopUpWindow _whRecLinePopUpWin = new WhRecLinesPopUpWindow(DG_Warehouse_CreateReceipts_RecLineList, ref _selLine);
                _whRecLinePopUpWin.Owner = this;
                _whRecLinePopUpWin.ShowDialog();
            }
        }

        #endregion

        #region Receiving Create
        //Receiving

        private void BTN_Warehouse_CreateReceipts_PopulateReceipts_Click(object sender, RoutedEventArgs e)
        {
            if (_whPoRecCol.Count != 0)
            {
                foreach (dc.ReceivingLine rec in _whPoRecCol)
                    rec.QtyRecForGp = rec.QtyOrdFromGp;
            }
            DG_Warehouse_CreateReceipts_RecLineList.Items.Refresh();
        }

        private void BTN_Warehouse_CreateReceipts_CopyDownLocation_Click(object sender, RoutedEventArgs e)
        {
            if (_whPoRecCol != null)
            {
                for (int x = 0; x < _whPoRecCol.Count; x++)
                {
                    _whPoRecCol[x].Location = TB_Warehouse_CreateReceipts_LineItemLocationCopy.Text;
                }
                DG_Warehouse_CreateReceipts_RecLineList.Items.Refresh();
            }
        }

        private void BTN_Warehouse_CreateReceipts_ZeroAllRecQuantities_Click(object sender, RoutedEventArgs e)
        {
            if (MessageBox.Show("Would you like to set all the received quantities to 0?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
            {
                if (_whPoRecCol != null)
                {
                    for (int x = 0; x < _whPoRecCol.Count; x++)
                    {
                        _whPoRecCol[x].QtyRecForGp = 0;
                    }
                    DG_Warehouse_CreateReceipts_RecLineList.Items.Refresh();
                }
            }
        }

        private void BTN_Warehouse_CreateReceipts_DeleteZeroRecQuantities_Click(object sender, RoutedEventArgs e)
        {
            if (MessageBox.Show("Would you like to remove all the line items with a receiving quantity of 0?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
            {
                if (_whPoRecCol != null)
                {
                    for (int x = _whPoRecCol.Count - 1; x >= 0; x--)
                    {
                        if (_whPoRecCol[x].QtyRecForGp == 0)
                            _whPoRecCol.Remove(_whPoRecCol[x]);
                    }
                    DG_Warehouse_CreateReceipts_RecLineList.Items.Refresh();
                }
            }
        }

        private void BTN_Warehouse_CreateReceipts_GetPoList_Click(object sender, RoutedEventArgs e)
        {
            bool _excludeComplete = (bool)ChkBox_Warehouse_CreateReceipts_HideFullReceivedLines.IsChecked;
            _whType = WarehouseReceiptType.PurchaseOrder;
            WhRecSelectPo _poHeaderWindow = new WhRecSelectPo(_whPoRecCol, DG_Warehouse_CreateReceipts_RecLineList, _excludeComplete);
            _poHeaderWindow.Owner = this;
            _poHeaderWindow.ShowDialog();
            if (_whPoRecCol != null && _whPoRecCol.Count > 0)
            {
                LBL_Warehouse_CreateReceipts_JobSopNumber.Content = _whPoRecCol[0].JobNumber;
                LBL_Warehouse_CreateReceipts_JobName.Content = _whPoRecCol[0].JobName;
                if (_poHeaderWindow.DeficiencyCheck)
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Visible;
                else
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Hidden;
            }
        }

        private void BTN_Warehouse_CreateReceipts_GetPoListSopList_Click(object sender, RoutedEventArgs e)
        {
            bool _excludeComplete = (bool)ChkBox_Warehouse_CreateReceipts_HideFullReceivedLines.IsChecked;
            _whType = WarehouseReceiptType.RetailOrder;
            WhRecSelectPoSop _poSopWindow = new WhRecSelectPoSop(_whPoRecCol, DG_Warehouse_CreateReceipts_RecLineList, _excludeComplete);
            _poSopWindow.Owner = this;
            _poSopWindow.ShowDialog();
            if (_whPoRecCol != null && _whPoRecCol.Count > 0)
            {
                LBL_Warehouse_CreateReceipts_JobSopNumber.Content = _whPoRecCol[0].SopNumber;
                LBL_Warehouse_CreateReceipts_JobName.Content = _whPoRecCol[0].JobName;
                if (_poSopWindow.DeficiencyCheck)
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Visible;
                else
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Hidden;
            }
        }

        private void BTN_Warehouse_CreateReceipts_GetPoListShowroom_Click(object sender, RoutedEventArgs e)
        {
            bool _excludeComplete = (bool)ChkBox_Warehouse_CreateReceipts_HideFullReceivedLines.IsChecked;
            _whType = WarehouseReceiptType.Showroom;
            WhRecSelectPoShowroom _poSopWindow = new WhRecSelectPoShowroom(_whPoRecCol, DG_Warehouse_CreateReceipts_RecLineList, _excludeComplete);
            _poSopWindow.Owner = this;
            _poSopWindow.ShowDialog();
            if (_whPoRecCol != null && _whPoRecCol.Count > 0)
            {
                LBL_Warehouse_CreateReceipts_JobSopNumber.Content = _whPoRecCol[0].SopNumber;
                LBL_Warehouse_CreateReceipts_JobName.Content = _whPoRecCol[0].JobName;
                if (_poSopWindow.DeficiencyCheck)
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Visible;
                else
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Hidden;
            }
        }

        private void BTN_Warehouse_CreateReceipts_GetPOListUnusual_Click(object sender, RoutedEventArgs e)
        {
            bool _excludeComplete = (bool)ChkBox_Warehouse_CreateReceipts_HideFullReceivedLines.IsChecked;
            _whType = WarehouseReceiptType.Unusual;
            WhRecSelectPoUnusual _poHeaderWindow = new WhRecSelectPoUnusual(_whPoRecCol, DG_Warehouse_CreateReceipts_RecLineList, _excludeComplete);
            _poHeaderWindow.Owner = this;
            _poHeaderWindow.ShowDialog();
            if (_whPoRecCol != null && _whPoRecCol.Count > 0)
            {
                LBL_Warehouse_CreateReceipts_JobSopNumber.Content = "";
                LBL_Warehouse_CreateReceipts_JobName.Content = "";
                if (_poHeaderWindow.DeficiencyCheck)
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Visible;
                else
                    LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies.Visibility = Visibility.Hidden;
            }


        }

        private void BTN_Warehouse_CreateReceipts_CommitRecLines_Click(object sender, RoutedEventArgs e)
        {

            //bool _eCcont = EConnect.PopRcptLineInsert.RunEconnect(ref _whPoRecCol);
            //bool _eCcont = EConnect.PopRcptLineInsertX.RunEconnectX(ref _whPoRecCol);
            //EConnect.PopEnterMatchInvLine.RunEconnect(ref _whPoRecCol);
            //Connect.PopEnterMatchInvLineNew.RunEconnect(ref _whPoRecCol);
            //EConnect.SupportProcedures.taPopRcptLandedCostOld.CreateLandedCosts(_whPoRecCol);

            var _poCount = _whPoRecCol.Where(x => x.QtyRecForGp > 0).Select(r => r.PoNumber).Distinct().Count();
            if (_poCount > 1) {
                MessageBox.Show("You're attempting to receive more than one PO at a time on this retail order. Operation terminating."); return;}

            

            BTN_Warehouse_CreateReceipts_CommitRecLines.IsEnabled = false;
            if (_whPoRecCol.Count > 0 && CheckRackFieldsForBlanksFullyReceived(_whPoRecCol))
            {
                /*
                IF YOU GET THE ERROR WHERE A PO RECEIPT GETS MADE IN GP BUT NOT CONNECTS, GO HERE AND CAREFULLY COPY THE CODE:
                P:\Documents\Matt Nash\06 MAJOR PROJECTS\PM10 - Project tracking program\ERROR CORRECTION
                */
                dc.UtilityMethods.RemoveNoQuantityPoReceipts.Removal(ref _whPoRecCol);
                if (_whPoRecCol.Count == 0) { MessageBox.Show("No lines have any quantities to receive on them"); BTN_Warehouse_CreateReceipts_CommitRecLines.IsEnabled = true; return; }
                bool _eCcont = EConnect.PopRcptLineInsert.RunEconnect(ref _whPoRecCol, _whType); //dc.WH_ReceivingLines.AddReceivingLines(_whPoRecCol); ;
                if (_eCcont)
                {
                    bool _cont = dc.WhReceivingLines.AddReceivingLines(_whPoRecCol);
                    if (!_cont)
                        dc.WhReceivingLines.DeleteReceivingLines(_whPoRecCol);
                    else
                    {
                        MessageBox.Show("Receipts successfully created in GP and in UCSH databases. Receipt number is: " + _whPoRecCol[0].PopRctNum);
                        if (_whPoRecCol[0].SopNumber == null || _whPoRecCol[0].SopNumber == "")
                        {
                            //EMAIL FUNCTIONALITY TURNED OFF SINCE THE MAIL SERVER HAS NOW MIGRATED TO THE CLOUD - 22 JUNE 2025
                            //OutlookConverters.OutlookGenerator _recEmail = new OutlookConverters.OutlookGenerator(_whPoRecCol[0]);
                        }
                    }

                    _whPoRecCol.Clear();
                }
            }
            BTN_Warehouse_CreateReceipts_CommitRecLines.IsEnabled = true;
        }


        private void BTN_Warehouse_CreateReceipts_ReportDeficiency_Click(object sender, RoutedEventArgs e)
        {
            if (_whPoRecCol.Count > 0)
            {
                dc.PurchaseOrderHeader _poHeader = dc.PurchaseOrderHeaders.GetPoHeaderSingle(_whPoRecCol[0].PoNumber);
                WhDeficiencyListWindow _whDefWin = new WhDeficiencyListWindow(_poHeader, ref LBL_Warehouse_CreateReceipts_NotifyIncompleteDeficiencies);
                _whDefWin.Owner = this;
                _whDefWin.ShowDialog();
            }
        }

        private void DataGridCell_PreviewMouseLeftButtonDownShipRec(object sender, MouseButtonEventArgs e)
        {
            DataGridCell cell = sender as DataGridCell;

            if (cell != null && !cell.IsEditing && !cell.IsReadOnly)
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
                            if (cell.Column.DisplayIndex == 15)
                            {
                                if (MessageBox.Show("Would you like to delete this item?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ReceivingLine _selItem = (dc.ReceivingLine)row.Item;
                                    _whPoRecCol.Remove(_selItem);
                                    //_sopDoc.LineItems.RemoveAt(row.GetIndex());
                                    DG_Warehouse_CreateShipments_ShipLines.Items.Refresh();
                                    //DG_Warehouse_ViewShipments_ShipmentList.Items.Refresh();
                                }
                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 15)
                            {
                                if (MessageBox.Show("Would you like to delete this item?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ReceivingLine _selItem = (dc.ReceivingLine)row.Item;
                                    _whPoRecCol.Remove(_selItem);
                                    //_sopDoc.LineItems.RemoveAt(row.GetIndex());
                                    DG_Warehouse_CreateShipments_ShipLines.Items.Refresh();
                                    //DG_Warehouse_ViewShipments_ShipmentList.Items.Refresh();
                                }
                            }
                        }

                        if (row != null && !row.IsSelected)
                        {
                            if (cell.Column.DisplayIndex == 13)
                            {
                                ObservableCollection<dc.PoUcshHeaderComment> _selItem = ((dc.ReceivingLine)row.Item).UcHeaderCommentCol;
                                //if (_selItem.UcHeaderHasComments)
                                //    _selItem.UcHeaderCommentCol = dc.PoUcshHeaderComments.GetPoUcshHeaderComments(_selItem.PoNumber);

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(_selItem.Cast<dc.Interfaces.IPoUcshComment>());
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 13)
                            {

                                ObservableCollection<dc.PoUcshHeaderComment> _selItem = ((dc.ReceivingLine)row.Item).UcHeaderCommentCol;
                                //if (_selItem.UcHeaderHasComments)
                                //    _selItem.UcHeaderCommentCol = dc.PoUcshHeaderComments.GetPoUcshHeaderComments(_selItem.PoNumber);

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(_selItem.Cast<dc.Interfaces.IPoUcshComment>());
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                        }

                        if (row != null && !row.IsSelected)
                        {
                            if (cell.Column.DisplayIndex == 14)
                            {

                                ObservableCollection<dc.PoUcshLineComment> _selItem = ((dc.ReceivingLine)row.Item).UcLineCommentCol;
                                //if (_selItem.UcLineHasComments)
                                //    _selItem.UcLineCommentCol = dc.PoUcshLineComments.GetPoUcshLineComments(_selItem.PoNumber, _selItem.Order);

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(_selItem);
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 14)
                            {

                                ObservableCollection<dc.PoUcshLineComment> _selItem = ((dc.ReceivingLine)row.Item).UcLineCommentCol;
                                //if (_selItem.UcLineHasComments)
                                //    _selItem.UcLineCommentCol = dc.PoUcshLineComments.GetPoUcshLineComments(_selItem.PoNumber, _selItem.Order);

                                PoAddNewUcshComment _poCommentWin = new PoAddNewUcshComment(_selItem);
                                _poCommentWin.Owner = this;
                                _poCommentWin.ShowDialog();

                            }
                        }
                    }
                }
            }
        }

        private bool CheckRackFieldsForBlanksFullyReceived(ObservableCollection<dc.ReceivingLine> whPoRecCol)
        {   
            foreach (dc.ReceivingLine rl in whPoRecCol)
            {
                if ((rl.Location == null || rl.Location == "") && rl.QtyRecForGp > 0)
                {
                    MessageBox.Show("Some rack locations have been left blank for the receiving lines.  Please ensure none of the 'Location' fields is left blank.");
                    return false;
                }
            }

            //quantityOrdered - quantityPrevOrderedGp
            bool _fullReceived = true;
            foreach (dc.ReceivingLine rl in whPoRecCol)
            {
                if ((rl.QtyOrdFromGp - rl.QtyCumulativePrevRecFromGp) != 0)
                    _fullReceived = false;
            }
            if (_fullReceived) { MessageBox.Show("PO has already been fully received; cannot commit anymore receipts."); return false; }

            return true;
        }

        private void Warehouse_ViewReceipts_CommitTagQuantities(object sender, RoutedEventArgs e)
        {
            dc.ReceivingLine _selRec = (dc.ReceivingLine)((Button)e.Source).DataContext;
            dc.TaggingLine _selTag = _selRec.TaggingLine;

            if (_selTag.OrigTaggedQuantity > (_selRec.QtyRecForGp - _selRec.TaggedQuantityCumulative))
            {
                MessageBox.Show("You can't tag more than was previously received (" + _selRec.QtyRecForGp + ") minus previously tagged (" + _selRec.TaggedQuantityCumulative + ")." +
                "Maximum tagged amount can be: " + (_selRec.QtyRecForGp - _selRec.TaggedQuantityCumulative));
                return;
            }

            bool _cont = dc.WhTaggingLines.AddTaggingLine(_selTag, _selRec.TaggedQuantityCumulative);
            if (_cont)
            {
                _selRec.TaggedQuantityCumulative += _selTag.OrigTaggedQuantity;
                _selTag.OrigTaggedQuantity = 0;
                _selTag.IsModified = false;
            }

        }



        #endregion

        #region Tagging

        private void BTN_Warehouse_ViewEditTags_Refresh_Click(object sender, RoutedEventArgs e)
        {
            //set textboxes to blank
            if (DG_Warehouse_ViewEditTags_TagList.ItemsSource != null)
            {
                CollectionViewSource.GetDefaultView(DG_Warehouse_ViewEditTags_TagList.ItemsSource).Filter = null;
            }
            _whTagViewEditCol = dc.WhTaggingLines.GetAllTagLines();
            DG_Warehouse_ViewEditTags_TagList.ItemsSource = _whTagViewEditCol;
            CollectionViewSource.GetDefaultView(DG_Warehouse_ViewEditTags_TagList.ItemsSource).Filter = WhTaggingViewFilter;
        }
        
        private void TB_Warehouse_ViewEditTags_SearchJobNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewEditTags_TagList.ItemsSource == null) return;
            if (this._tagVeDa == null)
            {
                this._tagVeDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewEditTags_TagList.ItemsSource).Refresh());
            }
            this._tagVeDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewEditTags_SearchJobName_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewEditTags_TagList.ItemsSource == null) return;
            if (this._tagVeDa == null)
            {
                this._tagVeDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewEditTags_TagList.ItemsSource).Refresh());
            }
            this._tagVeDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewEditTags_SearchPoNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewEditTags_TagList.ItemsSource == null) return;
            if (this._tagVeDa == null)
            {
                this._tagVeDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewEditTags_TagList.ItemsSource).Refresh());
            }
            this._tagVeDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewEditTags_SearchSopNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewEditTags_TagList.ItemsSource == null) return;
            if (this._tagVeDa == null)
            {
                this._tagVeDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewEditTags_TagList.ItemsSource).Refresh());
            }
            this._tagVeDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void BTN_Warehouse_Tagging_ClearSearch_Click(object sender, RoutedEventArgs e)
        {
            if (DG_Warehouse_ViewEditTags_TagList.ItemsSource == null) return;
            if (this._tagVeDa == null)
            {
                this._tagVeDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewEditTags_TagList.ItemsSource).Refresh());
            }
            this._tagVeDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private bool WhTaggingViewFilter(object tagLine)
        {
            var _recLineObject = (dc.TaggingLine)tagLine;
            DateTime? dt = _recLineObject.DateReceived;

            if (DP_Warehouse_ViewReceipts_ReceiveDate.Text == "")
            {
                return (_recLineObject.JobNumber.IndexOf(TB_Warehouse_ViewEditTags_SearchJobNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.JobName.IndexOf(TB_Warehouse_ViewEditTags_SearchJobName.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.PoNumber.IndexOf(TB_Warehouse_ViewEditTags_SearchPoNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.SopNumber.IndexOf(TB_Warehouse_ViewEditTags_SearchSopNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        );
            }
            else
            {
                return (_recLineObject.JobNumber.IndexOf(TB_Warehouse_ViewReceipts_JobNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.JobName.IndexOf(TB_Warehouse_ViewReceipts_JobName.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.PoNumber.IndexOf(TB_Warehouse_ViewReceipts_PoNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _recLineObject.SopNumber.IndexOf(TB_Warehouse_ViewReceipts_SopNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && String.Format("{0:M/dd/yy}", dt) == DP_Warehouse_ViewReceipts_ReceiveDate.Text
                        );
            }
        }


        private void Warehouse_ViewEditTags_DeleteTag(object sender, RoutedEventArgs e)
        {
            dc.TaggingLine _selTag = (dc.TaggingLine)((Button)e.Source).DataContext;
            if (dc.WhTaggingLines.DeleteTagLine(_selTag));
                _whTagViewEditCol.Remove(_selTag);
        }

        #endregion


        //Shipping
        #region ShippingView

        private void BTN_Warehouse_GenerateShipmentDocument(object sender, RoutedEventArgs e)
        {
            dc.ShippingHeader _selShip = (dc.ShippingHeader)((Button)e.Source).DataContext;
            ObservableCollection<dc.ShippingLine> _shipLines = dc.WhShippingLines.GetWhShippingLinesByMemoNum(_selShip.MemoNumber);

            WordConverters.ExportShipmentHeaderAndLines.CreateShipmentDocument(_selShip, _shipLines, 0, null, null);

        }

        private void BTN_Warehouse_ViewShipments_Refresh_Click(object sender, RoutedEventArgs e)
        {
            TB_Warehouse_ViewShipments_SearchJobNumber.Text = "";
            TB_Warehouse_ViewShipments_SearchJobName.Text = "";
            TB_Warehouse_ViewShipments_SearchSopbNumber.Text = "";
            DP_Warehouse_ViewShipments_ShipDate.Text = "";
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource != null)
            {
                CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Filter = null;
            }
            _whShipHeaderCol = dc.WhShippingHeaders.GetShippingHeaders(null);
            DG_Warehouse_ViewShipments_ShipmentList.ItemsSource = _whShipHeaderCol;
            CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Filter = WhShipmentViewFilter;
        }

        private void BTN_Warehouse_Shipments_ViewShipments_ExportToExcel_Click(object sender, RoutedEventArgs e)
        {
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.WarehouseShipHeaderAll, _curUserTwo);
            ExcelConverters.ExcelExporter.DatabaseToExcel(ExcelConverters.ExcelExporter.ReportName.WarehouseShipLineAll, _curUserTwo);
        }

        private void BTN_Warehouse_ViewShipments_ClearSearch_Click(object sender, RoutedEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource != null)
            {
                CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Filter = null;
            }
            TB_Warehouse_ViewShipments_SearchJobNumber.Text = null;
            TB_Warehouse_ViewShipments_SearchJobName.Text = null;
            TB_Warehouse_ViewShipments_SearchSopbNumber.Text = null;
            DP_Warehouse_ViewShipments_ShipDate.Text = null;
            CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Filter = WhShipmentViewFilter;
        }

        private void TB_Warehouse_ViewShipments_SearchJobNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource == null) return;
            if (this._whShDa == null)
            {
                this._whShDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Refresh());
            }
            this._whShDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewShipments_SearchJobName_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource == null) return;
            if (this._whShDa == null)
            {
                this._whShDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Refresh());
            }
            this._whShDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewShipments_SearchPoNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource == null) return;
            if (this._whShDa == null)
            {
                this._whShDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Refresh());
            }
            this._whShDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void TB_Warehouse_ViewShipments_SearchSopbNumber_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource == null) return;
            if (this._whShDa == null)
            {
                this._whShDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Refresh());
            }
            this._whShDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }


        private void TB_Warehouse_ViewShipments_ItemDescription_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource == null) return;
            if (this._whShDa == null)
            {
                this._whShDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Refresh());
            }
            this._whShDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private void DP_Warehouse_ViewShipments_ShipDate_CalendarClosed(object sender, RoutedEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.ItemsSource == null) return;
            if (this._whShDa == null)
            {
                this._whShDa = DeferredAction.Create(() => CollectionViewSource.GetDefaultView(DG_Warehouse_ViewShipments_ShipmentList.ItemsSource).Refresh());
            }
            this._whShDa.Defer(new TimeSpan(0, 0, 0, 0, 300));
        }

        private bool WhShipmentViewFilter(object shipHead)
        {
            var _shipHeadObject = (dc.ShippingHeader)shipHead;
            DateTime? dt = _shipHeadObject.DateShipped;

            if (DP_Warehouse_ViewShipments_ShipDate.Text == "")
            {
                return (_shipHeadObject.JobNumber.IndexOf(TB_Warehouse_ViewShipments_SearchJobNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _shipHeadObject.JobName.IndexOf(TB_Warehouse_ViewShipments_SearchJobName.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _shipHeadObject.SopNumber.IndexOf(TB_Warehouse_ViewShipments_SearchSopbNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _shipHeadObject.ConcatenatedPos.IndexOf(TB_Warehouse_ViewShipments_SearchPoNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0   
                        && _shipHeadObject.ConcatednatedItemDesc.IndexOf(TB_Warehouse_ViewShipments_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        );
            }
            else
            {
                return (_shipHeadObject.JobNumber.IndexOf(TB_Warehouse_ViewShipments_SearchJobNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _shipHeadObject.JobName.IndexOf(TB_Warehouse_ViewShipments_SearchJobName.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _shipHeadObject.SopNumber.IndexOf(TB_Warehouse_ViewShipments_SearchSopbNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _shipHeadObject.ConcatenatedPos.IndexOf(TB_Warehouse_ViewShipments_SearchPoNumber.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && _shipHeadObject.ConcatednatedItemDesc.IndexOf(TB_Warehouse_ViewShipments_ItemDescription.Text, StringComparison.OrdinalIgnoreCase) >= 0
                        && String.Format("{0:M/dd/yy}", dt) == DP_Warehouse_ViewShipments_ShipDate.Text
                        );
            }
        }

        private void DG_Warehouse_ViewShipments_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            if (DG_Warehouse_ViewShipments_ShipmentList.SelectedIndex != -1)
            {

                dc.ShippingHeader _selHeader = (dc.ShippingHeader)DG_Warehouse_ViewShipments_ShipmentList.SelectedItem;
                //dc.ShippingHeader _shipClone = uc.CloneClass.Clone<dc.ShippingHeader>(_selHeader);

                dc.ShipHeaderSession _session = dc.ShipHeaderSessions.CheckSession(_selHeader.JobNumber, _selHeader.MemoNumber);

                if (_session != null)
                {
                    MessageBox.Show("Shipment currently in use by " + _session.DomainUserName + " since " + _session.SessionTime.Value.ToString("HH:mm")
                                    + " on " + _session.SessionDate.Value.ToString("dd-MMM-yyyy"));

                    if (MessageBox.Show("Would you like to view this change order in read-only mode?", "Prompt",
                                       MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    {
                        WhShipLinesPopUpWindow _whShipLineWin = new WhShipLinesPopUpWindow(ref _selHeader, true); //ref _selHeader, ref _shipClone, true);
                        //_whShipLineWin.Owner = this;
                        _whShipLineWin.Show();
                    }
                }
                else if (_session == null)
                {
                    dc.ShipHeaderSessions.CreateSession(_selHeader.JobNumber, _selHeader.MemoNumber);
                    WhShipLinesPopUpWindow _whShipLineWin = new WhShipLinesPopUpWindow(ref _selHeader, false);
                    _whShipLineWin.Owner = this;
                    _whShipLineWin.ShowDialog();
                }
            }
        }

        #endregion

        #region ShippingCreate

        private void ChkBox_Warehouse_CreateShipments_ProjCust_Click(object sender, RoutedEventArgs e)
        {
            if (ChkBox_Warehouse_CreateShipments_ProjCust.IsChecked == false)
            {
                if (TB_Warehouse_CreateShipments_JobNumber.Text != "" || TB_Warehouse_CreateShipments_SopNumber.Text != "")
                {
                    if (MessageBox.Show("There is already info for a project shipment, if you continue that info will be overridden.", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    {
                        _whShipHeader = null;
                        _whShipLinesCol.Clear();
                        DG_Warehouse_CreateShipments_ShipLines.Items.Refresh();
                        ClearWhShippingTextBoxes();
                    }
                    else
                    {
                        ChkBox_Warehouse_CreateShipments_ProjCust.IsChecked = true;
                        return;
                    }
                }
                StckPan_Warehouse_CreateShipments_ProjectButtons.Visibility = System.Windows.Visibility.Visible;
                StckPan_Warehouse_CreateShipments_CustomerButtons.Visibility = System.Windows.Visibility.Hidden;
                StckPan_Warehouse_CreateShipments_CustProperties.Visibility = System.Windows.Visibility.Hidden;
                StckPan_Warehouse_CreateShipments_JobProperties.Visibility = System.Windows.Visibility.Visible;
                DG_Warehouse_CreateShipments_ShipLines.Columns[0].Header = "PO NUMBER";
            }
            else
            {
                if (TB_Warehouse_CreateShipments_JobNumber.Text != "" || TB_Warehouse_CreateShipments_SopNumber.Text != "")
                {
                    if (MessageBox.Show("There is already info for a retail shipment, if you continue that info will be overridden.", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                    {
                        _whShipHeader = null;
                        _whShipLinesCol.Clear();
                        DG_Warehouse_CreateShipments_ShipLines.Items.Refresh();
                        ClearWhShippingTextBoxes();
                    }
                    else
                    {
                        ChkBox_Warehouse_CreateShipments_ProjCust.IsChecked = false;
                        return;
                    }
                }
                StckPan_Warehouse_CreateShipments_ProjectButtons.Visibility = System.Windows.Visibility.Hidden;
                StckPan_Warehouse_CreateShipments_CustomerButtons.Visibility = System.Windows.Visibility.Visible;
                StckPan_Warehouse_CreateShipments_CustProperties.Visibility = System.Windows.Visibility.Visible;
                StckPan_Warehouse_CreateShipments_JobProperties.Visibility = System.Windows.Visibility.Hidden;
                DG_Warehouse_CreateShipments_ShipLines.Columns[0].Header = "SOP NUMBER";
            }
        }

        private void BTN_Warehouse_CreateShipments_ProjSelectWindow_Click(object sender, RoutedEventArgs e)
        {
            if (_whShipLinesCol.Count > 0)
            {
                if (MessageBox.Show("If you open the shipment selection window, all the shipping lines you've made will be lost.  Would you like to create a new shipment?", "Prompt",
                MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                {
                    _whShipLinesCol.Clear();
                    _whShipRlDataTrack.Clear();
                }
                else
                    return;
            }
            WhShipSelProject _selProjWin = new WhShipSelProject(this, StckPan_Warehouse_CreateShipments_JobProperties);
            _selProjWin.Owner = this;
            _selProjWin.ShowDialog();
        }

        private void BTN_Warehouse_CreateShipments_RetailSelectWindow_Click(object sender, RoutedEventArgs e)
        {
            if (_whShipLinesCol.Count > 0)
            {
                if (MessageBox.Show("If you open the shipment selection window, all the shipping lines you've made will be lost.  Would you like to create a new shipment?", "Prompt",
                MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                {
                    _whShipLinesCol.Clear();
                    _whShipRlDataTrack.Clear();
                }
                else
                    return;

            }
            WhShipSelCustomer _selCustWin = new WhShipSelCustomer(this, StckPan_Warehouse_CreateShipments_CustProperties);
            _selCustWin.Owner = this;
            _selCustWin.ShowDialog();
        }
            
        private void BTN_Warehouse_CreateShipments_GetShipLinePo_Click(object sender, RoutedEventArgs e)
        {
            if (_whShipHeader.JobNumber != null)
            {
                if (_whShipLinesCol.Count == 0)
                    _whShipRecCol = dc.WhShippingLines.GetReceivingLinesByProject(_whShipHeader.JobNumber);
                WhShipGetPoReceiptLines _whShipGetPoLines = new WhShipGetPoReceiptLines(_whShipLinesCol, ref _whShipRecCol, ref _whShipRlDataTrack, ref _poRecLinesCreateShipWinList);
                _whShipGetPoLines.Owner = this;
                _whShipGetPoLines.ShowDialog();
            }
            else
            {
                MessageBox.Show("A job has not been selected for this shipment yet.");
            }
        }

        private void BTN_Warehouse_CreateShipments_GetShipLineRtl_Click(object sender, RoutedEventArgs e)
        {
            if (TB_Warehouse_CreateShipments_SopNumber.Text != "")
            {
                if (_whShipLinesCol.Count == 0)
                {
                    _whShipRecCol = dc.WhShippingLines.GetReceivingLinesBySop(_whShipHeader.SopNumber);
                    _whShipHeader.JobNumber = null;
                }
                WhShipGetPoReceiptLines _whShipGetPoLines = new WhShipGetPoReceiptLines(_whShipLinesCol, ref _whShipRecCol, ref _whShipRlDataTrack, ref _poRecLinesCreateShipWinList);
                _whShipGetPoLines.Owner = this;
                _whShipGetPoLines.Show();
            }
            else
            {
                MessageBox.Show("An SOP number has not been selected for this shipment yet.");
            }
            
        }

        private void BTN_Warehouse_CreateShipments_CommitProject_Click(object sender, RoutedEventArgs e)
        {
            _whShipRlDataTrack.GetReceivingLines();
            if (TB_Warehouse_CreateShipments_JobNumber.Text == "")
            {
                MessageBox.Show("No job has been selected.");
                return;
            }
            else if (_whShipLinesCol.Count == 0)
            {
                MessageBox.Show("There are no line items selected for this shipment");  
                return;
            }
            else
            {
                int _memoNum = dc.WhShippingHeaders.GetNextMemoNumber();
                _whShipRlDataTrack.AssignSerial();
                if (dc.WhShippingHeaders.AddShippingHeader(_whShipHeader, _memoNum))
                {
                    if (dc.WhShippingLines.AddShippingLine(_whShipLinesCol, _memoNum))
                    {
                        if (uc.RecLineTrackers.AddRecLineTrackers(_whShipRlDataTrack, _memoNum))
                        {
                            //dc.WH_ReceivingLines.UpdateReceivingLines(_whShipRecCol, _memoNum);
                            dc.WhReceivingLines.UpdateReceivingLines(_whShipRecCol);
                        }
                    }
                }

                _whShipLinesCol.Clear();
                _whShipRlDataTrack.Clear();
                ClearWhShippingTextBoxes();
            }
        }

        private void BTN_Warehouse_CreateShipments_CommitCustomer_Click(object sender, RoutedEventArgs e)
        {
            if (TB_Warehouse_CreateShipments_SopNumber.Text == "")
            {
                MessageBox.Show("No retail order number has been selected.");
                return;     
            }
            else if (_whShipLinesCol.Count == 0)
            {
                MessageBox.Show("There are no line items selected for this shipment.");
                return;
            }
            else
            {
                int _memoNum = dc.WhShippingHeaders.GetNextMemoNumber();
                _whShipRlDataTrack.AssignSerial();
                if (dc.WhShippingHeaders.AddShippingHeader(_whShipHeader, _memoNum))
                {
                    if (dc.WhShippingLines.AddShippingLine(_whShipLinesCol, _memoNum))
                    {
                        if (uc.RecLineTrackers.AddRecLineTrackers(_whShipRlDataTrack, _memoNum))
                        {
                            //dc.WH_ReceivingLines.UpdateReceivingLines(_whShipRecCol, _memoNum);
                            dc.WhReceivingLines.UpdateReceivingLines(_whShipRecCol);
                        }
                    }
                }
                _whShipLinesCol.Clear();
                ClearWhShippingTextBoxes();
            }
        }

        private void BTN_Warehouse_CreateShipments_ClearItems_Click(object sender, RoutedEventArgs e)
        {
            _whShipLinesCol.Clear();
        }


        private void BTN_Warehouse_CreateShipments_AdjustShipments_Click(object sender, RoutedEventArgs e)
        {
            WhShipAdjustYesNo _whAdjYn = new WhShipAdjustYesNo();
            _whAdjYn.ShowDialog();
            if (_whAdjYn.YesCancel)
            {
                _whShipHeader = null;
                _whShipLinesCol.Clear();
                DG_Warehouse_CreateShipments_ShipLines.Items.Refresh();
                ClearWhShippingTextBoxes();

                WhShipAdjust _whAdjustWin = new WhShipAdjust();
                _whAdjYn.Owner = this;
                _whAdjustWin.ShowDialog();
            }

        }

        private void DataGridCell_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            DataGridCell cell = sender as DataGridCell;

            if (cell != null && !cell.IsEditing && !cell.IsReadOnly)
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
                            if (cell.Column.DisplayIndex == 9)
                            {
                                if (MessageBox.Show("Would you like to delete this item?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ShippingLine _selItem = (dc.ShippingLine)row.Item;
                                    _whShipLinesCol.Remove(_selItem);
                                    WhShipmentsRecalculateReceiptDrawDowns(_selItem);
                                    //_sopDoc.LineItems.RemoveAt(row.GetIndex());
                                    DG_Warehouse_CreateShipments_ShipLines.Items.Refresh();
                                }
                            }
                            row.IsSelected = true;
                        }
                        else if (row != null && row.IsSelected)//This is for when the row was already selected and the user presses the delete button again. No negation "!" on "row.IsSelected"
                        {
                            if (cell.Column.DisplayIndex == 9)
                            {
                                if (MessageBox.Show("Would you like to delete this item?", "Prompt", MessageBoxButton.YesNo, MessageBoxImage.Warning) == MessageBoxResult.Yes)
                                {
                                    dc.ShippingLine _selItem = (dc.ShippingLine)row.Item;
                                    _whShipLinesCol.Remove(_selItem);
                                    WhShipmentsRecalculateReceiptDrawDowns(_selItem);
                                    //_sopDoc.LineItems.RemoveAt(row.GetIndex());
                                    DG_Warehouse_CreateShipments_ShipLines.Items.Refresh();
                                }
                            }
                        }
                    }
                }
            }
        }

        private void WhShipmentsRecalculateReceiptDrawDowns(dc.ShippingLine sl)     //When someone deletes a line that they added to shipments, this has to put the receipt line quantities back to what they were
        {
            foreach (uc.RecLineTracker rlt in _whShipRlDataTrack)
            {
                if (sl.PoNumber == rlt.PoNumber && sl.Polnenum == rlt.Polnenum)
                {
                    for (int x = 0; x < _whShipRecCol.Count; x++)
                    {
                        if (rlt.PoNumber == _whShipRecCol[x].PoNumber &&
                            rlt.Polnenum == _whShipRecCol[x].Polnenum &&
                            rlt.PopRctNum == _whShipRecCol[x].PopRctNum &&
                            rlt.RcptLnNm == _whShipRecCol[x].RcptLnNm)
                        {
                            _whShipRecCol[x].QtyRemainingOnRec += rlt.QuantityDrawn;
                            rlt.Delete = true;
                        }
                    }
                }
            }
            _whShipRlDataTrack.DeleteItems();   //Delete the items in the collection marked for deletions prior to sending it off to the data access methods
        }

        internal void ClearWhShippingTextBoxes()
        {
            foreach (TextBox tb in FindVisualChildren<TextBox>(StckPan_Warehouse_CreateShipments_JobProperties)) { tb.Text = null; }
            foreach (TextBox tb in FindVisualChildren<TextBox>(StckPan_Warehouse_CreateShipments_CustProperties)) { tb.Text = null; }
        }

        #endregion

        #endregion

        #region Utility Methods
        //TEST BUTTON FOR TESTING STUFF
        private void Button_Click(object sender, RoutedEventArgs e)
        {

            //http://stackoverflow.com/questions/23345285/how-to-get-binding-expression-of-a-datagrid-column
            //http://stackoverflow.com/questions/9971594/how-to-get-path-of-binding-of-a-datagridboundcolumn


            //ExcelConverters.ExcelExporter.DataGridToDataTable(DG_MainProject_ProjectList);

            //http://stackoverflow.com/questions/2535287/getting-nested-object-property-value-using-reflection

            //property order and path array

            //PropertyPath[] propOrderArr = new PropertyPath[DG_OfferToTender_TenderList.Columns.Count];
            ////int i = 0;
            //for (int i = 0; i < DG_OfferToTender_TenderList.Columns.Count; i++)
            //{
            //    DataGridColumn col = DG_OfferToTender_TenderList.Columns[i];
            //    if (col.GetType() == typeof(DataGridTemplateColumn))
            //    {
            //         DataGridRow row = (DataGridRow)DG_OfferToTender_TenderList.ItemContainerGenerator.ContainerFromIndex(0);
            //         Rectangle asdfsdf = FindChildTwo<Rectangle>(row);
            //         var gdsg = (Brush)asdfsdf.Fill;
            //    }
            //    DataGridBoundColumn dgCol = (DataGridBoundColumn)DG_OfferToTender_TenderList.Columns[i];
            //    BindingBase binding = dgCol.Binding;
            //    PropertyPath path = ((Binding)binding).Path;
            //    propOrderArr[i] = path;
            //    i++;

            //}

            //DataGridBoundColumn dgCol = (DataGridBoundColumn)DG_MainProject_ProjectList.Columns[3];
            //BindingBase binding = dgCol.Binding;
            //PropertyPath path = ((Binding)binding).Path;

            //var mainProjLine = DG_MainProject_ProjectList.Items[0];
            //var prop = exc.GetPropertyValue(exc.GetPropertyValue(mainProjLine, "MainProject"), "JobNumber");

            //pm.ChangeIndexes.CheckSession("20836", "Q001");
            //pm.ChangeHeaders.GetChangeHeaders("20836");







            //----------TESTING STORED PROCEDURE/USER DEFINED FUNCTIONS.  WORKS! ------------------

            //dc.matListContext objContext = null;
            //try
            //{
            //    List<dc.HardwareSchedule> asdf = null;
            //    objContext = new dc.matListContext("Data Source=UCSHSQL2\\MSSQL2014; Initial Catalog=Avaware;Integrated Security=SSPI");
            //    asdf = objContext.getMatListByProject(8).ToList();
            //    //foreach (var row in objContext.getMatListByProject(8))
            //    //{
            //    //    //Debug.WriteLine(((dc.HardwareSchedule)row).ProductId);

            //    //}

            //}
            //catch (Exception ex)
            //{
            //    MessageBox.Show(ex.ToString());
            //    //if (objContext != null)
            //    //    objContext.Dispose();
            //}
            //finally
            //{
            //    if (objContext != null)
            //        objContext.Dispose();
            //}




            //dc.matListFunctionV2 objContext = null;
            //try
            //{
            //    List<dc.HardwareSchedule> asdf = null;
            //    objContext = new dc.matListFunctionV2("Data Source=UCSHSQL2\\MSSQL2014; Initial Catalog=Avaware;Integrated Security=SSPI");
            //    asdf = objContext.getMatListByProjectv2(8).ToList();
            //    //foreach (var row in objContext.getMatListByProject(8))
            //    //{
            //    //    //Debug.WriteLine(((dc.HardwareSchedule)row).ProductId);

            //    //}
            //}
            //catch (Exception ex)
            //{
            //    MessageBox.Show(ex.ToString());
            //    //if (objContext != null)
            //    //    objContext.Dispose();
            //}
            //finally
            //{
            //    if (objContext != null)
            //        objContext.Dispose();
            //}




            //ObservableCollection<dc.PurchaseOrderLineItem> asdf = new ObservableCollection<dc.PurchaseOrderLineItem>();
            //EConnect.PopTransaction.RunPoCreate(ref asdf);

            //ObservableCollection<pm.TaskScheduler> _lkj = new ObservableCollection<pm.TaskScheduler>();
            //_lkj.Add(new pm.TaskScheduler());
            //_lkj[0].Id = 1;








            //dc.PoListFunctionV1 objContext = null;
            //try
            //{
            //    List<dc.PurchaseOrderLineItem> asdf = null;
            //    objContext = new dc.PoListFunctionV1("Data Source=UCSHSQL2\\MSSQL2014; Initial Catalog=Avaware;Integrated Security=SSPI");
            //    asdf = objContext.ConnectsPoLineTestAllJobs().ToList();
            //    //foreach (var row in objContext.getMatListByProject(8))
            //    //{
            //    //    //Debug.WriteLine(((dc.HardwareSchedule)row).ProductId);

            //    //}
            //}
            //catch (Exception ex)
            //{
            //    MessageBox.Show(ex.ToString());
            //    //if (objContext != null)
            //    //    objContext.Dispose();
            //}
            //finally
            //{
            //    if (objContext != null)
            //        objContext.Dispose();
            //}




            //dc.ShippingHeader _shTest = new dc.ShippingHeader();
            //_shTest.MemoNumber = 9743543;
            //_shTest.JobName = "job asdf";
            //_shTest.Courier = "generic shipping";
            //uc.DeferredPropertySetter _dpSetter = new uc.DeferredPropertySetter();
            ////uc.DeferredPropertySetterNoRedundancy _dpSetterNr = new uc.DeferredPropertySetterNoRedundancy();

            //_dpSetter.SetValue(x => _shTest.MemoNumber = x, 7);
            //MessageBox.Show(_shTest.MemoNumber.ToString());
            //_dpSetter.SetValue(x => _shTest.MemoNumber = x, 11);
            //_dpSetter.SetValue(x => _shTest.MemoNumber = x, 19);
            //_dpSetter.SetValue(x => _shTest.JobName = x, "NEW job name");
            //_dpSetter.SetValue(x => _shTest.JobName = x, "ALSO NEW NEW job name");
            //MessageBox.Show(_shTest.JobName);
            //_dpSetter.ApplyChanges();
            //MessageBox.Show(_shTest.MemoNumber.ToString());
            //MessageBox.Show(_shTest.JobName);



            //dc.DrivePath _dp = dc.PathSchemas.GetDrivePathByKey(1);

            //Single method that adds the folder paths to jobs
            //um.CheckLinksJobFolders.GetFolders();

            //dc.ReceivingLine rl = new dc.ReceivingLine() { PoNumber = "PO032289", PopRctNum = "RCT069246" };
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            //int _recCount;

            //var asdf = dtCtx.GetTable<dc.ReceivingLine>().GroupBy(x => new { x.PoNumber, x.PopRctNum }).Where(r => r.Key.PoNumber == rl.PoNumber).Count();


            //dc.ReceivingLine rl = new dc.ReceivingLine() { JobNumber = "21943", PoNumber = "PO032289", PopRctNum = "RCT069246" };
            //OutlookConverters.OutlookGenerator _asdf = new olc(rl);

            //dc.DrivePath _dp = dc.PathSchemas.GetDrivePathByKey(1);

            //Single method that adds the folder paths to jobs
            //um.CheckLinksJobFolders.GetFolders();




            //string jobnumber = "20059";
            //lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            //lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            ////var hwlist = dtCtx.GetTable<dc.AVA_APJ_D8_MaterialList>().Join(dtCtx.GetTable<dc.AVA_APJ_D8_OpeningsSchedules>(), ml => ml.OsRowNum.GetValueOrDefault(0), ol => ol.RowNum.GetValueOrDefault(0), (ml, ol) => new { ml, ol })
            ////    .Join(dtCtx.GetTable<dc.AVA_FUSION_FileList>(), mlos => mlol.ol.ProjectId, fl => fl.ProjectNumber, (mlol, fl) => new { mlol, fl })

            //var hwlist = dtCtx.GetTable<dc.AVA_APJ_D8_MaterialList>().Join(dtCtx.GetTable<dc.AVA_APJ_D8_OpeningsSchedules>(), ml => ml.OsRowNum, ol => ol.RowNum, (ml, ol) => new { ml, ol })
            //                                                         .Join(dtCtx.GetTable<dc.AVA_FUSION_FileList>(), mlol => mlol.ol.ProjectId, fl => fl.Id, (mlol, fl) => new { mlol, fl })
            //                                                         .Where(r => r.fl.ProjectNumber == jobnumber ).Select(x => new
            //                                                         {
            //                                                             ProductId = x.mlol.ml.ProductHash,
            //                                                             OpeningNumber = x.mlol.ol.OpeningNumber,
            //                                                             JobNumber = x.fl.ProjectNumber,
            //                                                             JobName = x.fl.ProjectName

            //                                                         }).ToList();





            //string asdf = "c";

            //if (asdf == "a")
            //    MessageBox.Show("a");

            //else if (asdf == "b")
            //    MessageBox.Show("b");

            //else if (asdf == "c")
            //    MessageBox.Show("c");


            //ObservableCollection<dc.HardwareSchedule> _hwList = dc.Hardware.GetHardwareSchedule(4); //4 = 20059 aka PARQ
            //ExcelConverters.ExportCommissionSheets.ObjectArrFromList(_hwList);

            //ExcelConverters.ExportCommissionSheets.GenerateCommSheets(4);
            //ExcelConverters.ExportCommissionSheets.GenerateCommSheets(96);

            dc.QuoteSummaries.GetUniqueJobList();

        }

        private bool ViewsOverrideChecker(string permSig)
        {
            bool appr = false;
            foreach (string sig in _curUserTwo.ViewOverrides)
            {   
                if (sig.ToLower() == permSig.ToLower())
                    appr = true;
            }
            return appr;
        }

        private bool AccessOverrideChecker(string permSig)
        {
            bool appr = false;
            foreach (string sig in _curUserTwo.AccessOverrides)
            {
                if (sig.ToLower() == permSig.ToLower())
                    appr = true;
            }
            return appr;
        }


        private void CBox_DbSwitcher_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (_projWinList.Count != 0)
            {
                MessageBox.Show("Cannot switch database with existing project windows open");
                return;
            }
            if (CBox_DbSwitcher.SelectedIndex == -1)
                return;
            else if (CBox_DbSwitcher.SelectedIndex == 0)
            {
                GlobalVars.SwitchToUcsh();
                
                LBL_DisplayDatabase.Content = GlobalVars.CurrentPmDatabaseName;
            }
            else if (CBox_DbSwitcher.SelectedIndex == 1)
            {
                GlobalVars.SwitchToBc();
                LBL_DisplayDatabase.Content = GlobalVars.CurrentPmDatabaseName;
            }
            else if (CBox_DbSwitcher.SelectedIndex == 2)
            {
                GlobalVars.SwitchToTest();
                LBL_DisplayDatabase.Content = GlobalVars.CurrentPmDatabaseName;
            }
            SetModulesAccess(_curUserTwo);
        }

        //Change this to drop-down
        //private void BTN_ChangeServer_Click(object sender, RoutedEventArgs e)
        //{
        //    if (_projWinList.Count != 0)
        //    {
        //        MessageBox.Show("Cannot switch database with existing project windows open");
        //        return;
        //    }
        //    if (GlobalVars.CurrentPmDatabaseName == "PMUCSH")
        //    {
        //        GlobalVars.SwitchToTest(); 
        //        //LBL_DisplayDatabase.Content = GlobalVars.CurrentPmDatabaseName;
        //    }
        //    else if (GlobalVars.CurrentPmDatabaseName == "TESTPMUCSH")
        //    {
        //        GlobalVars.SwitchToLive(_curUserTwo);
        //        //LBL_DisplayDatabase.Content = GlobalVars.CurrentPmDatabaseName;
        //    }
        //    SetModulesAccess(_curUserTwo);
        //    //RefreshDataGrids();
        //}

        private void DG_MainProject_ProjectList_BeginningEdit(object sender, DataGridBeginningEditEventArgs e)
        {
            dc.CombinedProject asdf = (dc.CombinedProject)e.Row.Item;
            if (e.Column.DisplayIndex == 17)
            {
                var fff = DG_MainProject_ProjectList.SelectedCells;
                var cellInfo = DG_MainProject_ProjectList.SelectedCells[0];
                var content = cellInfo.Column.GetCellContent(cellInfo.Item);
            }
        }

        public static IEnumerable<T> FindVisualChildren<T>(DependencyObject depObj) where T : DependencyObject
        {
            if (depObj != null)
            {
                for (int i = 0; i < VisualTreeHelper.GetChildrenCount(depObj); i++)
                {
                    DependencyObject child = VisualTreeHelper.GetChild(depObj, i);
                    if (child != null && child is T)
                    {
                        yield return (T)child;
                    }

                    foreach (T childOfChild in FindVisualChildren<T>(child))
                    {
                        yield return childOfChild;
                    }
                }
            }
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


        public static T FindChild<T>(DependencyObject parent)where T : DependencyObject
        {
            // confirm parent is valid.
            if (parent == null) return null;
            if (parent is T) return parent as T;

            DependencyObject foundChild = null;

            if (parent is FrameworkElement) (parent as FrameworkElement).ApplyTemplate();

            int childrenCount = VisualTreeHelper.GetChildrenCount(parent);
            for (int i = 0; i < childrenCount; i++)
            {
                var child = VisualTreeHelper.GetChild(parent, i);
                foundChild = FindChild<T>(child);
                if (foundChild != null) break;
            }

            return foundChild as T;
        }

        public static T FindChildTwo<T>(DependencyObject parent) where T : DependencyObject
        {
            // Confirm parent is valid. 
            if (parent == null) return null;

            T foundChild = null;

            int childrenCount = VisualTreeHelper.GetChildrenCount(parent);
            for (int i = 0; i < childrenCount; i++)
            {
                var child = VisualTreeHelper.GetChild(parent, i);
                // If the child is not of the request child type child
                T childType = child as T;
                if (childType == null)
                {
                    // recursively drill down the tree
                    foundChild = FindChild<T>(child);

                    // If the child is found, break so we do not overwrite the found child. 
                    if (foundChild != null) break;
                }
                else
                {
                    // child element found.
                    foundChild = (T)child;
                    break;
                }
            }
            return foundChild;
        }

        public static IEnumerable<T> QuoteSummaryFindLogicalChildren<T>(DependencyObject depObj) where T : DependencyObject
        {
            if (depObj != null)
            {
                //var lsdjfds = LogicalTreeHelper.GetChildren(depObj);

                foreach (T uiObject in LogicalTreeHelper.GetChildren(depObj))
                {
                    if (uiObject != null && uiObject is T)
                    {
                        yield return (T)uiObject;
                    }

                    foreach (T childOfChild in QuoteSummaryFindLogicalChildren<T>(uiObject))
                    {
                        yield return childOfChild;
                    }
                }
            }
        }

        private void TB_WH_Rec_ActualShipDateCust_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            //CalendarWindow _calWin = new CalendarWindow();
            //_calWin.Owner = this;
            //_calWin.ShowDialog();
        }

        private void TB_WH_Rec_ReqShipDateCust_MouseDoubleClick(object sender, MouseButtonEventArgs e)
        {
            //CalendarWindow _calWin = new CalendarWindow();
            //_calWin.Owner = this;
            //_calWin.ShowDialog();
        }

        private void DP_WH_Receive_ReceiveDate_TextInput(object sender, TextCompositionEventArgs e)
        {

        }

        private void testrefresth_Click(object sender, RoutedEventArgs e)
        {
            DG_Warehouse_ViewShipments_ShipmentList.Items.Refresh();
        }

        private void DG_TaskScheduler_Tasks_LoadingRow(object sender, DataGridRowEventArgs e)
        {

            //DataGridRow gridRow = e.Row;
            //pm.TaskSchedulerItem _selItem = (gridRow.DataContext as pm.TaskSchedulerItem);
            //switch (_selItem.Completed)
            //{
            //    case false:
            //        gridRow.Background = new SolidColorBrush(Colors.Green);
            //        break;
            //    case true:
            //        gridRow.Background = new SolidColorBrush(Colors.Yellow);
            //        break;
            //}
        }

        private void BTN_MainProj_OutlookTest_Click(object sender, RoutedEventArgs e)
        {
            //dc.BidProject bidtest = new dc.BidProject();
            //dc.Pursuit pursuittest = new dc.Pursuit();

            //OutlookConverters.OutlookGenerator _asdf = new olc(pursuittest);

            //dc.ReceivingLine rl = new dc.ReceivingLine() { JobNumber = "21943", PoNumber = "TEST012345", PopRctNum = "TESTRCTNUM" };
            //OutlookConverters.OutlookGenerator _asdf = new olc(rl);
        }

        private void ComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            //dc.Pursuit _selPursuit = (dc.Pursuit)DG_Pursuits_PursuitList.SelectedItem;

            //if (_selPursuit != null && (_selPursuit.TenderPhase == "BIDDING" || _selPursuit.TenderPhase == "CONSULTING"))
            //    _selPursuit.PursuitStatus = "ACTIVE";

        }

    }

    //[AttributeUsage(AttributeTargets.All, Inherited = false, AllowMultiple = true)]
    //public sealed class LocalizableDescriptionAttribute : DescriptionAttribute
    //{
    //    #region Public methods.
    //    // ------------------------------------------------------------------

    //    /// <summary>
    //    /// Initializes a new instance of the <see cref="LocalizableDescriptionAttribute"/> class.
    //    /// </summary>
    //    /// <param name="description">The description.</param>
    //    /// <param name="resourcesType">Type of the resources.</param>
    //    public LocalizableDescriptionAttribute(string description, Type resourcesType) : base(description)
    //    {
    //        _resourcesType = resourcesType;
    //    }

    //    // ------------------------------------------------------------------
    //    #endregion

    //    #region Public properties.
    //    // ------------------------------------------------------------------

    //    /// <summary>
    //    /// Get the string value from the resources.
    //    /// </summary>
    //    /// <value></value>
    //    /// <returns>The description stored in this attribute.</returns>
    //    public override string Description
    //    {
    //        get
    //        {
    //            if (!_isLocalized)
    //            {
    //                ResourceManager resMan =
    //                     _resourcesType.InvokeMember(
    //                     @"ResourceManager",
    //                     BindingFlags.GetProperty | BindingFlags.Static |
    //                     BindingFlags.Public | BindingFlags.NonPublic,
    //                     null,
    //                     null,
    //                     new object[] { }) as ResourceManager;

    //                CultureInfo culture =
    //                     _resourcesType.InvokeMember(
    //                     @"Culture",
    //                     BindingFlags.GetProperty | BindingFlags.Static |
    //                     BindingFlags.Public | BindingFlags.NonPublic,
    //                     null,
    //                     null,
    //                     new object[] { }) as CultureInfo;

    //                _isLocalized = true;

    //                if (resMan != null)
    //                {
    //                    DescriptionValue =
    //                         resMan.GetString(DescriptionValue, culture);
    //                }
    //            }

    //            return DescriptionValue;
    //        }
    //    }

    //    // ------------------------------------------------------------------
    //    #endregion

    //    #region Private variables.
    //    // ------------------------------------------------------------------

    //    private readonly Type _resourcesType;
    //    private bool _isLocalized;

    //    // ------------------------------------------------------------------
    //    #endregion
    //}

    //[ValueConversion(typeof(object), typeof(String))]
    //public class EnumToFriendlyNameConverter : IValueConverter
    //{
    //    #region IValueConverter implementation

    //    /// <summary>
    //    /// Convert value for binding from source object
    //    /// </summary>
    //    public object Convert(object value, Type targetType,
    //            object parameter, CultureInfo culture)
    //    {
    //        // To get around the stupid wpf designer bug
    //        if (value != null)
    //        {
    //            FieldInfo fi = value.GetType().GetField(value.ToString());

    //            // To get around the stupid wpf designer bug
    //            if (fi != null)
    //            {
    //                var attributes =
    //                    (LocalizableDescriptionAttribute[])fi.GetCustomAttributes(typeof(LocalizableDescriptionAttribute), false);

    //                return ((attributes.Length > 0) &&
    //                        (!String.IsNullOrEmpty(attributes[0].Description)))
    //                           ?
    //                               attributes[0].Description
    //                           : value.ToString();
    //            }
    //        }

    //        return string.Empty;
    //    }

    //    /// <summary>
    //    /// ConvertBack value from binding back to source object
    //    /// </summary>
    //    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
    //    {
    //        throw new Exception("Cant convert back");
    //    }
    //    #endregion
    //}

    public class DeferredAction : IDisposable
    {
        private Timer timer;
        //private System.Timers.Timer _difTimer;
        //private Func<object, TextChangedEventArgs> prevAction;

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
            this.timer = new Timer(new TimerCallback(delegate { Application.Current.Dispatcher.Invoke(action); }));
        }

        public void Defer(TimeSpan delay)
        {
            // Fire action when time elapses (with no subsequent calls).
            this.timer.Change(delay, TimeSpan.FromMilliseconds(-1));
            //this.timer.Elapsed += this.Dispose();
        }

        //public void DeferMulti(Func<object, TextChangedEventArgs> action, TimeSpan delay)
        //{
        //    // Fire action when time elapses (with no subsequent calls).
        //    prevAction = action;
        //    this.timer.Change(delay, TimeSpan.FromMilliseconds(-1));
        //}

        public void Dispose()
        {

        }
    }

    internal class ChangeOrderConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            string _coStr;
            if ((bool)value)
            {
                _coStr = "YES";
            }
            else
            {
                _coStr = "NO";
            }
            return _coStr;
        }

        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            bool _coInt;
            if ((string)value == "YES")
            {
                _coInt = true;
            }
            else
            {
                _coInt = false;
            }
            return _coInt;
        }
    }

    internal class StatusToColor : IValueConverter
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

    internal class PercentageConverter : IValueConverter 
    {
        public object Convert(object value, Type targetType, object parameter,
                              System.Globalization.CultureInfo culture)
        {
            if (string.IsNullOrEmpty(value.ToString())) return 0;

            if (value.GetType() == typeof(double)) return (double)value / 100;

            if (value.GetType() == typeof(decimal)) return (decimal)value / 100;

            return value;
        }

        public object ConvertBack(object value, Type targetType, object parameter,
                                  System.Globalization.CultureInfo culture)
        {
            if (string.IsNullOrEmpty(value.ToString())) return 0;

            var trimmedValue = value.ToString().TrimEnd(new char[] { '%' });

            if (targetType == typeof(double))
            {
                double result;
                if (double.TryParse(trimmedValue, out result))
                    return result;
                else
                    return value;
            }

            if (targetType == typeof(decimal))
            {
                decimal result;
                if (decimal.TryParse(trimmedValue, out result))
                    return result;
                else
                    return value;
            }
            return value;
        }
    }

    //Not used
    class IndicatorColor : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture)
        {
            SolidColorBrush retColor = new SolidColorBrush();
            retColor.Color = System.Windows.Media.Color.FromRgb(0, 0, 0);
            if ((string)value == "1")
            {
                //retColor.Color = System.Windows.Media.Color.FromRgb(255, 0, 0);
                retColor.Color = (Color)ColorConverter.ConvertFromString("Orange");
            }
            else if ((string)value == "2")
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("Blue");
            }
            else if ((string)value == "3")
            {
                retColor.Color = (Color)ColorConverter.ConvertFromString("Green");
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

    [ValueConversion(typeof(DateTime), typeof(String))]
    public class DateConverter : IValueConverter
    {
        private const string _format = "dd-MMM-yy";

        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            DateTime date = (DateTime)value;

            return date.ToString(_format);
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            return DateTime.ParseExact((string)value, _format, culture);
        }
    }

    public class BooleanToBrushConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value == null)
                return Brushes.Transparent;

            Brush[] brushes = parameter as Brush[];
            if (brushes == null)
                return Brushes.Transparent;

            bool isTrue;
            bool.TryParse(value.ToString(), out isTrue);

            if (isTrue)
            {
                var brush = (SolidColorBrush)brushes[0];
                return brush ?? Brushes.Transparent;
            }
            else
            {
                var brush = (SolidColorBrush)brushes[1];
                return brush ?? Brushes.Transparent;
            }
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            throw new NotImplementedException();
        }
    }

    #endregion
}
