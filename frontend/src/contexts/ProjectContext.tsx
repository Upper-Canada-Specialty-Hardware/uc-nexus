import { createContext, useContext, useState, type ReactNode } from 'react';

export interface Project {
  id: string;
  projectId: string;
  description: string | null;
  jobSiteName: string | null;
}

interface ProjectContextType {
  project: Project | null;
  setProject: (project: Project | null) => void;
}

const ProjectContext = createContext<ProjectContextType | undefined>(undefined);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [project, setProject] = useState<Project | null>(null);

  return (
    <ProjectContext.Provider value={{ project, setProject }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  const context = useContext(ProjectContext);
  if (!context) throw new Error('useProject must be used within ProjectProvider');
  return context;
}
