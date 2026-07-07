import { useState } from 'react';
import { Button } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import AdoptGpJobDialog from './AdoptGpJobDialog';
import ImportWizard from './ImportWizard';
import type { Project } from '../../types/project';

export default function ImportModule() {
  const [adoptOpen, setAdoptOpen] = useState(false);
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
        emptyStateText="No projects yet. Click 'Adopt GP Job' to get started."
        createButton={
          <Button
            variant="contained"
            size="large"
            startIcon={<AddIcon />}
            onClick={() => setAdoptOpen(true)}
          >
            Adopt GP Job
          </Button>
        }
        onSelect={handleSelect}
      />
      <AdoptGpJobDialog open={adoptOpen} onClose={() => setAdoptOpen(false)} />
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
