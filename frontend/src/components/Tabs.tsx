import { useState, type ReactNode } from 'react';
import { Tabs as MuiTabs, Tab, Box } from '@mui/material';

interface TabItem {
  label: string;
  content: ReactNode;
}

interface TabsProps {
  tabs: TabItem[];
  defaultTab?: number;
}

export default function Tabs({ tabs, defaultTab = 0 }: TabsProps) {
  const [value, setValue] = useState(defaultTab);

  return (
    <Box>
      <MuiTabs value={value} onChange={(_, newValue) => setValue(newValue)}>
        {tabs.map((tab, index) => (
          <Tab key={index} label={tab.label} />
        ))}
      </MuiTabs>
      <Box sx={{ pt: 2 }}>{tabs[value]?.content}</Box>
    </Box>
  );
}
