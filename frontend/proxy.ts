import { NextRequest, NextResponse } from 'next/server';
import { randomBytes } from 'node:crypto';

export function proxy(request: NextRequest) {
  const nonce=randomBytes(24).toString('base64');
  const dev=process.env.NODE_ENV==='development';
  const csp=["default-src 'self'",`script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev?" 'unsafe-eval'":''}`,
    "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:", "font-src 'self'", "connect-src 'self'"+(dev?' ws:':''),
    "object-src 'none'", "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'"].join('; ');
  const headers=new Headers(request.headers);headers.set('x-nonce',nonce);headers.set('Content-Security-Policy',csp);
  const response=NextResponse.next({request:{headers}});
  response.headers.set('Content-Security-Policy',csp);
  response.headers.set('Permissions-Policy','camera=(), microphone=(), geolocation=(), payment=()');
  response.headers.set('Cache-Control','no-store');
  return response;
}
export const config={matcher:['/((?!api|_next/static|_next/image|favicon.ico|icon.svg).*)']};
