import { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { Box, Button } from '@mui/material';
import { LayoutGrid } from 'lucide-react';
import HardwareItemsTab from './HardwareItemsTab';
import ProjectLandingPage from '../../components/ProjectLandingPage';
import PageHeader from '../../components/PageHeader';
import GpCompanyTag from '../../components/GpCompanyTag';
import { FadeIn } from '../../motion';
import { GET_PROJECTS } from '../../graphql/shared';
import { useDropProjectOnCompanySwitch } from '../../hooks/useDropProjectOnCompanySwitch';
import type { Project } from '../../types/project';

const WAREHOUSE_PARENT = { label: 'Warehouse', to: '/app/warehouse' };

export default function InventoryView() {
  // The scoped project lives in the URL (#1359), so a project's page can link straight to its
  // inventory and a reload keeps it. No param is every project. The list scopes by the id alone; the
  // project itself is read only for the header's name and company.
  const [searchParams, setSearchParams] = useSearchParams();
  const projectId = searchParams.get('project') || undefined;
  const [picking, setPicking] = useState(false);
  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS, { skip: !projectId });
  const selectedProject = useMemo(
    () => (projectId ? (projectsData?.projects.find((p) => p.id === projectId) ?? null) : null),
    [projectsData, projectId],
  );

  // #1469: a company switch takes the scoped project with it.
  useDropProjectOnCompanySwitch();

  const choose = useCallback(
    (next: Project | null) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next) params.set('project', next.id);
          else params.delete('project');
          return params;
        },
        { replace: true },
      );
      setPicking(false);
    },
    [setSearchParams],
  );

  if (picking) {
    return <ProjectLandingPage title="Inventory" parent={WAREHOUSE_PARENT} onSelect={choose} />;
  }

  const projectLabel = !projectId
    ? 'All Projects'
    : selectedProject
      ? selectedProject.description || selectedProject.projectId
      : 'Project';

  return (
    <Box>
      {/* The PAGE HEADER names the way back to Warehouse; the only navigation this page owns is the
          project switch it actually controls. */}
      <PageHeader
        title="Inventory"
        parent={WAREHOUSE_PARENT}
        description={
          !selectedProject ? (
            projectLabel
          ) : (
            // #831: the project's GP company, inline after its name.
            <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              {projectLabel}
              <GpCompanyTag code={selectedProject.company} />
            </Box>
          )
        }
        actions={
          <Button
            size="small"
            variant="outlined"
            startIcon={<LayoutGrid size={18} strokeWidth={1.75} />}
            onClick={() => setPicking(true)}
          >
            Projects
          </Button>
        }
      />

      <FadeIn y={8}>
        <Box sx={{ mt: 2 }}>
          <HardwareItemsTab projectId={projectId} />
        </Box>
      </FadeIn>
    </Box>
  );
}
