# Endpoints

Base URL: `https://api.cineville.de`

Legend: ✅ verified live · 🔒 needs a user bearer token · 📦 seen in the client code only, not exercised

## Optional request headers

| Header | Effect |
|---|---|
| `locale: de-DE` | Language of `localizableAttributes`. **Default is `de-DE`**. `en-GB` returns empty strings (no English copy exists). `*` returns all locales as `{ "de-DE": {...} }`. See [querying.md](querying.md#locale). |
| `Authorization: Bearer <token>` | Only for 🔒 endpoints |
| `session-id: <id>` | Only used by the shop/order flow |

## Schedule & catalogue (public)

### Events: a single screening

| Method | Path | Notes |
|---|---|---|
| ✅ `POST` | `/events/search` | **Main endpoint.** JSON body = filters + `page`, `sort`, `embed`. See [querying.md](querying.md) |
| ✅ `GET` | `/events` | Same filters as bracket query params (`?startDate[gte]=...&page[limit]=100`) |
| ✅ `GET` | `/events/{id}` | `?embed[production]=true&embed[venue]=true` works |
| ✅ `GET` | `/events/{id}/collections` | Collections the event belongs to |

Response: `{count, totalCount, _links, _embedded: {events: Event[]}}`. See [data-model.md](data-model.md#event).

### Productions: a film

| Method | Path | Notes |
|---|---|---|
| ✅ `POST` | `/productions/search` | Filters on production fields **and** on its events via a nested `event: {...}` (e.g. "films showing in Hamburg this week") |
| ✅ `GET` | `/productions` | Bracket query params. ~8000 productions in total |
| ✅ `GET` | `/productions/{id}` | |
| ✅ `GET` | `/productions/{id}/events` | All events of a film (paginated, includes past events) |
| ✅ `GET` | `/productions/{id}/assets` | Asset relations (poster/cover/trailer) |
| ✅ `GET` | `/productions/{id}/collections` | e.g. `now-screening`, `coming-soon` |
| ✅ `GET` | `/productions/by-title/{title}` | Exact title lookup, used by the site search |

Response: `{..., _embedded: {productions: Production[]}}`.

### Venues: a cinema

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/venues` | e.g. `?collection[cities][in][0]=hamburg&isHidden[eq]=false&sort[name]=asc&page[limit]=1000` |
| ✅ `GET` | `/venues/{id}` | |
| ✅ `GET` | `/venues/{id}/collections` | The city collection the venue belongs to |
| ✅ `GET` | `/venues/{id}/assets` | |

There is no `/venues/search`; the website uses `GET /venues`. Without a filter, `GET /venues?page[limit]=1000` lists every
venue (77 as of 2026-10, 74 visible). See [data-model.md](data-model.md#all-venues-2026-10-11) for the full list by city.

### Collections: tagging and grouping

Collections are how CultureKit groups things. Venues → city, productions → "now screening",
events → festival/series. Each collection belongs to a collection group.

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/collection-groups` | 29 groups, e.g. `cities`, `common`, `highlights`, `specials`, `subtitles`, `events-hamburg`, ... |
| ✅ `GET` | `/collections` | 431 collections. Filter by group: `?collectionGroupId[eq]=cities&page[limit]=200` |
| 📦 `GET` | `/collections/{id}` | |

Collection groups and IDs that matter in practice:

| Group | IDs (2026-10) |
|---|---|
| `cities` | 21 IDs, but only 15 have venues: `aachen`, `Berlin`, `bonn`, `braunschweig`, `bremen`, `duesseldorf`, `freiburg`, `fuerth`, `hamburg`, `koeln`, `leverkusen`, `nuernberg`, `potsdam`, `wuerzburg`, `wuppertal`. These are the same 15 as the website's city filter. Empty or duplicate IDs: `dresden`, `erlangen`, `k`, `nu`, `neue-kinos`, and `Nürnberg` (its venues are a subset of `nuernberg`). ⚠️ IDs are **case-sensitive** and inconsistent (`Berlin` is capitalised). |
| `common` | `now-screening`, `coming-soon` (applied to productions) |
| `subtitles` | `OmeU`, `OmU`, `OV`, `english-subs` |
| `specials` | `introduction`, `diverse`, `cineville-trailer`, `open-air`, `film-der-woche`, `filmderwoche-neu` |
| `highlights` | `ff-now-screening`, `ff-coming-soon`, `homepage`, `tipp` |
| `events-<city>` | Film series / festivals per city, e.g. `filmfest-hamburg`, `metropolis-hitchcock` |

### Production types

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/production-types` | Only one: `film` |
| ✅ `GET` | `/production-types/film` | **JSON Schemas** for production and event `attributes` / `localizableAttributes`. This is the authoritative list of tags, highlight types and language codes. See [samples/production-type-film.json](samples/production-type-film.json) |

### Ratings

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/ratings/by-production/{productionId}` | `{"rating": 3.32, "count": 151}`: average of member ratings (scale looks like 1–5) |

### Assets

| Method | Path | Notes |
|---|---|---|
| 📦 `GET` | `/assets/{id}` | Usually not needed: `assets.poster.url` etc. are already inlined in productions and venues |

## User data 🔒

Need a member's bearer token (`Authorization: Bearer <access_token>`). See [authentication.md](authentication.md).
Unauthenticated calls return `401`. Verified 2026-10-11 with a real member account; **only GETs were
exercised**, so the write endpoints (📦) come from the client code alone.

There are two separate ID spaces:
- **`userId`**: the OIDC `sub` (from `/connect/userinfo`). Used for the "social" features: watchlist, history, ratings.
- **`customerId`**: from `GET /customers/me`. Used for the membership side: subscription, card, visits, reservations, invoices.

### Identity

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/connect/userinfo` | `{sub, email, email_verified, name, given_name, family_name}`. `sub` = `userId` |
| ✅ `GET` | `/customers/me` | `{id, firstName, lastName, fullName, birthdate, email, address{...}, billingAddress, paymentInfo{paymentMethod: "sepa", maskedBankAccount, inNameOf, creditcardExpirationDate}}`. `id` = `customerId` |
| ❌ `GET` | `/users/{userId}`, `/users/me`, `/customers/{customerId}` | 404. Not routes, despite the client classes |

### User features (`/users/{userId}/...`)

Standard HAL lists with `page[limit]` and cursor `next` links, like the public endpoints.

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/users/{userId}/watchlist` | `_embedded.items[]: {id, userId, productionId, createdAt, updatedAt}` |
| ✅ `GET` | `/users/{userId}/watchlist/production-ids` | `{productionIds: [...]}`. The website feeds this into the showtime filter `productionId: {in: [...]}` ("only my watchlist") |
| ✅ `GET` | `/users/{userId}/watchlist/by-production/{productionId}` | The item, or `204` if not on the list |
| 📦 `POST` | `/users/{userId}/watchlist` | body `{productionId}` |
| 📦 `DELETE` | `/users/{userId}/watchlist/{id}` | |
| ✅ `GET` | `/users/{userId}/visit-history` | `_embedded.items[]: {id, productionId, eventId, eventStartDate, isAddedByUser, recordedAt, createdAt}`. Oldest first. Includes visits added by hand (`isAddedByUser`) |
| ✅ `GET` | `/users/{userId}/visit-history/production-ids` | `{productionIds}`. The website uses it for "not seen yet": `productionId: {nin: [...]}` |
| 📦 `POST` | `/users/{userId}/visit-history` | Mark a film as seen ("Gesehen") |
| ✅ `GET` | `/users/{userId}/ratings` | `_embedded.ratings[]: {id, productionId, rating}`. ⚠️ `rating` is a **string** here (`"5.0"`) |
| ❌ `GET` | `/users/{userId}/ratings/production-ids` | 500 server error |
| 📦 `GET` | `/users/{userId}/ratings/by-production/{productionId}` | Own rating, `204` if none |
| 📦 `PUT` / `DELETE` | `/users/{userId}/ratings/{productionId}` | body `{rating}` |
| ✅ `GET` | `/users/{userId}/notification-preferences` | `_embedded.preferences[]: {type, isEnabled}`. Types: `reservation_reminder`, `watchlist_alert`, `rating_request` |
| ✅ `GET` | `/users/{userId}/productions/{productionId}` | Everything about one film for this user in one call: `_embedded: {rating, visitHistoryItems[], watchlistItem}` |

### Membership (`/customers/{customerId}/...`)

⚠️ **Different pagination:** these use `?size=N&page=P` (page numbers, starting at 1), not `page[limit]`/cursors.
`page[limit]` is ignored. `_links.next.href` still works. The website's client rewrites `page[limit]` → `size`.

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/customers/{customerId}/subscriptions` | `{id, startDate, endDate, status: "ACTIVE", hasOverdueInvoice, canMakeVisit, canBeReactivated, _embedded: {billing: {billingFrequency: "MONTHLY", billingFrequencyInterval, billingForecast[{startDate, endDate, regularPriceInclVat, priceInclVat}]}, cards[], product{id, name, image}, endDateOptions{earliestAllowedEndDate, fullLastMonth, minimumDurationMonths, cancellationPeriodMonths}}}` |
| ✅ `GET` | `/customers/{customerId}/cards` | `{photoUrl, isActive, isTemporary, endDate, barcode: {type: "code128", value}}`. The barcode is the membership card shown at the cinema |
| ✅ `GET` | `/customers/{customerId}/visits` | **Actual check-ins at the cinema**, newest first: `{id, eventId, eventStart, isCancelled, productionId, productionTitle, venueId, venueName, createdByClientId}`. Links to event/production/venue. Appears the same day |
| ✅ `GET` | `/customers/{customerId}/reservations` | `{id, eventId, eventStart, status, collectionDeadline, releaseAfter, productionId, productionTitle, venueId, venueName}`. Oldest first. Status ∈ `DRAFT`, `ACTIVE`, `CANCELLED`, `COLLECTED`, `EXPIRED`, `RELEASED` (`ACTIVE` = an upcoming reserved seat) |
| ✅ `GET` | `/customers/{customerId}/invoices` | `{id, invoiceNumber, issueDate, dueDate, paymentStatus: "PAID", amountOpen, totalPriceInclVat{amount, currency}, totalPriceExclVat, totalVat, paymentUrl}` + `_links.invoiceUrl` |
| 📦 `GET` | `/invoices/{id}/download-pdf` | |
| 📦 `GET` | `/subscriptions/{id}/available-products` | |
| 📦 `POST` | `/subscriptions/{id}/reactivate`, `/customers/{id}/cards/{cardId}/report-lost`, `/customers/{id}/start-change-payment-details-payment`, `/cards/{id}/upload-photo` | Account changes. Never call these from an integration |
| ✅ `GET` | `/payment-methods` | `_embedded.paymentMethods[]: {id}` (available methods, not the user's) |
| ❌ `GET` | `/subscriptions`, `/cards`, `/devices` | 500 / 404 / CORS-blocked. Only the customer-scoped variants work |
| 📦 `PUT` / `DELETE` | `/devices/{id}/push-token` | App push registration |

## Shop (public read)

| Method | Path | Notes |
|---|---|---|
| ✅ `GET` | `/products` | Membership products with prices (e.g. "Das Cineville-Abo", `priceInclVat: {amount: 2400, currency: "EUR"}`) |
| ✅ `GET` | `/order-forms` | Sign-up form config |
| 📦 | `/orders/{id}/line-items`, `/start-payment`, `/confirm`, `/voucher` | Checkout flow, uses `session-id` header |
| ✅ `GET` | `/address-lookup` | Dutch postcode format only (`1111AA`) → 422 for German postcodes |
## Errors

| Case | Response |
|---|---|
| Body validation failure | `400 {"statusCode":400,"message":"Validation failed","errors":[{path, code, message, ...}]}` (zod-style) |
| Unknown route | `404 {"error":{"code":404,"unique_identifier":"<uuid>","message":"HTTP 404: Not Found"}}` |
| Missing/expired token | `401 {"message":"Unauthorized","statusCode":401}` |
| Some user routes | `404 {"message":"Cannot GET /users/...","error":"Not Found","statusCode":404}` (NestJS-style) |
| Server bug | `500 {"statusCode":500,"message":"Internal server error"}` |
| Old GraphQL endpoint | `405 Method not allowed` at `https://cineville.de/api/graphql` |
