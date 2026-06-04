/**
 * lastdba.com — Language auto-redirect Worker
 *
 * Logic:
 * - First visit to / from non-China IP → redirect to /en/, set cookie
 * - If cookie exists → never redirect (user chose their language)
 * - All other paths → pass through
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
      const headers = new Headers({
        'Location': '/en/',
        'Set-Cookie': 'lang-auto=1; Path=/; Max-Age=2592000; SameSite=Lax',
      });
      return new Response(null, { status: 302, headers });
    }

    // Chinese visitors → stay on /, set cookie so we don't keep checking
    const response = await fetch(request);
    response.headers.set('Set-Cookie', 'lang-auto=1; Path=/; Max-Age=2592000; SameSite=Lax');
    return response;
  },
};
