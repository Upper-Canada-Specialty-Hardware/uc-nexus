import { createContext, useContext, useState, type ReactNode } from 'react';

export const ROLES = [
  'Hardware Schedule Import',
  'Warehouse Staff',
  'PO User',
  'Shipping Out',
  'Shop Assembly Manager',
  'Shop Assembly User',
  'Admin/Manager',
] as const;

export type Role = (typeof ROLES)[number];

interface RoleContextType {
  role: Role | null;
  setRole: (role: Role) => void;
  clearRole: () => void;
}

const RoleContext = createContext<RoleContextType | undefined>(undefined);

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role | null>(null);

  return (
    <RoleContext.Provider
      value={{
        role,
        setRole: setRoleState,
        clearRole: () => setRoleState(null),
      }}
    >
      {children}
    </RoleContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRole() {
  const context = useContext(RoleContext);
  if (!context) throw new Error('useRole must be used within RoleProvider');
  return context;
}
