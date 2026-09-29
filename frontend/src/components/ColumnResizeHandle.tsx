import { useRef } from 'react';
import { Box } from '@mui/material';
import { KEY_STEP_PX, type ResizeHandleBinding } from './fitColumns';

/**
 * The draggable right edge of a resizable column header (#856, shared with every table under #909).
 * Place it inside a header cell with `position: relative`. It is a focusable separator: Left and
 * Right arrows move the edge a step (Shift for four), so resizing never needs a mouse.
 */
export default function ColumnResizeHandle({ binding }: { binding: ResizeHandleBinding | null }) {
  // The pointer's last x while dragging; each move hands on only the distance since the last one.
  const lastX = useRef<number | null>(null);
  if (!binding) return null;
  const { label, valueNow, onResizeBy } = binding;

  const end = (e: React.PointerEvent<HTMLElement>) => {
    if (lastX.current === null) return;
    lastX.current = null;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* capture already gone */
    }
  };

  return (
    <Box
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${label} column`}
      aria-valuenow={valueNow}
      tabIndex={0}
      onPointerDown={(e) => {
        e.preventDefault();
        e.stopPropagation();
        lastX.current = e.clientX;
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch {
          /* no pointer capture (jsdom) - moves still arrive while over the handle */
        }
      }}
      onPointerMove={(e) => {
        if (lastX.current === null) return;
        const delta = e.clientX - lastX.current;
        if (delta === 0) return;
        lastX.current = e.clientX;
        onResizeBy(delta);
      }}
      onPointerUp={end}
      onPointerCancel={end}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        const step = KEY_STEP_PX * (e.shiftKey ? 4 : 1);
        onResizeBy(e.key === 'ArrowRight' ? step : -step);
      }}
      sx={{
        position: 'absolute',
        top: 0,
        bottom: 0,
        right: 0,
        width: 8,
        zIndex: 1,
        cursor: 'col-resize',
        touchAction: 'none',
        // A hairline at the column edge that shows on hover, drag and keyboard focus.
        '&::after': {
          content: '""',
          position: 'absolute',
          top: '20%',
          bottom: '20%',
          right: 1,
          width: 2,
          borderRadius: 1,
          bgcolor: 'transparent',
        },
        '&:hover::after, &:focus-visible::after, &:active::after': { bgcolor: 'primary.main' },
        '&:focus-visible': { outline: 'none' },
      }}
    />
  );
}
