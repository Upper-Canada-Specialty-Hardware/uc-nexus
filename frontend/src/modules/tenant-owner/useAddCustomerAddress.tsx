import { useCallback, useState, type ReactNode } from 'react';
import { useApolloClient } from '@apollo/client/react';
import { GET_GP_CUSTOMER_ADDRESSES } from '../../graphql/import';
import AddCustomerAddressDialog, { type CreatedGpCustomerAddress } from './AddCustomerAddressDialog';
import type { GpCustomerOption } from './gpJobFieldOptions';

/**
 * #444: everything the add-address round trip needs, captured once when the "+ Add new address" row is
 * chosen. Deriving it again on the way back would re-read state the user could have changed in the
 * meantime. Null keeps the nested dialog unmounted, so its fields start clean every time.
 */
interface AddAddressTarget {
  /**
   * The customer the address is created under: the one the asking picker is bound to. It is also the
   * whole address of that picker's query - the pickers read gpCustomerAddresses and differ only in
   * this variable - so it doubles as the cache key to write into and the list to re-read.
   */
  customer: GpCustomerOption;
  /** The picker's own value setter. */
  select: (addressCode: string) => void;
}

/**
 * #444 / #730: the "+ Add new address" flow behind a GP address picker, shared by the Create GP job
 * dialog and the project edit dialog. `open` is called with the picker's customer and setter; the
 * returned `dialog` is rendered by the caller while a picker is asking.
 */
export function useAddCustomerAddress(company: string, relayConnected: boolean) {
  // The address pickers render out of the cache, so a created row is written there rather than
  // waited on over the network. Same handle RegisterGpBuyerDialog takes to re-read the buyer master.
  const client = useApolloClient();
  const [target, setTarget] = useState<AddAddressTarget | null>(null);

  const open = useCallback((customer: GpCustomerOption, select: (addressCode: string) => void) => {
    setTarget({ customer, select });
  }, []);

  const close = useCallback(() => setTarget(null), []);

  // A one-off read rather than the picker's own useQuery refetch: a refetch that fails puts that hook
  // into an error state, and Apollo drops its `data` there - which would take the row just written to
  // the cache (and the selection made from it) straight back out of the list. This leaves the watching
  // query alone: on success the cache write broadcasts GP's list to it, on failure nothing changes and
  // the user keeps the address GP really did store.
  const reconcile = useCallback(
    (customerNumber: string) =>
      client.query({
        query: GET_GP_CUSTOMER_ADDRESSES,
        variables: { company, customer: customerNumber },
        fetchPolicy: 'network-only',
      }),
    [client, company],
  );

  /**
   * #444: the row GP just stored becomes the picker's selection.
   *
   * The cache write is what makes the code offerable: a picker renders its options from its own query,
   * so putting the returned row into that query's cache entry puts the option there without waiting on
   * the network. The re-read still runs, in the background and with its failure ignored, purely to
   * reconcile with GP - it can no longer strand the selection. That mattered: the relay can drop in the
   * window right after taCreateCustomerAddress commits.
   */
  const handleCreated = useCallback(
    (created: CreatedGpCustomerAddress) => {
      if (!target) return;
      client.cache.updateQuery<{ gpCustomerAddresses: CreatedGpCustomerAddress[] }>(
        {
          query: GET_GP_CUSTOMER_ADDRESSES,
          variables: { company, customer: target.customer.customerNumber },
        },
        (data) => {
          const existing = data?.gpCustomerAddresses ?? [];
          // A re-read that already landed makes this a no-op rather than a duplicate row.
          if (existing.some((a) => a.addressCode === created.addressCode)) return undefined;
          return { gpCustomerAddresses: [...existing, created] };
        },
      );
      target.select(created.addressCode);
      void reconcile(target.customer.customerNumber).catch(() => undefined);
    },
    [target, client, company, reconcile],
  );

  /** #444: see AddCustomerAddressDialog's onDuplicate - the re-read is what clears the dead end. */
  const handleDuplicate = useCallback(() => {
    if (!target) return;
    void reconcile(target.customer.customerNumber).catch(() => undefined);
  }, [target, reconcile]);

  // Mounted only while a picker is asking, so the half-filled form stays behind it.
  const dialog: ReactNode = target ? (
    <AddCustomerAddressDialog
      open
      onClose={close}
      customer={target.customer}
      relayConnected={relayConnected}
      onCreated={handleCreated}
      onDuplicate={handleDuplicate}
    />
  ) : null;

  return { open, close, dialog };
}
