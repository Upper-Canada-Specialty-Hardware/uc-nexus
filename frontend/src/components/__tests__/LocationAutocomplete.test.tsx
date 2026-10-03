import { useState } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import LocationAutocomplete, { NO_DEFINED_LOCATIONS_TEXT } from '../LocationAutocomplete';

// #1345: a strict pick with nothing defined says why, instead of MUI's bare "No options".

function Harness({ options }: { options: string[] }) {
  const [value, setValue] = useState('');
  return <LocationAutocomplete label="Aisle" value={value} onChange={setValue} options={options} freeSolo={false} />;
}

function openPicker(options: string[]) {
  render(<Harness options={options} />);
  const input = screen.getByLabelText('Aisle');
  input.focus();
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  return input;
}

describe('LocationAutocomplete', () => {
  it('points at the Locations tab when the warehouse has no defined locations', () => {
    openPicker([]);
    expect(screen.getByText(NO_DEFINED_LOCATIONS_TEXT)).toBeInTheDocument();
  });

  it('says no match, not no locations, when typing misses a defined aisle', () => {
    const input = openPicker(['A', 'B']);
    fireEvent.change(input, { target: { value: 'Z' } });
    expect(screen.getByText('No matching defined location')).toBeInTheDocument();
    expect(screen.queryByText(NO_DEFINED_LOCATIONS_TEXT)).toBeNull();
  });
});
