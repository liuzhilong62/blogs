/**
 * lastdba.com — Language auto-redirect Worker
 *
 * Logic:
 * - First visit to / from non-China IP → redirect to /en/, set cookie
 * - If cookie exists → never redirect (user chose their language)
 * - All other paths → pass through
 * - Cookie 'lang-auto=1' valid for 30 days
 */

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // Only redirect root path
    if (url.pathname !== '/') {
      return fetch(request);
    }

    // User has already been redirected — respect their choice
    const cookie = request.headers.get('Cookie') || '';
    if (cookie.includes('lang-auto')) {
      return fetch(request);
    }

    const country = request.cf?.country;

    // Non-Chinese visitors → English homepage (first time only)
    if (country && country !== 'CN') {
      return new Response(null, {
        status: 302,
        headers: {
          'Location': '/en/',
          'Set-Cookie': 'lang-auto=1; Path=/; Max-Age=2592000; SameSite=Lax',
        },
      });
    }

    // Chinese visitors → pass through + set cookie
    const response = await fetch(request);
    // Cannot modify response.headers (immutable), so recreate with cookie added
    const headers = new Headers(response.headers);
    headers.set('Set-Cookie', 'lang-auto=1; Path=/; Max-Age=2592000; SameSite=Lax');
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
