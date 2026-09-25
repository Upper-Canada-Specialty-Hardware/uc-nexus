import type { ReactElement } from 'react';
import { render, screen } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import GpCompanyTag from '../GpCompanyTag';
import { GET_RELAY_STATUS } from '../../graphql/shared';

// #831: the one way every screen names a GP company - code, then GP's own name for it.
const NAMES = [
  { id: 'TUBC', name: 'Test UBC' },
  { id: 'BARE', name: 'BARE' },
];

function renderTag(ui: ReactElement, mocks: MockedResponse[] = []) {
  return render(<MockedProvider mocks={mocks}>{ui}</MockedProvider>);
}

describe('GpCompanyTag', () => {
  it('shows the code and GP name, with the full label in the title', () => {
    renderTag(<GpCompanyTag code="TUBC" gpCompanies={NAMES} />);

    expect(screen.getByText('TUBC')).toBeInTheDocument();
    expect(screen.getByText('Test UBC')).toBeInTheDocument();
    expect(screen.getByTitle('GP company: TUBC - Test UBC')).toBeInTheDocument();
  });

  it('falls back to the bare code when GP gave no name, or a name that is the code', () => {
    renderTag(
      <>
        <GpCompanyTag code="NONAME" gpCompanies={NAMES} />
        <GpCompanyTag code="BARE" gpCompanies={NAMES} />
      </>,
    );

    expect(screen.getByTitle('GP company: NONAME')).toHaveTextContent(/^NONAME$/);
    expect(screen.getByTitle('GP company: BARE')).toHaveTextContent(/^BARE$/);
  });

  it('carries a plain caption in front when given one', () => {
    renderTag(<GpCompanyTag code="TUBC" gpCompanies={NAMES} caption="GP company" />);

    expect(screen.getByTitle('GP company: TUBC - Test UBC')).toHaveTextContent('GP companyTUBCTest UBC');
  });

  it('renders nothing without a code', () => {
    renderTag(<GpCompanyTag code={null} gpCompanies={NAMES} />);

    expect(screen.queryByTestId('gp-company-tag')).toBeNull();
  });

  it('reads the names itself when the caller holds none', async () => {
    const relayMock: MockedResponse = {
      request: { query: GET_RELAY_STATUS },
      result: {
        data: {
          relayStatus: {
            connected: true,
            companies: ['TUBC'],
            gpCompanies: [{ id: 'TUBC', name: 'Test UBC', __typename: 'GpCompany' }],
            companiesError: null,
            build: null,
            installId: null,
            lastConnectedAt: null,
            lastDisconnectedAt: null,
            lastDisconnectReason: null,
            previewChannels: [],
            __typename: 'RelayStatus',
          },
        },
      },
    };
    renderTag(<GpCompanyTag code="TUBC" />, [relayMock]);

    // The bare code first, while the one read is in flight; then GP's name once it lands.
    expect(screen.getByText('TUBC')).toBeInTheDocument();
    expect(await screen.findByText('Test UBC')).toBeInTheDocument();
  });
});
