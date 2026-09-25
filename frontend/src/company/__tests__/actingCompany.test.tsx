import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { useApolloClient } from '@apollo/client/react';
import { GET_NEXUS_COMPANIES } from '../../graphql/shared';
import { ActingCompanyProvider, useActingCompany } from '../ActingCompanyContext';
import {
  ACTING_COMPANY_STORAGE_KEY,
  publishActingCompanyHeader,
  readActingCompanyHeader,
  resolveActingCompany,
} from '../actingCompany';

// #845: a UC NEXUS ADMIN works in one GP company at a time. These pin which company they land in,
// that the Apollo header follows it, and that a scoped user never gets one to switch or send.

const identity = vi.hoisted(() => ({ isNexusAdmin: true, company: null as string | null }));

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Admin',
    userId: 'user_1',
    roles: identity.isNexusAdmin ? ['UC Nexus Admin'] : [],
    hasRole: (role: string) => identity.isNexusAdmin && role === 'UC Nexus Admin',
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: false,
    ownsTenant: identity.isNexusAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: { id: 'user_1' },
  }),
}));

const companiesMock: MockedResponse = {
  request: { query: GET_NEXUS_COMPANIES },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      nexusCompanies: [
        { id: 'TUBC', name: 'Test UBC', __typename: 'GpCompany' },
        { id: 'UCSH', name: 'Upper Canada', __typename: 'GpCompany' },
      ],
    },
  },
};

function wrapper(mocks: MockedResponse[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MockedProvider mocks={mocks}>
        <ActingCompanyProvider>{children}</ActingCompanyProvider>
      </MockedProvider>
    );
  };
}

function renderActing(mocks: MockedResponse[] = [companiesMock]) {
  return renderHook(() => ({ acting: useActingCompany(), client: useApolloClient() }), { wrapper: wrapper(mocks) });
}

/** An in-memory Storage: the runner may expose none, and each test wants its own. */
function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  };
}

let session: Storage;
let local: Storage;

beforeEach(() => {
  identity.isNexusAdmin = true;
  identity.company = null;
  session = memoryStorage();
  local = memoryStorage();
  vi.stubGlobal('sessionStorage', session);
  vi.stubGlobal('localStorage', local);
  publishActingCompanyHeader(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('resolveActingCompany', () => {
  const available = ['TUBC', 'UCSH', 'ZZZ'];

  it("prefers this tab's own pick, so a reload never moves the admin", () => {
    expect(resolveActingCompany({ tabPick: 'UCSH', own: 'TUBC', lastPick: 'ZZZ', available })).toBe('UCSH');
  });

  it('opens a new tab in the assigned company, then the last pick, then the first offered', () => {
    expect(resolveActingCompany({ tabPick: null, own: 'TUBC', lastPick: 'ZZZ', available })).toBe('TUBC');
    expect(resolveActingCompany({ tabPick: null, own: null, lastPick: 'ZZZ', available })).toBe('ZZZ');
    expect(resolveActingCompany({ tabPick: null, own: null, lastPick: null, available })).toBe('TUBC');
  });

  it('skips a remembered company the list no longer holds', () => {
    expect(resolveActingCompany({ tabPick: 'GONE', own: 'ALSO', lastPick: 'UCSH', available })).toBe('UCSH');
  });

  it('takes the first candidate on trust while the list is loading, so the first requests are scoped', () => {
    expect(resolveActingCompany({ tabPick: null, own: 'TUBC', lastPick: null, available: null })).toBe('TUBC');
    expect(resolveActingCompany({ tabPick: null, own: null, lastPick: null, available: null })).toBeNull();
  });
});

describe('ActingCompanyProvider', () => {
  it("lands an admin in their assigned company and sends it as the header", async () => {
    identity.company = 'UCSH';
    const { result } = renderActing();

    // Scoped from the very first render, before the list arrives.
    expect(result.current.acting.company).toBe('UCSH');
    expect(readActingCompanyHeader()).toBe('UCSH');
    await waitFor(() => expect(result.current.acting.companies).toHaveLength(2));
    expect(result.current.acting.canSwitch).toBe(true);
  });

  it('seeds a new tab from the last pick made in any tab', async () => {
    local.setItem(ACTING_COMPANY_STORAGE_KEY, 'UCSH');
    const { result } = renderActing();

    await waitFor(() => expect(result.current.acting.companies).toHaveLength(2));
    expect(result.current.acting.company).toBe('UCSH');
  });

  it("keeps this tab's pick over the assigned company", async () => {
    identity.company = 'TUBC';
    session.setItem(ACTING_COMPANY_STORAGE_KEY, 'UCSH');
    const { result } = renderActing();

    await waitFor(() => expect(result.current.acting.companies).toHaveLength(2));
    expect(result.current.acting.company).toBe('UCSH');
  });

  it('falls to the first company offered, holding pages off until the list is read', async () => {
    const { result } = renderActing();

    expect(result.current.acting.company).toBeNull();
    expect(result.current.acting.resolving).toBe(true);
    await waitFor(() => expect(result.current.acting.company).toBe('TUBC'));
    expect(result.current.acting.resolving).toBe(false);
    expect(readActingCompanyHeader()).toBe('TUBC');
  });

  it('a switch remembers the pick in both stores and empties the cache', async () => {
    identity.company = 'TUBC';
    const { result } = renderActing();
    await waitFor(() => expect(result.current.acting.companies).toHaveLength(2));
    const resetStore = vi.spyOn(result.current.client, 'resetStore').mockResolvedValue(null);

    act(() => result.current.acting.setCompany('UCSH'));

    expect(result.current.acting.company).toBe('UCSH');
    expect(readActingCompanyHeader()).toBe('UCSH');
    expect(session.getItem(ACTING_COMPANY_STORAGE_KEY)).toBe('UCSH');
    expect(local.getItem(ACTING_COMPANY_STORAGE_KEY)).toBe('UCSH');
    await waitFor(() => expect(resetStore).toHaveBeenCalledTimes(1));
  });

  it('a scoped user is always in their own company and never sends the header', () => {
    identity.isNexusAdmin = false;
    identity.company = 'TUBC';
    session.setItem(ACTING_COMPANY_STORAGE_KEY, 'UCSH');
    // No companies mock: a scoped user must not ask for the list at all.
    const { result } = renderActing([]);

    expect(result.current.acting.company).toBe('TUBC');
    expect(result.current.acting.canSwitch).toBe(false);
    expect(result.current.acting.companies).toEqual([]);
    expect(readActingCompanyHeader()).toBeNull();

    act(() => result.current.acting.setCompany('UCSH'));
    expect(result.current.acting.company).toBe('TUBC');
    expect(readActingCompanyHeader()).toBeNull();
  });

  it('survives storage that throws', async () => {
    // A private window or blocked site data: every touch throws.
    const blocked = () => {
      throw new Error('blocked');
    };
    for (const name of ['sessionStorage', 'localStorage']) {
      vi.stubGlobal(name, { getItem: blocked, setItem: blocked });
    }
    identity.company = 'TUBC';
    const { result } = renderActing();
    await waitFor(() => expect(result.current.acting.companies).toHaveLength(2));
    vi.spyOn(result.current.client, 'resetStore').mockResolvedValue(null);

    act(() => result.current.acting.setCompany('UCSH'));
    expect(result.current.acting.company).toBe('UCSH');
  });
});
