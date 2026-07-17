//---------------------------------------------------------------------
// 
// Summary: This Sample creates a customer.xml document and passes it to the Microsoft.Dynamics.GP.eConnect assembly. 
//
// Sample: eConnect_CSharp_ConsoleApplication.
//
//---------------------------------------------------------------------
// This file is part of the Microsoft Dynamics GP eConnect Samples.
//
// Copyright (c) Microsoft Corporation. All rights reserved.
//
// This source code is intended only as a supplement to Microsoft Dynamics GP
// eConnect version 12.0.0.0 release and/or on-line documentation. See these other
// materials for detailed information regarding Microsoft code samples.
//
// THIS CODE AND INFORMATION ARE PROVIDED "AS IS" WITHOUT WARRANTY OF ANY
// KIND, WHETHER EXPRESSED OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND/OR FITNESS FOR A PARTICULAR
// PURPOSE.
//---------------------------------------------------------------------

using System;
using System.IO;
using System.Xml;
using System.Text;
using System.Xml.Serialization;
using Microsoft.Dynamics.GP.eConnect;
using Microsoft.Dynamics.GP.eConnect.Serialization;

namespace eConnect_CSharp_ConsoleApplication
{
	class Test
	{
		/// <summary>
		/// The main entry point for the application.
		/// </summary>
		[STAThread]
		static void Main()
		{
			string sCustomerDocument;
			string sXsdSchema;
			string sConnectionString;

            using (eConnectMethods e = new eConnectMethods())
            {
                try
                {
                    // Create the customer data file
                    SerializeCustomerObject("Customer.xml");

                    // Use an XML document to create a string representation of the customer
                    XmlDocument xmldoc = new XmlDocument();
                    xmldoc.Load("Customer.xml");
                    sCustomerDocument = xmldoc.OuterXml;

                    // Specify the Microsoft Dynamics GP server and database in the connection string
                    sConnectionString = @"data source=localhost;initial catalog=TWO;integrated security=SSPI;persist security info=False;packet size=4096";

                    // Create an XML Document object for the schema
                    XmlDocument XsdDoc = new XmlDocument();

                    // Create a string representing the eConnect schema
                    sXsdSchema = XsdDoc.OuterXml;

                    // Pass in xsdSchema to validate against.
                    e.CreateEntity(sConnectionString, sCustomerDocument);
                }
                // The eConnectException class will catch eConnect business logic errors.
                // display the error message on the console
                catch (eConnectException exc)
                {
                    Console.Write(exc.ToString());
                }
                // Catch any system error that might occurr.
                // display the error message on the console
                catch (System.Exception ex)
                {
                    Console.Write(ex.ToString());
                }
                finally
                {
                    // Call the Dispose method to release the resources
                    // of the eConnectMethds object
                    e.Dispose();
                }
            } // end of using statement
		}

		public static void SerializeCustomerObject( string filename )
		{
			try
			{
				// Instantiate an eConnectType schema object
                eConnectType eConnect = new eConnectType();
				
				// Instantiate a RMCustomerMasterType schema object
                RMCustomerMasterType customertype = new RMCustomerMasterType();
                
                // Instantiate a taUpdateCreateCustomerRcd XML node object
                taUpdateCreateCustomerRcd customer = new taUpdateCreateCustomerRcd();
				
                // Create an XML serializer object
                XmlSerializer serializer = new XmlSerializer(eConnect.GetType());

				// Populate elements of the taUpdateCreateCustomerRcd XML node object
                customer.CUSTNMBR = "Customer001";
				customer.CUSTNAME = "Customer 1";
				customer.ADDRESS1 = "2002 60th St SW";
				customer.ADRSCODE = "Primary";
				customer.CITY = "NewCity";
				customer.ZIPCODE = "52302";
					
				// Populate the RMCustomerMasterType schema with the taUpdateCreateCustomerRcd XML node
                customertype.taUpdateCreateCustomerRcd = customer;
				RMCustomerMasterType [] mySMCustomerMaster = {customertype};
				
                // Populate the eConnectType object with the RMCustomerMasterType schema object
                eConnect.RMCustomerMasterType = mySMCustomerMaster;

				// Create objects to create file and write the customer XML to the file
                FileStream fs = new FileStream(filename, FileMode.Create);
				XmlTextWriter writer = new XmlTextWriter(fs, new UTF8Encoding());

				// Serialize the eConnectType object to a file using the XmlTextWriter.
				serializer.Serialize(writer, eConnect);
				writer.Close();
			}
            // catch any errors that occur and display them to the console
			catch (System.Exception ex)
			{
				Console.Write(ex.ToString());
			}
		}
	}
}
