using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.IO;
using System.Net;

namespace PM_Project_Tracking.TitanApi
{
    public enum httpVerb
    {
        GET,
        POST,
        PUT,
        DELETE
    }

    public enum authenticationType
    {
        Basic,
        NTLM
    }

    public enum autheticationTechnique
    {
        RollYourOwn,
        NetworkCredential
    }

    class RestClient
    {
        public string endPoint { get; set; }
        public httpVerb httpMethod { get; set; }
        public authenticationType authType { get; set; }
        public autheticationTechnique authTech { get; set; }
        public string userName { get; set; }
        public string userPassword { get; set; }


        public RestClient()
        {
            endPoint = string.Empty;
            httpMethod = httpVerb.GET;
        }

        public string makeRequest()
        {
            string strResponseValue = string.Empty;

            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(endPoint);

            request.Method = httpMethod.ToString();

            String authHeaer = System.Convert.ToBase64String(System.Text.ASCIIEncoding.ASCII.GetBytes(userName + ":" + userPassword));
            request.Headers.Add("Authorization", authType.ToString() + " " + authHeaer);

            HttpWebResponse response = null;

            try
            {
                response = (HttpWebResponse)request.GetResponse();


                //Proecess the resppnse stream... (could be JSON, XML or HTML etc..._

                using (Stream responseStream = response.GetResponseStream())
                {
                    if (responseStream != null)
                    {
                        using (StreamReader reader = new StreamReader(responseStream))
                        {
                            strResponseValue = reader.ReadToEnd();
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                strResponseValue = "{\"errorMessages\":[\"" + ex.Message.ToString() + "\"],\"errors\":{}}";
            }
            finally
            {
                if (response != null)
                {
                    ((IDisposable)response).Dispose();
                }
            }

            return strResponseValue;
        }
    }
}
