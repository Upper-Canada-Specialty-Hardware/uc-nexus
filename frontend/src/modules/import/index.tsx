import { useEffect, useRef, useState } from 'react';
import { Button } from '@mui/material';
import { Plus } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import CreateGpJobDialog from './CreateGpJobDialog';
import ImportWizard from './ImportWizard';
import { useIdentity } from '../../hooks/useIdentity';
import { GET_PROJECTS } from '../../graphql/shared';
import type { Project } from '../../types/project';
import type { ImportPurpose } from './types';

/** How the wizard was opened, when something else chose for the user. */
interface DeepLinkIntent {
  purpose?: ImportPurpose;
  fromLatest: boolean;
}

const PURPOSES: ImportPurpose[] = ['po', 'assembly', 'shipping'];

export default function ImportModule() {
  const { isAdmin } = useIdentity();
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [intent, setIntent] = useState<DeepLinkIntent | null>(null);
  // A purpose that arrived without a project (#471). Held rather than acted on: the module buttons
  // know what the user came to raise but not which job, so it waits for them to pick one.
  const [pendingPurpose, setPendingPurpose] = useState<ImportPurpose | null>(null);

  // `?projectId=&purpose=shipping&source=latest` - what "Ship out now" on a keep-or-ship decision
  // navigates to. `?purpose=` on its own is a module's "Start a Request" button (#471). The params
  // are consumed and cleared, so closing the wizard does not re-open it.
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const consumedRef = useRef(false);

  const projectIdParam = searchParams.get('projectId');
  const purposeParam = searchParams.get('purpose');
  const sourceParam = searchParams.get('source');
  const projects = projectsData?.projects;
  const linkedPurpose = PURPOSES.includes(purposeParam as ImportPurpose)
    ? (purposeParam as ImportPurpose)
    : null;

  useEffect(() => {
    if (consumedRef.current) return;
    if (!projectIdParam && !linkedPurpose) return;
    // Resolving a project id needs the project list; a purpose on its own does not, so a
    // purpose-only link is honoured immediately rather than waiting on the query.
    if (projectIdParam && !projects) return;
    consumedRef.current = true;
    const project = projectIdParam ? projects?.find((p) => p.id === projectIdParam) : undefined;
    if (project) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot open from the URL
      setSelectedProject(project);
      setIntent({ purpose: linkedPurpose ?? undefined, fromLatest: sourceParam === 'latest' });
      setWizardOpen(true);
    } else {
      // No project to open on: either none was named, or the id is stale and matches nothing. Both
      // land on the picker rather than on a wizard for the wrong job, keeping whatever purpose came
      // with the link so the choice the user already made is not asked for twice.
      setPendingPurpose(linkedPurpose);
    }
    setSearchParams({}, { replace: true });
  }, [projectIdParam, linkedPurpose, sourceParam, projects, setSearchParams]);

  const handleSelect = (project: Project | null) => {
    if (!project) return;
    setSelectedProject(project);
    // Seeds the Purpose step when the user arrived from a module's "Start a Request" button. Still a
    // seed, not a lock: the step lets them change it.
    setIntent(pendingPurpose ? { purpose: pendingPurpose, fromLatest: false } : null);
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
          autoStartFromLatest={intent?.fromLatest}
        />
      )}
    </>
  );
}
