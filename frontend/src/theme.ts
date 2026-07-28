import { createTheme, alpha } from '@mui/material/styles';
import type {} from '@mui/x-data-grid/themeAugmentation';

// Enable CSS variables type support
declare module '@mui/material/styles' {
  interface CssThemeVariables {
    enabled: true;
  }
}

/**
 * UC Nexus visual language — "shop instrument, not admin template".
 *
 * Warm steel & kraft neutrals instead of the stock Material grey ramp, one Shop
 * Amber accent spent as an EDGE (selection rails, active tabs, current step)
 * plus the primary action fill, square-cornered status tags, and a ledger table
 * treatment (2px ink rule under headers instead of a tinted fill).
 *
 * Rules that keep this coherent (DESIGN.md is the binding doc):
 * - Component overrides never hardcode a palette hex for text on arbitrary
 *   surfaces; they use theme.vars so `color="inherit"` keeps working on the
 *   ink app bar. (The old theme broke the DevAction button this way.)
 * - Identifiers (PO numbers, product codes, opening/leaf refs, bins) render in
 *   the mono face — use `monoSx` / `FONT_MONO`.
 * - Numbers that line up in columns get tabular numerals (tables have it
 *   globally; use `tabularSx` elsewhere).
 */

// ---- Warm steel & kraft tokens -------------------------------------------
const INK = '#1d1b17'; // warm near-black (light-scheme structural color)
const INK_HOVER = '#3a362f';
const PAPER = '#fdfcfa'; // warm white
const CANVAS = '#f2f0ea'; // bone
const TEXT_SECONDARY = '#5c564b';

const INK_DARK = '#e9e5dc'; // light warm grey (dark-scheme "ink")
const INK_DARK_HOVER = '#c9c4b8';
const PAPER_DARK = '#201e1b'; // warm charcoal surface
const CANVAS_DARK = '#161513';
const TEXT_SECONDARY_DARK = '#a49e91';

const AMBER = '#ffca28';
const AMBER_HOVER = '#ffb300';
const AMBER_DARK = '#ffd54f';
const AMBER_DARK_HOVER = '#ffca28';

// The app bar is ink in both schemes; its text is fixed warm-paper.
const BAR_BG = INK;
const BAR_BG_DARK = '#1b1917';
const BAR_TEXT = '#f6f3ec';

export const FONT_UI =
  '"Source Sans 3 Variable", "Source Sans 3", "Helvetica Neue", Arial, sans-serif';
export const FONT_MONO =
  '"IBM Plex Mono", "Cascadia Code", Consolas, ui-monospace, monospace';

/** Identifier styling: PO numbers, product codes, opening refs, bins. */
export const monoSx = {
  fontFamily: FONT_MONO,
  fontSize: '0.8125rem',
  letterSpacing: 0,
} as const;

/** Columns of figures line up. */
export const tabularSx = { fontVariantNumeric: 'tabular-nums' } as const;

/** Uppercase micro-label: table headers, stat captions, eyebrow labels. */
export const microLabelSx = {
  fontSize: '0.6875rem',
  fontWeight: 700,
  letterSpacing: '0.08em',
  textTransform: 'uppercase' as const,
  color: 'text.secondary',
};

