import { render, screen } from '@testing-library/react';
import DeliveryRequestFields from '../DeliveryRequestFields';
import { EMPTY_DELIVERY_DETAILS } from '../deliveryRequest';

// #1650: with no method picked the select shows "(none)", and its label sat on top of it.
it('keeps the shipment method label above "(none)"', () => {
  render(
    <DeliveryRequestFields
      details={EMPTY_DELIVERY_DETAILS}
      onChange={() => {}}
      shipperName="Demo Shipper"
      shipmentMethods={[{ id: 'm1', name: 'Demo courier' }]}
    />,
  );
  const label = screen.getByText('Shipment method', { selector: 'label' });
  expect(label).toHaveClass('MuiInputLabel-shrink');
  expect(screen.getByText('(none)')).toBeInTheDocument();
});
