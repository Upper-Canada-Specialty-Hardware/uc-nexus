import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ThemeProvider } from '@mui/material';
import theme from '../../theme';
import ReportBubble from '../ReportBubble';
import { SUBMIT_ISSUE_REPORT } from '../../graphql/issueReport';

// #1677: the report bubble opens into a dialog that files the report.

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Pat Lee',
    userId: 'user_test',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: false,
    company: 'TUBC',
    demoMode: false,
    user: null,
  }),
}));

let sent: Record<string, unknown> | null = null;

function filed(): MockedResponse {
  return {
    request: {
      query: SUBMIT_ISSUE_REPORT,
      variables: (vars: Record<string, unknown>) => {
        sent = vars;
        return true;
      },
    },
    result: {
      data: {
        submitIssueReport: {
          __typename: 'IssueReportResult',
          issueNumber: 4242,
          issueUrl: 'https://github.com/o/r/issues/4242',
          emailed: true,
        },
      },
    },
  };
}

function refused(): MockedResponse {
  return {
    request: { query: SUBMIT_ISSUE_REPORT, variables: () => true },
    error: new Error('The report could not be filed. Try again in a minute.'),
  };
}

function renderBubble(mocks: MockedResponse[]) {
  return render(
    <ThemeProvider theme={theme}>
      <MockedProvider mocks={mocks}>
        <ReportBubble />
      </MockedProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  sent = null;
});

it('opens the report dialog from the bubble', async () => {
  renderBubble([filed()]);

  fireEvent.click(screen.getByRole('button', { name: 'Report an issue' }));

  expect(await screen.findByRole('dialog', { name: 'Report an issue' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Send report' })).toBeDisabled();
});

it('sends the description with the page context and shows the issue it became', async () => {
  renderBubble([filed()]);
  fireEvent.click(screen.getByRole('button', { name: 'Report an issue' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Change request' }));
  fireEvent.change(screen.getByLabelText('What should change, and why?'), {
    target: { value: '  Let me filter POs by vendor  ' },
  });

  fireEvent.click(screen.getByRole('button', { name: 'Send report' }));

  expect(await screen.findByText('#4242')).toHaveAttribute('href', 'https://github.com/o/r/issues/4242');
  const input = (sent as { input: { kind: string; description: string; context: Record<string, unknown> } }).input;
  expect(input.kind).toBe('CHANGE');
  expect(input.description).toBe('Let me filter POs by vendor');
  expect(input.context).toMatchObject({ route: '/', module: 'home', build: 'dev' });
  // Who reported is not the client's to say.
  expect(JSON.stringify(input)).not.toContain('Pat Lee');
});

it('keeps the dialog open with the reason when the report is not filed', async () => {
  renderBubble([refused()]);
  fireEvent.click(screen.getByRole('button', { name: 'Report an issue' }));
  fireEvent.change(await screen.findByLabelText('What happened?'), { target: { value: 'It broke' } });

  fireEvent.click(screen.getByRole('button', { name: 'Send report' }));

  expect(await screen.findByRole('alert')).toHaveTextContent(/could not be filed/i);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});

it('closes again from Cancel', async () => {
  renderBubble([filed()]);
  fireEvent.click(screen.getByRole('button', { name: 'Report an issue' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
