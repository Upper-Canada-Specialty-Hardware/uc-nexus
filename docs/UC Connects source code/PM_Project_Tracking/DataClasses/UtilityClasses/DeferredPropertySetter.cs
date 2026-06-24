using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace PM_Project_Tracking.DataClasses.UtilityClasses
{
    [Serializable]
    public class DeferredPropertySetter
    {
        //https://stackoverflow.com/questions/4911920/c-sharp-deferred-property-setting
        interface Setter
        {
            void Apply();
        }
        class Setter<T> : Setter
        {
            public T Data;
            public Action<T> SetFn;
            public void Apply()
            {
                SetFn(Data);
            }
        }

        List<Setter> changeQueue = new List<Setter>();

        public void SetValue<T>(Action<T> setFn, T data)
        {
            changeQueue.Add(new Setter<T>
            {
                Data = data,
                SetFn = setFn,
            });
        }

        public void ApplyChanges()
        {
            foreach (var s in changeQueue)
            {
                s.Apply();
            }
        }
    }
}
