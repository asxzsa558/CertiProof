module.exports = {
  env: { browser: true, es2021: true, node: true },
  ignorePatterns: ['dist/**', 'node_modules/**'],
  plugins: ['react-hooks'],
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } },
  settings: { react: { version: 'detect' } },
  rules: {
    'no-undef': 'error',
    'no-unreachable': 'error',
    'no-constant-condition': 'error',
    'react-hooks/rules-of-hooks': 'error',
  },
}
