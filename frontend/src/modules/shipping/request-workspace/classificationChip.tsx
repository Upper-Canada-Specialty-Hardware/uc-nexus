import { Chip } from '@mui/material';
import type { HardwareClassification } from '../../import/types';

/**
 * The SITE / SHOP tag a composed line carries, shared by the openings-first catalog and the extras
 * lane (#610) so both surfaces read a shop-classified product the same way. Null (never classified)
 * renders nothing rather than a third neutral chip - the absence is the answer.
 */
export function classificationChip(classification: HardwareClassification | null) {
  if (classification === 'SITE_HARDWARE')
    return <Chip label="SITE" size="small" color="success" variant="outlined" sx={{ height: 20 }} />;
  if (classification === 'SHOP_HARDWARE')
    return <Chip label="SHOP" size="small" color="info" variant="outlined" sx={{ height: 20 }} />;
  return null;
}

export const isShopClassified = (classification: HardwareClassification | null): boolean =>
  classification === 'SHOP_HARDWARE';

/**
 * The framing shown once whenever any SHOP-tagged line is on offer. Shop hardware is still stock -
 * it never went to the bench - so shipping it is a deliberate send to site for field fitting, not a
 * mistake the screen should guard against with a confirm.
 */
export const SHOP_FRAMING =
  'SHOP-tagged hardware is still in inventory - it never went to the shop. Shipping it sends it to site for field fitting.';

/** A subtle row tint for a shop-classified line, keyed off the info palette the SHOP chip uses. */
export const shopRowTintSx = {
  bgcolor: (t: { vars?: { palette: { info: { mainChannel: string } } } }) =>
    t.vars ? `rgba(${t.vars.palette.info.mainChannel} / 0.06)` : 'rgba(2, 136, 209, 0.06)',
} as const;
