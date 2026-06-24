using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    class GetClassDbTableName
    {
        internal static string GetTableName(object decoratedClassObject)
        {
            var attribs = decoratedClassObject.GetType().GetCustomAttributes(true);
            if (attribs == null)
                return "";
            else
            {
                var classDbTableName = attribs.Where(x => x.GetType() == typeof(mp.TableAttribute)).Where(x => x.GetType().GetProperty("Name") != null).FirstOrDefault();
                if (classDbTableName != null)
                    return ((mp.TableAttribute)classDbTableName).Name;
                else
                    return ""; // object did not have a table attribute associated with it
            }
        }
    }
}
