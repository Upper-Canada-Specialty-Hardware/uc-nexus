import { createTheme } from '@mui/material/styles';
import type {} from '@mui/x-data-grid/themeAugmentation';

// Enable CSS variables type support
declare module '@mui/material/styles' {
  interface CssThemeVariables {
    enabled: true;
  }
}

// Shared brand tokens
const SECONDARY_LIGHT = '#ffca28';
const SECONDARY_DARK = '#ffd54f';

const theme = createTheme({
  cssVariables: {
    colorSchemeSelector: 'data',
  },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: '#212121', contrastText: '#ffffff' },
        secondary: { main: SECONDARY_LIGHT, contrastText: '#212121' },
        background: { default: '#f5f5f5', paper: '#ffffff' },
      },
    },
    dark: {
      palette: {
        primary: { main: '#e0e0e0', contrastText: '#121212' },
        secondary: { main: SECONDARY_DARK, contrastText: '#1a1a1a' },
        background: { default: '#121212', paper: '#1e1e1e' },
      },
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
    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          borderRadius: 8,
          padding: '6px 20px',
        },
        contained: ({ theme }) => ({
          backgroundColor: SECONDARY_LIGHT,
          color: '#212121',
          '&:hover': {
            backgroundColor: '#ffb300',
          },
          ...theme.applyStyles('dark', {
            backgroundColor: SECONDARY_DARK,
            color: '#1a1a1a',
            '&:hover': {
              backgroundColor: '#ffca28',
            },
          }),
        }),
        containedPrimary: ({ theme }) => ({
          backgroundColor: '#212121',
          color: '#ffffff',
          '&:hover': {
            backgroundColor: '#424242',
          },
          ...theme.applyStyles('dark', {
            backgroundColor: '#e0e0e0',
            color: '#121212',
            '&:hover': {
              backgroundColor: '#bdbdbd',
            },
          }),
        }),
        outlined: ({ theme }) => ({
          borderColor: '#212121',
          color: '#212121',
          ...theme.applyStyles('dark', {
            borderColor: '#e0e0e0',
            color: '#e0e0e0',
          }),
        }),
      },
    },

    MuiAppBar: {
      defaultProps: {
        elevation: 0,
      },
      styleOverrides: {
        colorPrimary: ({ theme }) => ({
          backgroundColor: '#212121',
          color: '#ffffff',
          ...theme.applyStyles('dark', {
            backgroundColor: '#1e1e1e',
          }),
        }),
      },
    },

    MuiCard: {
      defaultProps: {
        elevation: 0,
      },
      styleOverrides: {
        root: ({ theme }) => ({
          border: '1px solid',
          borderColor: 'rgba(0, 0, 0, 0.08)',
          transition: 'box-shadow 0.2s ease-in-out, border-color 0.2s ease-in-out',
          '&:hover': {
            borderColor: 'rgba(0, 0, 0, 0.16)',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)',
          },
          ...theme.applyStyles('dark', {
            borderColor: 'rgba(255, 255, 255, 0.12)',
            '&:hover': {
              borderColor: 'rgba(255, 255, 255, 0.24)',
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
            },
          }),
        }),
      },
    },

    MuiDataGrid: {
      styleOverrides: {
        root: {
          border: 'none',
          borderRadius: 8,
        },
        columnHeaders: ({ theme }) => ({
          backgroundColor: '#eeeeee',
          fontWeight: 600,
          ...theme.applyStyles('dark', {
            backgroundColor: '#2a2a2a',
          }),
        }),
        columnHeaderTitle: {
          fontWeight: 600,
        },
      },
    },

    MuiStepIcon: {
      styleOverrides: {
        root: ({ theme }) => ({
          '&.Mui-active': {
            color: SECONDARY_LIGHT,
          },
          '&.Mui-completed': {
            color: SECONDARY_LIGHT,
          },
          ...theme.applyStyles('dark', {
            '&.Mui-active': {
              color: SECONDARY_DARK,
            },
            '&.Mui-completed': {
              color: SECONDARY_DARK,
            },
          }),
        }),
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
        colorPrimary: ({ theme }) => ({
          backgroundColor: '#212121',
          color: '#ffffff',
          ...theme.applyStyles('dark', {
            backgroundColor: '#e0e0e0',
            color: '#121212',
          }),
        }),
        colorSecondary: ({ theme }) => ({
          backgroundColor: SECONDARY_LIGHT,
          color: '#212121',
          ...theme.applyStyles('dark', {
            backgroundColor: SECONDARY_DARK,
            color: '#1a1a1a',
          }),
        }),
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
        outlined: ({ theme }) => ({
          borderColor: 'rgba(0, 0, 0, 0.12)',
          ...theme.applyStyles('dark', {
            borderColor: 'rgba(255, 255, 255, 0.12)',
          }),
        }),
      },
    },

    MuiFab: {
      styleOverrides: {
        primary: ({ theme }) => ({
          backgroundColor: SECONDARY_LIGHT,
          color: '#212121',
          '&:hover': {
            backgroundColor: '#ffb300',
          },
          ...theme.applyStyles('dark', {
            backgroundColor: SECONDARY_DARK,
            color: '#1a1a1a',
            '&:hover': {
              backgroundColor: '#ffca28',
            },
          }),
        }),
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
        root: ({ theme }) => ({
          textTransform: 'none' as const,
          '&.Mui-selected': {
            backgroundColor: SECONDARY_LIGHT,
            color: '#212121',
            '&:hover': {
              backgroundColor: '#ffb300',
            },
          },
          ...theme.applyStyles('dark', {
            '&.Mui-selected': {
              backgroundColor: SECONDARY_DARK,
              color: '#1a1a1a',
              '&:hover': {
                backgroundColor: '#ffca28',
              },
            },
          }),
        }),
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
});

export default theme;
