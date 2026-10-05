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