const theme = createTheme({
  cssVariables: {
    colorSchemeSelector: 'data',
  },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: INK, contrastText: PAPER },
        secondary: { main: AMBER, contrastText: INK },
        background: { default: CANVAS, paper: PAPER },
        text: { primary: INK, secondary: TEXT_SECONDARY },
        divider: 'rgba(29, 27, 23, 0.14)',
        action: {
          hover: 'rgba(29, 27, 23, 0.05)',
          selected: 'rgba(29, 27, 23, 0.08)',
        },
      },
    },
    dark: {
      palette: {
        primary: { main: INK_DARK, contrastText: CANVAS_DARK },
        secondary: { main: AMBER_DARK, contrastText: '#1d1b17' },
        background: { default: CANVAS_DARK, paper: PAPER_DARK },
        text: { primary: INK_DARK, secondary: TEXT_SECONDARY_DARK },
        divider: 'rgba(233, 229, 220, 0.16)',
        action: {
          hover: 'rgba(233, 229, 220, 0.06)',
          selected: 'rgba(233, 229, 220, 0.10)',
        },
      },
    },
  },

  typography: {
    fontFamily: FONT_UI,
    h1: { fontWeight: 700, letterSpacing: '-0.01em' },
    h2: { fontWeight: 700, letterSpacing: '-0.01em' },
    h3: { fontWeight: 700, letterSpacing: '-0.01em' },
    h4: { fontWeight: 700, letterSpacing: '-0.01em' },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    subtitle1: { fontWeight: 600 },
    subtitle2: { fontWeight: 600 },
    button: { fontWeight: 600, textTransform: 'none' },
    caption: { lineHeight: 1.5 },
  },

  shape: {
    // Surfaces keep softness; controls sharpen via per-component overrides.
    borderRadius: 6,
  },

  components: {
    MuiCssBaseline: {
      styleOverrides: (themeParam) => ({
        '::selection': {
          backgroundColor: AMBER,
          color: INK,
        },
        '*': {
          scrollbarWidth: 'thin',
          scrollbarColor: `${alpha(INK, 0.28)} transparent`,
        },
        '[data-mui-color-scheme="dark"] *': {
          scrollbarColor: `${alpha(INK_DARK, 0.28)} transparent`,
        },
        // Non-MUI focusables still get a visible ring.
        ':focus-visible': {
          outline: `2px solid ${themeParam.vars.palette.secondary.main}`,
          outlineOffset: 2,
        },
      }),
    },

    MuiButton: {
      defaultProps: {
        disableElevation: true,
        color: 'secondary' as const,
      },
      styleOverrides: {
        root: {
          borderRadius: 3,
          padding: '6px 20px',
          '&.Mui-focusVisible': {
            outlineOffset: 2,
          },
        },
        sizeSmall: {
          padding: '3px 12px',
        },
        containedSecondary: ({ theme }) => ({
          backgroundColor: AMBER,
          color: INK,
          '&:hover': { backgroundColor: AMBER_HOVER },
          ...theme.applyStyles('dark', {
            backgroundColor: AMBER_DARK,
            color: '#1d1b17',
            '&:hover': { backgroundColor: AMBER_DARK_HOVER },
          }),
        }),
        containedPrimary: ({ theme }) => ({
          backgroundColor: INK,
          color: PAPER,
          '&:hover': { backgroundColor: INK_HOVER },
          ...theme.applyStyles('dark', {
            backgroundColor: INK_DARK,
            color: CANVAS_DARK,
            '&:hover': { backgroundColor: INK_DARK_HOVER },
          }),
        }),
        // The DEFAULT button color is secondary; make its outlined/text
        // variants read as quiet ink actions. Scoped to the secondary color
        // classes only, so color="inherit" (app bar) and color="error"
        // (destructive) keep their own colors.
        outlinedSecondary: ({ theme }) => ({
          color: theme.vars.palette.text.primary,
          borderColor: alpha(INK, 0.42),
          '&:hover': {
            borderColor: theme.vars.palette.text.primary,
            backgroundColor: theme.vars.palette.action.hover,
          },
          ...theme.applyStyles('dark', {
            borderColor: alpha(INK_DARK, 0.42),
          }),
        }),
        textSecondary: ({ theme }) => ({
          color: theme.vars.palette.text.primary,
          '&:hover': { backgroundColor: theme.vars.palette.action.hover },
        }),
      },
    },

    MuiIconButton: {
      styleOverrides: {
        root: { borderRadius: 6 },
      },
    },

    MuiAppBar: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        colorPrimary: ({ theme }) => ({
          backgroundColor: BAR_BG,
          color: BAR_TEXT,
          borderBottom: `1px solid ${alpha('#ffffff', 0.08)}`,
          ...theme.applyStyles('dark', {
            backgroundColor: BAR_BG_DARK,
          }),
        }),
      },
    },

    MuiCard: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: ({ theme }) => ({
          border: '1px solid',
          borderColor: theme.vars.palette.divider,
          backgroundImage: 'none',
          transition: 'box-shadow 0.2s ease, border-color 0.2s ease, transform 0.2s ease',
          '&:hover': {
            borderColor: alpha(INK, 0.28),
            boxShadow: '0 4px 14px rgba(29, 27, 23, 0.09)',
          },
          ...theme.applyStyles('dark', {
            '&:hover': {
              borderColor: alpha(INK_DARK, 0.32),
              boxShadow: '0 4px 14px rgba(0, 0, 0, 0.45)',
            },
          }),
        }),
      },
    },

    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: { backgroundImage: 'none' },
        outlined: ({ theme }) => ({
          borderColor: theme.vars.palette.divider,
        }),
      },
    },

    MuiDialog: {
      styleOverrides: {
        paper: ({ theme }) => ({
          borderRadius: 10,
          border: '1px solid',
          borderColor: theme.vars.palette.divider,
        }),
      },
    },

    MuiDialogTitle: {
      styleOverrides: {
        root: { fontWeight: 700 },
      },
    },

    // ---- The ledger: tables carry structure with rules, not fills ---------
    MuiTableCell: {
      styleOverrides: {
        root: {
          fontVariantNumeric: 'tabular-nums',
          padding: '10px 14px',
        },
        head: ({ theme }) => ({
          fontSize: '0.6875rem',
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: theme.vars.palette.text.secondary,
          backgroundColor: 'transparent',
          borderBottom: '2px solid',
          borderBottomColor: theme.vars.palette.text.primary,
          lineHeight: 1.4,
        }),
      },
    },

    MuiTableRow: {
      styleOverrides: {
        root: ({ theme }) => ({
          '&.MuiTableRow-hover:hover': {
            backgroundColor: theme.vars.palette.action.hover,
          },
          '&.Mui-selected': {
            backgroundColor: theme.vars.palette.action.selected,
            boxShadow: `inset 3px 0 0 ${theme.vars.palette.secondary.main}`,
          },
        }),
      },
    },

    MuiDataGrid: {
      styleOverrides: {
        root: ({ theme }) => ({
          border: 'none',
          borderRadius: 6,
          fontVariantNumeric: 'tabular-nums',
          '--DataGrid-rowBorderColor': theme.vars.palette.divider,
        }),
        columnHeaders: ({ theme }) => ({
          backgroundColor: 'transparent',
          borderBottom: '2px solid',
          borderBottomColor: theme.vars.palette.text.primary,
        }),
        columnHeader: {
          backgroundColor: 'transparent',
        },
        columnHeaderTitle: ({ theme }) => ({
          fontSize: '0.6875rem',
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: theme.vars.palette.text.secondary,
        }),
        row: ({ theme }) => ({
          '&:hover': { backgroundColor: theme.vars.palette.action.hover },
          '&.Mui-selected': {
            backgroundColor: theme.vars.palette.action.selected,
            boxShadow: `inset 3px 0 0 ${theme.vars.palette.secondary.main}`,
            '&:hover': { backgroundColor: theme.vars.palette.action.selected },
          },
        }),
      },
    },

    // ---- Status tags: square, stenciled, tinted-outlined ------------------
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 3,
          fontWeight: 600,
        },
        sizeSmall: {
          fontSize: '0.6875rem',
          letterSpacing: '0.05em',
          textTransform: 'uppercase',
        },
        colorPrimary: ({ theme }) => ({
          backgroundColor: INK,
          color: PAPER,
          ...theme.applyStyles('dark', {
            backgroundColor: INK_DARK,
            color: CANVAS_DARK,
          }),
        }),
        colorSecondary: ({ theme }) => ({
          backgroundColor: AMBER,
          color: INK,
          ...theme.applyStyles('dark', {
            backgroundColor: AMBER_DARK,
            color: '#1d1b17',
          }),
        }),
        colorSuccess: ({ theme }) => ({
          backgroundColor: alpha(theme.palette.success.main, 0.12),
          color: theme.vars.palette.success.dark,
          border: `1px solid ${alpha(theme.palette.success.main, 0.55)}`,
          ...theme.applyStyles('dark', {
            color: theme.vars.palette.success.light,
          }),
        }),
        colorWarning: ({ theme }) => ({
          backgroundColor: alpha(theme.palette.warning.main, 0.12),
          color: theme.vars.palette.warning.dark,
          border: `1px solid ${alpha(theme.palette.warning.main, 0.55)}`,
          ...theme.applyStyles('dark', {
            color: theme.vars.palette.warning.light,
          }),
        }),
        colorError: ({ theme }) => ({
          backgroundColor: alpha(theme.palette.error.main, 0.12),
          color: theme.vars.palette.error.dark,
          border: `1px solid ${alpha(theme.palette.error.main, 0.55)}`,
          ...theme.applyStyles('dark', {
            color: theme.vars.palette.error.light,
          }),
        }),
        colorInfo: ({ theme }) => ({
          backgroundColor: alpha(theme.palette.info.main, 0.12),
          color: theme.vars.palette.info.dark,
          border: `1px solid ${alpha(theme.palette.info.main, 0.55)}`,
          ...theme.applyStyles('dark', {
            color: theme.vars.palette.info.light,
          }),
        }),
      },
    },

    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 4 },
        standardSuccess: ({ theme }) => ({
          borderLeft: `3px solid ${theme.vars.palette.success.main}`,
        }),
        standardWarning: ({ theme }) => ({
          borderLeft: `3px solid ${theme.vars.palette.warning.main}`,
        }),
        standardError: ({ theme }) => ({
          borderLeft: `3px solid ${theme.vars.palette.error.main}`,
        }),
        standardInfo: ({ theme }) => ({
          borderLeft: `3px solid ${theme.vars.palette.info.main}`,
        }),
      },
    },

    MuiOutlinedInput: {
      styleOverrides: {
        root: { borderRadius: 4 },
      },
    },

    MuiTabs: {
      styleOverrides: {
        indicator: ({ theme }) => ({
          height: 3,
          backgroundColor: theme.vars.palette.secondary.main,
        }),
      },
    },

    MuiTab: {
      styleOverrides: {
        root: ({ theme }) => ({
          textTransform: 'none',
          fontWeight: 600,
          '&.Mui-selected': {
            color: theme.vars.palette.text.primary,
          },
        }),
      },
    },

    MuiToggleButton: {
      styleOverrides: {
        root: ({ theme }) => ({
          textTransform: 'none' as const,
          borderRadius: 3,
          '&.Mui-selected': {
            backgroundColor: AMBER,
            color: INK,
            '&:hover': { backgroundColor: AMBER_HOVER },
          },
          ...theme.applyStyles('dark', {
            '&.Mui-selected': {
              backgroundColor: AMBER_DARK,
              color: '#1d1b17',
              '&:hover': { backgroundColor: AMBER_DARK_HOVER },
            },
          }),
        }),
      },
    },

    MuiListItemButton: {
      styleOverrides: {
        root: ({ theme }) => ({
          borderRadius: 4,
          '&.Mui-selected': {
            backgroundColor: theme.vars.palette.action.selected,
            boxShadow: `inset 3px 0 0 ${theme.vars.palette.secondary.main}`,
            '&:hover': {
              backgroundColor: theme.vars.palette.action.selected,
            },
          },
        }),
      },
    },

    MuiMenu: {
      styleOverrides: {
        paper: ({ theme }) => ({
          borderRadius: 6,
          border: '1px solid',
          borderColor: theme.vars.palette.divider,
        }),
      },
    },

    MuiStepIcon: {
      styleOverrides: {
        root: ({ theme }) => ({
          '&.Mui-active': {
            color: AMBER,
            '& .MuiStepIcon-text': { fill: INK },
          },
          '&.Mui-completed': {
            color: theme.vars.palette.text.primary,
          },
          ...theme.applyStyles('dark', {
            '&.Mui-active': {
              color: AMBER_DARK,
              '& .MuiStepIcon-text': { fill: '#1d1b17' },
            },
          }),
        }),
      },
    },

    MuiStepLabel: {
      styleOverrides: {
        label: {
          '&.Mui-active': { fontWeight: 600 },
        },
      },
    },

    MuiFab: {
      styleOverrides: {
        primary: ({ theme }) => ({
          backgroundColor: AMBER,
          color: INK,
          '&:hover': { backgroundColor: AMBER_HOVER },
          ...theme.applyStyles('dark', {
            backgroundColor: AMBER_DARK,
            color: '#1d1b17',
            '&:hover': { backgroundColor: AMBER_DARK_HOVER },
          }),
        }),
      },
    },

    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: 2, height: 6 },
        bar: { borderRadius: 2 },
      },
    },

    MuiTooltip: {
      styleOverrides: {
        tooltip: ({ theme }) => ({
          backgroundColor: INK,
          fontSize: '0.75rem',
          borderRadius: 4,
          ...theme.applyStyles('dark', {
            backgroundColor: INK_DARK,
            color: CANVAS_DARK,
          }),
        }),
      },
    },

    MuiBreadcrumbs: {
      styleOverrides: {
        root: { fontSize: '0.875rem' },
      },
    },

    MuiSkeleton: {
      styleOverrides: {
        root: { borderRadius: 3 },
      },
    },
  },
});

export default theme;
