import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  Box,
  Button,
  Collapse,
  IconButton,
  Link,
  Modal,
  Paper,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import { styled, useColorScheme } from '@mui/material/styles';
import { useMutation } from '@apollo/client/react';
import { AnimatePresence, animate, motion, useMotionValue, type PanInfo } from 'motion/react';
import { ChevronDown, CircleCheck, MessageSquareWarning, X } from 'lucide-react';
import { useIdentity } from '../hooks/useIdentity';
import { springs } from '../motion';
import { SUBMIT_ISSUE_REPORT } from '../graphql/issueReport';
import { userMessage } from '../graphql/userMessage';
import { collectReportContext, type ReportContextInput } from './reportContext';
import {
  BUBBLE_SIZE,
  DEFAULT_SPOT,
  TOP_LIMIT,
  loadSpot,
  pointToSpot,
  saveSpot,
  spotToPoint,
  type BubbleSpot,
} from './bubblePosition';

type Kind = 'PROBLEM' | 'CHANGE';

interface Draft {
  kind: Kind;
  description: string;
}

const EMPTY_DRAFT: Draft = { kind: 'PROBLEM', description: '' };

interface SubmitResult {
  submitIssueReport: { issueNumber: number; issueUrl: string; emailed: boolean };
}

/** How far ahead of the release point a flick is read, in seconds of its velocity. */
const FLICK_LOOKAHEAD = 0.15;

// Positioned at the viewport's top-left corner and moved by its x/y motion values, so drag, snap and
// placement are all one transform. Above the page and the app bar (drawer + 1), below MUI's modals and
// the toasts, so a dialog opened from a page still covers it.
const BubbleButton = styled(motion.button)(({ theme }) => ({
  position: 'fixed',
  top: 0,
  left: 0,
  zIndex: theme.zIndex.drawer + 50,
  width: BUBBLE_SIZE,
  height: BUBBLE_SIZE,
  borderRadius: '50%',
  border: 'none',
  padding: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  cursor: 'grab',
  // The browser must not scroll the page under a finger that is dragging the bubble.
  touchAction: 'none',
  color: theme.vars?.palette.primary.contrastText ?? theme.palette.primary.contrastText,
  backgroundColor: theme.vars?.palette.primary.main ?? theme.palette.primary.main,
  boxShadow: '0 6px 18px rgba(29, 27, 23, 0.28)',
  '&:active': { cursor: 'grabbing' },
  '&:focus-visible': {
    outline: `2px solid ${theme.vars?.palette.primary.main ?? theme.palette.primary.main}`,
    outlineOffset: 3,
  },
}));

/**
 * The report bubble (#1677): a round button floating over every signed-in screen, for everybody, in
 * demo mode or out of it. Drag it anywhere and it snaps to the nearer edge, where it stays for that
 * person; tap it and it opens into the report dialog, which files the report as a GitHub issue and
 * emails the product owner.
 *
 * Mounted once, in AppLayout. Above the page and the app bar, below dialogs and toasts.
 */
