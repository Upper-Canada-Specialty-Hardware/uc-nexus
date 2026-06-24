using System;
using System.Collections.Generic;
using System.Linq;
using lq = System.Data.Linq; //Added
using mp = System.Data.Linq.Mapping; //Added
using System.Text;
using System.Threading.Tasks;
using uc = PM_Project_Tracking.DataClasses.UtilityClasses;

namespace PM_Project_Tracking.DataClasses.GpObjects
{
    [mp.Table(Name = "[SOP10202]")]
    public class Sop10202
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _docNumber;
        private int _lineSeq;
        private string _lineComment;

        [mp.Column(Name = "SOPNUMBE")]
        public string DocNumber
        {
            get { return _docNumber; }
            set { _docNumber = value; }
        }

        [mp.Column(Name = "LNITMSEQ")]
        public int LineSeq
        {
            get { return _lineSeq; }
            set { _lineSeq = value; }
        }

        [mp.Column(Name = "CMMTTEXT")]
        public string LineComment
        {
            get { return _lineComment; }
            set { _lineComment = value; }
        }
    }
}
