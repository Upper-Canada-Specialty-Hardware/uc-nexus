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
    [mp.Table(Name = "[POP10150]")]
    class Pop10150
    {
        public static Enum TableFamily = uc.EnumTableFamily.GP;

        private string _poNumber;
        private string _commentId;
        private string _commentOne;
        private string _commentTwo;
        private string _commentThree;
        private string _commentFour;
        private string _commentText;

        [mp.Column(Name = "POPNUMBE")]
        public string PoNumber
        {
            get { return _poNumber; }
            set { _poNumber = value; }
        }

        [mp.Column(Name = "COMMNTID")]
        public string CommentId
        {
            get { return _commentId; }
            set { _commentId = value; }
        }

        [mp.Column(Name = "COMMENT_1")]
        public string CommentOne
        {
            get { return _commentOne; }
            set { _commentOne = value; }
        }

        [mp.Column(Name = "COMMENT_2")]
        public string CommentTwo
        {
            get { return _commentTwo; }
            set { _commentTwo = value; }
        }

        [mp.Column(Name = "COMMENT_3")]
        public string CommentThree
        {
            get { return _commentThree; }
            set { _commentThree = value; }
        }

        [mp.Column(Name = "COMMENT_4")]
        public string CommentFour
        {
            get { return _commentFour; }
            set { _commentFour = value; }
        }

        [mp.Column(Name = "CMMTTEXT")]
        public string CommentText
        {
            get { return _commentText; }
            set { _commentText = value; }
        }
    }
}
