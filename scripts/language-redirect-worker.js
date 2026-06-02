/**
 * lastdba.com — Language auto-redirect Worker
 *
 * Logic:
 * - Only redirect root path /: non-China IP → /en/
 * - /en/ and all sub-paths: pass through (never redirect)
 */

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // Only redirect root path
    if (url.pathname !== '/') {
      return fetch(request);
    }

    const country = request.cf?.country;

    // Non-Chinese visitors → English homepage
    if (country && country !== 'CN') {
      return Response.redirect(url.origin + '/en/', 302);
    }

    // Chinese visitors → stay on /
    return fetch(request);
  },
};
