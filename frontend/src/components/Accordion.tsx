import {
  Accordion as MuiAccordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
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
        <MuiAccordion key={item.id} defaultExpanded={item.id === defaultExpanded}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography sx={{ fontWeight: 500 }}>{item.title}</Typography>
            {item.subtitle && (
              <Typography sx={{ ml: 2, color: 'text.secondary' }}>
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
