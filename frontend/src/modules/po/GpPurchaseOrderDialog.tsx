import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useApolloClient, useMutation, useQuery } from '@apollo/client/react';
import Modal from '../../components/Modal';
import { useToast } from '../../components/Toast';
import { CREATE_DRAFT_PO, REGISTER_PO_IN_GP, GET_GP_COST_CODES, GET_GP_VENDORS, GET_GP_TAX_DETAILS, SUGGEST_VENDOR_FOR_MANUFACTURER } from '../../graphql/po';
import { GET_BUYER_ASSIGNMENTS, GET_PROJECTS } from '../../graphql/shared';
import { useIdentity } from '../../hooks/useIdentity';
import VendorSelect from '../../components/VendorSelect';
import type { Project } from '../../types/project';
import type { PurchaseOrder } from './index';
import RelayStatusChip from '../../relay/RelayStatusChip';
import { useRelayStatus } from '../../relay/useRelayStatus';
import { poVendorName } from './poVendorName';
import { computeManufacturerVendorHint, type ManufacturerSuggestion } from './manufacturerVendorHint';
import GpErrorAlert from '../../components/GpErrorAlert';
import { extractGpError, type GpError } from '../../graphql/gpError';

// --- Types ---

interface LineItemRow {
  key: number;
  // The existing draft line item id (register mode). Absent for a row the user added in the dialog.
  id?: string;
  hardwareCategory: string;
  productCode: string;
  orderedQuantity: string;
  unitCost: string;
  classification: string;
  orderAs: string;
  // Issue #232: the line's derived manufacturer (register mode, from the imported HardwareItem). Absent
  // for a manually added row - drives the vendor suggestion, not editable here.
  manufacturer?: string | null;
}

interface GpVendorOption {
  vendorId: string;
  vendorName: string;
  vendorClass: string | null;
  status: number;
  currency: string; // GP CURNCYID (issue #257); the PO inherits it, blank -> 'CAD'
}

interface GpCostCode {
  costCode: string; // two-segment number 'cc1-cc2' e.g. '310-000'
  description: string | null;
  costElement: number; // GP Cost_Element (varies by code); the /po cost_code trailing digit
}

interface GpTaxDetailOption {
  taxDetailId: string; // GP TAXDTLID (purchase detail, TX00201 TXDTLTYP=2)
  description: string | null;
  percent: number; // GP TXDTLPCT
}

const EMPTY_LINE_ITEM: Omit<LineItemRow, 'key' | 'id'> = {
  hardwareCategory: '',
  productCode: '',
  orderedQuantity: '1',
  unitCost: '0',
  classification: '',
  orderAs: '',
};

// Pick the live GP vendor that best matches an imported draft's vendor name (issue #175, reworked for
// #200 now that the picker reads gpVendors live instead of a locally-synced mirror). Returns the match
// plus whether it is CONFIDENT - an exact name match - versus a loose substring guess the user must
// explicitly confirm before registering against it. vendorId is null when nothing plausibly matches,
// and the user then picks one.
function bestGuessGpVendor(
  gpVendors: GpVendorOption[],
  draftVendorName: string | null,
): { vendorId: string | null; vendorName: string | null; confident: boolean } {
  const name = (draftVendorName ?? '').trim().toLowerCase();
  if (!name) return { vendorId: null, vendorName: null, confident: false };
  const exact = gpVendors.find((v) => v.vendorName.trim().toLowerCase() === name);
  if (exact) return { vendorId: exact.vendorId, vendorName: exact.vendorName, confident: true };
  const partial = gpVendors.find((v) => {
    const vn = v.vendorName.trim().toLowerCase();
    return vn.includes(name) || name.includes(vn);
  });
  // a fuzzy substring hit can be wrong (a short name is a substring of an unrelated vendor) - not confident
  return { vendorId: partial?.vendorId ?? null, vendorName: partial?.vendorName ?? null, confident: false };
}

// --- Props ---

interface GpPurchaseOrderDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmitted: () => void;
  defaultProjectId?: string;
  // Relay status owned by the PO page (single source of truth). null while its first check is in
  // flight. When omitted, the dialog queries relayStatus itself so it stays usable standalone.
  relayConnected?: boolean | null;
  // When provided, the dialog registers this existing Draft PO into GP instead of creating a new one.
  registerPo?: PurchaseOrder | null;
}

// --- Component ---

