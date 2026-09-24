import { render, screen } from '@testing-library/react';
import GpJobNotOpenBanner, { GpJobStateTag } from '../GpJobStateTag';
import type { GpJobState } from '../../types/project';

describe('GpJobStateTag (#730)', () => {
  it.each([
    ['INACTIVE', 'Inactive in GP'],
    ['CLOSED', 'Closed in GP'],
    ['NOT_IN_GP', 'Not in GP'],
  ] as Array<[GpJobState, string]>)('tags a %s job "%s"', (state, label) => {
    render(<GpJobStateTag project={{ gpJobState: state }} />);
    expect(screen.getByTestId('gp-job-state-tag')).toHaveTextContent(label);
  });

  it.each([['ACTIVE'], [null], [undefined]] as Array<[GpJobState | null | undefined]>)(
    'renders nothing for %s - an open or never-mirrored job carries no tag',
    (state) => {
      const { container } = render(<GpJobStateTag project={{ gpJobState: state }} />);
      expect(container).toBeEmptyDOMElement();
    },
  );
});

describe('GpJobNotOpenBanner (#730)', () => {
  it('names the job, its tag and the refused action', () => {
    render(<GpJobNotOpenBanner project={{ projectId: 'JOB-9', gpJobState: 'CLOSED' }} action="receiving PO-1" />);
    const banner = screen.getByTestId('gp-job-not-open-banner');
    expect(banner).toHaveTextContent('GP job JOB-9: Closed in GP');
    expect(banner).toHaveTextContent('which is permanent');
    expect(banner).toHaveTextContent('So receiving PO-1 is not possible.');
  });

  it('says an inactive job can come back', () => {
    render(<GpJobNotOpenBanner project={{ projectId: 'JOB-9', gpJobState: 'INACTIVE' }} action="x" />);
    expect(screen.getByTestId('gp-job-not-open-banner')).toHaveTextContent('made active again in GP');
  });

  it('renders nothing for an open job', () => {
    const { container } = render(<GpJobNotOpenBanner project={{ gpJobState: 'ACTIVE' }} action="x" />);
    expect(container).toBeEmptyDOMElement();
  });
});
