/**
 * Module: layout.tsx
 * Purpose: Next.js frontend UI
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ConditionalNav } from "@/components/conditional-nav";
import { Toaster } from "sonner";
import { ConnectionProvider } from "@/lib/ConnectionContext";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { AuthInit } from "@/components/auth-init";
import { Providers } from "./providers";
import { ThemeProvider } from "@/components/theme-provider";
import { CommandPalette } from "@/components/command-palette";
import { GlobalAlertsProvider } from "@/components/alerts/global-alerts-provider";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "SQL Optima Migration — SQL Server to PostgreSQL",
  description:
    "SQL Optima Migration — Enterprise platform for migrating SQL Server databases to PostgreSQL",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} antialiased`}>
        {/* API endpoint bootstrap — does not touch theme (next-themes handles that) */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                if (!localStorage.getItem("api_endpoint")) {
                  const h = window.location.hostname;
                  localStorage.setItem("api_endpoint",
                    h === "localhost" ? "http://localhost:8508"
                    : window.location.protocol + "//" + h + ":8508");
                }
              } catch(e) {}
            `,
          }}
        />
        <AuthInit />
        <ThemeProvider>
          <Providers>
            <GlobalAlertsProvider>
            <div className="flex h-screen overflow-hidden">
              <ConditionalNav />
              <main className="flex-1 overflow-auto bg-background min-h-0">
                <ErrorBoundary>
                  <ConnectionProvider>
                    {children}
                  </ConnectionProvider>
                </ErrorBoundary>
              </main>
            </div>
            <CommandPalette />
            </GlobalAlertsProvider>
          </Providers>
        </ThemeProvider>
        <Toaster richColors expand position="top-right" duration={1000} />
      </body>
    </html>
  );
}
