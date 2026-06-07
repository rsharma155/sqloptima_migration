/**
 * Externalized UI strings — i18n scaffold (§13.10).
 * Replace with next-intl or similar when full localization is required.
 */
export type Locale = "en";

export const messages: Record<Locale, Record<string, string>> = {
  en: {
    "nav.migrations": "Migrations",
    "nav.connections": "Connections",
    "nav.projects": "Projects",
    "nav.reports": "Reports",
    "migration.status.running": "Running",
    "migration.status.completed": "Completed",
    "migration.status.failed": "Failed",
    "error.generic": "Something went wrong",
    "error.retry": "Please try again or contact your administrator.",
  },
};

export function t(key: string, locale: Locale = "en"): string {
  return messages[locale][key] ?? key;
}
