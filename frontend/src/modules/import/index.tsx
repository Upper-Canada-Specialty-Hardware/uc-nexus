import { useState } from 'react';
import { Button } from '@mui/material';
import { Plus } from 'lucide-react';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import CreateGpJobDialog from './CreateGpJobDialog';
import ImportWizard from './ImportWizard';
import { useIdentity } from '../../hooks/useIdentity';
import type { Project } from '../../types/project';

export default function ImportModule() {
  const { isAdmin } = useIdentity();
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);

  const handleSelect = (project: Project | null) => {
    if (!project) return;
    setSelectedProject(project);
    setWizardOpen(true);
  };

  const handleWizardClose = () => {
    setWizardOpen(false);
    setSelectedProject(null);
  };

  return (
    <>
      <ProjectLandingPage
        title="Hardware Schedule Import"
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
        />
      )}
    </>
  );
}
