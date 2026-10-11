# Authentication

Only needed for the 🔒 endpoints in [endpoints.md](endpoints.md#user-data-). Schedule data is public.
Verified 2026-10-11 by logging in on cineville.de with a real member account.

## Identity provider

`api.cineville.de` is a standard **OpenID Connect** provider (Duende/IdentityServer-style). Discovery:
`GET https://api.cineville.de/.well-known/openid-configuration`

| | |
|---|---|
| Issuer | `https://api.cineville.de` |
| Authorize | `https://api.cineville.de/connect/authorize` |
| Token | `https://api.cineville.de/connect/token` |
| Userinfo | `https://api.cineville.de/connect/userinfo` |
| Login UI | `https://api.cineville.de/auth/login`: **passwordless**. You enter your email and get a one-time code by email (the token still says `amr: ["pwd"]`) |
| Grant types advertised | `authorization_code` (PKCE `S256`/`plain`), `refresh_token`, `client_credentials`, `implicit`, `password`, **`urn:ietf:params:oauth:grant-type:device_code`**, CIBA |

## Tokens

| | Access token | ID token |
|---|---|---|
| Format | JWT, `RS256`, `typ: at+jwt` | JWT, `RS256` |
| Lifetime | **1 hour** | 5 minutes |
| Scopes | `openid api profile email offline_access` | |
| Subject | `sub` = `userId` | |

`offline_access` means the website gets a **refresh token**. It lives server-side in the NextAuth session
and is never exposed to the browser.

## How the website does it

1. `cineville.de/account/signin` → NextAuth redirects to `/connect/authorize` (authorization code flow)
   with the website's client (`client_id` `cc7fa760-c171-4bb8-b28d-436d6a5213dc`, almost certainly a
   *confidential* client with a server-side secret).
2. NextAuth stores the tokens in its own encrypted session cookie on `cineville.de` (session lifetime ~30 days)
   and refreshes the access token server-side.
3. The browser reads `GET https://cineville.de/api/auth/session` →
   `{user{id, email, name, ...}, access_token, id_token, customer{...}, hasActiveSubscription, expires}`
   and calls `api.cineville.de` directly with `Authorization: Bearer <access_token>`.

## Known clients

All client IDs per country are published in the **tenant config** at `GET https://cineville.de/api/tenants`
(public, used by the app at startup). It lists `appAuthClientId` and `webAuthClientId` for NL, BE, DE and SE,
along with `cultureKitApiUrl`, `selfcareUrl`, `timezone`, `scheduleWeek` and `disabledFeatures`. It also contains
the per-country Strapi CMS tokens, which these docs deliberately leave out.

| Client | `client_id` | Flow | Device code? |
|---|---|---|---|
| cineville.de website (NextAuth) | `cc7fa760-c171-4bb8-b28d-436d6a5213dc` (`webAuthClientId`) | auth code, server-side | ❌ `unauthorized_client` |
| mein.cineville.de portal (Auth.js) | `02a86625-750d-42db-8aca-cab5feb1e892` | auth code + PKCE `S256`, redirect `https://mein.cineville.de/api/auth/callback/identity` | ❌ `unauthorized_client` |
| **Cineville mobile app** (Expo/React Native, v2.6.2) | **`0d6499ff-c493-4647-8ea3-72cf7543c369`** (`appAuthClientId`) | auth code + PKCE `S256` via `expo-auth-session`, redirect **`cineville://login-callback`**, scopes `openid api offline_access profile email` | ❌ `unauthorized_client` |

Device authorization endpoint: `POST https://api.cineville.de/connect/deviceauthorization`
(`client_id=...&scope=openid api offline_access`). All three clients were tested on 2026-10-11 and rejected.
Other endpoints: `/connect/revocation`, `/connect/introspect`, `/connect/endsession`.

### Mobile app client: what's verified

- ✅ `/connect/authorize` with `client_id=0d6499ff-…` + `redirect_uri=cineville://login-callback` + PKCE
  forwards to the login page. Every other redirect URI tried (`cineville://`, `cineville:///login-callback`,
  `…/login-callback/`, `nl.cineville.cineville://…`, `cineville://redirect|auth|callback|oauthredirect`) → error page.
- ✅ After login (email + code), the server redirects to `cineville://login-callback?code=…&state=…`.
- ✅ `response_mode=form_post` is accepted too. The code then comes back in a hidden `<input name="code">` on a
  blank page instead of a `cineville://` redirect, which makes it much easier to copy on a desktop browser.
- ✅ **Public client: no secret needed.** `POST /connect/token` with `grant_type=authorization_code`, `client_id`,
  `code`, `redirect_uri`, `code_verifier` → 200 with `access_token` (3600 s), `refresh_token`, `id_token`,
  `scope: openid api offline_access profile email`. (A wrong or stale code gives `invalid_grant`, not `invalid_client`.)
- ✅ `grant_type=refresh_token` (+ `client_id`) → 200 with a new access token. **The refresh token was not rotated**
  (the same one is returned). Store whatever comes back anyway, in case that changes.
- ✅ The new access token reads `/users/{userId}/watchlist/production-ids` and `/visit-history/production-ids`.
- ✅ `POST /connect/revocation` (`client_id`, `token`, `token_type_hint=refresh_token`) → 200.
- ❓ Refresh token lifetime (absolute vs. sliding) is unknown. The HA integration needs a reauth flow for when
  refresh fails.
- Verified end to end on 2026-10-11 with [`tools/cineville_login_test.py`](../../tools/cineville_login_test.py).
- How it was found: the app is an Expo/React Native app (`assets/index.android.bundle`, Hermes bytecode).
  The bundle has an Expo Router route `/login-callback` and the scheme `cineville` (`assets/app.config`).
  The client ID isn't in the bundle; it comes from `/api/tenants`.

## Options for the Home Assistant integration

Ordered by preference (2026-10-11):

1. ✅ **Chosen: authorization code + PKCE with the app's public client, plus the refresh token** (verified above).
   HA config flow: show the authorize URL (with `response_mode=form_post`) → the user logs in with the email code →
   a blank page appears → the user copies the `code` from the page source (Ctrl+U) and pastes it into HA →
   HA exchanges it and stores the refresh token. The copy-paste is the only rough edge, because HA can't receive a
   `cineville://` redirect. Codes expire after ~5 minutes and only work with the PKCE verifier from the same flow,
   so HA has to keep the verifier in the config flow between the "show link" and "paste code" steps.
2. ~~Device code flow.~~ Not allowed for any known client.
3. **Borrow the website session.** Store the `cineville.de` NextAuth session cookie and poll
   `/api/auth/session` for a fresh access token. Brittle; fallback only.
4. **Paste an access token.** Only for one-off testing: it expires after 1 hour.

Don't try the `password` grant. Accounts are passwordless.
