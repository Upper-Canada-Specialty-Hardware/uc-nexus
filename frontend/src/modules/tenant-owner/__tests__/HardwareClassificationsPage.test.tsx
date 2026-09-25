import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import HardwareClassificationsPage from '../HardwareClassificationsPage';
import {
  GET_HARDWARE_CLASSIFICATION_CHANGES,
  GET_PROJECT_HARDWARE_CLASSIFICATIONS,
  SET_HARDWARE_CLASSIFICATIONS,
} from '../../../graphql/classificationOverride';

// #735: the Tenant Owner corrects a product's classification after import, one row or in bulk, and a
// change something depends on comes back refused with the reason.

const INFINITE = Number.POSITIVE_INFINITY;
const PID = 'p1';

const row = (productCode: string, choice: string) => ({
  hardwareCategory: 'HINGE',
  productCode,
  quantity: 4,
  openingCount: 2,
  choice,
  __typename: 'ProjectHardwareClassification',
});

const listMock: MockedResponse = {
  request: { query: GET_PROJECT_HARDWARE_CLASSIFICATIONS, variables: { projectId: PID } },
  maxUsageCount: INFINITE,
  result: { data: { projectHardwareClassifications: [row('HG-1', 'UCH_SHOP'), row('HG-2', 'MIXED')] } },
};

const changesMock: MockedResponse = {
  request: { query: GET_HARDWARE_CLASSIFICATION_CHANGES, variables: { projectId: PID } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      hardwareClassificationChanges: [
        {
          id: 'c1',
          hardwareCategory: 'HINGE',
          productCode: 'HG-9',
          fromChoice: 'UCH_SITE',
          toChoice: 'UCH_SHOP',
          changedBy: 'Greg',
          changedAt: '2026-09-25T10:00:00',
          __typename: 'HardwareClassificationChange',
        },
      ],
    },
  },
};

const setMock = (result: MockedResponse['result']): MockedResponse => ({
  request: {
    query: SET_HARDWARE_CLASSIFICATIONS,
    variables: {
      input: { projectId: PID, changes: [{ hardwareCategory: 'HINGE', productCode: 'HG-1', choice: 'UCH_SITE' }] },
    },
  },
  result,
});

function renderPage(extra: MockedResponse[] = []) {
  return render(
    <MockedProvider mocks={[listMock, changesMock, ...extra]}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/app/tenant-owner/projects/${PID}/classifications`]}>
          <Routes>
            <Route path="/app/tenant-owner/projects/:id/classifications" element={<HardwareClassificationsPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('shows each product with its classification, a mixed one flagged, and the change log', async () => {
  renderPage();

  const group = await screen.findByRole('group', { name: 'Classification of HG-1' });
  expect(within(group).getByRole('button', { name: 'UCH Shop' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByText('Mixed')).toBeInTheDocument();
  expect(screen.getByLabelText('Classification change log')).toHaveTextContent('HG-9UCH Site → UCH Shopby Greg');
});

it('shows the server refusal naming what holds the product', async () => {
  renderPage([
    setMock({
      errors: [new GraphQLError('Nothing was changed. HG-1 (HINGE): on shop assembly SAR-001', { extensions: { code: 'CONFLICT' } })],
    }),
  ]);

  const group = await screen.findByRole('group', { name: 'Classification of HG-1' });
  fireEvent.click(within(group).getByRole('button', { name: 'UCH Site' }));

  expect(await screen.findByText(/on shop assembly SAR-001/)).toBeInTheDocument();
});
