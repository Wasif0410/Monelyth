/** Route paths, so links and redirects never hard-code a string twice. */
export const paths = {
  home: "/",
  welcome: "/welcome",
  transactions: "/transactions",
  import: "/import",
  accounts: "/accounts",
  settings: "/settings",
} as const;
