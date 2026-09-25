import type { ReactElement } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Button } from '@mui/material';
import PageHeader from '../PageHeader';

function renderHeader(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('PageHeader', () => {
  it('names the parent page as a link to it', () => {
    renderHeader(<PageHeader title="Receives" parent={{ label: 'Warehouse', to: '/app/warehouse' }} />);
    const link = screen.getByRole('link', { name: 'Warehouse' });
    expect(link).toHaveAttribute('href', '/app/warehouse');
  });

  it('renders no link when the page has no parent', () => {
    renderHeader(<PageHeader title="Warehouse" description="Everything on the shelves." />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('Everything on the shelves.')).toBeInTheDocument();
  });

  it('renders the page actions', () => {
    renderHeader(
      <PageHeader
        title="Receives"
        parent={{ label: 'Warehouse', to: '/app/warehouse' }}
        actions={<Button>Export</Button>}
      />,
    );
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument();
  });

  // #845: an admin page that spans every GP company says so, since the app bar's switcher names one.
  it('says the page spans every GP company when asked', () => {
    renderHeader(<PageHeader title="Relay Installs" allCompanies />);
    expect(screen.getByText(/^All GP companies/)).toBeInTheDocument();
  });

  it('says nothing about companies otherwise', () => {
    renderHeader(<PageHeader title="Receives" />);
    expect(screen.queryByText(/All GP companies/)).not.toBeInTheDocument();
  });
});
