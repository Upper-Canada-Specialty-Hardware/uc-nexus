import { createTheme, type ThemeOptions } from '@mui/material/styles';
import type {} from '@mui/x-data-grid/themeAugmentation';

// UC Covet brand palette
const PRIMARY = '#212121';    // dark charcoal -- structural
const SECONDARY = '#ffca28';  // amber/gold -- CTAs, accents
const BG_DEFAULT = '#f5f5f5'; // off-white page background
const BG_PAPER = '#ffffff';   // white cards/dialogs

// Contrast text
const ON_PRIMARY = '#ffffff';
const ON_SECONDARY = '#212121';

const themeOptions: ThemeOptions = {
  palette: {
    primary: {
      main: PRIMARY,
      contrastText: ON_PRIMARY,
    },
    secondary: {
      main: SECONDARY,
      contrastText: ON_SECONDARY,
    },
    background: {
      default: BG_DEFAULT,
      paper: BG_PAPER,
    },
  },

  typography: {
    fontFamily: '"Source Sans 3 Variable", "Source Sans 3", "Helvetica Neue", Arial, sans-serif',
    h1: { fontWeight: 700 },
    h2: { fontWeight: 700 },
    h3: { fontWeight: 600 },
    h4: { fontWeight: 600 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    subtitle1: { fontWeight: 500 },
    subtitle2: { fontWeight: 500 },
    button: { fontWeight: 600, textTransform: 'none' },
  },

  shape: {
    borderRadius: 8,
  },

  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: BG_DEFAULT,
        },
      },
    },

    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          borderRadius: 8,
          padding: '6px 20px',
        },
        contained: {
          backgroundColor: SECONDARY,
          color: ON_SECONDARY,
          '&:hover': {
            backgroundColor: '#ffb300',
          },
        },
        containedPrimary: {
          backgroundColor: PRIMARY,
          color: ON_PRIMARY,
          '&:hover': {
            backgroundColor: '#424242',
          },
        },
        outlined: {
          borderColor: PRIMARY,
          color: PRIMARY,
        },
      },
    },

    MuiAppBar: {
      defaultProps: {
        elevation: 0,
      },
      styleOverrides: {
        colorPrimary: {
          backgroundColor: PRIMARY,
          color: ON_PRIMARY,
        },
      },
    },

    MuiCard: {
      defaultProps: {
        elevation: 0,
      },
      styleOverrides: {
        root: {
          border: '1px solid',
          borderColor: 'rgba(0, 0, 0, 0.08)',
          transition: 'box-shadow 0.2s ease-in-out, border-color 0.2s ease-in-out',
          '&:hover': {
            borderColor: 'rgba(0, 0, 0, 0.16)',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)',
          },
        },
      },
    },

    MuiDataGrid: {
      styleOverrides: {
        root: {
          border: 'none',
          borderRadius: 8,
        },
        columnHeaders: {
          backgroundColor: '#eeeeee',
          fontWeight: 600,
        },
        columnHeaderTitle: {
          fontWeight: 600,
        },
      },
    },

    MuiStepIcon: {
      styleOverrides: {
        root: {
          '&.Mui-active': {
            color: SECONDARY,
          },
          '&.Mui-completed': {
            color: SECONDARY,
          },
        },
      },
    },

    MuiStepLabel: {
      styleOverrides: {
        label: {
          '&.Mui-active': {
            fontWeight: 600,
          },
        },
      },
    },

    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 500,
        },
        colorPrimary: {
          backgroundColor: PRIMARY,
          color: ON_PRIMARY,
        },
        colorSecondary: {
          backgroundColor: SECONDARY,
          color: ON_SECONDARY,
        },
      },
    },

    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },

    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: 12,
        },
      },
    },

    MuiPaper: {
      defaultProps: {
        elevation: 0,
      },
      styleOverrides: {
        outlined: {
          borderColor: 'rgba(0, 0, 0, 0.12)',
        },
      },
    },

    MuiFab: {
      styleOverrides: {
        primary: {
          backgroundColor: SECONDARY,
          color: ON_SECONDARY,
          '&:hover': {
            backgroundColor: '#ffb300',
          },
        },
      },
    },

    MuiLinearProgress: {
      styleOverrides: {
        root: {
          borderRadius: 4,
          height: 6,
        },
        bar: {
          borderRadius: 4,
        },
      },
    },

    MuiToggleButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          '&.Mui-selected': {
            backgroundColor: SECONDARY,
            color: ON_SECONDARY,
            '&:hover': {
              backgroundColor: '#ffb300',
            },
          },
        },
      },
    },

    MuiBreadcrumbs: {
      styleOverrides: {
        root: {
          fontSize: '0.875rem',
        },
      },
    },
  },
};

const theme = createTheme(themeOptions);

export default theme;