export default function ReportBubble() {
  const { userId } = useIdentity();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  // Read from storage by the layout effect below, once per person, not on every render.
  const spot = useRef<BubbleSpot>(DEFAULT_SPOT);
  // The report being written outlives the dialog: a stray click outside or an Escape closes it, and
  // reopening finds the text still there. Cleared once the report is filed.
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [viewport, setViewport] = useState(() => ({ width: window.innerWidth, height: window.innerHeight }));
  // A drag ends in a click on the same element; this is how that click is told apart from a tap.
  const dragged = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [hinting, setHinting] = useState(false);
  const [open, setOpen] = useState(false);
  // The modal stays mounted until the panel's exit animation has finished.
  const [modalMounted, setModalMounted] = useState(false);
  const [origin, setOrigin] = useState({ x: 0, y: 0 });

  const place = useCallback(
    (animated: boolean) => {
      const point = spotToPoint(spot.current, window.innerWidth, window.innerHeight);
      if (animated) {
        animate(x, point.x, springs.base);
        animate(y, point.y, springs.base);
      } else {
        x.set(point.x);
        y.set(point.y);
      }
    },
    [x, y],
  );

  // The person's own spot, once Clerk has said who they are.
  useLayoutEffect(() => {
    spot.current = loadSpot(userId);
    place(false);
  }, [userId, place]);

  useEffect(() => {
    const onResize = () => {
      setViewport({ width: window.innerWidth, height: window.innerHeight });
      place(false);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [place]);

  const onDragEnd = (_event: PointerEvent | MouseEvent | TouchEvent, info: PanInfo) => {
    const next = pointToSpot(
      x.get() + info.velocity.x * FLICK_LOOKAHEAD,
      y.get() + info.velocity.y * FLICK_LOOKAHEAD,
      window.innerWidth,
      window.innerHeight,
    );
    spot.current = next;
    saveSpot(userId, next);
    place(true);
  };

  const onClick = () => {
    // The click a mouse drag ends in. Cleared as it is swallowed, so a keyboard press next - which sends
    // no pointerdown - is a tap again.
    if (dragged.current) {
      dragged.current = false;
      return;
    }
    // The panel grows out of the bubble: its offset from the middle of the screen, where the panel sits.
    setOrigin({
      x: x.get() + BUBBLE_SIZE / 2 - window.innerWidth / 2,
      y: y.get() + BUBBLE_SIZE / 2 - window.innerHeight / 2,
    });
    setModalMounted(true);
    setOpen(true);
  };

  return (
    <>
      {/* Controlled: a tooltip is placed once when it opens, so it would stay behind while the bubble
          is dragged away from it. */}
      <Tooltip
        title="Report an issue"
        placement="left"
        disableInteractive
        open={hinting && !dragging && !open}
        onOpen={() => setHinting(true)}
        onClose={() => setHinting(false)}
      >
        <BubbleButton
          type="button"
          aria-label="Report an issue"
          drag
          dragMomentum={false}
          dragElastic={0.15}
          dragConstraints={{
            left: 0,
            top: TOP_LIMIT,
            right: Math.max(0, viewport.width - BUBBLE_SIZE),
            bottom: Math.max(TOP_LIMIT, viewport.height - BUBBLE_SIZE),
          }}
          // Every press starts as a tap. Touch browsers send no click after a drag at all, so the flag
          // is cleared here rather than by the click, or the next real tap would be swallowed.
          onPointerDown={() => {
            dragged.current = false;
          }}
          onDragStart={() => {
            dragged.current = true;
            setDragging(true);
          }}
          onDragEnd={(event, info) => {
            setDragging(false);
            onDragEnd(event, info);
          }}
          onClick={onClick}
          whileTap={{ scale: 0.94 }}
          whileDrag={{ scale: 1.08 }}
          animate={open ? { opacity: 0, scale: 0.6 } : { opacity: 1, scale: 1 }}
          transition={springs.fast}
          style={{ x, y }}
          tabIndex={open ? -1 : 0}
        >
          <MessageSquareWarning size={22} strokeWidth={1.75} aria-hidden />
        </BubbleButton>
      </Tooltip>

      <Modal open={modalMounted} hideBackdrop onClose={() => setOpen(false)} aria-labelledby="report-dialog-title">
        <Box
          tabIndex={-1}
          sx={{
            position: 'fixed',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            p: 2,
            outline: 'none',
          }}
        >
          <AnimatePresence onExitComplete={() => setModalMounted(false)}>
            {open && (
              <motion.div
                key="backdrop"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                onClick={() => setOpen(false)}
                style={{ position: 'absolute', inset: 0, background: 'rgba(29, 27, 23, 0.42)' }}
              />
            )}
            {open && (
              <motion.div
                key="panel"
                role="dialog"
                aria-modal="true"
                aria-labelledby="report-dialog-title"
                initial={{ opacity: 0, scale: 0.2, x: origin.x, y: origin.y }}
                animate={{ opacity: 1, scale: 1, x: 0, y: 0 }}
                exit={{ opacity: 0, scale: 0.2, x: origin.x, y: origin.y }}
                transition={springs.base}
                style={{ position: 'relative', width: '100%', maxWidth: 560, minWidth: 0 }}
              >
                <ReportPanel
                  draft={draft}
                  onDraftChange={setDraft}
                  onFiled={() => setDraft(EMPTY_DRAFT)}
                  onClose={() => setOpen(false)}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </Box>
      </Modal>
    </>
  );
}

interface ReportPanelProps {
  draft: Draft;
  onDraftChange: (draft: Draft) => void;
  onFiled: () => void;
  onClose: () => void;
}

function ReportPanel({ draft, onDraftChange, onFiled, onClose }: ReportPanelProps) {
  const { mode, systemMode } = useColorScheme();
  const { displayName, company, demoMode } = useIdentity();
  const { kind, description } = draft;
  const setKind = (next: Kind) => onDraftChange({ ...draft, kind: next });
  const setDescription = (next: string) => onDraftChange({ ...draft, description: next });
  const [showSent, setShowSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filed, setFiled] = useState<SubmitResult['submitIssueReport'] | null>(null);
  // Read once, when the panel opens: that is the page the report is about.
  const [context] = useState<ReportContextInput>(() =>
    collectReportContext((mode === 'system' ? systemMode : mode) ?? 'light'),
  );
  const [submit, { loading }] = useMutation<SubmitResult>(SUBMIT_ISSUE_REPORT);

  const send = async () => {
    setError(null);
    try {
      const res = await submit({ variables: { input: { kind, description: description.trim(), context } } });
      if (res.data) {
        setFiled(res.data.submitIssueReport);
        onFiled();
      }
    } catch (err) {
      setError(userMessage(err));
    }
  };

  const sentRows: [string, string][] = [
    ['You', `${displayName}${company ? `, ${company}` : ''}${demoMode ? ' (demo mode)' : ''}`],
    ['Page', context.pageTitle || context.route],
    ['Address', context.url],
    ['Screen', `${context.viewport}, ${context.colorScheme}`],
    ['Browser', context.userAgent],
    ['Build', context.build],
    ['Recent errors', context.recentErrors.length ? `${context.recentErrors.length} in this tab` : 'none'],
  ];

  return (
    <Paper
      elevation={8}
      sx={{ p: { xs: 2, sm: 2.5 }, borderRadius: 3, maxHeight: 'calc(100vh - 32px)', overflowY: 'auto', minWidth: 0 }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <Typography id="report-dialog-title" variant="h6" sx={{ flexGrow: 1, minWidth: 0 }}>
          {filed ? 'Report sent' : 'Report an issue'}
        </Typography>
        <IconButton aria-label="Close" onClick={onClose} size="small">
          <X size={18} strokeWidth={1.75} />
        </IconButton>
      </Box>

      {filed ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <CircleCheck size={20} strokeWidth={1.75} color="var(--mui-palette-success-main)" aria-hidden />
            <Typography>
              Filed as{' '}
              <Link href={filed.issueUrl} target="_blank" rel="noreferrer">
                #{filed.issueNumber}
              </Link>
              . Thanks - it goes straight to the people who fix things.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button variant="contained" onClick={onClose}>
              Done
            </Button>
          </Box>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={kind}
            onChange={(_e, value: Kind | null) => value && setKind(value)}
            aria-label="What kind of report"
          >
            <ToggleButton value="PROBLEM">Something's wrong</ToggleButton>
            <ToggleButton value="CHANGE">Change request</ToggleButton>
          </ToggleButtonGroup>
          <TextField
            autoFocus
            multiline
            minRows={5}
            maxRows={14}
            label={kind === 'PROBLEM' ? 'What happened?' : 'What should change, and why?'}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            slotProps={{ htmlInput: { maxLength: 5000 } }}
            fullWidth
          />

          <Box>
            <Button
              size="small"
              color="inherit"
              onClick={() => setShowSent((v) => !v)}
              aria-expanded={showSent}
              endIcon={
                <ChevronDown
                  size={16}
                  strokeWidth={1.75}
                  style={{ transform: showSent ? 'rotate(180deg)' : undefined, transition: 'transform 150ms' }}
                />
              }
              sx={{ color: 'text.secondary', px: 0.5 }}
            >
              What gets sent with it
            </Button>
            <Collapse in={showSent}>
              <Box
                component="dl"
                sx={{
                  display: 'grid',
                  gridTemplateColumns: 'max-content minmax(0, 1fr)',
                  columnGap: 1.5,
                  rowGap: 0.25,
                  m: 0,
                  mt: 0.5,
                  fontSize: 13,
                }}
              >
                {sentRows.map(([label, value]) => (
                  <Box key={label} sx={{ display: 'contents' }}>
                    <Box component="dt" sx={{ color: 'text.secondary' }}>
                      {label}
                    </Box>
                    <Box
                      component="dd"
                      title={value}
                      sx={{ m: 0, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                      {value}
                    </Box>
                  </Box>
                ))}
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>
                It is filed as an issue on the UC Nexus GitHub repository, which anyone can read.
              </Typography>
            </Collapse>
          </Box>

          {error && (
            <Typography color="error" variant="body2" role="alert">
              {error}
            </Typography>
          )}

          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
            <Button onClick={onClose} color="inherit">
              Cancel
            </Button>
            <Button variant="contained" onClick={send} disabled={loading || !description.trim()}>
              {loading ? 'Sending…' : 'Send report'}
            </Button>
          </Box>
        </Box>
      )}
    </Paper>
  );
}
