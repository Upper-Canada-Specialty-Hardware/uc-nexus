import { render, screen } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import CompanyWordmark from '../CompanyWordmark';
import { GET_COMPANY_LETTERHEAD } from '../../graphql/po';

// #1689: the app bar names the company the user is working in, GP's name for it, under the wordmark.
const acting = vi.hoisted(() => ({ company: 'TUBC' as string | null, canSwitch: false }));
vi.mock('../../company/ActingCompanyContext', () => ({ useActingCompany: () => acting }));

const letterhead = (company: string | null, name: string): MockedResponse => ({
  request: { query: GET_COMPANY_LETTERHEAD, variables: { company } },
  result: { data: { companyLetterhead: { __typename: 'CompanyLetterhead', company: company ?? 'TUBC', name, address: '' } } },
});

function renderWordmark(mocks: MockedResponse[]) {
  render(
    <MockedProvider mocks={mocks}>
      <CompanyWordmark />
    </MockedProvider>,
  );
}

describe('CompanyWordmark', () => {
  it("names a scoped user's company by GP's name, asking for the company the server scopes them to", async () => {
    Object.assign(acting, { company: 'TUBC', canSwitch: false });
    renderWordmark([letterhead(null, 'Test UBC')]);

    expect(screen.getByText('UC Nexus')).toBeInTheDocument();
    expect(await screen.findByText('Test UBC')).toBeInTheDocument();
  });

  it('names the company an admin switched to', async () => {
    Object.assign(acting, { company: 'UCSH', canSwitch: true });
    renderWordmark([letterhead('UCSH', 'UC Specialty Hardware')]);

    expect(await screen.findByText('UC Specialty Hardware')).toBeInTheDocument();
  });

  it('shows the code until the name is read', () => {
    Object.assign(acting, { company: 'UCSH', canSwitch: true });
    renderWordmark([]);

    expect(screen.getByTestId('company-wordmark-name')).toHaveTextContent('UCSH');
  });

  it('shows only the wordmark for an admin working in no company', () => {
    Object.assign(acting, { company: null, canSwitch: true });
    renderWordmark([]);

    expect(screen.getByText('UC Nexus')).toBeInTheDocument();
    expect(screen.queryByTestId('company-wordmark-name')).toBeNull();
  });
});
