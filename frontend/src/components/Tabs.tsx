import { useState, type ReactNode } from 'react';
import { Tabs as MuiTabs, Tab, Box } from '@mui/material';
import { FadeIn } from '../motion';

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
      <MuiTabs
        value={value}
        onChange={(_, newValue) => setValue(newValue)}
        sx={{ borderBottom: 1, borderColor: 'divider', minHeight: 42 }}
      >
        {tabs.map((tab, index) => (
          <Tab key={index} label={tab.label} sx={{ minHeight: 42, px: 2 }} />
        ))}
      </MuiTabs>
      {/* Keyed by tab so the panel swaps with a short rise instead of a hard cut. */}
      <FadeIn key={value} y={6}>
        <Box sx={{ pt: 2 }}>{tabs[value]?.content}</Box>
      </FadeIn>
    </Box>
  );
}
