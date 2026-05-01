import { useState } from 'react';
import { Button } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import CreateProjectDialog from './CreateProjectDialog';
import ImportWizard from './ImportWizard';
import type { Project } from '../../types/project';

export default function ImportModule() {
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
        emptyStateText="No projects yet. Click 'Create New Project' to get started."
        createButton={
          <Button
            variant="contained"
            size="large"
            startIcon={<AddIcon />}
            onClick={() => setCreateOpen(true)}
          >
            Create New Project
          </Button>
        }
        onSelect={handleSelect}
      />
      <CreateProjectDialog open={createOpen} onClose={() => setCreateOpen(false)} />
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
