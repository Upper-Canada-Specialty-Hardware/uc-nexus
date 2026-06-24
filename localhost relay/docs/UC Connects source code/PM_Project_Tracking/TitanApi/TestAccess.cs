using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Net.Http;
using Newtonsoft.Json;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Json;
using to = PM_Project_Tracking.DataClasses.TitanObjects;

namespace PM_Project_Tracking.TitanApi
{
    public class TestAccess
    {
        //https://stackoverflow.com/questions/10928528/receiving-json-data-back-from-http-request
        public async Task<object> TestMethod(TitanProject model)
        {
            string _token = "Bearer eyJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJUSVRBTiIsInN1YiI6IlRlc3R2MSIsImV4cCI6OTIyMzM3MjAzNjg1NDc3NSwiaWF0IjoxNzE0ODU0NTIyLCJqdGkiOiI5NjNhN2FhMi01M2FjLTQwNWMtODc4OC00YzY3MWRkNzYzNGEiLCJiYXNlRW50aXR5SWQiOiI1NTIwNzE3In0.aXnDi67wXeNLTwmZMgQ1Ixxqn0NLwi667HSchsC5mBvoMIfjyJ_spBdN7ypJLKvXeMb6z7mvRLVofrmAFcyX7w";
            try
            {
                var apicallObject = new
                {
                    name = model.name
                };

                if (apicallObject != null)
                {
                    var bodyContent = JsonConvert.SerializeObject(apicallObject);
                    using (HttpClient client = new HttpClient())
                    {
                        System.Net.ServicePointManager.SecurityProtocol = (System.Net.SecurityProtocolType)(768 | 3072);
                        //var content = new StringContent(bodyContent.ToString(), Encoding.UTF8, "application/json");

                        //content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
                        //client.DefaultRequestHeaders.Add("access-token", _token); // _token = access token

                        client.DefaultRequestHeaders.Add("Accept", "application/json"); // _token = access token
                        client.DefaultRequestHeaders.Add("Authorization", _token); // _token = access token
                        var response = await client.GetAsync("https://ucsh.protechtitan.com/titan/api/customer/projects/20"); // _url =api endpoint url
                        if (response != null)
                        {
                            var jsonString = await response.Content.ReadAsStringAsync();

                            try
                            {
                                var result = JsonConvert.DeserializeObject<to.Project>(jsonString, new JsonSerializerSettings
                                {
                                    DateFormatString = "d MMMM, yyyy"
                                }); // TestModel2 = deserialize object
                            }
                            catch (HttpRequestException httpEx)
                            {
                                throw httpEx;
                            }
                            catch (Exception e)
                            {
                                //msg
                                throw e;
                            }
                        }
                    }
                }
            }
            catch (HttpRequestException httpEx)
            {
                throw httpEx;
            }
            //catch (Exception ex)
            //{
            //    throw ex;
            //}
            return null;
        }

        public async Task<object> TestMethodTwo(TitanProject model)
        {
            object asdf;
            string _token = "Bearer eyJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJUSVRBTiIsInN1YiI6IlRlc3R2MSIsImV4cCI6OTIyMzM3MjAzNjg1NDc3NSwiaWF0IjoxNzE0ODU0NTIyLCJqdGkiOiI5NjNhN2FhMi01M2FjLTQwNWMtODc4OC00YzY3MWRkNzYzNGEiLCJiYXNlRW50aXR5SWQiOiI1NTIwNzE3In0.aXnDi67wXeNLTwmZMgQ1Ixxqn0NLwi667HSchsC5mBvoMIfjyJ_spBdN7ypJLKvXeMb6z7mvRLVofrmAFcyX7w";
            try
            {
                var apicallObject = new
                {
                    name = model.name
                };

                if (apicallObject != null)
                {
                    var bodyContent = JsonConvert.SerializeObject(apicallObject);
                    using (HttpClient client = new HttpClient())
                    {
                        //client.DefaultRequestHeaders.Add("access-token", _token);
                        System.Net.ServicePointManager.SecurityProtocol = (System.Net.SecurityProtocolType)(768 | 3072);
                        var request = new HttpRequestMessage()
                        {
                            RequestUri = new Uri("https://ucsh.protechtitan.com/titan/api/customer/projects/20"),
                            Method = HttpMethod.Get,
                        };
                        //request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
                        //client.DefaultRequestHeaders.Add("access-token", _token);
                        //client.DefaultRequestHeaders.Add("location", "/titan/api/customer/projects/20");
                        client.DefaultRequestHeaders.Add("Accept", "application/json");
                        client.DefaultRequestHeaders.Add("Authorization", _token);
                        var task = client.SendAsync(request).ContinueWith((taskwithmsg) =>
                            {
                                var response = taskwithmsg.Result;

                                var jsonTask = response.Content.ReadAsAsync<JsonObject>();
                                jsonTask.Wait();
                                var jsonObject = jsonTask.Result;
                                asdf = jsonTask.Result;
                            });
                        task.Wait();
                    }
                }
            }
            catch (HttpRequestException httpEx)
            {
                throw httpEx;
            }
            catch (Exception ex)
            {
                throw ex;
            }
            return null;
        }
    }

    public class TitanProject
    {
        string _name;
        public string name
        {
            get { return _name; }
            set { _name = value; }
        }
    }
}
