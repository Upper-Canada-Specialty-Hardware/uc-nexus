using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using dc = PM_Project_Tracking.DataClasses;
using gp = PM_Project_Tracking.DataClasses.GpObjects;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;
using pm = PM_Project_Tracking.ProjectManagementClasses;
using System.Reflection;
using System.Windows;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    public static class DatabaseSwitcher
    {
        public static uc.OverrideMappingSource Convert(ref lq.DataContext dtCtx)
        {
            LoadAllEntities(ref dtCtx);
            uc.OverrideMappingSource overrideSource = SwapMappingSources(ref dtCtx);
            ChangeQualifiedTableNames(dtCtx.Mapping.GetTables(), ref overrideSource);
            return overrideSource;
        }

        private static void LoadAllEntities(ref lq.DataContext dtCtx)
        {
            RelationalObjects relObj = new RelationalObjects();
            foreach (Type tb in relObj)
            {
                dtCtx.GetTable(tb);
            }
        }

        private static uc.OverrideMappingSource SwapMappingSources(ref lq.DataContext dtCtx)
        {
            var realSource = dtCtx.Mapping.MappingSource;
            var overrrideSource = new uc.OverrideMappingSource(realSource);
            return overrrideSource;
        }

        private static void ChangeQualifiedTableNames(IEnumerable<mp.MetaTable> tableCol, ref uc.OverrideMappingSource overSource)
        {
            uc.EnumTableFamily tabFam;
            foreach (mp.MetaTable tb in tableCol)
            {
                Type tempType = Type.GetType(tb.RowType.Type.FullName);
                try
                {
                    tabFam = (uc.EnumTableFamily)tempType.GetField("TableFamily").GetValue(tempType);

                    if (tabFam == uc.EnumTableFamily.GP)
                        overSource.OverrideTable(tempType, "[" + GlobalVars.CurrentGpDatabaseName + "].[dbo]." + tb.TableName);
                    else if (tabFam == uc.EnumTableFamily.UCSH)
                        overSource.OverrideTable(tempType, "[" + GlobalVars.CurrentPmDatabaseName + "].[dbo]." + tb.TableName);
                }
                catch (Exception ex)
                {
                    MessageBox.Show(ex.ToString());
                    throw new Exception("Class " + tb.RowType.Type.FullName + @" likely did not implement TableFamily enum or have LINQ attribute mapping." +
                                                                                "Current table or object is: " + tempType.Name);
                }
            }
        }
    }

    public class RelationalObjects : List<Type>
    {
        public RelationalObjects()
        {
            this.Add(typeof(gp.Jc00102));
            this.Add(typeof(gp.Jc00701));
            this.Add(typeof(gp.Jc00901));
            this.Add(typeof(gp.Jc20001));
            this.Add(typeof(gp.Pm00200));
            this.Add(typeof(gp.Pop10100));
            this.Add(typeof(gp.Pop10110));
            this.Add(typeof(gp.Pop10150));
            this.Add(typeof(gp.Pop30300));
            this.Add(typeof(gp.Pop10500));
            this.Add(typeof(gp.Pop10550));
            this.Add(typeof(gp.Rm00101));
            this.Add(typeof(gp.Rm00102));
            this.Add(typeof(gp.Sop10100));
            this.Add(typeof(gp.Sop10200));
            this.Add(typeof(gp.Sop10202));
            this.Add(typeof(gp.Sop30200));
            this.Add(typeof(gp.Sop30300));
            this.Add(typeof(gp.Sop60100));
            this.Add(typeof(gp.Ws10101));
            //this.Add(typeof(dc.HardwareSchedule)); //Not decorated with LINQ attributes.  All the decorated AVA tables that feed into 'HardwareSchedule' are hard coded because there's no test DB for AVA
            //Reserved for Fusion objects in Hardware class
            this.Add(typeof(dc.Pursuit));
            this.Add(typeof(dc.ShopDrawingLine));
            this.Add(typeof(dc.OfferToTender));
            this.Add(typeof(dc.BidProject));
            this.Add(typeof(dc.QuoteSummary));
            this.Add(typeof(dc.AwardedContract));
            this.Add(typeof(dc.MainProject));
            //Project Management Classes
            this.Add(typeof(pm.ChangeIndex));
            this.Add(typeof(pm.ChangeHeader));
            this.Add(typeof(pm.ChangeLine));
            this.Add(typeof(pm.ProgressBillingHeader));
            this.Add(typeof(pm.ProgressBillingLine));
            this.Add(typeof(pm.ChangeLineDrawDown));
            this.Add(typeof(pm.RequestForInfo));
            this.Add(typeof(pm.SubmittalHeader));
            this.Add(typeof(pm.SubmittalLine));
            this.Add(typeof(uc.RecLineTracker));
            this.Add(typeof(pm.TaskSchedulerItem));
            this.Add(typeof(pm.TaskEnum));
            //Path Schema Classes
            this.Add(typeof(dc.JobPathRoot));
            this.Add(typeof(dc.DrivePath));
            //this.Add(typeof(dc.CombinedProject));  //Not decorated because it's a composite class
            this.Add(typeof(dc.PoConfirmation));
            this.Add(typeof(dc.PurchaseOrderHeader));
            this.Add(typeof(dc.PoUcshHeaderComment));
            this.Add(typeof(dc.PoUcshLineComment));
            //this.Add(typeof(dc.PurchaseOrderLineItem));  //Not decorated because it's a composite class
            //Sop Link
            this.Add(typeof(dc.SopLink));
 
            this.Add(typeof(dc.User));
            this.Add(typeof(dc.UserOverride));
            this.Add(typeof(dc.UserAssociation));
            this.Add(typeof(dc.UserRole));
            this.Add(typeof(dc.UserRoleList));
            this.Add(typeof(dc.ReceivingLine));
            this.Add(typeof(dc.ShippingHeader));
            this.Add(typeof(dc.ShippingLine));
            //
           
            //this.Add(typeof(pm.ChangeOrder));
            //this.Add(typeof(pm.ProgressBilling));
        }
    }
}