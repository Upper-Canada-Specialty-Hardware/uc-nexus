import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import ProjectPicker from '../ProjectPicker';
import { GET_PROJECTS } from '../../graphql/shared';

vi.mock('../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    roles: [],
    hasRole: () => false,
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

const INFINITE = Number.POSITIVE_INFINITY;

// Neither name carries its own number, so a search that hits one from the other can only have come
// from the number being searched too.
const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: INFINITE,
  result: {
    data: {
      projects: [
        {
          id: 'p1',
          projectId: 'JOB-100',
          description: 'Main St Job',
          client: 'ACME',
          jobSiteName: 'Main St',
          company: 'TUBC',
          openingCount: 3,
          __typename: 'Project',
        },
        {
          id: 'p2',
          projectId: 'JOB-200',
          description: 'Elm St Job',
          client: 'ACME',
          jobSiteName: 'Elm St',
          company: 'TUBC',
          openingCount: 2,
          __typename: 'Project',
        },
      ],
    },
  },
};

// The text has to be typed into a focused input: unfocused, MUI wipes it back to the selected option
// the next time anything re-renders.
function typeInto(input: HTMLElement, text: string) {
  input.focus();
  fireEvent.change(input, { target: { value: text } });
}

function renderPicker() {
  const onChange = vi.fn();
  render(
    <MockedProvider mocks={[projectsMock]}>
      <ProjectPicker value={null} onChange={onChange} placeholder="Type to search projects…" />
    </MockedProvider>,
  );
  return { onChange };
}

describe('ProjectPicker', () => {
  it('finds a project by its number', async () => {
    const { onChange } = renderPicker();

    typeInto(screen.getByLabelText('Project'), 'JOB-200');

    fireEvent.click(await screen.findByText('Elm St Job'));
    expect(screen.queryByText('Main St Job')).toBeNull();
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'p2' }));
  });

  it('finds a project by its name', async () => {
    const { onChange } = renderPicker();

    typeInto(screen.getByLabelText('Project'), 'Main St');

    fireEvent.click(await screen.findByText('Main St Job'));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'p1' }));
  });

  // #689: the label used to sit inside the empty field, printing on top of the placeholder. Held in
  // the outline notch it cannot, and the placeholder reads as the hint it is meant to be.
  it('keeps the label out of the placeholder while the field is empty and unfocused', () => {
    renderPicker();

    // The notched outline carries the same words in its legend, so the label itself is asked for.
    expect(screen.getByText('Project', { selector: 'label' })).toHaveAttribute('data-shrink', 'true');
    expect(screen.getByPlaceholderText('Type to search projects…')).toBeInTheDocument();
  });
});
