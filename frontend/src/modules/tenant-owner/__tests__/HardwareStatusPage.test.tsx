import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import HardwareStatusPage from '../HardwareStatusPage';
import { GET_PROJECTS } from '../../../graphql/shared';
import { GET_HARDWARE_STATUS_BY_PRODUCT } from '../../../graphql/admin';

const INFINITE = Number.POSITIVE_INFINITY;

const project = (id: string, projectId: string, description: string, openingCount: number) => ({
  id,
  projectId,
  description,
  client: null,
  jobSiteName: null,
  scheduleFilename: null,
  company: 'TUBC',
  openingCount,
  gpSetupOk: true,
  gpSetupCheckedAt: null,
  gpSetupIssues: [],
  gpJobState: null,
  __typename: 'Project',
});

// 80001 has an imported schedule; 80003 is a GP-mirrored job with POs and no schedule (#741).
const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      projects: [
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
    <MockedProvider mocks={[projectsMock, statusMock(['p3']), statusMock(['p1']), statusMock(['p1', 'p3'])]}>
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
