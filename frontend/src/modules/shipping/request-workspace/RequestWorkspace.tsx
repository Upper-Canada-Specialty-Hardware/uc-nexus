import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  CircularProgress,
  Drawer,
  Skeleton,
  Stack,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { ShoppingCart } from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery } from '@apollo/client/react';
import ProjectPicker from '../../../components/ProjectPicker';
import GpSetupQuarantineBanner from '../../../components/GpSetupQuarantineBanner';
import { useToast } from '../../../components/Toast';
import { GET_PROJECTS } from '../../../graphql/shared';
import { GET_PROJECT_INVENTORY_AVAILABILITY } from '../../../graphql/warehouse';
import {
  CREATE_SHIPPING_OUT_REQUEST,
  EDIT_SHIPPING_OUT_REQUEST,
  GET_SHIPPING_OUT_REQUEST,
} from '../../../graphql/shipping';
import { RESERVATION_STALE_ROOT_FIELDS } from '../../../graphql/refetch';
import { isGpSetupBroken, type Project } from '../../../types/project';
import type { InventoryAvailabilityRow } from '../../import/types';
import {
  buildRequestItems,
  headroomByProduct,
  heldByRequest,
  productKey,
  totalUnits,
  type CartLine,
} from './requestCart';
import RequestWorkspaceScheduleTab from './RequestWorkspaceScheduleTab';
import RequestWorkspaceInventoryTab from './RequestWorkspaceInventoryTab';
import RequestWorkspaceCartRail from './RequestWorkspaceCartRail';

interface SeededItem {
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  requestedQuantity: number;
}

interface SeededRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: string;
  items: SeededItem[];
}

const RAIL_WIDTH = 340;
const cartStorageKey = (projectId: string) => `shipping-request-cart:${projectId}`;

/**
 * The one place a shipping request is composed (#493 successor): schedule-driven lines and loose
 * inventory lines land in the same cart, on a full page.
 *
 * Create mode (`/shipping/requests/new`, optional `?projectId=`) opens on a project picker and keeps
 * a per-project draft in sessionStorage so a half-made request survives navigating away. Edit mode
 * (`/shipping/requests/:id/edit`) seeds once from the server and is never persisted - that is what
 * keeps a background refetch from clobbering a half-made edit.
 */
export default function RequestWorkspace({ mode }: { mode: 'create' | 'edit' }) {
  return mode === 'edit' ? <EditRoute /> : <CreateRoute />;
}

function CreateRoute() {
  const [searchParams] = useSearchParams();
  const preselectId = searchParams.get('projectId');
  const { data } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const [project, setProject] = useState<Project | null>(null);
  const [touched, setTouched] = useState(false);

  // Preselect the project a deep link named (generic ?projectId deep-link support), once the list is
  // in and only until the user takes over the picker themselves.
  useEffect(() => {
    if (touched || project || !preselectId || !data?.projects) return;
    const found = data.projects.find((p) => p.id === preselectId);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot preselect once the list is in
    if (found) setProject(found);
  }, [touched, project, preselectId, data, setProject]);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        New shipping request
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Compose from what the schedule still owes and from what the project holds loose. The request is
        raised pending; someone accepts it, and the warehouse pulls it.
      </Typography>
      <Box sx={{ mb: 2 }}>
        <ProjectPicker
          value={project}
          onChange={(p) => {
            setTouched(true);
            setProject(p);
          }}
          sx={{ maxWidth: 420 }}
        />
      </Box>
      {project ? (
        <Composer key={project.id} project={project} mode="create" />
      ) : (
        <Alert severity="info" variant="outlined">
          Pick a project to compose its request.
        </Alert>
      )}
    </Box>
  );
}

