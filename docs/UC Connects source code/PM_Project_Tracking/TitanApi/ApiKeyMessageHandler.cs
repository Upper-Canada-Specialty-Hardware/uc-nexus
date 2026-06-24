using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Net.Http;

namespace PM_Project_Tracking.TitanApi
{
    public class ApiKeyMessageHandler : DelegatingHandler
    {
        private static readonly string ApiKeyToValidate = "eyJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJUSVRBTiIsInN1YiI6IlRlc3R2MSIsImV4cCI6OTIyMzM3MjAzNjg1NDc3NSwiaWF0IjoxNzE0ODU0NTIyLCJqdGkiOiI5NjNhN2FhMi01M2FjLTQwNWMtODc4OC00YzY3MWRkNzYzNGEiLCJiYXNlRW50aXR5SWQiOiI1NTIwNzE3In0.aXnDi67wXeNLTwmZMgQ1Ixxqn0NLwi667HSchsC5mBvoMIfjyJ_spBdN7ypJLKvXeMb6z7mvRLVofrmAFcyX7w";

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, System.Threading.CancellationToken cancellationToken)
        {
            var isValidKey = false;
            IEnumerable<string> requestHeaders;
            var checkApiKeyExists = request.Headers.TryGetValues("ApiKey", out requestHeaders);
            if (checkApiKeyExists)
            {
                if (requestHeaders.FirstOrDefault().Equals(ApiKeyToValidate))
                {
                    isValidKey = true;
                }
            }

            if (!isValidKey)
            {
                return request.CreateResponse();
            }

            var resposne = await base.SendAsync(request, cancellationToken);
            return resposne;
        }
    }
}
