/**
 * lastdba.com — Language auto-redirect Worker
 *
 * Logic:
 * 1. Only intercept root path (/ and /en/)
 * 2. If user has "lang-pref" cookie, respect it (don't redirect)
 * 3. China IP → redirect to / (Chinese homepage)
 * 4. Non-China IP → redirect to /en/ (English homepage)
 * 5. Set lang-pref cookie so user's manual language switch overrides geo-redirect
 */

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;
    const country = request.cf?.country;

    // Only handle root path redirects
    if (path !== '/' && path !== '/en/' && path !== '/en') {
      return fetch(request);
    }

    // User has manually chosen a language — respect it
    const cookie = request.headers.get('Cookie') || '';
    if (cookie.includes('lang-pref')) {
      return fetch(request);
    }

    const setCookie = 'lang-pref=1; Path=/; Max-Age=2592000; SameSite=Lax';

    // Chinese visitors on English page → go to Chinese
    if (country === 'CN' && path.startsWith('/en')) {
      return Response.redirect(url.origin + '/', 302);
    }

    // Non-Chinese visitors on Chinese page → go to English
    if (country && country !== 'CN' && path === '/') {
      return Response.redirect(url.origin + '/en/', 302);
    }

    // Correct page already — set cookie so we stop checking
    const response = await fetch(request);
    const newHeaders = new Headers(response.headers);
    newHeaders.set('Set-Cookie', setCookie);
    return new Response(response.body, {
      status: response.status,
      headers: newHeaders,
    });
  },
};