function EditRoute() {
  const { id } = useParams<{ id: string }>();
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const { data, loading, error } = useQuery<{ shippingOutRequest: SeededRequest | null }>(
    GET_SHIPPING_OUT_REQUEST,
    { variables: { id }, fetchPolicy: 'cache-and-network' },
  );

  const request = data?.shippingOutRequest ?? null;
  const project = useMemo(
    () => (request ? projectsData?.projects.find((p) => p.id === request.projectId) ?? null : null),
    [request, projectsData],
  );

  if (loading && !data) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (error) {
    return <Alert severity="error">Could not load this request: {error.message}</Alert>;
  }
  if (!request) {
    return <Alert severity="warning">This request no longer exists.</Alert>;
  }
  if (request.status !== 'PENDING') {
    return (
      <Alert severity="warning">
        Request {request.requestNumber} has already been accepted, so it can no longer be edited.
      </Alert>
    );
  }
  if (!project) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Edit request {request.requestNumber}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {project.description || project.projectId}. Saving replaces the request with exactly what is in
        the cart.
      </Typography>
      <Composer key={request.id} project={project} mode="edit" request={request} />
    </Box>
  );
}

function Composer({
  project,
  mode,
  request,
}: {
  project: Project;
  mode: 'create' | 'edit';
  request?: SeededRequest;
}) {
  const theme = useTheme();
  const wide = useMediaQuery(theme.breakpoints.up('md'));
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [drawerOpen, setDrawerOpen] = useState(false);
  // Which products the picked openings still owe, lifted from the catalog so the extras lane below can
  // nudge a loose add toward the door it is scheduled for (#610).
  const [scheduledByProduct, setScheduledByProduct] = useState<Map<string, string[]>>(() => new Map());

  // Seeded once at mount: create from the project's saved draft, edit from the server's request.
  const [cart, setCart] = useState<CartLine[]>(() => {
    if (mode === 'edit') {
      return (request?.items ?? []).map((item) => ({
        openingNumber: item.openingNumber,
        hardwareCategory: item.hardwareCategory,
        productCode: item.productCode,
        quantity: item.requestedQuantity,
      }));
    }
    try {
      const raw = sessionStorage.getItem(cartStorageKey(project.id));
      return raw ? (JSON.parse(raw) as CartLine[]) : [];
    } catch {
      return [];
    }
  });

  // Create-mode drafts persist per project; an edit never does, so a background refetch cannot
  // overwrite a half-made edit.
  useEffect(() => {
    if (mode !== 'create') return;
    try {
      sessionStorage.setItem(cartStorageKey(project.id), JSON.stringify(cart));
    } catch {
      /* storage full or unavailable - the draft just will not survive navigation */
    }
  }, [cart, mode, project.id]);

  const {
    data: availabilityData,
    loading: availabilityLoading,
    error: availabilityError,
    refetch: refetchAvailability,
  } = useQuery<{
    projectInventoryAvailability: InventoryAvailabilityRow[];
  }>(GET_PROJECT_INVENTORY_AVAILABILITY, {
    variables: { projectId: project.id },
    fetchPolicy: 'cache-and-network',
  });

  const availabilityRows = useMemo(
    () => availabilityData?.projectInventoryAvailability ?? [],
    [availabilityData],
  );

  const headroom = useMemo(() => {
    const available = new Map<string, number>();
    for (const row of availabilityRows) available.set(productKey(row), row.availableQuantity);
    const held = mode === 'edit' ? heldByRequest(request?.items ?? []) : new Map<string, number>();
    return headroomByProduct(available, held);
  }, [availabilityRows, mode, request]);

  const cacheUpdate = {
    update(cache: { evict: (o: { id: string; fieldName: string }) => void; gc: () => void }) {
      for (const fieldName of RESERVATION_STALE_ROOT_FIELDS) cache.evict({ id: 'ROOT_QUERY', fieldName });
      cache.gc();
    },
  };

  const settle = (message: string) => {
    if (mode === 'create') {
      try {
        sessionStorage.removeItem(cartStorageKey(project.id));
      } catch {
        /* ignore */
      }
    }
    showToast(message, 'success');
    navigate('/app/shipping/requests');
  };

  const [createRequest, { loading: creating }] = useMutation(CREATE_SHIPPING_OUT_REQUEST, {
    ...cacheUpdate,
    onCompleted: (data: unknown) => {
      const minted = (data as { createShippingOutRequest?: { requestNumber?: string } })
        ?.createShippingOutRequest?.requestNumber;
      settle(minted ? `Request ${minted} created` : 'Request created');
    },
    onError: (e) => showToast(e.message, 'error'),
  });
  const [editRequest, { loading: saving }] = useMutation(EDIT_SHIPPING_OUT_REQUEST, {
    ...cacheUpdate,
    onCompleted: () => settle('Request updated'),
    onError: (e) => showToast(e.message, 'error'),
  });

  const submitting = creating || saving;

  const submit = () => {
    const items = buildRequestItems(cart);
    if (items.length === 0) return;
    if (mode === 'edit' && request) {
      editRequest({ variables: { input: { id: request.id, items } } });
    } else {
      createRequest({ variables: { input: { projectId: project.id, items } } });
    }
  };

  if (isGpSetupBroken(project)) {
    return <GpSetupQuarantineBanner project={project} action="raising a shipping request" />;
  }

  // Every quantity is clamped against availability, so the composer cannot be trusted until it is in:
  // a half-loaded pool reads as "nothing free" and would silently refuse adds and, worse, trim a
  // persisted draft to zero. Wait for the first answer, then compose against real numbers.
  const haveAvailability = availabilityRows.length > 0;
  if (availabilityError && !haveAvailability) {
    return (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={() => refetchAvailability()}>
            Retry
          </Button>
        }
      >
        Could not read this project&rsquo;s available inventory, so the request cannot be composed yet.
      </Alert>
    );
  }
  if (!haveAvailability && availabilityLoading) {
    return (
      <Stack spacing={1.5}>
        <Typography variant="body2" color="text.secondary">
          Reading available stock…
        </Typography>
        <Skeleton variant="rounded" height={300} />
      </Stack>
    );
  }

  const rail = (
    <RequestWorkspaceCartRail
      cart={cart}
      headroom={headroom}
      onCartChange={setCart}
      onSubmit={submit}
      submitting={submitting}
      mode={mode}
      onClear={mode === 'create' ? () => setCart([]) : undefined}
    />
  );

  // Openings-first (#610): the schedule catalog is the spine, every ship-out line tagged to an opening
  // by default. The extras lane renders under it in every view - source gate included - so a request
  // that is only unscheduled stock never has to pass the gate or pick an opening.
  const catalog = (
    <Stack spacing={3} sx={{ minWidth: 0 }}>
      <RequestWorkspaceScheduleTab
        projectId={project.id}
        cart={cart}
        headroom={headroom}
        onCartChange={setCart}
        onScheduledProductsChange={setScheduledByProduct}
      />
      <RequestWorkspaceInventoryTab
        cart={cart}
        headroom={headroom}
        onCartChange={setCart}
        rows={availabilityRows}
        loading={availabilityLoading}
        error={availabilityRows.length === 0 && !!availabilityError}
        scheduledByProduct={scheduledByProduct}
      />
    </Stack>
  );

  if (wide) {
    return (
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: `minmax(0, 1fr) ${RAIL_WIDTH}px`,
          gap: 2,
          alignItems: 'start',
        }}
      >
        {catalog}
        <Box sx={{ position: 'sticky', top: 16, height: 'calc(100vh - 32px)', minWidth: 0 }}>{rail}</Box>
      </Box>
    );
  }

  // Narrow: the rail collapses to a summary chip that opens it as a drawer.
  return (
    <Box sx={{ minWidth: 0 }}>
      {catalog}
      <Box
        sx={{
          position: 'sticky',
          bottom: 0,
          py: 1.5,
          bgcolor: 'background.default',
          borderTop: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Button
          fullWidth
          variant="outlined"
          startIcon={
            <Badge badgeContent={totalUnits(cart)} color="primary">
              <ShoppingCart size={18} strokeWidth={1.75} />
            </Badge>
          }
          onClick={() => setDrawerOpen(true)}
        >
          Review request
        </Button>
      </Box>
      <Drawer anchor="right" open={drawerOpen} onClose={() => setDrawerOpen(false)}>
        <Box sx={{ width: Math.min(RAIL_WIDTH, 360), height: '100%' }}>{rail}</Box>
      </Drawer>
    </Box>
  );
}
