import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import HardwareStatusPage from '../HardwareStatusPage';
import { GET_HARDWARE_STATUS_BY_PRODUCT, GET_REPORT_PROJECT_OPTIONS } from '../../../graphql/admin';

const INFINITE = Number.POSITIVE_INFINITY;

const project = (id: string, projectId: string, description: string, openingCount: number, archived = false) => ({
  id,
  projectId,
  description,
  archived,
  openingCount,
  __typename: 'Project',
});

// 80001 has an imported schedule; 80003 is a GP-mirrored job with POs and no schedule (#741); 79990
// is a finished job that has been archived (#1200).
const projectsMock: MockedResponse = {
  request: { query: GET_REPORT_PROJECT_OPTIONS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      adminProjects: [
        project('p9', '79990', 'Old Library Annex', 12, true),
        project('p1', '80001', 'Cowichan Dist Hospital', 66),
        project('p3', '80003', 'Sea Bus Terminal Refurbishment', 0),
      ],
    },
  },
};

const statusMock = (projectIds: string[]): MockedResponse => ({
  request: { query: GET_HARDWARE_STATUS_BY_PRODUCT, variables: { projectIds } },
  maxUsageCount: INFINITE,
  result: { data: { hardwareStatusByProduct: [] } },
});

function renderPage() {
  return render(
    <MockedProvider
      mocks={[projectsMock, statusMock(['p3']), statusMock(['p1']), statusMock(['p1', 'p3']), statusMock(['p9'])]}
    >
      <MemoryRouter>
        <HardwareStatusPage />
      </MemoryRouter>
    </MockedProvider>,
  );
}

async function pick(label: string) {
  const input = screen.getByRole('combobox', { name: 'Projects' });
  fireEvent.mouseDown(input);
  fireEvent.click(await screen.findByRole('option', { name: label }));
}

it('names a picked project that has no imported schedule', async () => {
  renderPage();
  await pick('Sea Bus Terminal Refurbishment');

  expect(await screen.findByText(/No hardware schedule has been imported for 80003\./)).toBeInTheDocument();
});

it('says nothing about schedules when every picked project has one', async () => {
  renderPage();
  await pick('Cowichan Dist Hospital');

  expect(await screen.findByText('No hardware found for the selected projects.')).toBeInTheDocument();
  expect(screen.queryByText(/No hardware schedule has been imported/)).not.toBeInTheDocument();
});

it('names only the scheduleless projects in a mixed pick', async () => {
  renderPage();
  await pick('Cowichan Dist Hospital');
  await pick('Sea Bus Terminal Refurbishment');

  const notice = await screen.findByText(/No hardware schedule has been imported for/);
  expect(notice).toHaveTextContent('80003');
  expect(notice).not.toHaveTextContent('80001');
});

it('lists an archived project after the live ones, tagged, and it can be picked', async () => {
  renderPage();
  const input = screen.getByRole('combobox', { name: 'Projects' });
  fireEvent.mouseDown(input);

  const options = await screen.findAllByRole('option');
  expect(options.map((o) => o.textContent)).toEqual([
    'Cowichan Dist Hospital',
    'Sea Bus Terminal Refurbishment',
    'Old Library Annex (archived)',
  ]);
  fireEvent.click(options[2]);
  expect(await screen.findByText('No hardware found for the selected projects.')).toBeInTheDocument();
});
