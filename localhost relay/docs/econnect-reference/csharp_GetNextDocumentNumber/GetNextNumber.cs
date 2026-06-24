//---------------------------------------------------------------------
// 
// Summary: This sample uses the Microsoft.Dynamics.GP.eConnect.MiscRoutines 
//			to get the next document numbers for SOP, PM, PO, IV, and SOP Payments. 
//
// Sample: DocumentNumberSample.
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
using System.Drawing;
using System.Collections;
using System.ComponentModel;
using System.Windows.Forms;
using System.Data;
using Microsoft.Dynamics.GP.eConnect;

namespace DocumentNumberSample
{
	/// <summary>
	/// Summary description for Form1.
	/// </summary>
	public class frmGetNextNumber : System.Windows.Forms.Form
	{
		private System.Windows.Forms.GroupBox groupBox1;
		private System.Windows.Forms.Label label1;
		private System.Windows.Forms.Label label2;
		private System.Windows.Forms.Label label3;
		private System.Windows.Forms.Label label4;
		private System.Windows.Forms.Label label5;
		private System.Windows.Forms.Label lblSOPNUMBER;
		private System.Windows.Forms.Label lblPMNUMBER;
		private System.Windows.Forms.Label lblSOPPAYMENT;
		private System.Windows.Forms.Label lblIVDOCNUMBER;
		private System.Windows.Forms.Label lblPONUMBER;
		private System.Windows.Forms.TextBox txtSqlServer;
		private System.Windows.Forms.TextBox txtDataBase;
		private System.Windows.Forms.Label label6;
		private System.Windows.Forms.Label label7;
		private System.Windows.Forms.Button btnGetNextNumber;
		/// <summary>
		/// Required designer variable.
		/// </summary>
		private System.ComponentModel.Container components = null;

		public frmGetNextNumber()
		{
			// Required for Windows Form Designer support
			InitializeComponent();
		}

		/// <summary>
		/// Clean up any resources being used.
		/// </summary>
		protected override void Dispose( bool disposing )
		{
			if( disposing )
			{
				if (components != null) 
				{
					components.Dispose();
				}
			}
			base.Dispose( disposing );
		}