export default function GpPurchaseOrderDialog({
  open,
  onClose,
  onSubmitted,
  defaultProjectId,
  relayConnected: relayConnectedProp,
  registerPo,
}: GpPurchaseOrderDialogProps) {
  const { showToast } = useToast();
  // Issue #216: a PO is REGISTERED as the CALLER's GP buyer identity (Clerk publicMetadata.gpBuyerId),
  // not a free pick - enforced again server-side. Drafting (issue #256) involves no buyer at all.
  const { gpBuyerId } = useIdentity();
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const projects = useMemo(() => projectsData?.projects ?? [], [projectsData]);

  const isRegister = !!registerPo;

  // Form state
  const [projectId, setProjectId] = useState(defaultProjectId ?? '');
  const [gpVendorId, setGpVendorId] = useState<string | null>(null);
  const [gpVendorName, setGpVendorName] = useState<string | null>(null);
  // Register mode only: false while a fuzzy name-matched GP vendor is pre-filled but not yet confirmed.
  // A confident match (the draft's own GP vendor / an exact name hit) and any manual pick start confirmed.
  const [vendorConfirmed, setVendorConfirmed] = useState(true);
  const [notes, setNotes] = useState('');
  // Issue #156: optional order-time dollar costs. Kept as strings ('' = not entered, distinct from 0).
  const [shippingCost, setShippingCost] = useState('');
  const [tariffAmount, setTariffAmount] = useState('');
  // Issue #257: GP header charges captured at register time. taxDetailId is a GP purchase tax detail
  // (CAD only); miscellaneous + tradeDiscount are dollar inputs. Freight maps from shippingCost above.
  const [taxDetailId, setTaxDetailId] = useState('');
  const [miscellaneous, setMiscellaneous] = useState('');
  const [tradeDiscount, setTradeDiscount] = useState('');
  // Issue #256: create mode drafts carry an optional Nexus vendor link + the PM's preferred date.
  const [vendorId, setVendorId] = useState<string | null>(null);
  const [preferredDeliveryDate, setPreferredDeliveryDate] = useState('');
  const [costCode, setCostCode] = useState('');
  const [nextKey, setNextKey] = useState(2);
  const [lineItems, setLineItems] = useState<LineItemRow[]>([{ key: 1, ...EMPTY_LINE_ITEM }]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [gpBusy, setGpBusy] = useState(false);
  // A GP/eConnect failure from create/register, shown persistently and in detail (issue #187) so the end
  // user can screenshot it. Distinct from the field-level `errors` map.
  const [gpError, setGpError] = useState<GpError | null>(null);

  const [createDraftPo, { loading: createLoading }] = useMutation<{ createDraftPo: { requestNumber: string } }>(
    CREATE_DRAFT_PO,
  );
  const [registerPoInGp, { loading: registerLoading }] = useMutation<{ registerPoInGp: { poNumber: string | null } }>(
    REGISTER_PO_IN_GP,
  );

  // One idempotency key per user action (create or register), reused across retries so a retry is a
  // no-op in GP instead of a second PO. Reset on a fresh open and after a successful submit; kept on
  // failure so the retry carries the same key.
  const idempotencyKeyRef = useRef<string | null>(null);

  // GP relay status. The company comes from the connected relay (it's enrolled for exactly one), so it's
  // read from the hook here rather than picked by the user. The page still passes relayConnected in as
  // the single source of truth for the connected flag; standalone, the hook's own connected value is used.
  // Issue #256: only register mode talks to GP - create mode is a plain draft and needs no relay.
  const relay = useRelayStatus({ skip: !open || !isRegister });
  const company = relay.company ?? '';
  const relayStatus: boolean | null = relayConnectedProp !== undefined ? relayConnectedProp : relay.connected;
  const relayConnected = relayStatus === true;

  const selectedProject = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId]);
  const isJob = !!projectId && !!selectedProject;
  const jobNumber = selectedProject?.projectId ?? null;

  // Issue #216: the caller's buyer assignment (their projects + designated cost codes). Register-only
  // (issue #256: drafting is open to everyone; the GP registration is where the buyer gating applies) -
  // the caller must be assigned to the draft's project and only designated cost codes are offered.
  interface BuyerAssignmentData {
    buyerId: string;
    costCodes: string[];
    projects: { id: string; projectId: string; description: string | null }[];
  }
  const { data: assignmentsData } = useQuery<{ buyerAssignments: BuyerAssignmentData[] }>(GET_BUYER_ASSIGNMENTS, {
    skip: !open || !isRegister,
    fetchPolicy: 'cache-and-network',
  });
  const myAssignment = useMemo(() => {
    if (!gpBuyerId) return null;
    return (
      (assignmentsData?.buyerAssignments ?? []).find(
        (a) => a.buyerId.trim().toUpperCase() === gpBuyerId.trim().toUpperCase(),
      ) ?? null
    );
  }, [assignmentsData, gpBuyerId]);
  const assignedProjectIds = useMemo(() => new Set((myAssignment?.projects ?? []).map((p) => p.id)), [myAssignment]);
  const designatedCostCodes = useMemo(() => new Set(myAssignment?.costCodes ?? []), [myAssignment]);
  const registerProjectAllowed = !isRegister || !registerPo?.projectId || assignedProjectIds.has(registerPo.projectId);

  // Live GP vendor list (PM00200), per company - issue #200 replaces the locally-synced vendor mirror
  // with a direct pick from this list, snapshotted onto the PO.
  const { data: gpVendorsData, refetch: refetchVendors } = useQuery<{ gpVendors: GpVendorOption[] }>(GET_GP_VENDORS, {
    variables: { company },
    skip: !open || !isRegister || !relayConnected || !company,
    fetchPolicy: 'cache-first',
  });
  const gpVendors = gpVendorsData?.gpVendors ?? [];

  // Issue #257: live GP purchase tax details (TX00201, TXDTLTYP=2) for the tax-detail dropdown.
  const { data: gpTaxDetailsData } = useQuery<{ gpTaxDetails: GpTaxDetailOption[] }>(GET_GP_TAX_DETAILS, {
    variables: { company },
    skip: !open || !isRegister || !relayConnected || !company,
    fetchPolicy: 'cache-first',
  });
  const gpTaxDetails = gpTaxDetailsData?.gpTaxDetails ?? [];

  // Issue #257: the PO currency is the selected GP vendor's (GP-first, resolved again server-side).
  // A foreign-currency PO (non-CAD) carries no tax schedule/detail - the relay blanks TAXSCHID and
  // prices the PO from GP's own maintained exchange rate - so the CAD-only tax-detail dropdown is
  // hidden for it. Freight/misc/trade discount still apply (in the PO's currency).
  const gpVendorCurrency = gpVendors.find((v) => v.vendorId === gpVendorId)?.currency ?? 'CAD';
  const isForeignCurrency = isRegister && !!gpVendorId && gpVendorCurrency !== 'CAD';

  // Issue #232: suggest the ordering vendor from each line's TITAN manufacturer. The manufacturer is
  // the derived POLineItem.manufacturer (resolved server-side from the line's linked HardwareItem),
  // carried on the line rows. Register mode (draft from import) -> lines carry it; a manually added
  // create-mode row has none, so its (category, code) simply contributes no manufacturer.
  const client = useApolloClient();
  const distinctManufacturers = useMemo(() => {
    const set = new Set<string>();
    for (const li of lineItems) {
      const mfr = (li.manufacturer ?? '').trim();
      if (mfr) set.add(mfr);
    }
    return Array.from(set);
  }, [lineItems]);
  // Stable key so the fetch effect doesn't refire on every render (arrays are new each render).
  const manufacturerKey = useMemo(() => distinctManufacturers.slice().sort().join('|'), [distinctManufacturers]);

  const [mfrSuggestions, setMfrSuggestions] = useState<Record<string, ManufacturerSuggestion>>({});
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional reset on close, guarded by !open
    if (!open) setMfrSuggestions({});
  }, [open]);

  useEffect(() => {
    if (!open || !isRegister || !relayConnected || !company || distinctManufacturers.length === 0) return;
    let cancelled = false;
    (async () => {
      // Fetch each manufacturer's suggestion concurrently, not one after another, so N distinct
      // manufacturers cost one round-trip of latency rather than N.
      const entries = await Promise.all(
        distinctManufacturers.map(async (manufacturer): Promise<[string, ManufacturerSuggestion]> => {
          try {
            const { data } = await client.query<{ suggestVendorForManufacturer: ManufacturerSuggestion }>({
              query: SUGGEST_VENDOR_FOR_MANUFACTURER,
              variables: { gpCompany: company, manufacturer },
              fetchPolicy: 'cache-first',
            });
            if (data?.suggestVendorForManufacturer) return [manufacturer, data.suggestVendorForManufacturer];
          } catch {
            // A failed suggestion must not break the dialog - fall through to the "no candidate" soft note.
          }
          return [manufacturer, { manufacturer, savedMapping: false, candidates: [] }];
        }),
      );
      if (!cancelled) setMfrSuggestions((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isRegister, relayConnected, company, manufacturerKey, client]);

  const suggestionsLoaded =
    distinctManufacturers.length > 0 && distinctManufacturers.every((m) => mfrSuggestions[m] !== undefined);
  const manufacturerHint = useMemo(
    () => computeManufacturerVendorHint(distinctManufacturers, mfrSuggestions),
    [distinctManufacturers, mfrSuggestions],
  );

  // This job's cost codes from GP (JC00701), live via the backend relay channel. Cost codes are
  // per-job and each carries its own Cost_Element, so the dropdown comes from GP, not a static list.
  // A stock PO (no project) carries no cost code. cache-first still keys on { company, job }, so a
  // different job re-queries; the refresh control re-pulls the current job's codes.
  const {
    data: costCodesData,
    loading: costCodesLoading,
    refetch: refetchCostCodes,
  } = useQuery<{ gpCostCodes: GpCostCode[] }>(GET_GP_COST_CODES, {
    variables: { company, job: jobNumber ?? '' },
    skip: !open || !isRegister || !relayConnected || !company || !jobNumber,
    fetchPolicy: 'cache-first',
  });
  // Issue #216: only the caller's designated cost codes ('cc1-cc2') are offered for the job.
  const costCodes = (costCodesData?.gpCostCodes ?? []).filter((c) => designatedCostCodes.has(c.costCode));

  // Seed the form when the dialog opens. Create mode -> empty; register mode -> the draft's values
  // (project locked, line items carrying their ids so edits map back). The vendor is seeded separately
  // (below) once the live GP vendor list has loaded, so the best-guess match isn't clobbered before data
  // arrives.
  const seededRef = useRef(false);
  const gpVendorSeededForCompanyRef = useRef<string | null>(null);
  // Issue #232: which manufacturer-signature has already driven a pre-select, and whether the user has
  // since taken over the vendor pick (a manual pick freezes the manufacturer suggestion from moving it).
  const appliedMfrSignatureRef = useRef<string | null>(null);
  const userPickedVendorRef = useRef(false);
  useEffect(() => {
    if (!open) {
      seededRef.current = false;
      gpVendorSeededForCompanyRef.current = null;
      appliedMfrSignatureRef.current = null;
      userPickedVendorRef.current = false;
      return;
    }
    if (seededRef.current) return;
    seededRef.current = true;
    // Fresh open = fresh user action, so start a new idempotency key on the next submit.
    idempotencyKeyRef.current = null;
    setCostCode('');
    setErrors({});
    if (registerPo) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time form seed on open, guarded by seededRef
      setProjectId(registerPo.projectId ?? '');
      setNotes(registerPo.notes ?? '');
      setShippingCost(registerPo.shippingCost != null ? String(registerPo.shippingCost) : '');
      setTariffAmount(registerPo.tariffAmount != null ? String(registerPo.tariffAmount) : '');
      // Issue #257: no draft-side source for these; the user enters them at register time.
      setTaxDetailId('');
      setMiscellaneous('');
      setTradeDiscount('');
      const rows: LineItemRow[] = registerPo.lineItems.map((li, i) => ({
        key: i + 1,
        id: li.id,
        hardwareCategory: li.hardwareCategory ?? '',
        productCode: li.productCode ?? '',
        orderedQuantity: String(li.orderedQuantity ?? 1),
        unitCost: li.unitCost != null ? String(li.unitCost) : '0',
        classification: li.classification ?? '',
        orderAs: li.orderAs ?? '',
        manufacturer: li.manufacturer ?? null,
      }));
      setLineItems(rows.length > 0 ? rows : [{ key: 1, ...EMPTY_LINE_ITEM }]);
      setNextKey((rows.length || 1) + 1);
    } else {
      setProjectId(defaultProjectId ?? '');
      setNotes('');
      setShippingCost('');
      setTariffAmount('');
      setTaxDetailId('');
      setMiscellaneous('');
      setTradeDiscount('');
      setVendorId(null);
      setPreferredDeliveryDate('');
      setLineItems([{ key: 1, ...EMPTY_LINE_ITEM }]);
      setNextKey(2);
    }
  }, [open, registerPo, defaultProjectId]);

  // Seed the GP vendor once this company's live list is available: register mode defaults to the
  // best-guess match against the imported vendor name, create mode starts empty. A fuzzy guess seeds
  // unconfirmed so submit is blocked until the user confirms (or picks another); a confident match /
  // create mode needs no confirmation. Re-seeds if the company changes, since the vendor master is
  // per-company and a pick from one company's list isn't valid against another's.
  useEffect(() => {
    if (!open) return;
    const vendors = gpVendorsData?.gpVendors;
    if (!vendors) return;
    if (gpVendorSeededForCompanyRef.current === company) return;
    gpVendorSeededForCompanyRef.current = company;
    const guess = registerPo
      ? bestGuessGpVendor(vendors, poVendorName(registerPo))
      : { vendorId: null, vendorName: null, confident: true };
    setGpVendorId(guess.vendorId);
    setGpVendorName(guess.vendorName);
    setVendorConfirmed(guess.confident);
  }, [open, company, registerPo, gpVendorsData]);

  // Issue #232: once every line manufacturer's suggestion has loaded, pre-select the suggested vendor
  // for a single-vendor result (unless the user has already picked one). A mixed result never pre-
  // selects. Runs once per manufacturer-signature; a manual pick freezes it. The pre-selected vendor
  // must exist in the live picker list so the dropdown can actually show it.
  useEffect(() => {
    if (!open || !suggestionsLoaded || userPickedVendorRef.current) return;
    if (appliedMfrSignatureRef.current === manufacturerKey) return;
    if (manufacturerHint.kind === 'single') {
      const vendors = gpVendorsData?.gpVendors ?? [];
      if (!vendors.some((v) => v.vendorId === manufacturerHint.top.gpVendorId)) return;
      appliedMfrSignatureRef.current = manufacturerKey;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time pre-select once suggestions load, guarded by appliedMfrSignatureRef
      setGpVendorId(manufacturerHint.top.gpVendorId);
      setGpVendorName(manufacturerHint.top.gpVendorName);
      setVendorConfirmed(true);
    } else if (manufacturerHint.kind === 'mixed') {
      // Conflicting manufacturers: record the signature so this doesn't re-run, but don't pre-select.
      appliedMfrSignatureRef.current = manufacturerKey;
    }
  }, [open, suggestionsLoaded, manufacturerHint, manufacturerKey, gpVendorsData]);

  // A manual vendor pick is an explicit choice, so it counts as confirmed and stops the manufacturer
  // suggestion from moving the selection out from under the user.
  const handleGpVendorChange = useCallback(
    (id: string) => {
      userPickedVendorRef.current = true;
      const picked = gpVendors.find((v) => v.vendorId === id) ?? null;
      setGpVendorId(picked?.vendorId ?? null);
      setGpVendorName(picked?.vendorName ?? null);
      setVendorConfirmed(true);
    },
    [gpVendors],
  );

  // Clear the selected cost code only when the job or company changes - a code from another job must
  // not carry over. Deliberately NOT keyed on relayConnected: the page polls relayStatus every 10s,
  // and a transient blip must not wipe the user's pick mid-form.
  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clear cost code when job/company changes
    setCostCode('');
  }, [open, company, jobNumber]);

  // --- Handlers ---

  const addLineItem = useCallback(() => {
    setLineItems((prev) => [...prev, { key: nextKey, ...EMPTY_LINE_ITEM }]);
    setNextKey((k) => k + 1);
  }, [nextKey]);

  const removeLineItem = useCallback((key: number) => {
    setLineItems((prev) => prev.filter((li) => li.key !== key));
  }, []);

  const updateLineItem = useCallback((key: number, field: keyof Omit<LineItemRow, 'key' | 'id'>, value: string) => {
    setLineItems((prev) => prev.map((li) => (li.key === key ? { ...li, [field]: value } : li)));
  }, []);

  const validate = useCallback(() => {
    const errs: Record<string, string> = {};
    if (lineItems.length === 0) errs.lineItems = 'At least one line item is required';
    for (let i = 0; i < lineItems.length; i++) {
      const li = lineItems[i];
      if (!li.hardwareCategory.trim()) errs[`li_${i}_cat`] = 'Required';
      if (!li.productCode.trim()) errs[`li_${i}_code`] = 'Required';
      const qty = parseInt(li.orderedQuantity, 10);
      if (isNaN(qty) || qty < 1) errs[`li_${i}_qty`] = 'Must be >= 1';
      const cost = parseFloat(li.unitCost);
      if (isNaN(cost) || cost < 0) errs[`li_${i}_cost`] = 'Must be >= 0';
      if (!li.orderAs.trim()) errs[`li_${i}_orderAs`] = 'Required';
    }
    // Issue #256: only register mode talks to GP - draft creation has no relay/vendor/buyer/cost-code
    // requirements at all.
    if (isRegister) {
      if (!relayConnected) errs.gp = 'GP relay not detected on this machine - it must be running to push a PO to GP';
      if (!gpVendorId) errs.vendor = 'Select a GP vendor';
      else if (!vendorConfirmed) errs.vendor = 'Confirm the suggested GP vendor before registering';
      // Issue #216: the PO is pushed as the caller's own GP buyer identity.
      if (!gpBuyerId) errs.buyer = 'Your account has no GP buyer identity - ask an Admin to set it in User Management';
      else if (!registerProjectAllowed) errs.buyer = `Buyer ${gpBuyerId} is not assigned to this project`;
      if (isJob && !costCode) errs.costCode = 'Cost code is required for a project PO';
      // Issue #257: a CAD PO must carry a tax detail (the relay computes tax from it); a foreign-currency
      // PO carries none (the relay blanks the schedule), so require it for CAD only. Only enforce it when
      // the company actually defines purchase tax details - a company with none would otherwise be
      // hard-blocked, since the dropdown is disabled/empty when gpTaxDetails is empty.
      if (!isForeignCurrency && gpVendorId && gpTaxDetails.length > 0 && !taxDetailId)
        errs.taxDetail = 'Select a tax detail';
    }
    // Issue #156: optional, but a non-empty entry must be a valid non-negative dollar value.
    if (shippingCost.trim() !== '' && (isNaN(parseFloat(shippingCost)) || parseFloat(shippingCost) < 0))
      errs.shippingCost = 'Must be >= 0';
    if (tariffAmount.trim() !== '' && (isNaN(parseFloat(tariffAmount)) || parseFloat(tariffAmount) < 0))
      errs.tariffAmount = 'Must be >= 0';
    // Issue #257: the new GP charges are optional but must be valid non-negative dollars when entered.
    if (miscellaneous.trim() !== '' && (isNaN(parseFloat(miscellaneous)) || parseFloat(miscellaneous) < 0))
      errs.miscellaneous = 'Must be >= 0';
    if (tradeDiscount.trim() !== '' && (isNaN(parseFloat(tradeDiscount)) || parseFloat(tradeDiscount) < 0))
      errs.tradeDiscount = 'Must be >= 0';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [lineItems, relayConnected, gpVendorId, isRegister, vendorConfirmed, gpBuyerId, registerProjectAllowed, isJob, costCode, shippingCost, tariffAmount, isForeignCurrency, taxDetailId, gpTaxDetails.length, miscellaneous, tradeDiscount]);

  const handleSubmit = useCallback(async () => {
    if (!validate()) return;

    // costCode already holds GP's 'phase-step-element' (e.g. '310-000-3'); the element is the real
    // one from JC00701, not a hardcoded 2. A stock PO (no project) carries no cost code.
    const gpCostCode = isJob ? costCode : null;
    const lineItemsInput = lineItems.map((li) => ({
      hardwareCategory: li.hardwareCategory.trim(),
      productCode: li.productCode.trim(),
      orderedQuantity: parseInt(li.orderedQuantity, 10),
      unitCost: parseFloat(li.unitCost),
      classification: li.classification || null,
      orderAs: li.orderAs.trim(),
    }));

    // Same key for every retry of this action so a retry is a no-op in GP (won't post a second PO).
    const idempotencyKey = (idempotencyKeyRef.current ??= crypto.randomUUID());

    // Issue #156: '' = not entered (null); 0 is a valid entered value.
    const shippingCostValue = shippingCost.trim() === '' ? null : parseFloat(shippingCost);
    const tariffAmountValue = tariffAmount.trim() === '' ? null : parseFloat(tariffAmount);
    // Issue #257: same '' -> null convention. tax detail is not sent for a foreign-currency PO (none).
    const miscellaneousValue = miscellaneous.trim() === '' ? null : parseFloat(miscellaneous);
    const tradeDiscountValue = tradeDiscount.trim() === '' ? null : parseFloat(tradeDiscount);
    const taxDetailIdValue = isForeignCurrency || !taxDetailId ? null : taxDetailId;

    setGpError(null);
    setGpBusy(true);
    try {
      // GP-first, server-side (issue #199): the resolver pushes to GP via the relay before persisting
      // anything, so a GP rejection changes nothing in UC Nexus.
      if (registerPo) {
        const resp = await registerPoInGp({
          variables: {
            input: {
              poId: registerPo.id,
              gpVendorId,
              gpVendorName,
              buyerId: gpBuyerId,
              gpCompany: company,
              costCode: gpCostCode,
              shippingCost: shippingCostValue,
              tariffAmount: tariffAmountValue,
              taxDetailId: taxDetailIdValue,
              miscellaneous: miscellaneousValue,
              tradeDiscount: tradeDiscountValue,
              idempotencyKey,
              lineItems: lineItems.map((li, idx) => ({
                id: li.id ?? null,
                ...lineItemsInput[idx],
              })),
            },
          },
        });
        showToast(`PO ${resp.data?.registerPoInGp?.poNumber} registered in GP`, 'success');
      } else {
        // Issue #256: manual creation lands as a plain DRAFT - no relay, no GP fields. Registering
        // it into GP is a separate, conscious action on the draft row.
        const resp = await createDraftPo({
          variables: {
            input: {
              projectId: projectId || null,
              vendorId: vendorId || null,
              notes: notes.trim() || null,
              preferredDeliveryDate: preferredDeliveryDate || null,
              shippingCost: shippingCostValue,
              tariffAmount: tariffAmountValue,
              lineItems: lineItemsInput,
            },
          },
        });
        showToast(`PO request ${resp.data?.createDraftPo?.requestNumber} created as draft`, 'success');
      }

      // Succeeded: clear the key so a later reopen starts a new action.
      idempotencyKeyRef.current = null;
      onSubmitted();
    } catch (err: unknown) {
      // Keep idempotencyKeyRef so a retry reuses the same key - the GP write may have committed even if
      // the mutation reported failure, and reusing the key makes the retry safe.
      // Surface the full GP error persistently (issue #187) so the user can screenshot it; the toast
      // just points at the detail panel.
      setGpError(extractGpError(err) ?? { message: isRegister ? 'Failed to push PO to GP' : 'Failed to create the draft PO' });
      showToast(
        isRegister
          ? "Could not complete the PO in GP - see the error detail below. A retry won't create a duplicate."
          : 'Could not create the draft PO - see the error detail below.',
        'error',
      );
    } finally {
      setGpBusy(false);
    }
  }, [
    validate,
    isJob,
    costCode,
    company,
    gpBuyerId,
    lineItems,
    projectId,
    vendorId,
    preferredDeliveryDate,
    gpVendorId,
    gpVendorName,
    notes,
    shippingCost,
    tariffAmount,
    taxDetailId,
    miscellaneous,
    tradeDiscount,
    isForeignCurrency,
    registerPo,
    isRegister,
    createDraftPo,
    registerPoInGp,
    showToast,
    onSubmitted,
  ]);

  // --- Render ---

  const busy = createLoading || registerLoading || gpBusy;
  const title = isRegister ? 'Register Purchase Order in GP' : 'Create PO Request (Draft)';
  const submitIdleLabel = isRegister ? 'Register in GP' : 'Create Draft';
  const submitBusyLabel = isRegister ? (gpBusy ? 'Pushing to GP…' : 'Registering…') : 'Saving…';

  // Status line under the cost-code dropdown (an explicit validation error takes precedence).
  const costCodeHelper =
    !isJob || !relayConnected
      ? ''
      : costCodesLoading
        ? 'Loading cost codes from GP…'
        : costCodes.length === 0
          ? 'No cost codes defined for this job in GP'
          : '';

  const importedVendorName = registerPo ? poVendorName(registerPo) || null : null;
  const vendorHelper =
    errors.vendor ||
    (isRegister && importedVendorName ? `Imported as: ${importedVendorName} - confirm the GP vendor` : '');

  // Issue #232: the manufacturer-driven vendor suggestion, shown under the vendor picker once every
  // line manufacturer's suggestion has resolved. Nothing renders until then, or when the lines carry
  // no known manufacturer ('none').
  const manufacturerHintNode =
    suggestionsLoaded && manufacturerHint.kind !== 'none' ? (
      manufacturerHint.kind === 'single' ? (
        <Alert severity="info" sx={{ mt: 1 }}>
          Suggested from manufacturer <strong>{manufacturerHint.label}</strong>:{' '}
          {manufacturerHint.top.gpVendorName}
          {manufacturerHint.savedMapping
            ? ' (learned from a prior PO)'
            : ` (${Math.round(manufacturerHint.top.score)}% name match)`}
          .
          {manufacturerHint.others.length > 0 &&
            ` Other candidates: ${manufacturerHint.others.map((c) => c.gpVendorName).join(', ')}.`}
        </Alert>
      ) : manufacturerHint.kind === 'mixed' ? (
        <Alert severity="warning" sx={{ mt: 1 }}>
          These lines span manufacturers that map to different vendors:{' '}
          {manufacturerHint.entries.map((e) => `${e.manufacturer} → ${e.vendorName ?? 'no match'}`).join('; ')}. Pick
          the GP vendor to order from.
        </Alert>
      ) : (
        <Alert severity="info" icon={false} sx={{ mt: 1 }}>
          No saved or matching GP vendor for {manufacturerHint.manufacturers.join(', ')} - pick a vendor manually.
        </Alert>
      )
    ) : null;

  const actions = (
    <Stack direction="row" spacing={1}>
      <Button onClick={onClose} disabled={busy}>
        Cancel
      </Button>
      <Button variant="contained" onClick={handleSubmit} disabled={busy || lineItems.length === 0}>
        {busy ? submitBusyLabel : submitIdleLabel}
      </Button>
    </Stack>
  );

  return (
    <Modal open={open} title={title} onClose={onClose} actions={actions} maxWidth="md">
      {gpError && (
        <Box sx={{ mb: 2 }}>
          <GpErrorAlert error={gpError} onClose={() => setGpError(null)} />
        </Box>
      )}
      {/* Issue #216: GP registration happens as YOUR buyer identity, against your assigned projects.
          Drafting (issue #256) is open to everyone, so these gate register mode only. */}
      {isRegister && !gpBuyerId ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          Your account has no GP buyer identity - an Admin must set it in User Management before you can
          register purchase orders.
        </Alert>
      ) : isRegister && !registerProjectAllowed ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          Buyer {gpBuyerId} is not assigned to this project - an Admin can change assignments under
          Admin → Buyers.
        </Alert>
      ) : null}
      {/* Header Fields */}
      <Stack spacing={2} sx={{ mb: 3 }}>
        <TextField
          select
          label={isRegister ? 'Project' : 'Project (Optional)'}
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          size="small"
          fullWidth
          disabled={isRegister}
        >
          <MenuItem value="">No Project (stock PO)</MenuItem>
          {projects.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.description || p.projectId}
            </MenuItem>
          ))}
        </TextField>

        {isRegister ? (
          <Box>
            <Stack direction="row" spacing={0.5} alignItems="flex-start">
              <TextField
                select
                label="GP Vendor"
                value={gpVendorId ?? ''}
                onChange={(e) => handleGpVendorChange(e.target.value)}
                size="small"
                sx={{ flex: 1 }}
                disabled={!relayConnected || gpVendors.length === 0}
                error={!!errors.vendor}
                helperText={vendorHelper}
              >
                {gpVendors.map((v) => (
                  <MenuItem key={v.vendorId} value={v.vendorId}>
                    {v.vendorName}
                  </MenuItem>
                ))}
              </TextField>
              <IconButton
                size="small"
                aria-label="Refresh GP vendors"
                onClick={() => refetchVendors()}
                disabled={!relayConnected}
                sx={{ mt: 0.5 }}
              >
                <RefreshIcon fontSize="small" />
              </IconButton>
            </Stack>
            {gpVendorId && !vendorConfirmed && (
              <FormControlLabel
                sx={{ mt: 0.5 }}
                control={
                  <Checkbox size="small" checked={vendorConfirmed} onChange={(e) => setVendorConfirmed(e.target.checked)} />
                }
                label={`This is the correct GP vendor${gpVendorName ? ` (${gpVendorName})` : ''}`}
              />
            )}
            {manufacturerHintNode}
          </Box>
        ) : (
          /* Issue #256: a draft carries an optional Nexus vendor link + the PM's preferred date; the
             GP vendor is picked later, at register time. */
          <Stack direction="row" spacing={2}>
            <Box sx={{ flex: 1 }}>
              <VendorSelect value={vendorId} onChange={setVendorId} />
            </Box>
            <TextField
              label="Preferred delivery date"
              type="date"
              value={preferredDeliveryDate}
              onChange={(e) => setPreferredDeliveryDate(e.target.value)}
              size="small"
              sx={{ width: 190 }}
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Stack>
        )}
        <Stack direction="row" spacing={2}>
          <TextField
            label="Shipping costs (optional)"
            value={shippingCost}
            onChange={(e) => setShippingCost(e.target.value)}
            size="small"
            type="number"
            slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
            sx={{ width: 200 }}
            error={!!errors.shippingCost}
            helperText={errors.shippingCost}
          />
          <TextField
            label="Tariffs (optional)"
            value={tariffAmount}
            onChange={(e) => setTariffAmount(e.target.value)}
            size="small"
            type="number"
            slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
            sx={{ width: 200 }}
            error={!!errors.tariffAmount}
            helperText={errors.tariffAmount}
          />
        </Stack>
        <TextField
          label="Notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          size="small"
          fullWidth
          multiline
          minRows={2}
          maxRows={4}
          placeholder="Optional notes for this purchase order"
        />
      </Stack>

      {/* GP purchase order - register mode only (issue #256: a draft doesn't touch GP; company,
          buyer identity, and cost code are captured when the draft is consciously registered). */}
      {isRegister && (
      <Box sx={{ mb: 3, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            GP purchase order
          </Typography>
          <RelayStatusChip connected={relayStatus} />
        </Stack>
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="flex-start">
          {/* The connected relay is enrolled for exactly one company, so this is read-only, not a pick. */}
          <TextField
            label="GP company"
            value={company || '—'}
            size="small"
            sx={{ minWidth: 140 }}
            disabled
          />
          {/* Issue #216: the buyer IS the caller's GP identity - display only, never a pick. */}
          <TextField
            label="Buyer (you)"
            value={gpBuyerId ?? '—'}
            size="small"
            sx={{ minWidth: 180 }}
            disabled
          />
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5 }}>
            <TextField
              select
              label={isJob ? 'Cost code (required)' : 'Cost code (project POs)'}
              value={costCode}
              onChange={(e) => setCostCode(e.target.value)}
              size="small"
              sx={{ minWidth: 260 }}
              disabled={!isJob || !relayConnected || costCodesLoading || costCodes.length === 0}
              error={!!errors.costCode}
              helperText={errors.costCode || costCodeHelper}
            >
              {costCodes.map((c) => (
                <MenuItem key={`${c.costCode}-${c.costElement}`} value={`${c.costCode}-${c.costElement}`}>
                  {c.description ? `${c.costCode} · ${c.description}` : c.costCode}
                </MenuItem>
              ))}
            </TextField>
            <IconButton
              size="small"
              aria-label="Refresh cost codes"
              onClick={() => refetchCostCodes()}
              disabled={!isJob || !relayConnected}
              sx={{ mt: 0.5 }}
            >
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Box>
        </Stack>
        {/* Issue #257: GP currency (read-only, from the vendor), the CAD-only tax detail, and the
            Miscellaneous / Trade discount charges. Freight is the "Shipping costs" field above. */}
        <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="flex-start" sx={{ mt: 2 }}>
          <TextField
            label="Currency"
            value={gpVendorId ? gpVendorCurrency : '-'}
            size="small"
            sx={{ minWidth: 120 }}
            disabled
            helperText={isForeignCurrency ? `${gpVendorCurrency}: no tax schedule, GP rate applied` : ' '}
          />
          <TextField
            select
            label={isForeignCurrency ? 'Tax detail' : 'Tax detail (required)'}
            value={isForeignCurrency ? '' : taxDetailId}
            onChange={(e) => setTaxDetailId(e.target.value)}
            size="small"
            sx={{ minWidth: 260 }}
            disabled={!relayConnected || isForeignCurrency || gpTaxDetails.length === 0}
            error={!!errors.taxDetail}
            helperText={errors.taxDetail || (isForeignCurrency ? 'Not applicable for a foreign-currency PO' : '')}
          >
            {gpTaxDetails.map((t) => (
              <MenuItem key={t.taxDetailId} value={t.taxDetailId}>
                {t.description
                  ? `${t.taxDetailId} · ${t.description} (${t.percent}%)`
                  : `${t.taxDetailId} (${t.percent}%)`}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Miscellaneous (optional)"
            value={miscellaneous}
            onChange={(e) => setMiscellaneous(e.target.value)}
            size="small"
            type="number"
            slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
            sx={{ width: 190 }}
            error={!!errors.miscellaneous}
            helperText={errors.miscellaneous}
          />
          <TextField
            label="Trade discount (optional)"
            value={tradeDiscount}
            onChange={(e) => setTradeDiscount(e.target.value)}
            size="small"
            type="number"
            slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
            sx={{ width: 190 }}
            error={!!errors.tradeDiscount}
            helperText={errors.tradeDiscount}
          />
        </Stack>
        {errors.gp && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {errors.gp}
          </Alert>
        )}
      </Box>
      )}

      {/* Line Items */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          Line Items
        </Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={addLineItem}>
          Add Item
        </Button>
      </Box>

      {errors.lineItems && (
        <Typography variant="body2" color="error" sx={{ mb: 1 }}>
          {errors.lineItems}
        </Typography>
      )}

      {/* Column headers. Site/shop classification is set by the PM at request creation (issue #216),
          so there is no Classification column here - register mode passes the draft's values through. */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '1.3fr 1.3fr 0.6fr 0.7fr 1.2fr auto',
          gap: 1,
          mb: 0.5,
        }}
      >
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Hardware Category</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Product Code</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Qty</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Unit Cost</Typography>
        <Typography variant="caption" sx={{ fontWeight: 'bold' }}>Order As</Typography>
        <Box />
      </Box>

      {/* Line item rows */}
      {lineItems.map((li, idx) => (
        <Box
          key={li.key}
          sx={{
            display: 'grid',
            gridTemplateColumns: '1.3fr 1.3fr 0.6fr 0.7fr 1.2fr auto',
            gap: 1,
            mb: 1,
            alignItems: 'start',
          }}
        >
          <TextField
            size="small"
            value={li.hardwareCategory}
            onChange={(e) => updateLineItem(li.key, 'hardwareCategory', e.target.value)}
            error={!!errors[`li_${idx}_cat`]}
            helperText={errors[`li_${idx}_cat`]}
            placeholder="e.g. Hinges"
          />
          <TextField
            size="small"
            value={li.productCode}
            onChange={(e) => updateLineItem(li.key, 'productCode', e.target.value)}
            error={!!errors[`li_${idx}_code`]}
            helperText={errors[`li_${idx}_code`]}
            placeholder="e.g. AB123"
          />
          <TextField
            size="small"
            type="number"
            value={li.orderedQuantity}
            onChange={(e) => updateLineItem(li.key, 'orderedQuantity', e.target.value)}
            error={!!errors[`li_${idx}_qty`]}
            helperText={errors[`li_${idx}_qty`]}
            slotProps={{ htmlInput: { min: 1 } }}
          />
          <TextField
            size="small"
            type="number"
            value={li.unitCost}
            onChange={(e) => updateLineItem(li.key, 'unitCost', e.target.value)}
            error={!!errors[`li_${idx}_cost`]}
            helperText={errors[`li_${idx}_cost`]}
            slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
          />
          <TextField
            size="small"
            required
            value={li.orderAs}
            onChange={(e) => updateLineItem(li.key, 'orderAs', e.target.value)}
            error={!!errors[`li_${idx}_orderAs`]}
            helperText={errors[`li_${idx}_orderAs`]}
            placeholder="e.g. ML2010"
          />
          <IconButton
            size="small"
            color="error"
            onClick={() => removeLineItem(li.key)}
            disabled={lineItems.length <= 1}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Box>
      ))}
    </Modal>
  );
}
