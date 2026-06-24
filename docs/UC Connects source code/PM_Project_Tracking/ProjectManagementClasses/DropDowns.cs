using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using lq = System.Data.Linq; //Added
using dc = PM_Project_Tracking.DataClasses;
using um = PM_Project_Tracking.DataClasses.UtilityMethods;
using System.Windows;

namespace PM_Project_Tracking.ProjectManagementClasses
{
    public class CostCodeDropDowns : List<CostCodeType>
    {
        public CostCodeDropDowns()
        {
            this.Add(new CostCodeType() { CostCode = "210-200-2", Description = "Supply Hardware" });
            this.Add(new CostCodeType() { CostCode = "220-000-2", Description = "Supply Washroom Accessories" });
            this.Add(new CostCodeType() { CostCode = "310-000-3", Description = "Supply HM Frames & Screens" });
            this.Add(new CostCodeType() { CostCode = "320-000-3", Description = "Supply Hollow Metal Doors" });
            this.Add(new CostCodeType() { CostCode = "330-000-3", Description = "Supply Wood Doors & Frames" });
            this.Add(new CostCodeType() { CostCode = "340-000-3", Description = "Supply Glazing" });
            this.Add(new CostCodeType() { CostCode = "350-000-3", Description = "Specialty Doors & Frames" });
            this.Add(new CostCodeType() { CostCode = "410-000-4", Description = "Supply Auto Door Operator" });
            this.Add(new CostCodeType() { CostCode = "430-000-4", Description = "Install Auto Door Operators" });
            this.Add(new CostCodeType() { CostCode = "440-000-4", Description = "Install/Comm Electrical Integration Hardware" });
            this.Add(new CostCodeType() { CostCode = "450-000-4", Description = "Shop Installation Hardware" });
            this.Add(new CostCodeType() { CostCode = "460-000-4", Description = "Shop Installation Glazing" });
            this.Add(new CostCodeType() { CostCode = "510-000-5", Description = "Field Install Doors & Hardware" });
            this.Add(new CostCodeType() { CostCode = "520-000-5", Description = "Field Install Frames" });
            this.Add(new CostCodeType() { CostCode = "530-000-5", Description = "Warranty Work" });
            this.Add(new CostCodeType() { CostCode = "540-000-5", Description = "Service Work" });
            this.Add(new CostCodeType() { CostCode = "550-000-5", Description = "Shop Installation of Hardware" });
            this.Add(new CostCodeType() { CostCode = "560-000-5", Description = "Shop Installation of Glazing" });
            this.Add(new CostCodeType() { CostCode = "570-000-5", Description = "Remedial Work" });
            this.Add(new CostCodeType() { CostCode = "580-000-5", Description = "Travel (UCI)" });
            this.Add(new CostCodeType() { CostCode = "610-000-6", Description = "Install Frames (3rd Party)" });
            this.Add(new CostCodeType() { CostCode = "620-000-6", Description = "Install Doors & Hardware (3rd Party)" });
            this.Add(new CostCodeType() { CostCode = "630-000-6", Description = "Remedial Work (3rd Party)" });
            this.Add(new CostCodeType() { CostCode = "640-000-6", Description = "Supply & Install Auto Op (3rd Party)" });
            this.Add(new CostCodeType() { CostCode = "710-000-7", Description = "Travel Expenses" });
            this.Add(new CostCodeType() { CostCode = "720-000-7", Description = "Automobile Expenses" });
            this.Add(new CostCodeType() { CostCode = "730-000-7", Description = "Gas Expenses" });
            this.Add(new CostCodeType() { CostCode = "800-000-8", Description = "Freight" });
            this.Add(new CostCodeType() { CostCode = "900-000-9", Description = "MISC" });
        }
    }

    public class CostDropDownTwo : List<string>
    {
        public CostDropDownTwo()
        {
            this.Add("210-200-2");
            this.Add("220-000-2");
            this.Add("310-000-3");
            this.Add("320-000-3");
            this.Add("330-000-3");
        }
    }

    public class SubmittalItemType : List<string> //MainProject - Hardware, DoorsAndFrames, UCA
    {
        public SubmittalItemType()
        {
            this.Add("SHOP DRAWING");
            this.Add("SAMPLE");
            this.Add("HARDWARE SCHEDULE");
            this.Add("");
        }
    }

    public class CostCodeType
    {
        private string _costCode;
        private string _Description;

        public string CostCode
        {
            get { return _costCode; }
            set { _costCode = value; }
        }

        public string Description
        {
            get { return _Description; }
            set { _Description = value; }
        }
    }

    internal class LabourValuePair
    {
        private int _key;
        private string _value;

        public int Key
        {
            get { return _key; }
            set { _key = value; }
        }

        public string Value
        {
            get { return _value; }
            set { _value = value; }
        }

        public LabourValuePair(int key, string value)
        {
            _key = key;
            _value = value;
        }
    }

    internal class LabourValueContainer : List<LabourValuePair>
    {
        public LabourValueContainer()
        {
            this.Add(new LabourValuePair(1, "Indeterminate"));
            this.Add(new LabourValuePair(2, "Consulting"));
            this.Add(new LabourValuePair(3, "Shop Drawing Revision"));
            this.Add(new LabourValuePair(4, "Project Management"));
            this.Add(new LabourValuePair(5, "Coordinator"));
        }
    }

    internal class UserCompleteList : ObservableCollection<dc.User>
    {
        public UserCompleteList()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<dc.User> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<dc.User>().Select(x => x).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                System.Diagnostics.Debug.Print(this.Items.Count.ToString());
            }
            finally
            {
                dtCtx.Dispose();
            }
            //Obvervablecollection doesn't support .AddRange method but I fanatically wanted to keep this to one line.  Voila: (see below)
            viewsList.ForEach(delegate (dc.User x) { this.Add(x); });
        }
    }

    internal class GetAllUserList : List<string>
    {
        public GetAllUserList()
        {
            ObservableCollection<dc.User> _taskUserCol = null;
            List<string> _users = null;
            try
            {
                _taskUserCol = dc.Users.GetUsers();
                _users = _taskUserCol.Select(x => x.DomainUserName).ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                this.AddRange(new List<string>());
            }

            this.AddRange(_users);
        }
    }

    public class UserTwoTest : List<string>
    {
        public UserTwoTest()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<string> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<dc.User>().Select(x => x.DomainUserName).Distinct().ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                this.AddRange(new List<string>());
            }
            finally
            {
                dtCtx.Dispose();
            }

            this.AddRange(viewsList);
        }
    }

    public class UserTwoObjects : List<dc.User>
    {
        public UserTwoObjects()
        {
            lq.DataContext tempdtCtx = new lq.DataContext(GlobalVars.UcshConnectionString);
            lq.DataContext dtCtx = new lq.DataContext(GlobalVars.UcshConnectionString, um.DatabaseSwitcher.Convert(ref tempdtCtx));
            List<dc.User> viewsList = null;

            try
            {
                viewsList = dtCtx.GetTable<dc.User>().ToList();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.ToString());
                this.AddRange(new List<dc.User>());
            }
            finally
            {
                dtCtx.Dispose();
            }

            this.AddRange(viewsList);
        }
    }

    public class SampleShipmentCommercialRetail : List<string>
    {
        public SampleShipmentCommercialRetail()
        {
            this.Add("Commercial");
            this.Add("Retail");
        }
    }

}
