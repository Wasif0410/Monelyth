/** Route paths, so links and redirects never hard-code a string twice. */
export const paths = {
  home: "/",
  welcome: "/welcome",
  transactions: "/transactions",
  review: "/review",
  import: "/import",
  accounts: "/accounts",
  rules: "/rules",
  settings: "/settings",
} as const;
