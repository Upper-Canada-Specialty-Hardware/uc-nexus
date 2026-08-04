import { useQuery } from '@apollo/client/react';
import { GET_SHIPMENT_METHODS } from '../../graphql/shipping';

export interface ShipmentMethod {
  id: string;
  name: string;
  isActive: boolean;
  sortOrder: number;
}

/**
 * The active shipment methods, for the Delivery Request form (#451).
 *
 * Both the create form and the edit dialog need the same list, and both have to degrade to an empty
 * one rather than blocking: a company that has not set any methods up yet still has to be able to
 * book and correct shipments, and the field falls back to free text when the list is empty.
 */
export function useShipmentMethods(skip = false): ShipmentMethod[] {
  const { data } = useQuery<{ shipmentMethods: ShipmentMethod[] }>(GET_SHIPMENT_METHODS, {
    variables: { activeOnly: true },
    skip,
    fetchPolicy: 'cache-and-network',
  });
  return data?.shipmentMethods ?? [];
}