		#region Windows Form Designer generated code
		/// <summary>
		/// Required method for Designer support - do not modify
		/// the contents of this method with the code editor.
		/// </summary>
		private void InitializeComponent()
		{
            this.groupBox1 = new System.Windows.Forms.GroupBox();
            this.label7 = new System.Windows.Forms.Label();
            this.label6 = new System.Windows.Forms.Label();
            this.txtDataBase = new System.Windows.Forms.TextBox();
            this.txtSqlServer = new System.Windows.Forms.TextBox();
            this.lblPONUMBER = new System.Windows.Forms.Label();
            this.lblIVDOCNUMBER = new System.Windows.Forms.Label();
            this.lblSOPPAYMENT = new System.Windows.Forms.Label();
            this.lblPMNUMBER = new System.Windows.Forms.Label();
            this.lblSOPNUMBER = new System.Windows.Forms.Label();
            this.label5 = new System.Windows.Forms.Label();
            this.label4 = new System.Windows.Forms.Label();
            this.label3 = new System.Windows.Forms.Label();
            this.label2 = new System.Windows.Forms.Label();
            this.label1 = new System.Windows.Forms.Label();
            this.btnGetNextNumber = new System.Windows.Forms.Button();
            this.groupBox1.SuspendLayout();
            this.SuspendLayout();
            // 
            // groupBox1
            // 
            this.groupBox1.Controls.Add(this.label7);
            this.groupBox1.Controls.Add(this.label6);
            this.groupBox1.Controls.Add(this.txtDataBase);
            this.groupBox1.Controls.Add(this.txtSqlServer);
            this.groupBox1.Controls.Add(this.lblPONUMBER);
            this.groupBox1.Controls.Add(this.lblIVDOCNUMBER);
            this.groupBox1.Controls.Add(this.lblSOPPAYMENT);
            this.groupBox1.Controls.Add(this.lblPMNUMBER);
            this.groupBox1.Controls.Add(this.lblSOPNUMBER);
            this.groupBox1.Controls.Add(this.label5);
            this.groupBox1.Controls.Add(this.label4);
            this.groupBox1.Controls.Add(this.label3);
            this.groupBox1.Controls.Add(this.label2);
            this.groupBox1.Controls.Add(this.label1);
            this.groupBox1.Location = new System.Drawing.Point(8, 8);
            this.groupBox1.Name = "groupBox1";
            this.groupBox1.Size = new System.Drawing.Size(280, 200);
            this.groupBox1.TabIndex = 0;
            this.groupBox1.TabStop = false;
            // 
            // label7
            // 
            this.label7.Location = new System.Drawing.Point(8, 168);
            this.label7.Name = "label7";
            this.label7.Size = new System.Drawing.Size(80, 23);
            this.label7.TabIndex = 15;
            this.label7.Text = "Database:";
            // 
            // label6
            // 
            this.label6.Location = new System.Drawing.Point(8, 144);
            this.label6.Name = "label6";
            this.label6.Size = new System.Drawing.Size(80, 23);
            this.label6.TabIndex = 14;
            this.label6.Text = "SQL Server:";
            // 
            // txtDataBase
            // 
            this.txtDataBase.Location = new System.Drawing.Point(88, 168);
            this.txtDataBase.Name = "txtDataBase";
            this.txtDataBase.Size = new System.Drawing.Size(176, 20);
            this.txtDataBase.TabIndex = 13;
            // 
            // txtSqlServer
            // 
            this.txtSqlServer.Location = new System.Drawing.Point(88, 144);
            this.txtSqlServer.Name = "txtSqlServer";
            this.txtSqlServer.Size = new System.Drawing.Size(176, 20);
            this.txtSqlServer.TabIndex = 12;
            // 
            // lblPONUMBER
            // 
            this.lblPONUMBER.Location = new System.Drawing.Point(120, 112);
            this.lblPONUMBER.Name = "lblPONUMBER";
            this.lblPONUMBER.Size = new System.Drawing.Size(136, 23);
            this.lblPONUMBER.TabIndex = 9;
            // 
            // lblIVDOCNUMBER
            // 
            this.lblIVDOCNUMBER.Location = new System.Drawing.Point(120, 88);
            this.lblIVDOCNUMBER.Name = "lblIVDOCNUMBER";
            this.lblIVDOCNUMBER.Size = new System.Drawing.Size(136, 23);
            this.lblIVDOCNUMBER.TabIndex = 8;
            // 
            // lblSOPPAYMENT
            // 
            this.lblSOPPAYMENT.Location = new System.Drawing.Point(120, 64);
            this.lblSOPPAYMENT.Name = "lblSOPPAYMENT";
            this.lblSOPPAYMENT.Size = new System.Drawing.Size(136, 23);
            this.lblSOPPAYMENT.TabIndex = 7;
            // 
            // lblPMNUMBER
            // 
            this.lblPMNUMBER.Location = new System.Drawing.Point(120, 40);
            this.lblPMNUMBER.Name = "lblPMNUMBER";
            this.lblPMNUMBER.Size = new System.Drawing.Size(144, 23);
            this.lblPMNUMBER.TabIndex = 6;
            // 
            // lblSOPNUMBER
            // 
            this.lblSOPNUMBER.Location = new System.Drawing.Point(120, 16);
            this.lblSOPNUMBER.Name = "lblSOPNUMBER";
            this.lblSOPNUMBER.Size = new System.Drawing.Size(144, 23);
            this.lblSOPNUMBER.TabIndex = 5;
            // 
            // label5
            // 
            this.label5.Location = new System.Drawing.Point(16, 112);
            this.label5.Name = "label5";
            this.label5.Size = new System.Drawing.Size(100, 23);
            this.label5.TabIndex = 4;
            this.label5.Text = "PO NUMBER:";
            // 
            // label4
            // 
            this.label4.Location = new System.Drawing.Point(16, 88);
            this.label4.Name = "label4";
            this.label4.Size = new System.Drawing.Size(100, 23);
            this.label4.TabIndex = 3;
            this.label4.Text = "IV DOC NUMBER:";
            // 
            // label3
            // 
            this.label3.Location = new System.Drawing.Point(16, 64);
            this.label3.Name = "label3";
            this.label3.Size = new System.Drawing.Size(100, 23);
            this.label3.TabIndex = 2;
            this.label3.Text = "SOP PAYMENT:";
            // 
            // label2
            // 
            this.label2.Location = new System.Drawing.Point(16, 40);
            this.label2.Name = "label2";
            this.label2.Size = new System.Drawing.Size(100, 23);
            this.label2.TabIndex = 1;
            this.label2.Text = "PM NUMBER:";
            // 
            // label1
            // 
            this.label1.Location = new System.Drawing.Point(16, 16);
            this.label1.Name = "label1";
            this.label1.Size = new System.Drawing.Size(100, 23);
            this.label1.TabIndex = 0;
            this.label1.Text = "SOP NUMBER:";
            // 
            // btnGetNextNumber
            // 
            this.btnGetNextNumber.Location = new System.Drawing.Point(8, 216);
            this.btnGetNextNumber.Name = "btnGetNextNumber";
            this.btnGetNextNumber.Size = new System.Drawing.Size(280, 40);
            this.btnGetNextNumber.TabIndex = 1;
            this.btnGetNextNumber.Text = "Get Next Numbers";
            this.btnGetNextNumber.Click += new System.EventHandler(this.btnGetNextNumber_Click);
            // 
            // frmGetNextNumber
            // 
            this.AutoScaleBaseSize = new System.Drawing.Size(5, 13);
            this.ClientSize = new System.Drawing.Size(292, 261);
            this.Controls.Add(this.btnGetNextNumber);
            this.Controls.Add(this.groupBox1);
            this.Name = "frmGetNextNumber";
            this.Text = "Get Next Numbers";
            this.groupBox1.ResumeLayout(false);
            this.groupBox1.PerformLayout();
            this.ResumeLayout(false);

		}
		#endregion

