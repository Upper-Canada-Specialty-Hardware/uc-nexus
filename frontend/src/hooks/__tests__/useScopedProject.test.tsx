import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { useApolloClient } from '@apollo/client/react';
import { GET_PROJECTS } from '../../graphql/shared';
import { useScopedProject } from '../useScopedProject';

const project = (id: string) => ({
  __typename: 'Project',
  id,
  projectId: `J-${id}`,
  description: `Job ${id}`,
  client: null,
  jobSiteName: null,
  scheduleFilename: null,
  company: 'A',
  openingCount: 0,
  gpSetupOk: true,
  gpSetupCheckedAt: null,
  gpSetupIssues: [],
  gpJobState: null,
});

it('drops a pick the acting company no longer offers (#1467)', async () => {
  let company = 'A';
  const projectsMock: MockedResponse = {
    request: { query: GET_PROJECTS },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: () => ({ data: { projects: company === 'A' ? [project('a1')] : [project('b1')] } }),
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MockedProvider mocks={[projectsMock]}>{children}</MockedProvider>
  );
  const picked = { id: 'a1' };
  const { result } = renderHook(() => ({ scoped: useScopedProject(picked), client: useApolloClient() }), {
    wrapper,
  });

  await waitFor(() => expect(result.current.scoped).toBe(picked));

  company = 'B';
  await act(async () => {
    await result.current.client.resetStore().catch(() => undefined);
  });
  await waitFor(() => expect(result.current.scoped).toBeNull());
});

it('passes no pick through as none', () => {
  const { result } = renderHook(() => useScopedProject(null), {
    wrapper: ({ children }: { children: ReactNode }) => <MockedProvider mocks={[]}>{children}</MockedProvider>,
  });
  expect(result.current).toBeNull();
});
