using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using dc = PM_Project_Tracking.DataClasses;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    public static class RemoveNoQuantityPoReceipts
    {
        public static void Removal(ref ObservableCollection<dc.ReceivingLine> rlCol)
        {
            for (int x = rlCol.Count - 1; x >= 0; x--)
            {
                if (rlCol[x].QtyRecForGp == 0)
                    rlCol.Remove(rlCol[x]);
            }
        }
    }
}
