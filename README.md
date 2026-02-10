# Epic: Develop SAP Application with Purchasing, Warehouse, and Customer Modules

---

# Core User Flows

# Core User Flows

This document defines the step-by-step user journeys for the SAP door hardware management application. Each flow describes user actions, UI feedback, and navigation patterns.

## Navigation Structure

### Global Layout

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; }
.layout { display: flex; height: 100vh; }
.sidebar { width: 240px; background: #f5f5f5; border-right: 1px solid #ddd; padding: 16px; }
.main { flex: 1; display: flex; flex-direction: column; }
.header { height: 60px; background: white; border-bottom: 1px solid #ddd; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; }
.content { flex: 1; padding: 24px; overflow-y: auto; background: #fafafa; }
.module-section { margin-bottom: 24px; }
.module-title { font-weight: 600; font-size: 12px; color: #666; margin-bottom: 8px; text-transform: uppercase; }
.nav-item { padding: 8px 12px; margin-bottom: 4px; border-radius: 4px; cursor: pointer; }
.nav-item:hover { background: #e5e5e5; }
.nav-item.active { background: #2563eb; color: white; }
.project-selector { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; min-width: 300px; }
.user-menu { display: flex; align-items: center; gap: 12px; }
.notification-bell { width: 24px; height: 24px; cursor: pointer; }
</style>
</head>
<body>
<div class="layout">
  <div class="sidebar">
    <div style="font-weight: 700; font-size: 18px; margin-bottom: 24px;">UC Covet SAP</div>
    
    <div class="module-section">
      <div class="module-title">Main</div>
      <div class="nav-item active" data-element-id="nav-dashboard">Dashboard</div>
    </div>
    
    <div class="module-section">
      <div class="module-title">Project Management</div>
      <div class="nav-item" data-element-id="nav-projects">Projects</div>
      <div class="nav-item" data-element-id="nav-purchase-requests">Purchase Requests</div>
      <div class="nav-item" data-element-id="nav-checkout">Checkout</div>
    </div>
    
    <div class="module-section">
      <div class="module-title">Purchasing</div>
      <div class="nav-item" data-element-id="nav-vendors">Vendors</div>
      <div class="nav-item" data-element-id="nav-purchase-orders">Purchase Orders</div>
    </div>
    
    <div class="module-section">
      <div class="module-title">Warehouse</div>
      <div class="nav-item" data-element-id="nav-receiving">Receiving</div>
      <div class="nav-item" data-element-id="nav-pulls">Pull Requests</div>
      <div class="nav-item" data-element-id="nav-inventory">Inventory</div>
    </div>
    
    <div class="module-section">
      <div class="module-title">Assembly</div>
      <div class="nav-item" data-element-id="nav-assembly">Assembly Work</div>
    </div>
  </div>
  
  <div class="main">
    <div class="header">
      <select class="project-selector" data-element-id="project-selector">
        <option>All Projects</option>
        <option>Project 74 - Main Street Building</option>
        <option>Project 82 - Downtown Office</option>
      </select>
      
      <div class="user-menu">
        <div class="notification-bell" data-element-id="notifications">🔔</div>
        <div data-element-id="user-menu">John Doe (Admin)</div>
      </div>
    </div>
    
    <div class="content">
      <h1>Dashboard</h1>
      <p style="color: #666;">Main content area</p>
    </div>
  </div>
</div>
</body>
</html>

**Key Elements:**

- **Sidebar Navigation**: Expandable module sections for easy access
- **Global Project Selector**: Filters all views to selected project
- **Notification Bell**: Shows pending actions and alerts
- **User Menu**: Access to profile and settings

---

## Flow 1: Hardware Schedule Import (New Project)

**Trigger**: Admin/PM clicks "Import Hardware Schedule" in Projects module

**Steps**:

1. User navigates to Projects module via sidebar
2. User clicks "Import Hardware Schedule" button
3. File upload dialog appears
4. User selects XML hardware schedule file
5. System parses XML and shows preview:
  - Project metadata (name, contractor, address, etc.)
  - Count of openings, doors, hardware items
6. User reviews preview and clicks "Import"
7. System creates:
  - Project record
  - Opening records (status: "Not Ordered")
  - Door Leaf records (status: "Not Ordered")
  - Hardware Item records (status: "Not Ordered")
8. Success toast notification appears (using shadcn sonner)
9. User is navigated to the new project detail page
10. Project appears in global project selector

**UI Feedback**:

- Loading spinner during parsing
- Progress indicator during import
- Success toast with project name
- New project highlighted in project list

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.btn-primary { background: #2563eb; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }
.btn-secondary { background: white; color: #333; padding: 10px 20px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; margin-left: 8px; }
.modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; }
.modal-content { background: white; padding: 24px; border-radius: 8px; width: 600px; max-height: 80vh; overflow-y: auto; }
.preview-section { margin: 16px 0; padding: 16px; background: #f5f5f5; border-radius: 4px; }
.preview-label { font-weight: 600; margin-bottom: 8px; }
.preview-value { color: #666; }
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 16px; }
.stat-card { background: white; padding: 16px; border-radius: 4px; border: 1px solid #ddd; }
.stat-number { font-size: 24px; font-weight: 700; color: #2563eb; }
.stat-label { font-size: 12px; color: #666; margin-top: 4px; }
</style>
</head>
<body>
<div class="page-header">
  <h1>Projects</h1>
  <div>
    <button class="btn-primary" data-element-id="import-schedule">Import Hardware Schedule</button>
    <button class="btn-secondary" data-element-id="update-schedule">Update Hardware Schedule</button>
  </div>
</div>

<div class="modal">
  <div class="modal-content">
    <h2>Import Hardware Schedule</h2>
    <p style="color: #666; margin-bottom: 24px;">Review the parsed data before importing</p>
    
    <div class="preview-section">
      <div class="preview-label">Project Information</div>
      <div class="preview-value">
        <div><strong>Name:</strong> Main Street Building</div>
        <div><strong>Project ID:</strong> 74</div>
        <div><strong>Contractor:</strong> ABC Construction</div>
        <div><strong>Location:</strong> 123 Main St, Springfield, IL 62701</div>
      </div>
    </div>
    
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-number">156</div>
        <div class="stat-label">Openings</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">312</div>
        <div class="stat-label">Door Leafs</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">1,248</div>
        <div class="stat-label">Hardware Items</div>
      </div>
    </div>
    
    <div style="margin-top: 24px; display: flex; justify-content: flex-end; gap: 8px;">
      <button class="btn-secondary" data-element-id="cancel-import">Cancel</button>
      <button class="btn-primary" data-element-id="confirm-import">Import Project</button>
    </div>
  </div>
</div>
</body>
</html>

---

## Flow 2: Hardware Schedule Update (Existing Project)

**Trigger**: Admin/PM clicks "Update Hardware Schedule" for an existing project

**Steps**:

1. User navigates to project detail page
2. User clicks "Update Hardware Schedule" button
3. File upload dialog appears
4. User selects updated XML file
5. System parses and compares with existing data
6. Full-page review screen appears with sections:
  - **Summary**: Counts of new, deleted, unchanged openings/items
  - **Detailed Changes**: Side-by-side diff view
  - **Impact Analysis**: Shows affected modules (POs, inventory, assembly, checkouts)
7. User reviews each section
8. User clicks "Approve Update" with confirmation dialog showing impact summary
9. System applies changes:
  - Creates new openings/items (status: "Not Ordered")
  - Marks deleted openings/items
  - Returns items from deleted openings to unallocated inventory
10. Success toast notification
11. User returns to updated project detail page

**UI Feedback**:

- Loading during comparison
- Color-coded changes (green=new, red=deleted, yellow=modified)
- Warning badges for items in assembly or checked out
- Confirmation dialog with impact summary

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; background: #fafafa; }
.review-header { background: white; border-bottom: 1px solid #ddd; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
.review-content { padding: 24px; max-width: 1400px; margin: 0 auto; }
.section { background: white; border-radius: 8px; padding: 24px; margin-bottom: 24px; border: 1px solid #ddd; }
.section-title { font-size: 18px; font-weight: 600; margin-bottom: 16px; }
.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.summary-card { padding: 16px; border-radius: 4px; border: 1px solid #ddd; }
.summary-card.new { background: #f0fdf4; border-color: #86efac; }
.summary-card.deleted { background: #fef2f2; border-color: #fca5a5; }
.summary-card.unchanged { background: #f5f5f5; border-color: #d4d4d4; }
.change-number { font-size: 32px; font-weight: 700; margin-bottom: 4px; }
.change-label { font-size: 14px; color: #666; }
.diff-table { width: 100%; border-collapse: collapse; margin-top: 16px; }
.diff-table th { background: #f5f5f5; padding: 12px; text-align: left; border-bottom: 2px solid #ddd; }
.diff-table td { padding: 12px; border-bottom: 1px solid #eee; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.badge-new { background: #86efac; color: #166534; }
.badge-deleted { background: #fca5a5; color: #991b1b; }
.impact-item { padding: 12px; background: #fef3c7; border-left: 3px solid #f59e0b; margin-bottom: 8px; border-radius: 4px; }
.btn-primary { background: #2563eb; color: white; padding: 10px 24px; border: none; border-radius: 6px; cursor: pointer; }
.btn-secondary { background: white; color: #333; padding: 10px 24px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; margin-right: 8px; }
</style>
</head>
<body>
<div class="review-header">
  <div>
    <h2 style="margin: 0;">Review Hardware Schedule Update</h2>
    <p style="margin: 4px 0 0 0; color: #666;">Project 74 - Main Street Building</p>
  </div>
  <div>
    <button class="btn-secondary" data-element-id="cancel-review">Cancel</button>
    <button class="btn-primary" data-element-id="approve-update">Approve Update</button>
  </div>
</div>

<div class="review-content">
  <div class="section">
    <div class="section-title">Summary of Changes</div>
    <div class="summary-grid">
      <div class="summary-card new">
        <div class="change-number">12</div>
        <div class="change-label">New Openings</div>
        <div style="margin-top: 8px; font-size: 12px; color: #666;">24 Doors, 96 Hardware Items</div>
      </div>
      <div class="summary-card deleted">
        <div class="change-number">5</div>
        <div class="change-label">Deleted Openings</div>
        <div style="margin-top: 8px; font-size: 12px; color: #666;">10 Doors, 40 Hardware Items</div>
      </div>
      <div class="summary-card unchanged">
        <div class="change-number">139</div>
        <div class="change-label">Unchanged Openings</div>
      </div>
    </div>
  </div>
  
  <div class="section">
    <div class="section-title">Detailed Changes</div>
    <table class="diff-table">
      <thead>
        <tr>
          <th>Opening</th>
          <th>Change Type</th>
          <th>Location</th>
          <th>Doors</th>
          <th>Hardware Items</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>101A</td>
          <td><span class="badge badge-new">NEW</span></td>
          <td>Building A, Floor 1</td>
          <td>2</td>
          <td>8</td>
        </tr>
        <tr>
          <td>205B</td>
          <td><span class="badge badge-deleted">DELETED</span></td>
          <td>Building B, Floor 2</td>
          <td>2</td>
          <td>8</td>
        </tr>
      </tbody>
    </table>
  </div>
  
  <div class="section">
    <div class="section-title">Impact Analysis</div>
    <div class="impact-item">
      <strong>⚠️ Assembly Impact:</strong> Opening 205B has 3 hardware items already installed. These will be returned to inventory.
    </div>
    <div class="impact-item">
      <strong>⚠️ Inventory Impact:</strong> 40 hardware items from deleted openings will return to unallocated status.
    </div>
    <div class="impact-item">
      <strong>📦 Purchasing Impact:</strong> 96 new hardware items and 24 doors will need to be ordered.
    </div>
  </div>
</div>
</body>
</html>

---

## Flow 3: Purchase Request Creation (PM → Purchasing)

**Trigger**: PM decides certain openings need to be ordered based on project schedule

**Steps**:

1. PM navigates to project detail page
2. PM views list of openings (expandable to see items)
3. PM selects openings that need to be ordered (checkboxes)
4. PM clicks "Create Purchase Request" button
5. Modal appears showing:
  - Selected openings
  - Total doors and hardware items
  - Estimated total cost (if available)
6. PM adds notes/priority and clicks "Submit Request"
7. System creates purchase request record
8. Purchase request appears in Purchasing module queue
9. Success toast notification
10. Selected openings show "Purchase Requested" badge

**UI Feedback**:

- Selected count indicator
- Validation: can't request openings already ordered
- Toast notification to PM
- Notification to Purchasing users

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.action-bar { background: white; padding: 16px; border-radius: 8px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; border: 1px solid #ddd; }
.openings-list { background: white; border-radius: 8px; border: 1px solid #ddd; }
.opening-row { padding: 16px; border-bottom: 1px solid #eee; display: flex; align-items: center; gap: 12px; }
.opening-row:hover { background: #f9fafb; }
.checkbox { width: 20px; height: 20px; }
.opening-info { flex: 1; }
.opening-number { font-weight: 600; }
.opening-location { color: #666; font-size: 14px; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-left: 8px; }
.badge-not-ordered { background: #fef3c7; color: #92400e; }
.badge-requested { background: #dbeafe; color: #1e40af; }
.expand-btn { background: none; border: none; cursor: pointer; padding: 4px; }
.items-detail { padding: 16px; background: #f9fafb; border-top: 1px solid #eee; }
.item-section { margin-bottom: 12px; }
.item-section-title { font-weight: 600; font-size: 14px; margin-bottom: 8px; }
.item { padding: 8px; background: white; border-radius: 4px; margin-bottom: 4px; font-size: 14px; }
.btn-primary { background: #2563eb; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }
.btn-primary:disabled { background: #cbd5e1; cursor: not-allowed; }
</style>
</head>
<body>
<div class="page-header">
  <div>
    <h1>Project 74 - Main Street Building</h1>
    <p style="color: #666; margin: 4px 0 0 0;">156 Openings</p>
  </div>
</div>

<div class="action-bar">
  <div>
    <span style="font-weight: 600;">3 openings selected</span>
    <span style="color: #666; margin-left: 8px;">6 doors, 24 hardware items</span>
  </div>
  <button class="btn-primary" data-element-id="create-purchase-request">Create Purchase Request</button>
</div>

<div class="openings-list">
  <div class="opening-row">
    <input type="checkbox" class="checkbox" checked data-element-id="select-opening-101">
    <div class="opening-info">
      <div class="opening-number">101A <span class="badge badge-not-ordered">Not Ordered</span></div>
      <div class="opening-location">Building A, Floor 1, Room 101</div>
    </div>
    <button class="expand-btn" data-element-id="expand-101">▼</button>
  </div>
  
  <div class="items-detail">
    <div class="item-section">
      <div class="item-section-title">Door Leafs (2)</div>
      <div class="item">3'0" x 7'0" Hollow Metal Door - Not Ordered</div>
      <div class="item">3'0" x 7'0" Hollow Metal Door - Not Ordered</div>
    </div>
    <div class="item-section">
      <div class="item-section-title">Hardware Items (8)</div>
      <div class="item">Schlage L9050 Lever Lock - Not Ordered</div>
      <div class="item">LCN 4040XP Door Closer - Not Ordered</div>
      <div class="item">Hinge, 4.5" x 4.5" - Not Ordered</div>
      <div class="item">Exit Device, Von Duprin 99 - Not Ordered</div>
      <div class="item">+ 4 more items</div>
    </div>
  </div>
  
  <div class="opening-row">
    <input type="checkbox" class="checkbox" checked data-element-id="select-opening-102">
    <div class="opening-info">
      <div class="opening-number">102A <span class="badge badge-not-ordered">Not Ordered</span></div>
      <div class="opening-location">Building A, Floor 1, Room 102</div>
    </div>
    <button class="expand-btn" data-element-id="expand-102">▶</button>
  </div>
  
  <div class="opening-row">
    <input type="checkbox" class="checkbox" data-element-id="select-opening-103">
    <div class="opening-info">
      <div class="opening-number">103A <span class="badge badge-requested">Purchase Requested</span></div>
      <div class="opening-location">Building A, Floor 1, Room 103</div>
    </div>
    <button class="expand-btn" data-element-id="expand-103">▶</button>
  </div>
</div>
</body>
</html>

---

## Flow 4: Purchase Order Creation (Purchasing)

**Trigger**: Purchasing user sees purchase request in their queue

**Steps**:

1. Purchasing user navigates to Purchase Orders module
2. User sees "Purchase Requests" tab with pending requests
3. User clicks on a purchase request to view details
4. System shows:
  - Requested openings
  - All doors and hardware items needed
  - Vendor information (from item data)
5. User groups items by vendor
6. For each vendor, user creates a PO:
  - Selects vendor from dropdown
  - Reviews line items (auto-populated)
  - Adjusts quantities if needed
  - Adds expected delivery date
  - Adds notes/terms
7. User clicks "Create PO" for each vendor
8. System creates PO records (status: "Draft")
9. User reviews all draft POs
10. User clicks "Send POs" to finalize
11. PO status changes to "Sent"
12. Items status changes from "Not Ordered" to "Ordered"
13. Success toast notification

**UI Feedback**:

- Auto-grouping by vendor
- Validation: all items must be assigned to a PO
- Draft POs can be edited before sending
- Toast notification when POs are sent

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { margin-bottom: 24px; }
.tabs { display: flex; gap: 8px; margin-bottom: 24px; border-bottom: 2px solid #ddd; }
.tab { padding: 12px 24px; background: none; border: none; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab.active { border-bottom-color: #2563eb; color: #2563eb; font-weight: 600; }
.request-card { background: white; border-radius: 8px; padding: 24px; margin-bottom: 16px; border: 1px solid #ddd; }
.request-header { display: flex; justify-content: space-between; align-items: start; margin-bottom: 16px; }
.vendor-section { background: #f9fafb; padding: 16px; border-radius: 4px; margin-bottom: 16px; border: 1px solid #e5e7eb; }
.vendor-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.items-table { width: 100%; border-collapse: collapse; }
.items-table th { background: #f5f5f5; padding: 8px; text-align: left; font-size: 12px; }
.items-table td { padding: 8px; border-bottom: 1px solid #eee; font-size: 14px; }
.btn-primary { background: #2563eb; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }
.btn-secondary { background: white; color: #333; padding: 10px 20px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.badge-pending { background: #fef3c7; color: #92400e; }
</style>
</head>
<body>
<div class="page-header">
  <h1>Purchase Orders</h1>
</div>

<div class="tabs">
  <button class="tab active" data-element-id="tab-requests">Purchase Requests (3)</button>
  <button class="tab" data-element-id="tab-pos">Purchase Orders (12)</button>
</div>

<div class="request-card">
  <div class="request-header">
    <div>
      <h3 style="margin: 0;">Purchase Request #PR-2024-001</h3>
      <p style="color: #666; margin: 4px 0 0 0;">Project 74 - Main Street Building</p>
      <p style="color: #666; margin: 4px 0 0 0;">Requested by: John Doe (PM) on Jan 15, 2024</p>
    </div>
    <span class="badge badge-pending">Pending</span>
  </div>
  
  <div style="margin-bottom: 16px; padding: 12px; background: #eff6ff; border-radius: 4px;">
    <strong>3 Openings:</strong> 101A, 102A, 103A<br>
    <strong>Total Items:</strong> 6 Doors, 24 Hardware Items
  </div>
  
  <div class="vendor-section">
    <div class="vendor-header">
      <div>
        <strong>Vendor: Allegion</strong>
        <div style="font-size: 14px; color: #666;">12 items</div>
      </div>
      <button class="btn-primary" data-element-id="create-po-allegion">Create PO</button>
    </div>
    <table class="items-table">
      <thead>
        <tr>
          <th>Product Code</th>
          <th>Description</th>
          <th>Qty</th>
          <th>Unit Price</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>L9050</td>
          <td>Schlage L9050 Lever Lock</td>
          <td>3</td>
          <td>$245.00</td>
          <td>$735.00</td>
        </tr>
        <tr>
          <td>4040XP</td>
          <td>LCN 4040XP Door Closer</td>
          <td>3</td>
          <td>$189.00</td>
          <td>$567.00</td>
        </tr>
        <tr>
          <td colspan="5" style="text-align: center; color: #666;">+ 10 more items</td>
        </tr>
      </tbody>
    </table>
  </div>
  
  <div class="vendor-section">
    <div class="vendor-header">
      <div>
        <strong>Vendor: Steelcraft Doors</strong>
        <div style="font-size: 14px; color: #666;">6 items</div>
      </div>
      <button class="btn-primary" data-element-id="create-po-steelcraft">Create PO</button>
    </div>
    <table class="items-table">
      <thead>
        <tr>
          <th>Product Code</th>
          <th>Description</th>
          <th>Qty</th>
          <th>Unit Price</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>HM-3070</td>
          <td>3'0" x 7'0" Hollow Metal Door</td>
          <td>6</td>
          <td>$425.00</td>
          <td>$2,550.00</td>
        </tr>
      </tbody>
    </table>
  </div>
  
  <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px;">
    <button class="btn-secondary" data-element-id="defer-request">Defer</button>
    <button class="btn-primary" data-element-id="create-all-pos">Create All POs</button>
  </div>
</div>
</body>
</html>

---

## Flow 5: Receiving Items (Warehouse)

**Trigger**: Warehouse staff receives shipment from vendor

**Steps**:

1. Warehouse user navigates to Receiving module
2. User sees list of open POs (status: "Sent" or "Partially Received")
3. User selects PO to receive against
4. System shows PO line items with expected quantities
5. For each line item, user enters actual quantity received
6. If quantity differs from expected:
  - System shows warning
  - User must enter reason/note for discrepancy
7. User enters warehouse location for each item
8. User clicks "Complete Receipt"
9. System:
  - Creates receipt record
  - Adds items to inventory (status: "Unallocated")
  - Updates PO status (Partially Received or Completed)
  - Updates item status from "Ordered" to "Received"
10. Success toast notification
11. Receipt confirmation screen with summary

**UI Feedback**:

- Quantity validation (can't receive more than ordered without override)
- Discrepancy warnings
- Location autocomplete
- Receipt summary with print option

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { margin-bottom: 24px; }
.po-card { background: white; border-radius: 8px; padding: 24px; border: 1px solid #ddd; }
.po-header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #eee; }
.receive-table { width: 100%; border-collapse: collapse; }
.receive-table th { background: #f5f5f5; padding: 12px; text-align: left; font-size: 12px; }
.receive-table td { padding: 12px; border-bottom: 1px solid #eee; }
.qty-input { width: 80px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
.qty-input.warning { border-color: #f59e0b; background: #fef3c7; }
.location-input { width: 150px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
.warning-icon { color: #f59e0b; margin-right: 4px; }
.note-input { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; margin-top: 4px; font-size: 12px; }
.btn-primary { background: #2563eb; color: white; padding: 10px 24px; border: none; border-radius: 6px; cursor: pointer; }
.btn-secondary { background: white; color: #333; padding: 10px 24px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; margin-right: 8px; }
</style>
</head>
<body>
<div class="page-header">
  <h1>Receiving</h1>
  <p style="color: #666; margin: 4px 0 0 0;">Receive items against purchase orders</p>
</div>

<div class="po-card">
  <div class="po-header">
    <h3 style="margin: 0;">PO #2024-001 - Allegion</h3>
    <p style="color: #666; margin: 4px 0 0 0;">Project 74 - Main Street Building</p>
    <p style="color: #666; margin: 4px 0 0 0;">Expected Delivery: Jan 20, 2024</p>
  </div>
  
  <table class="receive-table">
    <thead>
      <tr>
        <th>Product Code</th>
        <th>Description</th>
        <th>Ordered</th>
        <th>Previously Received</th>
        <th>Receiving Now</th>
        <th>Warehouse Location</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>L9050</td>
        <td>Schlage L9050 Lever Lock</td>
        <td>3</td>
        <td>0</td>
        <td><input type="number" class="qty-input" value="3" data-element-id="qty-l9050"></td>
        <td><input type="text" class="location-input" placeholder="e.g., A-12-3" data-element-id="loc-l9050"></td>
      </tr>
      <tr>
        <td>4040XP</td>
        <td>LCN 4040XP Door Closer</td>
        <td>3</td>
        <td>0</td>
        <td>
          <input type="number" class="qty-input warning" value="2" data-element-id="qty-4040xp">
          <div style="margin-top: 4px;">
            <span class="warning-icon">⚠️</span>
            <span style="font-size: 12px; color: #f59e0b;">Quantity mismatch</span>
          </div>
          <input type="text" class="note-input" placeholder="Reason for discrepancy..." data-element-id="note-4040xp">
        </td>
        <td><input type="text" class="location-input" placeholder="e.g., A-12-3" data-element-id="loc-4040xp"></td>
      </tr>
      <tr>
        <td colspan="6" style="text-align: center; color: #666;">+ 10 more items</td>
      </tr>
    </tbody>
  </table>
  
  <div style="margin-top: 24px; padding: 16px; background: #f9fafb; border-radius: 4px;">
    <strong>Receipt Summary:</strong><br>
    Total Items: 12 | Receiving: 11 | Discrepancies: 1
  </div>
  
  <div style="margin-top: 24px; display: flex; justify-content: flex-end; gap: 8px;">
    <button class="btn-secondary" data-element-id="cancel-receipt">Cancel</button>
    <button class="btn-primary" data-element-id="complete-receipt">Complete Receipt</button>
  </div>
</div>
</body>
</html>

---

## Flow 6: Inventory Allocation (PM/Inventory Manager)

**Trigger**: User wants to allocate inventory to specific openings

**Steps**:

1. User navigates to Inventory module
2. User selects project from global selector
3. Inventory view shows items grouped by: Project → Opening → (Doors + Hardware)
4. User sees unallocated items in a separate section
5. User drags unallocated item to target opening
6. System validates:
  - Item matches opening requirements
  - Item is not already allocated
7. Confirmation dialog shows allocation details
8. User confirms
9. System updates item allocation status
10. Item moves from "Unallocated" to opening's item list
11. Item badge changes to "Allocated to Opening [number]"
12. Success toast notification

**UI Feedback**:

- Drag-and-drop visual feedback
- Drop zones highlighted when dragging
- Validation errors shown immediately
- Color-coded allocation status badges

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { margin-bottom: 24px; }
.inventory-layout { display: grid; grid-template-columns: 300px 1fr; gap: 24px; }
.unallocated-panel { background: white; border-radius: 8px; padding: 16px; border: 1px solid #ddd; height: fit-content; }
.panel-title { font-weight: 600; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #eee; }
.item-card { padding: 12px; background: #f9fafb; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 8px; cursor: move; }
.item-card:hover { background: #f3f4f6; }
.item-code { font-weight: 600; font-size: 14px; }
.item-desc { font-size: 12px; color: #666; margin-top: 4px; }
.badge { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; margin-top: 4px; }
.badge-unallocated { background: #fef3c7; color: #92400e; }
.badge-allocated { background: #dbeafe; color: #1e40af; }
.openings-panel { background: white; border-radius: 8px; padding: 16px; border: 1px solid #ddd; }
.opening-section { margin-bottom: 16px; padding: 16px; background: #f9fafb; border-radius: 4px; border: 1px solid #e5e7eb; }
.opening-header { font-weight: 600; margin-bottom: 12px; }
.drop-zone { min-height: 100px; border: 2px dashed #cbd5e1; border-radius: 4px; padding: 12px; margin-top: 8px; }
.drop-zone.active { border-color: #2563eb; background: #eff6ff; }
.subsection { margin-bottom: 12px; }
.subsection-title { font-size: 12px; font-weight: 600; color: #666; margin-bottom: 8px; }
</style>
</head>
<body>
<div class="page-header">
  <h1>Inventory - Project 74</h1>
  <p style="color: #666; margin: 4px 0 0 0;">Allocate items to openings</p>
</div>

<div class="inventory-layout">
  <div class="unallocated-panel">
    <div class="panel-title">Unallocated Items (48)</div>
    
    <div style="margin-bottom: 16px;">
      <div style="font-size: 12px; font-weight: 600; color: #666; margin-bottom: 8px;">DOORS (12)</div>
      <div class="item-card" draggable="true" data-element-id="drag-door-1">
        <div class="item-code">HM-3070</div>
        <div class="item-desc">3'0" x 7'0" Hollow Metal Door</div>
        <div class="badge badge-unallocated">Unallocated</div>
      </div>
      <div class="item-card" draggable="true" data-element-id="drag-door-2">
        <div class="item-code">HM-3070</div>
        <div class="item-desc">3'0" x 7'0" Hollow Metal Door</div>
        <div class="badge badge-unallocated">Unallocated</div>
      </div>
    </div>
    
    <div>
      <div style="font-size: 12px; font-weight: 600; color: #666; margin-bottom: 8px;">HARDWARE (36)</div>
      <div class="item-card" draggable="true" data-element-id="drag-hw-1">
        <div class="item-code">L9050</div>
        <div class="item-desc">Schlage L9050 Lever Lock</div>
        <div class="badge badge-unallocated">Unallocated</div>
      </div>
      <div class="item-card" draggable="true" data-element-id="drag-hw-2">
        <div class="item-code">4040XP</div>
        <div class="item-desc">LCN 4040XP Door Closer</div>
        <div class="badge badge-unallocated">Unallocated</div>
      </div>
      <div style="text-align: center; color: #666; font-size: 12px; margin-top: 8px;">+ 34 more items</div>
    </div>
  </div>
  
  <div class="openings-panel">
    <div class="panel-title">Openings</div>
    
    <div class="opening-section">
      <div class="opening-header">Opening 101A - Building A, Floor 1</div>
      
      <div class="subsection">
        <div class="subsection-title">Doors (2 needed, 1 allocated)</div>
        <div class="item-card">
          <div class="item-code">HM-3070</div>
          <div class="item-desc">3'0" x 7'0" Hollow Metal Door</div>
          <div class="badge badge-allocated">Allocated</div>
        </div>
        <div class="drop-zone active" data-element-id="drop-zone-101a-doors">
          Drop door here to allocate
        </div>
      </div>
      
      <div class="subsection">
        <div class="subsection-title">Hardware Items (8 needed, 3 allocated)</div>
        <div class="item-card">
          <div class="item-code">L9050</div>
          <div class="item-desc">Schlage L9050 Lever Lock</div>
          <div class="badge badge-allocated">Allocated</div>
        </div>
        <div class="drop-zone" data-element-id="drop-zone-101a-hardware">
          Drop hardware here to allocate
        </div>
      </div>
    </div>
    
    <div class="opening-section">
      <div class="opening-header">Opening 102A - Building A, Floor 1</div>
      <div style="color: #666; font-size: 14px;">Click to expand...</div>
    </div>
  </div>
</div>
</body>
</html>

---

## Flow 7: Assembly Work Trigger (PM)

**Trigger**: PM decides certain openings are ready for assembly

**Steps**:

1. PM navigates to project detail page
2. PM views openings list
3. PM selects openings ready for assembly (checkboxes)
4. PM clicks "Send to Assembly" button
5. Confirmation dialog shows:
  - Selected openings
  - Items that will be pulled from warehouse
  - Warning if any items not yet received
6. PM confirms
7. System creates warehouse pull request (type: "Assembly")
8. Pull request appears in Warehouse module
9. Openings status changes to "Pending Assembly"
10. Success toast notification
11. Notification sent to Warehouse users

**UI Feedback**:

- Validation: can't send openings without allocated items
- Warning for partially allocated openings
- Confirmation with impact summary
- Toast notifications

---

## Flow 8: Warehouse Pull for Assembly

**Trigger**: Warehouse user sees assembly pull request

**Steps**:

1. Warehouse user navigates to Pull Requests module
2. User sees pull requests grouped by project, with type indicators
3. User clicks on assembly pull request
4. System shows:
  - Openings to be pulled
  - All doors and hardware items needed
  - Current warehouse locations
5. User marks pull as "In Progress"
6. For each item, user:
  - Locates item in warehouse
  - Enters quantity pulled
  - Checks off item
7. User clicks "Complete Pull"
8. System:
  - Updates item allocation status to "In Assembly"
  - Creates pull completion record
  - Openings automatically appear in Assembly queue
9. Success toast notification
10. Notification sent to Assembly users

**UI Feedback**:

- Pull status: Pending → In Progress → Completed
- Item checklist with locations
- Support for partial pulls
- Completion summary

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { margin-bottom: 24px; }
.pull-card { background: white; border-radius: 8px; padding: 24px; border: 1px solid #ddd; margin-bottom: 16px; }
.pull-header { display: flex; justify-content: space-between; align-items: start; margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #eee; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.badge-assembly { background: #dbeafe; color: #1e40af; }
.badge-checkout { background: #fce7f3; color: #9f1239; }
.badge-in-progress { background: #fef3c7; color: #92400e; }
.items-table { width: 100%; border-collapse: collapse; }
.items-table th { background: #f5f5f5; padding: 12px; text-align: left; font-size: 12px; }
.items-table td { padding: 12px; border-bottom: 1px solid #eee; }
.checkbox { width: 18px; height: 18px; }
.qty-input { width: 60px; padding: 6px; border: 1px solid #ddd; border-radius: 4px; }
.btn-primary { background: #2563eb; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }
.btn-secondary { background: white; color: #333; padding: 10px 20px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; margin-right: 8px; }
</style>
</head>
<body>
<div class="page-header">
  <h1>Pull Requests</h1>
  <p style="color: #666; margin: 4px 0 0 0;">Warehouse pull requests by project</p>
</div>

<div class="pull-card">
  <div class="pull-header">
    <div>
      <h3 style="margin: 0;">Pull Request #WP-2024-015</h3>
      <p style="color: #666; margin: 4px 0 0 0;">Project 74 - Main Street Building</p>
      <p style="color: #666; margin: 4px 0 0 0;">Requested by: John Doe (PM) on Jan 18, 2024</p>
      <div style="margin-top: 8px;">
        <span class="badge badge-assembly">Assembly Pull</span>
        <span class="badge badge-in-progress">In Progress</span>
      </div>
    </div>
    <button class="btn-primary" data-element-id="complete-pull">Complete Pull</button>
  </div>
  
  <div style="margin-bottom: 16px; padding: 12px; background: #eff6ff; border-radius: 4px;">
    <strong>Openings:</strong> 101A, 102A, 103A<br>
    <strong>Total Items to Pull:</strong> 6 Doors, 24 Hardware Items
  </div>
  
  <table class="items-table">
    <thead>
      <tr>
        <th style="width: 40px;"></th>
        <th>Opening</th>
        <th>Type</th>
        <th>Product Code</th>
        <th>Description</th>
        <th>Location</th>
        <th>Qty Needed</th>
        <th>Qty Pulled</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><input type="checkbox" class="checkbox" checked data-element-id="check-item-1"></td>
        <td>101A</td>
        <td>Door</td>
        <td>HM-3070</td>
        <td>3'0" x 7'0" Hollow Metal Door</td>
        <td>A-12-3</td>
        <td>2</td>
        <td><input type="number" class="qty-input" value="2" data-element-id="qty-pulled-1"></td>
      </tr>
      <tr>
        <td><input type="checkbox" class="checkbox" checked data-element-id="check-item-2"></td>
        <td>101A</td>
        <td>Hardware</td>
        <td>L9050</td>
        <td>Schlage L9050 Lever Lock</td>
        <td>B-05-2</td>
        <td>1</td>
        <td><input type="number" class="qty-input" value="1" data-element-id="qty-pulled-2"></td>
      </tr>
      <tr>
        <td><input type="checkbox" class="checkbox" data-element-id="check-item-3"></td>
        <td>101A</td>
        <td>Hardware</td>
        <td>4040XP</td>
        <td>LCN 4040XP Door Closer</td>
        <td>B-05-3</td>
        <td>1</td>
        <td><input type="number" class="qty-input" value="0" data-element-id="qty-pulled-3"></td>
      </tr>
      <tr>
        <td colspan="8" style="text-align: center; color: #666;">+ 27 more items</td>
      </tr>
    </tbody>
  </table>
  
  <div style="margin-top: 16px; padding: 12px; background: #f9fafb; border-radius: 4px;">
    <strong>Progress:</strong> 2 of 30 items pulled
  </div>
  
  <div style="margin-top: 24px; display: flex; justify-content: flex-end; gap: 8px;">
    <button class="btn-secondary" data-element-id="save-progress">Save Progress</button>
    <button class="btn-primary" data-element-id="complete-pull-btn">Complete Pull</button>
  </div>
</div>
</body>
</html>

---

## Flow 9: Assembly Installation Work

**Trigger**: Assembly technician sees openings in their queue

**Steps**:

1. Assembly user navigates to Assembly Work module
2. User sees openings grouped by project
3. User expands project to see openings
4. User clicks on an opening to work on
5. Opening detail view shows:
  - Opening properties
  - Door leafs (separate section)
  - Hardware items (separate section)
  - Each item has checkbox for "Installed"
6. As technician installs items, they check boxes
7. System auto-saves progress
8. When all items installed, opening status changes to "Assembly Complete"
9. User moves to next opening
10. Progress tracked in real-time

**UI Feedback**:

- Auto-save indicator
- Progress bar showing completion %
- Color-coded status (not started, in progress, complete)
- Toast notification when opening completed

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { margin-bottom: 24px; }
.assembly-layout { display: grid; grid-template-columns: 300px 1fr; gap: 24px; }
.openings-list { background: white; border-radius: 8px; padding: 16px; border: 1px solid #ddd; }
.project-group { margin-bottom: 16px; }
.project-header { font-weight: 600; padding: 8px; background: #f5f5f5; border-radius: 4px; cursor: pointer; }
.opening-item { padding: 12px; margin: 4px 0; border-radius: 4px; cursor: pointer; }
.opening-item:hover { background: #f9fafb; }
.opening-item.active { background: #eff6ff; border-left: 3px solid #2563eb; }
.opening-number { font-weight: 600; }
.opening-progress { font-size: 12px; color: #666; margin-top: 4px; }
.progress-bar { height: 4px; background: #e5e7eb; border-radius: 2px; margin-top: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: #2563eb; }
.detail-panel { background: white; border-radius: 8px; padding: 24px; border: 1px solid #ddd; }
.section { margin-bottom: 24px; }
.section-title { font-weight: 600; font-size: 16px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #eee; }
.item-row { padding: 12px; background: #f9fafb; border-radius: 4px; margin-bottom: 8px; display: flex; align-items: center; gap: 12px; }
.item-row.installed { background: #f0fdf4; }
.checkbox { width: 20px; height: 20px; }
.item-info { flex: 1; }
.item-code { font-weight: 600; }
.item-desc { font-size: 14px; color: #666; margin-top: 2px; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.badge-installed { background: #86efac; color: #166534; }
.badge-not-installed { background: #fef3c7; color: #92400e; }
</style>
</head>
<body>
<div class="page-header">
  <h1>Assembly Work</h1>
  <p style="color: #666; margin: 4px 0 0 0;">Install hardware items on openings</p>
</div>

<div class="assembly-layout">
  <div class="openings-list">
    <div class="project-group">
      <div class="project-header" data-element-id="expand-project-74">▼ Project 74 (3 openings)</div>
      <div class="opening-item active" data-element-id="select-opening-101a">
        <div class="opening-number">101A</div>
        <div class="opening-progress">3 of 8 items installed</div>
        <div class="progress-bar">
          <div class="progress-fill" style="width: 37.5%;"></div>
        </div>
      </div>
      <div class="opening-item" data-element-id="select-opening-102a">
        <div class="opening-number">102A</div>
        <div class="opening-progress">0 of 8 items installed</div>
        <div class="progress-bar">
          <div class="progress-fill" style="width: 0%;"></div>
        </div>
      </div>
      <div class="opening-item" data-element-id="select-opening-103a">
        <div class="opening-number">103A</div>
        <div class="opening-progress">8 of 8 items installed</div>
        <div class="progress-bar">
          <div class="progress-fill" style="width: 100%;"></div>
        </div>
      </div>
    </div>
  </div>
  
  <div class="detail-panel">
    <div style="margin-bottom: 24px;">
      <h2 style="margin: 0;">Opening 101A</h2>
      <p style="color: #666; margin: 4px 0 0 0;">Building A, Floor 1, Room 101</p>
      <p style="color: #666; margin: 4px 0 0 0;">3'0" x 7'0" | Single Door | Interior</p>
    </div>
    
    <div style="margin-bottom: 24px; padding: 12px; background: #eff6ff; border-radius: 4px;">
      <strong>Progress:</strong> 3 of 10 items installed (30%)
      <div class="progress-bar" style="margin-top: 8px; height: 8px;">
        <div class="progress-fill" style="width: 30%;"></div>
      </div>
    </div>
    
    <div class="section">
      <div class="section-title">Door Leafs (2)</div>
      <div class="item-row installed">
        <input type="checkbox" class="checkbox" checked data-element-id="install-door-1">
        <div class="item-info">
          <div class="item-code">HM-3070</div>
          <div class="item-desc">3'0" x 7'0" Hollow Metal Door</div>
        </div>
        <span class="badge badge-installed">Installed</span>
      </div>
      <div class="item-row installed">
        <input type="checkbox" class="checkbox" checked data-element-id="install-door-2">
        <div class="item-info">
          <div class="item-code">HM-3070</div>
          <div class="item-desc">3'0" x 7'0" Hollow Metal Door</div>
        </div>
        <span class="badge badge-installed">Installed</span>
      </div>
    </div>
    
    <div class="section">
      <div class="section-title">Hardware Items (8)</div>
      <div class="item-row installed">
        <input type="checkbox" class="checkbox" checked data-element-id="install-hw-1">
        <div class="item-info">
          <div class="item-code">L9050</div>
          <div class="item-desc">Schlage L9050 Lever Lock</div>
        </div>
        <span class="badge badge-installed">Installed</span>
      </div>
      <div class="item-row">
        <input type="checkbox" class="checkbox" data-element-id="install-hw-2">
        <div class="item-info">
          <div class="item-code">4040XP</div>
          <div class="item-desc">LCN 4040XP Door Closer</div>
        </div>
        <span class="badge badge-not-installed">Not Installed</span>
      </div>
      <div class="item-row">
        <input type="checkbox" class="checkbox" data-element-id="install-hw-3">
        <div class="item-info">
          <div class="item-code">HINGE-4545</div>
          <div class="item-desc">Hinge, 4.5" x 4.5"</div>
        </div>
        <span class="badge badge-not-installed">Not Installed</span>
      </div>
      <div style="text-align: center; color: #666; margin-top: 8px;">+ 5 more items</div>
    </div>
    
    <div style="margin-top: 24px; padding: 12px; background: #f0fdf4; border-radius: 4px; font-size: 14px; color: #166534;">
      ✓ Auto-saved 2 seconds ago
    </div>
  </div>
</div>
</body>
</html>

---

## Flow 10: Checkout Trigger (PM)

**Trigger**: PM decides openings are ready to ship to construction site

**Steps**:

1. PM navigates to Checkout module
2. PM selects project from dropdown
3. Multi-step wizard begins:
  - **Step 1: Select Openings**
    - List of openings with status indicators
    - PM selects openings to checkout (checkboxes)
  - **Step 2: Review Items**
    - Shows all items for selected openings
    - Indicates which items are installed vs not installed
    - Shows warehouse pull requirements
  - **Step 3: Confirm Checkout**
    - Summary of what will be shipped
    - Impact: items will leave inventory permanently
    - Warehouse pull request will be created
4. PM clicks "Confirm Checkout"
5. Confirmation dialog with impact summary
6. System creates:
  - Checkout record
  - Warehouse pull request (type: "Checkout")
7. Pull request appears in Warehouse module
8. Success toast notification
9. Notification sent to Warehouse users

**UI Feedback**:

- Validation: can't checkout openings without all items received
- Warning for openings with uninstalled items
- Multi-step progress indicator
- Confirmation with detailed summary

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; background: #fafafa; }
.wizard-header { background: white; border-bottom: 1px solid #ddd; padding: 16px 24px; }
.steps { display: flex; gap: 24px; margin-top: 16px; }
.step { flex: 1; text-align: center; position: relative; }
.step::after { content: ''; position: absolute; top: 16px; left: 50%; width: 100%; height: 2px; background: #e5e7eb; z-index: 0; }
.step:last-child::after { display: none; }
.step-circle { width: 32px; height: 32px; border-radius: 50%; background: #e5e7eb; color: #666; display: flex; align-items: center; justify-content: center; margin: 0 auto 8px; position: relative; z-index: 1; font-weight: 600; }
.step.active .step-circle { background: #2563eb; color: white; }
.step.completed .step-circle { background: #10b981; color: white; }
.step-label { font-size: 14px; color: #666; }
.step.active .step-label { color: #2563eb; font-weight: 600; }
.wizard-content { padding: 24px; max-width: 1200px; margin: 0 auto; }
.openings-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.opening-card { background: white; border: 1px solid #ddd; border-radius: 8px; padding: 16px; cursor: pointer; }
.opening-card:hover { border-color: #2563eb; }
.opening-card.selected { border-color: #2563eb; background: #eff6ff; }
.checkbox { width: 20px; height: 20px; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-left: 8px; }
.badge-ready { background: #d1fae5; color: #065f46; }
.badge-partial { background: #fef3c7; color: #92400e; }
.wizard-footer { background: white; border-top: 1px solid #ddd; padding: 16px 24px; display: flex; justify-content: space-between; }
.btn-primary { background: #2563eb; color: white; padding: 10px 24px; border: none; border-radius: 6px; cursor: pointer; }
.btn-secondary { background: white; color: #333; padding: 10px 24px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; }
</style>
</head>
<body>
<div class="wizard-header">
  <h2 style="margin: 0;">Create Checkout</h2>
  <p style="color: #666; margin: 4px 0 0 0;">Project 74 - Main Street Building</p>
  
  <div class="steps">
    <div class="step active">
      <div class="step-circle">1</div>
      <div class="step-label">Select Openings</div>
    </div>
    <div class="step">
      <div class="step-circle">2</div>
      <div class="step-label">Review Items</div>
    </div>
    <div class="step">
      <div class="step-circle">3</div>
      <div class="step-label">Confirm</div>
    </div>
  </div>
</div>

<div class="wizard-content">
  <div style="margin-bottom: 16px; padding: 12px; background: #eff6ff; border-radius: 4px;">
    <strong>3 openings selected</strong> - 6 doors, 24 hardware items (18 installed, 6 to be pulled)
  </div>
  
  <div class="openings-grid">
    <div class="opening-card selected" data-element-id="select-opening-101a">
      <div style="display: flex; align-items: start; gap: 12px; margin-bottom: 12px;">
        <input type="checkbox" class="checkbox" checked>
        <div style="flex: 1;">
          <div style="font-weight: 600;">Opening 101A</div>
          <div style="font-size: 14px; color: #666;">Building A, Floor 1</div>
        </div>
        <span class="badge badge-partial">Partial Assembly</span>
      </div>
      <div style="font-size: 14px; color: #666;">
        <div>Doors: 2 (2 installed)</div>
        <div>Hardware: 8 (3 installed, 5 to pull)</div>
      </div>
    </div>
    
    <div class="opening-card selected" data-element-id="select-opening-102a">
      <div style="display: flex; align-items: start; gap: 12px; margin-bottom: 12px;">
        <input type="checkbox" class="checkbox" checked>
        <div style="flex: 1;">
          <div style="font-weight: 600;">Opening 102A</div>
          <div style="font-size: 14px; color: #666;">Building A, Floor 1</div>
        </div>
        <span class="badge badge-ready">Ready</span>
      </div>
      <div style="font-size: 14px; color: #666;">
        <div>Doors: 2 (2 installed)</div>
        <div>Hardware: 8 (8 installed)</div>
      </div>
    </div>
    
    <div class="opening-card" data-element-id="select-opening-103a">
      <div style="display: flex; align-items: start; gap: 12px; margin-bottom: 12px;">
        <input type="checkbox" class="checkbox">
        <div style="flex: 1;">
          <div style="font-weight: 600;">Opening 103A</div>
          <div style="font-size: 14px; color: #666;">Building A, Floor 1</div>
        </div>
        <span class="badge badge-partial">Partial Assembly</span>
      </div>
      <div style="font-size: 14px; color: #666;">
        <div>Doors: 2 (2 installed)</div>
        <div>Hardware: 8 (7 installed, 1 to pull)</div>
      </div>
    </div>
  </div>
</div>

<div class="wizard-footer">
  <button class="btn-secondary" data-element-id="cancel-checkout">Cancel</button>
  <button class="btn-primary" data-element-id="next-step">Next: Review Items</button>
</div>
</body>
</html>

---

## Flow 11: Warehouse Pull for Checkout

**Trigger**: Warehouse user sees checkout pull request

**Steps**:

1. Warehouse user navigates to Pull Requests module
2. User sees checkout pull request (type: "Checkout")
3. User clicks on pull request
4. System shows:
  - Openings being checked out
  - Only uninstalled items (installed items already with opening)
  - Warehouse locations
5. User marks pull as "In Progress"
6. User pulls uninstalled items
7. User enters quantities pulled for each item
8. User clicks "Complete Pull"
9. System updates item status to "Checked Out"
10. Checkout status changes to "Ready to Ship"
11. Success toast notification

**UI Feedback**:

- Clear distinction: only uninstalled items shown
- Pull progress tracking
- Completion summary

---

## Flow 12: Checkout Completion

**Trigger**: Warehouse completes pull for checkout

**Steps**:

1. PM or Warehouse user navigates to Checkout module
2. User sees checkout with status "Ready to Ship"
3. User clicks "Complete Checkout"
4. Confirmation dialog shows:
  - All openings being shipped
  - All items (installed + pulled)
  - Impact: items will leave inventory permanently
5. User confirms
6. System:
  - Removes all items from inventory
  - Updates opening status to "Checked Out"
  - Creates checkout completion record
7. Checkout confirmation/summary screen appears showing:
  - Checkout number
  - Date/time
  - Openings shipped
  - Total items
  - Option to print packing list
8. User can return to project view or view checkout history

**UI Feedback**:

- Confirmation with detailed impact
- Success screen with summary
- Print/export options
- Toast notification

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.confirmation-card { background: white; border-radius: 8px; padding: 32px; max-width: 800px; margin: 0 auto; border: 1px solid #ddd; }
.success-icon { width: 64px; height: 64px; background: #10b981; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 24px; font-size: 32px; }
.summary-section { margin: 24px 0; padding: 16px; background: #f9fafb; border-radius: 4px; }
.summary-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e5e7eb; }
.summary-row:last-child { border-bottom: none; }
.summary-label { color: #666; }
.summary-value { font-weight: 600; }
.items-list { margin-top: 16px; }
.item-group { margin-bottom: 16px; }
.item-group-title { font-weight: 600; margin-bottom: 8px; }
.item { padding: 8px; background: white; border-radius: 4px; margin-bottom: 4px; font-size: 14px; }
.btn-primary { background: #2563eb; color: white; padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; }
.btn-secondary { background: white; color: #333; padding: 12px 24px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; font-size: 16px; margin-right: 8px; }
</style>
</head>
<body>
<div class="confirmation-card">
  <div class="success-icon">✓</div>
  
  <h2 style="text-align: center; margin: 0 0 8px 0;">Checkout Complete</h2>
  <p style="text-align: center; color: #666; margin: 0 0 32px 0;">Items have been shipped to the construction site</p>
  
  <div class="summary-section">
    <div class="summary-row">
      <div class="summary-label">Checkout Number</div>
      <div class="summary-value">CO-2024-042</div>
    </div>
    <div class="summary-row">
      <div class="summary-label">Project</div>
      <div class="summary-value">Project 74 - Main Street Building</div>
    </div>
    <div class="summary-row">
      <div class="summary-label">Date & Time</div>
      <div class="summary-value">Jan 22, 2024 at 2:45 PM</div>
    </div>
    <div class="summary-row">
      <div class="summary-label">Openings Shipped</div>
      <div class="summary-value">3 openings (101A, 102A, 103A)</div>
    </div>
    <div class="summary-row">
      <div class="summary-label">Total Items</div>
      <div class="summary-value">6 Doors, 24 Hardware Items</div>
    </div>
  </div>
  
  <div class="summary-section">
    <h3 style="margin: 0 0 16px 0;">Shipped Items</h3>
    
    <div class="item-group">
      <div class="item-group-title">Opening 101A</div>
      <div class="item">2 Doors (installed)</div>
      <div class="item">3 Hardware Items (installed)</div>
      <div class="item">5 Hardware Items (shipped separately)</div>
    </div>
    
    <div class="item-group">
      <div class="item-group-title">Opening 102A</div>
      <div class="item">2 Doors (installed)</div>
      <div class="item">8 Hardware Items (installed)</div>
    </div>
    
    <div class="item-group">
      <div class="item-group-title">Opening 103A</div>
      <div class="item">2 Doors (installed)</div>
      <div class="item">7 Hardware Items (installed)</div>
      <div class="item">1 Hardware Item (shipped separately)</div>
    </div>
  </div>
  
  <div style="margin-top: 32px; display: flex; justify-content: center; gap: 12px;">
    <button class="btn-secondary" data-element-id="print-packing-list">Print Packing List</button>
    <button class="btn-primary" data-element-id="return-to-project">Return to Project</button>
  </div>
</div>
</body>
</html>

---

## Dashboard View

<!DOCTYPE html>
<html>
<head>
<style>
body { margin: 0; font-family: system-ui; padding: 24px; background: #fafafa; }
.page-header { margin-bottom: 24px; }
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.metric-card { background: white; border-radius: 8px; padding: 20px; border: 1px solid #ddd; }
.metric-value { font-size: 32px; font-weight: 700; color: #2563eb; margin-bottom: 4px; }
.metric-label { font-size: 14px; color: #666; }
.metric-change { font-size: 12px; color: #10b981; margin-top: 4px; }
.content-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }
.card { background: white; border-radius: 8px; padding: 24px; border: 1px solid #ddd; }
.card-title { font-weight: 600; font-size: 18px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #eee; }
.task-item { padding: 12px; background: #f9fafb; border-radius: 4px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.task-title { font-weight: 600; font-size: 14px; }
.task-desc { font-size: 12px; color: #666; margin-top: 2px; }
.badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.badge-urgent { background: #fef2f2; color: #991b1b; }
.badge-normal { background: #fef3c7; color: #92400e; }
.activity-item { padding: 12px 0; border-bottom: 1px solid #eee; }
.activity-item:last-child { border-bottom: none; }
.activity-time { font-size: 12px; color: #666; }
.activity-text { font-size: 14px; margin-top: 4px; }
</style>
</head>
<body>
<div class="page-header">
  <h1>Dashboard</h1>
  <p style="color: #666; margin: 4px 0 0 0;">Welcome back, John Doe</p>
</div>

<div class="metrics-grid">
  <div class="metric-card">
    <div class="metric-value">42</div>
    <div class="metric-label">Active Projects</div>
    <div class="metric-change">↑ 3 this week</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">18</div>
    <div class="metric-label">Open Purchase Orders</div>
    <div class="metric-change">↓ 5 from last week</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">156</div>
    <div class="metric-label">Openings in Assembly</div>
    <div class="metric-change">↑ 12 this week</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">$248K</div>
    <div class="metric-label">Inventory Value</div>
    <div class="metric-change">↑ $15K this month</div>
  </div>
</div>

<div class="content-grid">
  <div class="card">
    <div class="card-title">Pending Actions</div>
    
    <div class="task-item">
      <div>
        <div class="task-title">Review Purchase Request #PR-2024-003</div>
        <div class="task-desc">Project 82 - 5 openings need ordering</div>
      </div>
      <span class="badge badge-urgent">Urgent</span>
    </div>
    
    <div class="task-item">
      <div>
        <div class="task-title">Complete Pull Request #WP-2024-018</div>
        <div class="task-desc">Assembly pull for Project 74</div>
      </div>
      <span class="badge badge-normal">Normal</span>
    </div>
    
    <div class="task-item">
      <div>
        <div class="task-title">Approve Hardware Schedule Update</div>
        <div class="task-desc">Project 91 - 8 new openings, 3 deleted</div>
      </div>
      <span class="badge badge-urgent">Urgent</span>
    </div>
    
    <div class="task-item">
      <div>
        <div class="task-title">Receive PO #2024-015</div>
        <div class="task-desc">Allegion shipment arrived</div>
      </div>
      <span class="badge badge-normal">Normal</span>
    </div>
  </div>
  
  <div class="card">
    <div class="card-title">Recent Activity</div>
    
    <div class="activity-item">
      <div class="activity-time">2 minutes ago</div>
      <div class="activity-text">Sarah completed assembly on Opening 205B</div>
    </div>
    
    <div class="activity-item">
      <div class="activity-time">15 minutes ago</div>
      <div class="activity-text">Mike received PO #2024-014 (12 items)</div>
    </div>
    
    <div class="activity-item">
      <div class="activity-time">1 hour ago</div>
      <div class="activity-text">John created checkout CO-2024-041 for Project 74</div>
    </div>
    
    <div class="activity-item">
      <div class="activity-time">2 hours ago</div>
      <div class="activity-text">Lisa approved purchase request PR-2024-002</div>
    </div>
    
    <div class="activity-item">
      <div class="activity-time">3 hours ago</div>
      <div class="activity-text">New project imported: Project 95</div>
    </div>
  </div>
</div>
</body>
</html>

---

## State Diagram

```mermaid
stateDiagram-v2
    [*] --> NotOrdered: Hardware Schedule Imported
    NotOrdered --> PurchaseRequested: PM Creates Purchase Request
    PurchaseRequested --> Ordered: Purchasing Creates PO
    Ordered --> Received: Warehouse Receives Items
    Received --> Allocated: Inventory Allocated to Opening
    Allocated --> InAssembly: PM Sends to Assembly
    InAssembly --> AssemblyComplete: All Items Installed
    AssemblyComplete --> CheckedOut: PM Triggers Checkout
    Allocated --> CheckedOut: PM Triggers Checkout (No Assembly)
    CheckedOut --> [*]: Items Leave Ecosystem
```

---

## Key Interaction Patterns

### Color-Coded Status Badges

- **Not Ordered**: Yellow (#fef3c7)
- **Purchase Requested**: Blue (#dbeafe)
- **Ordered**: Purple (#e9d5ff)
- **Received**: Green (#d1fae5)
- **Allocated**: Cyan (#cffafe)
- **In Assembly**: Orange (#fed7aa)
- **Assembly Complete**: Green (#86efac)
- **Checked Out**: Gray (#e5e7eb)

### Notification Patterns

- **Toast Notifications**: Use shadcn sonner for all real-time feedback
- **Task List**: Pending actions shown in dashboard and notification center
- **Real-time Updates**: Auto-refresh when state changes occur

### Validation Rules

- Can't create purchase request for already ordered openings
- Can't send to assembly without allocated items
- Can't checkout without all items received
- Can't receive more than ordered without override
- Drag-and-drop only works for unallocated items

### Confirmation Dialogs

- All critical actions show impact summary
- Destructive actions require explicit confirmation
- Multi-step wizards for complex workflows

&nbsp;
