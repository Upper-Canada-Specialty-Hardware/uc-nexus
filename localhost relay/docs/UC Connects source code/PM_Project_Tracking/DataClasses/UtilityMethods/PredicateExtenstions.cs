using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.UtilityMethods
{
    //http://stackoverflow.com/questions/1248232/combine-multiple-predicates
    class PredicateExtenstions
    {
        public static Predicate<T> Or<T>(params Predicate<T>[] predicates)
        {
            return delegate(T item)
            {
                foreach (Predicate<T> predicate in predicates)
                {
                    if (predicate(item))
                    {
                        return true;
                    }
                }
                return false;
            };
        }
    }
}
