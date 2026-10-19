import { render, screen } from '@testing-library/react';
import ShipmentSiteFormFields from '../ShipmentSiteFormFields';
import { EMPTY_SITE_FORM } from '../shipmentSiteForm';

// #1650: with no method picked the select shows "(none)", and its label sat on top of it.
it('keeps the shipment method label above "(none)"', () => {
  render(
    <ShipmentSiteFormFields
      details={EMPTY_SITE_FORM}
      onChange={() => {}}
      shipperName="Demo Shipper"
      shipmentMethods={[{ id: 'm1', name: 'Demo courier' }]}
    />,
  );
  const label = screen.getByText('Shipment method', { selector: 'label' });
  expect(label).toHaveClass('MuiInputLabel-shrink');
  expect(screen.getByText('(none)')).toBeInTheDocument();
});
