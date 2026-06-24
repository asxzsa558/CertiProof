// VeriSure Design System - Professional Theme

export const theme = {
  // Brand Colors
  colors: {
    primary: {
      50: '#eef2ff',
      100: '#e0e7ff',
      200: '#c7d2fe',
      300: '#a5b4fc',
      400: '#818cf8',
      500: '#6366f1', // Main brand color - Indigo
      600: '#4f46e5',
      700: '#4338ca',
      800: '#3730a3',
      900: '#312e81',
    },
    secondary: {
      50: '#faf5ff',
      100: '#f3e8ff',
      200: '#e9d5ff',
      300: '#d8b4fe',
      400: '#c084fc',
      500: '#a855f7', // Purple accent
      600: '#9333ea',
      700: '#7e22ce',
      800: '#6b21a8',
      900: '#581c87',
    },
    success: {
      50: '#ecfdf5',
      100: '#d1fae5',
      500: '#10b981',
      600: '#059669',
    },
    warning: {
      50: '#fffbeb',
      100: '#fef3c7',
      500: '#f59e0b',
      600: '#d97706',
    },
    danger: {
      50: '#fef2f2',
      100: '#fee2e2',
      500: '#ef4444',
      600: '#dc2626',
    },
    // Neutral / Slate
    slate: {
      50: '#f8fafc',
      100: '#f1f5f9',
      200: '#e2e8f0',
      300: '#cbd5e1',
      400: '#94a3b8',
      500: '#64748b',
      600: '#475569',
      700: '#334155',
      800: '#1e293b',
      900: '#0f172a',
      950: '#020617',
    },
  },

  // Gradients
  gradients: {
    primary: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
    secondary: 'linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)',
    success: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
    warning: 'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
    dark: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
    light: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)',
    mesh: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  },

  // Shadows
  shadows: {
    sm: '0 1px 2px 0 rgb(0 0 0 / 0.05)',
    md: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
    lg: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
    xl: '0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)',
    '2xl': '0 25px 50px -12px rgb(0 0 0 / 0.25)',
    inner: 'inset 0 2px 4px 0 rgb(0 0 0 / 0.05)',
    glow: '0 0 20px rgba(99, 102, 241, 0.5)',
  },

  // Border Radius
  borderRadius: {
    none: '0',
    sm: '0.125rem',
    md: '0.375rem',
    lg: '0.5rem',
    xl: '0.75rem',
    '2xl': '1rem',
    '3xl': '1.5rem',
    full: '9999px',
  },

  // Typography
  fontFamily: {
    sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    mono: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
  },

  // Spacing
  spacing: {
    xs: '0.5rem',
    sm: '0.75rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem',
    '2xl': '3rem',
    '3xl': '4rem',
  },

  // Transitions
  transitions: {
    fast: '150ms cubic-bezier(0.4, 0, 0.2, 1)',
    normal: '300ms cubic-bezier(0.4, 0, 0.2, 1)',
    slow: '500ms cubic-bezier(0.4, 0, 0.2, 1)',
  },
}

// Ant Design Theme Config
export const antdTheme = {
  token: {
    // Colors
    colorPrimary: theme.colors.primary[500],
    colorSuccess: theme.colors.success[500],
    colorWarning: theme.colors.warning[500],
    colorError: theme.colors.danger[500],
    colorInfo: theme.colors.primary[500],
    
    // Typography
    fontFamily: theme.fontFamily.sans,
    fontSize: 14,
    
    // Border
    borderRadius: 8,
    borderRadiusLG: 12,
    
    // Shadows
    boxShadow: theme.shadows.md,
    boxShadowSecondary: theme.shadows.lg,
    
    // Motion
    motionDurationMid: '300ms',
    motionEaseInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
  },
  components: {
    Button: {
      borderRadius: 8,
      controlHeight: 40,
      controlHeightLG: 48,
      fontWeight: 500,
    },
    Card: {
      borderRadiusLG: 16,
    },
    Input: {
      controlHeight: 40,
      borderRadius: 8,
    },
    Menu: {
      itemBorderRadius: 8,
      itemMarginInline: 8,
    },
  },
}

export default theme
