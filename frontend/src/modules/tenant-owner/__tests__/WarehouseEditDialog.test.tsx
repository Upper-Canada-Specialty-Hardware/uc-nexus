import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import WarehouseEditDialog, { type WarehouseFormValue } from '../WarehouseEditDialog';
import { ToastProvider } from '../../../components/Toast';
import { UPDATE_WAREHOUSE } from '../../../graphql/admin';

vi.mock('../../../company/ActingCompanyContext', () => ({
  useActingCompany: () => ({ company: 'TUBC', companies: [], canSwitch: false, setCompany: () => {}, resolving: false }),
}));

const existing: WarehouseFormValue = {
  id: 'wh-1',
  name: 'Main',
  code: 'MAIN',
  company: 'TUBC',
  address: '12 Depot Rd',
  city: 'Toronto',
  province: 'ON',
  postalCode: 'M1M 1M1',
  isPrimary: false,
  isActive: true,
};

describe('WarehouseEditDialog', () => {
  it('clears a blanked address field on an edit instead of leaving it (#1463)', async () => {
    const calls: Record<string, unknown>[] = [];
    const mocks: MockedResponse[] = [
      {
        request: { query: UPDATE_WAREHOUSE, variables: () => true },
        result: (vars) => {
          calls.push(vars as Record<string, unknown>);
          return {
            data: {
              updateWarehouse: {
                __typename: 'Warehouse',
                ...existing,
                postalCode: null,
                createdAt: '2026-01-01T00:00:00',
                updatedAt: '2026-01-02T00:00:00',
              },
            },
          };
        },
      },
    ];
    render(
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <WarehouseEditDialog open warehouse={existing} onClose={() => {}} />
        </ToastProvider>
      </MockedProvider>,
    );

    fireEvent.change(screen.getByLabelText('Postal Code'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(calls).toHaveLength(1));
    const input = calls[0].input as Record<string, unknown>;
    // '' clears (the server stores it as empty); null would mean "leave it".
    expect(input.postalCode).toBe('');
    expect(input.address).toBe('12 Depot Rd');
  });

  // #1470: each error shows under the field it is about, not all of them under Name.
  const renderEdit = (mocks: MockedResponse[] = []) =>
    render(
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <WarehouseEditDialog open warehouse={existing} onClose={() => {}} />
        </ToastProvider>
      </MockedProvider>,
    );
  const helperOf = (label: string) => {
    const describedBy = screen.getByLabelText(new RegExp(`^${label}`)).getAttribute('aria-describedby');
    return describedBy ? (document.getElementById(describedBy)?.textContent ?? '') : '';
  };
  const refused = (field: string, message: string): MockedResponse => ({
    request: { query: UPDATE_WAREHOUSE, variables: () => true },
    result: { errors: [new GraphQLError(message, { extensions: { code: 'CONFLICT', field } })] },
  });

  it('marks Code, not Name, when the code is left empty (#1470)', () => {
    renderEdit();
    fireEvent.change(screen.getByLabelText(/^Code/), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(helperOf('Code')).toBe('Warehouse code is required');
    expect(helperOf('Name')).toBe('');
  });

  it('puts a server refusal under the field it names (#1470)', async () => {
    renderEdit([refused('code', "A warehouse with code 'MAIN' already exists")]);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(helperOf('Code')).toBe("A warehouse with code 'MAIN' already exists"));
    expect(helperOf('Name')).toBe('');
  });

  it('puts a duplicate name under Name (#1470)', async () => {
    renderEdit([refused('name', "A warehouse named 'Main' already exists")]);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(helperOf('Name')).toBe("A warehouse named 'Main' already exists"));
    expect(helperOf('Code')).toBe('');
  });
});
