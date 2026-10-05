import { render, screen } from '@testing-library/react';
import LoadError from '../LoadError';
import { NETWORK_MESSAGE, READ_NETWORK_MESSAGE } from '../../graphql/userMessage';

// #1553: a read that failed during a redeploy said "...the read failed. Failed to fetch".
it('says a read that never reached Nexus failed for a connection reason, in plain words', () => {
  render(<LoadError what="the shipping requests" error={new TypeError('Failed to fetch')} />);

  // #1556: and as a read - nobody was saving, so the save advice does not belong here.
  expect(screen.getByRole('alert')).toHaveTextContent(READ_NETWORK_MESSAGE);
  expect(screen.getByRole('alert')).not.toHaveTextContent(NETWORK_MESSAGE);
  expect(screen.getByRole('alert')).not.toHaveTextContent('Failed to fetch');
});

// #1561: the read line itself promises no button, so the banner - which has one - points at it, and only then.
it('points at its Retry button only when it shows one', () => {
  const { unmount } = render(
    <LoadError what="the pull requests" error={new TypeError('Failed to fetch')} onRetry={() => undefined} />,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('Press Retry when the connection is back.');
  unmount();

  render(<LoadError what="the pull requests" error={new TypeError('Failed to fetch')} />);
  expect(screen.getByRole('alert')).not.toHaveTextContent(/press retry/i);
});
