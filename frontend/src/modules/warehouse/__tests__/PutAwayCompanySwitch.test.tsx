import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import PutAwayTab from '../PutAwayTab';
import { GET_UNLOCATED_INVENTORY, GET_STOCK_ITEMS } from '../../../graphql/warehouse';
import { GET_PROJECTS, GET_WAREHOUSES } from '../../../graphql/shared';

// #1469: a UC NEXUS ADMIN's company switch reloads the project and warehouse lists. A filter picked in
// the previous company must drop out of what the queues are asked for, not narrow them to nothing.
const project = (id: string, description: string) => ({ id, projectId: id, description, company: 'X' });
const warehouse = (id: string, name: string) => ({ id, name, code: id.toUpperCase(), isActive: true });

const COMPANY_A = {
  projects: [project('pa-1', 'A Job')],
  warehouses: [warehouse('wa-1', 'A Main'), warehouse('wa-2', 'A Yard')],
};
const COMPANY_B = {
  projects: [project('pb-1', 'B Job')],
  warehouses: [warehouse('wb-1', 'B Main'), warehouse('wb-2', 'B Yard')],
};
let company = COMPANY_A;
const sent: { query: DocumentNode; variables: Record<string, unknown> | undefined }[] = [];

vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { variables?: Record<string, unknown> }) => {
    sent.push({ query, variables: options?.variables });
    const data =
      query === GET_PROJECTS
        ? { projects: company.projects }
        : query === GET_WAREHOUSES
          ? { warehouses: company.warehouses }
          : query === GET_UNLOCATED_INVENTORY
            ? { unlocatedInventory: [] }
            : query === GET_STOCK_ITEMS
              ? { stockItems: [] }
              : undefined;
    return { data, loading: false, error: undefined, refetch: vi.fn() };
  },
  useMutation: () => [vi.fn(), { loading: false }],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));

beforeEach(() => {
  company = COMPANY_A;
  sent.length = 0;
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => vi.unstubAllGlobals());

const lastVariables = (query: DocumentNode) => [...sent].reverse().find((s) => s.query === query)?.variables;

function pick(combobox: HTMLElement, option: string) {
  fireEvent.mouseDown(combobox);
  fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: option }));
}

it("drops the previous company's project and warehouse filters on a company switch (#1469)", () => {
  // A fresh element each time: the same one again would let React skip the re-render.
  const ui = () => (
    <MemoryRouter>
      <PutAwayTab />
    </MemoryRouter>
  );
  const { rerender } = render(ui());

  pick(screen.getByRole('combobox', { name: 'Warehouse' }), 'A Yard (WA-2)');
  pick(screen.getAllByRole('combobox')[0], 'A Job');
  expect(lastVariables(GET_UNLOCATED_INVENTORY)).toEqual({ projectId: 'pa-1', warehouseId: 'wa-2' });

  company = COMPANY_B;
  rerender(ui());

  expect(lastVariables(GET_UNLOCATED_INVENTORY)).toEqual({ projectId: undefined, warehouseId: undefined });
  expect(lastVariables(GET_STOCK_ITEMS)).toMatchObject({ warehouseId: null });
  // Back on the empty choice: nothing of the previous company's warehouse is left showing.
  expect(screen.getByRole('combobox', { name: 'Warehouse' })).not.toHaveTextContent('A Yard');
});
