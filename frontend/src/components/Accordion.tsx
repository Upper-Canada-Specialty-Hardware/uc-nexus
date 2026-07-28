import {
  Accordion as MuiAccordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
} from '@mui/material';
import { ChevronDown } from 'lucide-react';
import type { ReactNode } from 'react';

interface AccordionItem {
  id: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}

interface AccordionProps {
  items: AccordionItem[];
  defaultExpanded?: string;
}

export default function Accordion({ items, defaultExpanded }: AccordionProps) {
  return (
    <>
      {items.map((item) => (
        <MuiAccordion
          key={item.id}
          defaultExpanded={item.id === defaultExpanded}
          sx={{
            '& .MuiAccordionSummary-root': { minHeight: 48 },
            '&.Mui-expanded': { borderLeft: '3px solid', borderLeftColor: 'secondary.main' },
          }}
        >
          <AccordionSummary expandIcon={<ChevronDown size={18} strokeWidth={1.75} />}>
            <Typography sx={{ fontWeight: 600 }}>{item.title}</Typography>
            {item.subtitle && (
              <Typography variant="body2" sx={{ ml: 2, color: 'text.secondary', alignSelf: 'center' }}>
                {item.subtitle}
              </Typography>
            )}
          </AccordionSummary>
          <AccordionDetails>{item.children}</AccordionDetails>
        </MuiAccordion>
      ))}
    </>
  );
}
