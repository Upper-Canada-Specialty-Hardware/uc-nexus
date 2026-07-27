# Admin UI: provision relay enrollment tokens + list relay installs

Closes the deferred nexus-side relay-installs admin view (#204).

**Why:** the relay's Setup tab (guided first-run) asks the operator to paste an enrollment token, but Nexus has no UI to mint one - today an admin must call the provisionRelayInstall GraphQL mutation directly. This is the missing Nexus half of guided setup.

frontend-only. backend already provides these, unchanged:
- relayInstalls -> [RelayInstallInfo] { id label company hostname enrolled enrolledAt lastSeenAt createdAt }, require_admin (backend/app/schemas/types.py:116; queries.py:1039).
- relayStatus -> { connected company }, require_user (used by useRelayStatus).
- provisionRelayInstall(label, company) -> RelayInstallProvision { installId label company enrollmentToken enrollmentTokenExpiresAt }, require_admin (mutations.py:1254).
- token one-time (enrolled_at guard), 24h TTL (enrollment_token_expires_at). consumed via relay Setup tab or enroll CLI.

## admin gating
- isAdmin = useIdentity().hasRole('Admin/Manager') (src/hooks/useIdentity.ts, reads Clerk user.publicMetadata.roles). existing pages gate via const { isAdmin } = useIdentity() (VendorsPage.tsx:34).
- sidebar nav requiredRoles: ['Admin/Manager'] (Sidebar.tsx:89).
- backend enforces require_admin on query + mutation.
- new page gates render on isAdmin, else "Admins only". nav item carries same requiredRoles.

## graphql documents
- src/graphql/queries.ts add RELAY_INSTALLS (relayInstalls { id label company hostname enrolled enrolledAt lastSeenAt createdAt }). GET_RELAY_STATUS exists.
- src/graphql/mutations.ts add PROVISION_RELAY_INSTALL (provisionRelayInstall(label, company) { installId label company enrollmentToken enrollmentTokenExpiresAt }).

## new page src/modules/admin/RelayInstallsPage.tsx
- gate on const { isAdmin } = useIdentity(); non-admin -> "Admins only" notice, stop.
- header - title + live relay-status chip (RelayStatusChip + useRelayStatus).
- "Provision install" button opens Modal (label text field + company - Select of known GP companies or text field w/ hint). submit runs PROVISION_RELAY_INSTALL.
- on success show persistent copyable panel (pattern like GpErrorAlert), containing:
  - one-time token, monospace + Copy token button.
  - warning it is shown ONCE, expires 24h (show enrollmentTokenExpiresAt).
  - next step "paste this token into the relay's Setup tab (Enroll step)".
  - CLI alternative `ucnexus-relay.exe enroll --token <TOKEN> --backend-url https://<backend-host>/graphql` + Copy command button (derive <backend-host> from import.meta.env.VITE_GRAPHQL_URL).
- DataGrid of relayInstalls -> columns Label, Company, Hostname, Enrolled (chip), Enrolled at, Last seen, Created. refetch after provision. empty state when none.
- useToast on success/failure; surface GraphQL error message on failure.

## routing + nav
- src/modules/admin/index.tsx add `<Route path="relay-installs" element={<AdminSubLayout><RelayInstallsPage/></AdminSubLayout>} />`.
- src/modules/admin/AdminLanding.tsx add SUB_ROUTES entry { label: 'Relay Installs', path: '/app/admin/relay-installs', icon: <RouterIcon> }.
- src/components/Sidebar.tsx add subItem { label: 'Relay Installs', path: '/app/admin/relay-installs' } under Admin (requiredRoles: ['Admin/Manager']).

## conventions
- match VendorsPage / UserManagementPage: DataGrid + Modal + useQuery/useMutation + refetch + useToast. wrap in AdminSubLayout (BackToModule).
- company field Select seeded from TUBC, TUCSH, UBC, UCSH or free text w/ hint. confirm list with user.

## edge cases
- each provision creates a NEW pending un-enrolled install row; re-provision does not reuse a prior row. list shows pending (enrolled=false) vs enrolled.
- no backend delete/revoke mutation -> install can't be removed from UI. possible follow-up - add revoke mutation if stale pending rows become noise.
- last_seen_at updates on enroll + each channel authenticate -> doubles as liveness signal.

## Simulated User Testing
against Railway (frontend-production-34fc, backend-production-7866), signed in as Admin/Manager (jayp has role):
1. https://frontend-production-34fc.up.railway.app/app/admin -> confirm "Relay Installs" card -> click -> lands /app/admin/relay-installs.
2. confirm page renders: relay-status chip (reads "relay connected", TUBC relay enrolled/running) + DataGrid listing existing enrolled install (TUBC, enrolled=true, recent last-seen).
3. "Provision install" -> label "test-install" + company "TUBC" -> submit. expect one-time token panel (token, 24h expiry, paste-into-Setup-tab instruction + enroll command, Copy buttons); verify Copy token puts token on clipboard. expect DataGrid refetch showing new install enrolled=false (pending), company TUBC.
4. reload -> token NOT shown again, pending install still appears.
5. sidebar shows "Relay Installs" only under Admin. if non-admin test user available, page shows "Admins only" + nav item hidden; else verify backend rejects relayInstalls / provisionRelayInstall without admin.
6. optional full loop: relay Setup tab, paste provisioned token + enroll -> back on Relay Installs, refetch -> pending install flips enrolled=true with fresh last-seen.
