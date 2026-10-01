import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { GraphQLError } from 'graphql';
import { ToastProvider } from '../../../components/Toast';
import HardwareClassificationsPage from '../HardwareClassificationsPage';
import {
  GET_HARDWARE_CLASSIFICATION_CHANGES,
  GET_HARDWARE_CLASSIFICATION_IMPACT,
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
          note: 'went to the shop on B-7',
          __typename: 'HardwareClassificationChange',
        },
      ],
    },
  },
};

const CHANGE = { projectId: PID, changes: [{ hardwareCategory: 'HINGE', productCode: 'HG-1', choice: 'UCH_SITE' }] };

// #1050: the impact the server plans for HG-1 -> UCH Site, shaped per test.
const impactMock = (lines: Partial<Record<'wentOut' | 'adjusts' | 'unaffected' | 'blocks', string[]>>): MockedResponse => ({
  request: { query: GET_HARDWARE_CLASSIFICATION_IMPACT, variables: { input: CHANGE } },
  result: {
    data: {
      hardwareClassificationImpact: [
        {
          hardwareCategory: 'HINGE',
          productCode: 'HG-1',
          fromChoice: 'UCH_SHOP',
          toChoice: 'UCH_SITE',
          wentOut: [],
          adjusts: [],
          unaffected: [],
          blocks: [],
          ...lines,
          __typename: 'HardwareClassificationImpact',
        },
      ],
    },
  },
});

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
  expect(screen.getByLabelText('Classification change log')).toHaveTextContent(
    'HG-9UCH Site → UCH Shopby Gregwent to the shop on B-7',
  );
  // #1050: the rules are spelled out before anyone changes anything.
  expect(screen.getByRole('region', { name: 'How a change works' })).toHaveTextContent(/applies to what is still owed/);
});

it('shows the server refusal naming what holds the product', async () => {
  renderPage([
    impactMock({}),
    setMock({
      errors: [new GraphQLError('Nothing was changed. HG-1 (HINGE): on shop assembly SAR-001', { extensions: { code: 'CONFLICT' } })],
    }),
  ]);

  const group = await screen.findByRole('group', { name: 'Classification of HG-1' });
  fireEvent.click(within(group).getByRole('button', { name: 'UCH Site' }));

  expect(await screen.findByText(/on shop assembly SAR-001/)).toBeInTheDocument();
});

const savedMock = () => {
  const saved = vi.fn(() => ({ data: { setHardwareClassifications: [row('HG-1', 'UCH_SITE'), row('HG-2', 'MIXED')] } }));
  return { saved, mock: setMock(saved) };
};

it('saves a change that touches nothing else straight away (#1050)', async () => {
  const { saved, mock } = savedMock();
  renderPage([impactMock({}), mock]);

  const group = await screen.findByRole('group', { name: 'Classification of HG-1' });
  fireEvent.click(within(group).getByRole('button', { name: 'UCH Site' }));

  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(screen.queryByLabelText('What this change does')).toBeNull();
});

it('shows what a change does and saves it only on confirm (#1050)', async () => {
  const { saved, mock } = savedMock();
  renderPage([
    impactMock({
      wentOut: ['went to the shop on B-7'],
      adjusts: ['comes off shop assembly request SAR-3 (opening A01); the Shop Assembly Manager is told'],
    }),
    mock,
  ]);

  const group = await screen.findByRole('group', { name: 'Classification of HG-1' });
  fireEvent.click(within(group).getByRole('button', { name: 'UCH Site' }));

  const preview = await screen.findByLabelText('What this change does');
  expect(preview).toHaveTextContent('Already went out - stays as it went');
  expect(preview).toHaveTextContent('went to the shop on B-7');
  expect(preview).toHaveTextContent('comes off shop assembly request SAR-3');
  expect(saved).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(saved).toHaveBeenCalled());
});

it('will not save while a product is blocked (#1050)', async () => {
  renderPage([impactMock({ blocks: ['on shop assembly batch B-8, still being pulled'] })]);

  const group = await screen.findByRole('group', { name: 'Classification of HG-1' });
  fireEvent.click(within(group).getByRole('button', { name: 'UCH Site' }));

  expect(await screen.findByRole('button', { name: 'Save' })).toBeDisabled();
  expect(screen.getByLabelText('What this change does')).toHaveTextContent(/Blocks the change.*still being pulled/);
});
