/**
 * Module: middleware.ts
 * Purpose: Next.js Edge middleware — enforces authentication before any page renders.
 *          Shared/bookmarked URLs are redirected to /login for unauthenticated users;
 *          the actual JWT is still verified by the FastAPI backend on every API call.
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/** Pages that are accessible without authentication. */
const PUBLIC_PATHS = new Set(["/setup", "/login"]);

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  // Always allow public auth pages through
  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  // Check for the auth cookie set by api.ts on successful login
  const token = request.cookies.get("auth_token")?.value;

  if (!token) {
    // No session — redirect to login, preserving the intended destination
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  // Token present — let the page render; the FastAPI backend will validate it on API calls
  return NextResponse.next();
}

export const config = {
  /*
   * Apply to all routes EXCEPT:
   *   - Next.js internals (_next/static, _next/image)
   *   - Favicon and static assets at root
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon\\.svg|favicon\\.ico|.*\\.png|.*\\.jpg|.*\\.webp).*)",
  ],
};
