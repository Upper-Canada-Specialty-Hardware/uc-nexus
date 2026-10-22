import { render, screen, fireEvent } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import PhotoStrip from '../PhotoStrip';
import PhotoCapture from '../PhotoCapture';
import { ADD_SHIPMENT_PHOTO, DELETE_SHIPMENT_PHOTO } from '../../../graphql/shipping';
import type { ShipmentPhoto } from '../photos';

/**
 * Shipment photos on screen (#1728). Pinned: each thumbnail opens the full photo, a mistake can be taken
 * back off, and a picked photo is sent as the kind and subject the button was given.
 */

const photo: ShipmentPhoto = {
  id: 'ph-1',
  kind: 'DELIVERY',
  containerId: null,
  packingSlipId: 'ps-1',
  fileName: 'IMG_0001.jpg',
  takenBy: 'Dan Driver',
  takenByUserId: 'u_dan',
  takenAt: '2026-10-16T18:00:00Z',
  url: 'https://signed.example/ph-1',
};

it('opens each photo full size and removes one taken by mistake', async () => {
  const onRemoved = vi.fn(() => ({ data: { deleteShipmentPhoto: true } }));
  const removed: MockedResponse = {
    request: { query: DELETE_SHIPMENT_PHOTO, variables: { id: 'ph-1' } },
    result: onRemoved,
  };
  render(
    <MockedProvider mocks={[removed]}>
      <ToastProvider>
        <PhotoStrip photos={[photo]} removeRefetchQueries={[]} />
      </ToastProvider>
    </MockedProvider>,
  );
  expect(screen.getByRole('link', { name: /Delivery photo by Dan Driver/ })).toHaveAttribute('href', photo.url);
  fireEvent.click(screen.getByRole('button', { name: /Remove Delivery photo by Dan Driver/ }));
  await vi.waitFor(() => expect(onRemoved).toHaveBeenCalled());
});

it('offers remove only on the photos it is told may be removed (#1823)', () => {
  const office: ShipmentPhoto = { ...photo, id: 'ph-2', takenBy: 'Olive Office', takenByUserId: 'u_office' };
  render(
    <MockedProvider mocks={[]}>
      <ToastProvider>
        <PhotoStrip photos={[photo, office]} removeRefetchQueries={[]} canRemove={(p) => p.takenByUserId === 'u_dan'} />
      </ToastProvider>
    </MockedProvider>,
  );
  expect(screen.getByRole('button', { name: /Remove Delivery photo by Dan Driver/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Remove Delivery photo by Olive Office/ })).not.toBeInTheDocument();
});

it('sends a picked photo as the kind and shipment it was taken for', async () => {
  const added = vi.fn(() => ({
    data: { addShipmentPhoto: { __typename: 'ShipmentPhoto', ...photo } },
  }));
  render(
    <MockedProvider
      mocks={[
        {
          // A matcher, since the file's bytes arrive base64-encoded: what matters is what it was taken of.
          request: {
            query: ADD_SHIPMENT_PHOTO,
            variables: (v: Record<string, unknown>) =>
              v.kind === 'DELIVERY' && v.packingSlipId === 'ps-1' && v.containerId === null && v.fileName === 'site.jpg',
          },
          result: added,
        },
      ]}
    >
      <ToastProvider>
        <PhotoCapture kind="DELIVERY" packingSlipId="ps-1" refetchQueries={[]} label="Add delivery photo" />
      </ToastProvider>
    </MockedProvider>,
  );
  const file = new File(['jpeg-bytes'], 'site.jpg', { type: 'image/jpeg' });
  fireEvent.change(screen.getByTestId('photo-input-delivery'), { target: { files: [file] } });
  await vi.waitFor(() => expect(added).toHaveBeenCalled());
});
