import { useEffect, useRef, useState } from 'react';
import { Button } from '@mui/material';
import { Plus } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import CreateGpJobDialog from './CreateGpJobDialog';
import ImportWizard from './ImportWizard';
import { useIdentity } from '../../hooks/useIdentity';
import { GET_PROJECTS } from '../../graphql/shared';
import type { Project } from '../../types/project';
import type { ImportPurpose, SelectionMode } from './types';

/** How the wizard was opened, when something else chose for the user. */
interface DeepLinkIntent {
  purpose?: ImportPurpose;
  // #565: which pathway the PO import runs - by opening (default) or by product. Carried through the
  // pick-a-project fall-through so the chooser's "by hardware" card survives when no project was named.
  selectionMode: SelectionMode;
  fromLatest: boolean;
  // #608: where to return when the wizard closes, carried from the request workspace's "upload a
  // newer schedule" hand-off.
  returnTo?: string | null;
}

const PURPOSES: ImportPurpose[] = ['po', 'assembly', 'schedule'];

export default function ImportModule() {
  const { isAdmin } = useIdentity();
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [intent, setIntent] = useState<DeepLinkIntent | null>(null);
  // A purpose that arrived without a project (#471). Held rather than acted on: the module buttons
  // know what the user came to raise but not which job, so it waits for them to pick one.
  const [pendingPurpose, setPendingPurpose] = useState<ImportPurpose | null>(null);
  // #565: the selection mode that rode in with a projectless purpose link, held alongside it.
  const [pendingMode, setPendingMode] = useState<SelectionMode>('openings');

  // `?purpose=` on its own is a module's "Start a Request" button (#471). The params are consumed and
  // cleared, so closing the wizard does not re-open it. A `purpose=shipping` link is a fossil - that
  // composer moved to the shipping request workspace - and is redirected below rather than opened here.
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const consumedRef = useRef(false);

  const projectIdParam = searchParams.get('projectId');
  const purposeParam = searchParams.get('purpose');
  const sourceParam = searchParams.get('source');
  const modeParam = searchParams.get('mode');
  const returnToParam = searchParams.get('returnTo');
  const projects = projectsData?.projects;
  const linkedPurpose = PURPOSES.includes(purposeParam as ImportPurpose)
    ? (purposeParam as ImportPurpose)
    : null;
  // #565: the PO chooser's "by hardware" card links `?purpose=po&mode=hardware`. Anything else is the
  // by-opening pathway, so an unknown or absent mode falls to 'openings'.
  const linkedMode: SelectionMode = modeParam === 'hardware' ? 'hardware' : 'openings';

  useEffect(() => {
    if (consumedRef.current) return;
    // Old shipping links (the receive-decision "Ship out now", any bookmark) now land on the request
    // workspace, which composes off the schedule AND off loose inventory in one cart. source=latest is
    // dropped - the workspace computes coverage server-side, so there is nothing to hydrate.
    if (purposeParam === 'shipping') {
      consumedRef.current = true;
      navigate(`/app/shipping/requests/new${projectIdParam ? `?projectId=${projectIdParam}` : ''}`, {
        replace: true,
      });
      return;
    }
    if (!projectIdParam && !linkedPurpose) return;
    // Resolving a project id needs the project list; a purpose on its own does not, so a
    // purpose-only link is honoured immediately rather than waiting on the query.
    if (projectIdParam && !projects) return;
    consumedRef.current = true;
    const project = projectIdParam ? projects?.find((p) => p.id === projectIdParam) : undefined;
    if (project) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot open from the URL
      setSelectedProject(project);
      setIntent({
        purpose: linkedPurpose ?? undefined,
        selectionMode: linkedMode,
        fromLatest: sourceParam === 'latest',
        returnTo: returnToParam,
      });
      setWizardOpen(true);
    } else {
      // No project to open on: either none was named, or the id is stale and matches nothing. Both
      // land on the picker rather than on a wizard for the wrong job, keeping whatever purpose came
      // with the link so the choice the user already made is not asked for twice.
      setPendingPurpose(linkedPurpose);
      setPendingMode(linkedMode);
    }
    setSearchParams({}, { replace: true });
  }, [projectIdParam, purposeParam, linkedPurpose, linkedMode, sourceParam, returnToParam, projects, setSearchParams, navigate]);

  const handleSelect = (project: Project | null) => {
    if (!project) return;
    setSelectedProject(project);
    // Seeds the Purpose step when the user arrived from a module's "Start a Request" button. Still a
    // seed, not a lock: the step lets them change it. The selection mode, on the other hand, does
    // lock the pathway - a "by hardware" link stays by-hardware once a project is chosen.
    setIntent(pendingPurpose ? { purpose: pendingPurpose, selectionMode: pendingMode, fromLatest: false } : null);
    setWizardOpen(true);
  };

  const handleWizardClose = () => {
    setWizardOpen(false);
    setSelectedProject(null);
    setIntent(null);
  };

  return (
    <>
      <ProjectLandingPage
        title="Start a Request"
        showAllProjects={false}
        // Projects arrive on their own now (issue #380): the GP job sync creates one for every job in
        // GP, so an empty list means GP has no jobs yet - or the relay has never connected.
        emptyStateText="No projects yet. Projects appear automatically for every job in GP."
        createButton={
          // Creating a job writes to the accounting system of record, so it's Admin/Manager only.
          // Everyone else still gets the landing page, just without the button.
          isAdmin ? (
            <Button
              variant="contained"
              size="large"
              startIcon={<Plus size={18} strokeWidth={1.75} />}
              onClick={() => setCreateOpen(true)}
            >
              Create GP Job
            </Button>
          ) : undefined
        }
        onSelect={handleSelect}
      />
      {isAdmin && <CreateGpJobDialog open={createOpen} onClose={() => setCreateOpen(false)} />}
      {selectedProject && (
        <ImportWizard
          open={wizardOpen}
          project={selectedProject}
          onClose={handleWizardClose}
          initialPurpose={intent?.purpose}
          initialSelectionMode={intent?.selectionMode}
          autoStartFromLatest={intent?.fromLatest}
          returnTo={intent?.returnTo}
        />
      )}
    </>
  );
}