		/// <summary>
		/// The main entry point for the application.
		/// </summary>
		[STAThread]
		static void Main() 
		{
			Application.Run(new frmGetNextNumber());
		}

		// Use the button's click event to retrieve the next available document 
        // numbers for Microsoft Dynamics GP documents.
        private void btnGetNextNumber_Click(object sender, System.EventArgs e)
		{
            // Instantiate a GetNextDocNumbers object
            GetNextDocNumbers myDocNumbers = new GetNextDocNumbers();

            // Instantiate a GetSopNumber object
            GetSopNumber mySopNumber = new GetSopNumber();

            try
            {
                // Create a string that specifies the Microsoft Dynamics GP server and database
                // The server name and database will use the values supplied by the user through the UI textboxes.
                string connString = string.Empty;
                connString = "data source=" + txtSqlServer.Text + ";" + "initial catalog=" + txtDataBase.Text + ";" + "Integrated Security=SSPI;";

                // Use the GetNextSopNumber method of the GetSopNumber object to retrieve the next 
                // number for a Microsoft Dynamics GP invoice document
                lblSOPNUMBER.Text = mySopNumber.GetNextSopNumber(3, "STDINV", connString);

                // Use each method of the GetNextDocNumber object to retrieve the next document number 
                // for the available Microsoft Dynamics GP document types
                lblPMNUMBER.Text = myDocNumbers.GetPMNextVoucherNumber(IncrementDecrement.Increment, connString);
                lblSOPPAYMENT.Text = myDocNumbers.GetNextRMNumber(IncrementDecrement.Increment, RMPaymentType.RMPayments, connString);
                lblIVDOCNUMBER.Text = myDocNumbers.GetNextIVNumber(IncrementDecrement.Increment, IVDocType.IVAdjustment, connString);
                lblPONUMBER.Text = myDocNumbers.GetNextPONumber(IncrementDecrement.Increment, connString);
            }
            catch (Exception ex)
            {// If an error occurs, diplay the error information to the user
                MessageBox.Show(ex.ToString());
            }
            finally
            {
                // Release the resources of the GetNextDocNumber and GetSoopNumber objects
                myDocNumbers.Dispose();
                mySopNumber.Dispose();
            }
		}
	}
}
