/**
 * #730: the option shapes and small helpers behind the GP job pickers, shared by the Create GP job
 * dialog and the project edit dialog. Both write the same GP job, so both offer the same lists the
 * same way - a fix to one picker is a fix to both.
 */

export interface GpCustomerOption {
  customerNumber: string;
  customerName: string | null;
}

export interface GpCustomerAddressOption {
  addressCode: string;
  address1: string | null;
  city: string | null;
  state: string | null;
}

export interface GpTaxScheduleOption {
  taxScheduleId: string;
  description: string | null;
}

export interface GpEmployeeOption {
  employeeId: string;
  firstName: string | null;
  lastName: string | null;
}

/** GP column widths, so an over-length value is caught in the field rather than by the proc. */
export const MAX = { jobNumber: 17, jobName: 31, projectNumber: 17, id: 15 };

export function employeeLabel(e: GpEmployeeOption): string {
  const name = [e.firstName, e.lastName].filter(Boolean).join(' ');
  return name ? `${e.employeeId} - ${name}` : e.employeeId;
}

export function customerLabel(c: GpCustomerOption): string {
  return c.customerName ? `${c.customerNumber} - ${c.customerName}` : c.customerNumber;
}

export function addressLabel(a: GpCustomerAddressOption): string {
  // An address code on its own ('MAIN', 'PRIMARY', 'RIH') doesn't say which site it is.
  const where = [a.address1, a.city].filter(Boolean).join(', ');
  return where ? `${a.addressCode} - ${where}` : a.addressCode;
}

export function taxScheduleLabel(t: GpTaxScheduleOption): string {
  return t.description ? `${t.taxScheduleId} - ${t.description}` : t.taxScheduleId;
}

/**
 * #444: the value the "+ Add new address" row carries. A MUI select has no way to hold an action
 * alongside its options, so the choice arrives through onChange like any other - and this is the one
 * value that must never be stored, since it is not an address code GP would accept.
 */
export const ADD_ADDRESS = '__add__';

/**
 * #444: the sentinel is never a code GP would accept, so anything holding it is holding no selection.
 * The onChange interceptors are the first line - this is the second, so a future writer that manages
 * to store the sentinel still cannot enable the submit or get it as far as the proc.
 */
export function addressCodeOrBlank(value: string): string {
  return value === ADD_ADDRESS ? '' : value;
}

/**
 * The list a picker offers, with the value it already holds kept in it. The edit dialog opens on the
 * job's current values before (or without) the live read answering, and a select whose value is not
 * among its options renders blank - which would read as "the job has none".
 */
export function withCurrent<T>(options: T[], current: T | null, same: (a: T, b: T) => boolean): T[] {
  if (!current || options.some((o) => same(o, current))) return options;
  return [current, ...options];
}
