/**
 * Cineville card for Home Assistant.
 *
 * Shows a day's program from the Cineville integration (service cineville.get_program),
 * either grouped by film or as a chronological list, with a day picker and cinema / time filters.
 * Dependency-free web component; served and registered by the integration itself.
 */

const CARD_VERSION = "0.4.0-alpha.1";
const REFRESH_MS = 10 * 60 * 1000;
const VIEW_STORAGE_KEY = "cineville-card-view";
// Watchlist filter: "" (all films), "any", "all" (everyone's) or an account ID. The old boolean key is migrated.
const WATCHLIST_STORAGE_KEY = "cineville-card-watchlist";
const OLD_WATCHLIST_STORAGE_KEY = "cineville-card-watchlist-only";
// Marker colours for the people whose watchlists are combined
const PERSON_COLORS = ["#e91e63", "#3f51b5", "#009688", "#ff9800", "#9c27b0", "#795548"];

const STRINGS = {
  en: {
    today: "Today",
    tomorrow: "Tomorrow",
    allCinemas: "All cinemas",
    fromNow: "From now",
    allTimes: "All times",
    from: "From",
    films: "By film",
    list: "List",
    loading: "Loading program…",
    empty: "No screenings for this selection.",
    error: "Could not load the program.",
    retry: "Retry",
    minutes: "min",
    by: "by",
    tickets: "Tickets",
    started: "started",
    ages: "Age",
    watchlist: "Watchlist",
    watchlistOnly: "Only films on my watchlist",
    allFilms: "All films",
    seen: "Seen",
    votes: "votes",
    emptyWatchlist: "None of your watchlist films is showing in this selection.",
    wlAny: "Anyone's watchlist",
    wlEveryone: "Everyone's watchlist",
    wlPerson: "{name}'s watchlist",
    seenBy: "Seen by",
    editor: {
      title: "Title",
      config_entry_id: "City (only needed if you set up several)",
      view: "Default view",
      days: "Days in the day picker",
      show_past: "Show screenings that have already started",
      max_height: "Maximum height (e.g. 500px; only for dashboards without a grid)",
      watchlist: "Watchlist films (when logged in)",
      watchlist_highlight: "Highlight them",
      watchlist_only: "Show only them (switchable on the card)",
      seen: "Films you've already seen",
      seen_dim: "Dim",
      seen_hide: "Hide",
      seen_show: "Show normally",
      films: "Grouped by film",
      list: "Chronological list",
    },
  },
  de: {
    today: "Heute",
    tomorrow: "Morgen",
    allCinemas: "Alle Kinos",
    fromNow: "Ab jetzt",
    allTimes: "Alle Zeiten",
    from: "Ab",
    films: "Nach Film",
    list: "Liste",
    loading: "Programm wird geladen…",
    empty: "Keine Vorstellungen für diese Auswahl.",
    error: "Das Programm konnte nicht geladen werden.",
    retry: "Erneut versuchen",
    minutes: "Min.",
    by: "von",
    tickets: "Tickets",
    started: "läuft",
    ages: "FSK",
    watchlist: "Merkliste",
    watchlistOnly: "Nur Filme von meiner Merkliste",
    allFilms: "Alle Filme",
    seen: "Gesehen",
    votes: "Stimmen",
    emptyWatchlist: "Kein Film von deiner Merkliste läuft in dieser Auswahl.",
    wlAny: "Merkliste: irgendwer",
    wlEveryone: "Merkliste: alle gemeinsam",
    wlPerson: "Merkliste: {name}",
    seenBy: "Gesehen von",
    editor: {
      title: "Titel",
      config_entry_id: "Stadt (nur nötig bei mehreren Städten)",
      view: "Standardansicht",
      days: "Tage in der Tagesauswahl",
      show_past: "Bereits begonnene Vorstellungen anzeigen",
      max_height: "Maximale Höhe (z. B. 500px; nur für Dashboards ohne Raster)",
      watchlist: "Filme auf der Merkliste (wenn angemeldet)",
      watchlist_highlight: "Hervorheben",
      watchlist_only: "Nur diese zeigen (auf der Karte umschaltbar)",
      seen: "Bereits gesehene Filme",
      seen_dim: "Abblenden",
      seen_hide: "Ausblenden",
      seen_show: "Normal anzeigen",
      films: "Nach Film gruppiert",
      list: "Chronologische Liste",
    },
  },
};

const HIGHLIGHT_LABELS = {
  en: { filmOfTheWeek: "Film of the week", tip: "Tip", upcomingFilm: "Upcoming", freshTrailer: "Fresh trailer" },
  de: { filmOfTheWeek: "Film der Woche", tip: "Tipp", upcomingFilm: "Demnächst", freshTrailer: "Frischer Trailer" },
};

const FROM_HOURS = [17, 19, 21];

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Only allow http(s) URLs in href/src. */
function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : "";
  } catch {
    return "";
  }
}

/** imgix poster URL resized for the card. */
function posterUrl(url, width) {
  const safe = safeUrl(url);
  if (!safe) return "";
  const u = new URL(safe);
  if (u.hostname.endsWith("imgix.net")) {
    u.searchParams.set("auto", "format");
    u.searchParams.set("fit", "crop");
    u.searchParams.set("w", String(width));
    u.searchParams.set("h", String(Math.round(width * 1.5)));
  }
  return u.toString();
}

function addDays(isoDate, days) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

class CinevilleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._programs = {}; // day -> response
    this._loading = new Set();
    this._errors = {};
    this._day = null;
    this._venue = "";
    this._from = null; // null = default ("now" for today, all times otherwise)
    this._view = null;
    this._wlMode = null; // null = from config, then remembered per browser (see WATCHLIST_STORAGE_KEY)
  }

  static getStubConfig() {
    return { view: "films" };
  }

  static getConfigForm() {
    const lang = (document.querySelector("home-assistant")?.hass?.locale?.language || navigator.language || "en").slice(0, 2);
    const t = (STRINGS[lang] || STRINGS.en).editor;
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        { name: "config_entry_id", selector: { config_entry: { integration: "cineville" } } },
        {
          name: "view",
          selector: { select: { mode: "dropdown", options: [{ value: "films", label: t.films }, { value: "list", label: t.list }] } },
        },
        { name: "days", selector: { number: { min: 1, max: 8, mode: "box" } } },
        { name: "show_past", selector: { boolean: {} } },
        { name: "max_height", selector: { text: {} } },
        {
          name: "watchlist",
          selector: { select: { mode: "dropdown", options: [
            { value: "highlight", label: t.watchlist_highlight },
            { value: "only", label: t.watchlist_only },
          ] } },
        },
        {
          name: "seen",
          selector: { select: { mode: "dropdown", options: [
            { value: "dim", label: t.seen_dim },
            { value: "hide", label: t.seen_hide },
            { value: "show", label: t.seen_show },
          ] } },
        },
      ],
      computeLabel: (schema) => t[schema.name] || schema.name,
    };
  }

  setConfig(config) {
    this._config = { view: "films", days: 7, show_past: false, watchlist: "highlight", seen: "dim", ...config };
    this._config.days = Math.max(1, Math.min(8, Number(this._config.days) || 7));
    if (this._hass) this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._ensureDay();
      this._fetch(this._day);
      this._render();
    }
  }

  connectedCallback() {
    this._timer = setInterval(() => {
      if (!this._hass) return;
      const day = this._day;
      delete this._programs[day];
      this._fetch(day);
    }, REFRESH_MS);
    // Re-render every minute so "started" screenings drop off
    this._tick = setInterval(() => this._render(), 60 * 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    clearInterval(this._tick);
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 4 };
  }

  // --- helpers -----------------------------------------------------------------------

  get _lang() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return STRINGS[lang] ? lang : "en";
  }

  get _t() {
    return STRINGS[this._lang];
  }

  get _today() {
    const known = Object.values(this._programs)[0];
    if (known?.today) return known.today;
    // Before the first response: Cineville day in Berlin (starts at 04:00)
    const berlin = new Date(Date.now() - 4 * 3600 * 1000).toLocaleDateString("sv-SE", { timeZone: "Europe/Berlin" });
    return berlin;
  }

  _ensureDay() {
    if (!this._day) this._day = this._today;
    if (!this._view) {
      let stored = null;
      try {
        stored = localStorage.getItem(VIEW_STORAGE_KEY);
      } catch {
        /* storage unavailable */
      }
      this._view = stored === "films" || stored === "list" ? stored : this._config.view;
    }
    if (this._wlMode === null) {
      let stored = null;
      let old = null;
      try {
        stored = localStorage.getItem(WATCHLIST_STORAGE_KEY);
        old = localStorage.getItem(OLD_WATCHLIST_STORAGE_KEY);
      } catch {
        /* storage unavailable */
      }
      if (stored !== null) this._wlMode = stored;
      else if (old !== null) this._wlMode = old === "1" ? "any" : "";
      else this._wlMode = this._config.watchlist === "only" ? "any" : "";
    }
  }

  /**
   * Formatting settings from the user's HA profile: language, time format (language/system/12/24),
   * time zone (local = browser, server = HA's configured zone) and date format (language/system/DMY/MDY/YMD).
   */
  get _fmt() {
    const locale = this._hass?.locale || {};
    const language = locale.language || this._hass?.language || navigator.language || "en";
    const timeZone = locale.time_zone === "server" ? this._hass?.config?.time_zone || undefined : undefined;
    let hour12;
    if (locale.time_format === "12") hour12 = true;
    else if (locale.time_format === "24") hour12 = false;
    else if (locale.time_format === "system") hour12 = new Intl.DateTimeFormat(undefined, { hour: "numeric" }).resolvedOptions().hour12;
    const key = [language, timeZone, hour12, locale.date_format].join("|");
    if (this._fmtCache?.key !== key) {
      // 12-hour clocks read better without a leading zero ("7:30 PM"), 24-hour ones with ("07:30")
      const probe = new Intl.DateTimeFormat(language, { hour: "numeric", hour12 });
      const twelve = probe.resolvedOptions().hour12;
      const hour = twelve ? "numeric" : "2-digit";
      this._fmtCache = {
        key,
        language,
        timeZone,
        dateFormat: locale.date_format || "language",
        time: new Intl.DateTimeFormat(language, { hour, minute: "2-digit", hour12, timeZone }),
        // Formats a bare hour for the "from" filter labels (UTC, so no zone shift)
        hourLabel: new Intl.DateTimeFormat(language, { hour, minute: "2-digit", hour12, timeZone: "UTC" }),
      };
    }
    return this._fmtCache;
  }

  _fmtTime(iso) {
    return this._fmt.time.format(new Date(iso));
  }

  _fmtHour(hour) {
    return this._fmt.hourLabel.format(new Date(Date.UTC(2000, 0, 1, hour)));
  }

  /** Hour of day in the display time zone; after-midnight screenings count as 24+ (same Cineville day). */
  _hour(iso) {
    const parts = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: this._fmt.timeZone }).formatToParts(new Date(iso));
    const h = Number(parts.find((p) => p.type === "hour").value);
    const m = Number(parts.find((p) => p.type === "minute").value);
    // Screenings after midnight belong to the previous Cineville day
    return (h < 4 ? h + 24 : h) + m / 60;
  }

  _dayLabel(day) {
    const t = this._t;
    if (day === this._today) return t.today;
    if (day === addDays(this._today, 1)) return t.tomorrow;
    const [y, m, d] = day.split("-").map(Number);
    const date = new Date(Date.UTC(y, m - 1, d));
    const { language, dateFormat } = this._fmt;
    if (dateFormat === "DMY" || dateFormat === "MDY" || dateFormat === "YMD") {
      const weekday = new Intl.DateTimeFormat(language, { weekday: "short", timeZone: "UTC" }).format(date);
      const dd = String(d).padStart(2, "0");
      const mm = String(m).padStart(2, "0");
      const order = { DMY: `${dd}/${mm}`, MDY: `${mm}/${dd}`, YMD: `${mm}-${dd}` }[dateFormat];
      return `${weekday} ${order}`;
    }
    const lang = dateFormat === "system" ? undefined : language;
    return new Intl.DateTimeFormat(lang, { weekday: "short", day: "numeric", month: "numeric", timeZone: "UTC" }).format(date);
  }

  // --- data ----------------------------------------------------------------------------

  async _fetch(day) {
    if (!this._hass || this._loading.has(day) || this._programs[day]) return;
    this._loading.add(day);
    delete this._errors[day];
    this._render();
    const serviceData = {};
    if (day !== this._today) serviceData.date = day;
    if (this._config.config_entry_id) serviceData.config_entry_id = this._config.config_entry_id;
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "call_service",
        domain: "cineville",
        service: "get_program",
        service_data: serviceData,
        return_response: true,
      });
      const program = result.response;
      // File it under the day the server says it is: when "today" is requested without a date, the
      // server's idea of today can differ from ours (e.g. right around the 04:00 day boundary)
      this._programs[program.day] = program;
      if (this._day === day && day !== program.day) this._day = program.day;
    } catch (err) {
      this._errors[day] = err?.message || String(err);
    } finally {
      this._loading.delete(day);
      this._render();
    }
  }

  _filtered(program) {
    const isToday = program.day === program.today;
    const now = Date.now();
    const from = this._from ?? (isToday ? "now" : "");
    const mode = this._watchlistMode(program);
    const everyone = (program.accounts || []).length;
    return program.showtimes.filter((s) => {
      if (this._venue && s.venue.id !== this._venue) return false;
      const by = s.film.watchlist_by || (s.film.on_watchlist ? ["?"] : []);
      if (mode === "any" && !by.length) return false;
      if (mode === "all" && by.length < everyone) return false;
      if (mode && mode !== "any" && mode !== "all" && !by.includes(mode)) return false;
      if (this._config.seen === "hide" && s.film.seen) return false;
      if (from === "now" && !this._config.show_past && new Date(s.start).getTime() < now) return false;
      if (from && from !== "now" && this._hour(s.start) < Number(from)) return false;
      return true;
    });
  }

  /** Effective watchlist filter for this program: "" when nobody is logged in or the chosen person is gone. */
  _watchlistMode(program) {
    if (!program?.logged_in || !this._wlMode) return "";
    const ids = (program.accounts || []).map((a) => a.id);
    if (this._wlMode === "any") return "any";
    if (this._wlMode === "all") return ids.length > 1 ? "all" : "any";
    return ids.includes(this._wlMode) ? this._wlMode : "";
  }

  _setWatchlistMode(mode) {
    this._wlMode = mode;
    try {
      localStorage.setItem(WATCHLIST_STORAGE_KEY, mode);
    } catch {
      /* storage unavailable */
    }
  }

  // --- events --------------------------------------------------------------------------

  _onClick(ev) {
    const el = ev.target.closest("[data-action]");
    if (!el) return;
    const { action, value } = el.dataset;
    if (action === "day") {
      this._day = value;
      this._from = null;
      this._fetch(value);
    } else if (action === "view") {
      this._view = value;
      try {
        localStorage.setItem(VIEW_STORAGE_KEY, value);
      } catch {
        /* storage unavailable */
      }
    } else if (action === "watchlist") {
      this._setWatchlistMode(this._wlMode ? "" : "any");
    } else if (action === "retry") {
      this._fetch(this._day);
    }
    this._render();
  }

  _onChange(ev) {
    const el = ev.target;
    if (el.dataset.filter === "venue") this._venue = el.value;
    if (el.dataset.filter === "from") this._from = el.value;
    if (el.dataset.filter === "watchlist") this._setWatchlistMode(el.value);
    this._render();
  }

  // --- rendering -----------------------------------------------------------------------

  _render() {
    if (!this._config || !this._hass) return;
    this._ensureDay();
    const t = this._t;
    const program = this._programs[this._day];
    const city = program?.city?.name || Object.values(this._programs)[0]?.city?.name || "";
    const title = this._config.title ?? (city ? `Cineville ${city}` : "Cineville");

    // Keep scroll positions across re-renders (the card re-renders every minute). The program list
    // only keeps its position while the same day/view/filters are shown.
    const dayStrip = this.shadowRoot.querySelector(".days");
    const scrollLeft = dayStrip ? dayStrip.scrollLeft : 0;
    const contentKey = [this._day, this._view, this._venue, this._from, this._wlMode].join("|");
    const oldContent = this.shadowRoot.querySelector(".content");
    const scrollTop = oldContent && contentKey === this._contentKey ? oldContent.scrollTop : 0;
    this._contentKey = contentKey;
    this.style.setProperty("--cineville-max-height", this._maxHeight());

    let body;
    if (this._errors[this._day]) {
      body = `<div class="state error">${esc(t.error)}<br><small>${esc(this._errors[this._day])}</small>
        <button class="retry" data-action="retry">${esc(t.retry)}</button></div>`;
    } else if (!program) {
      body = `<div class="state">${esc(t.loading)}</div>`;
    } else {
      const shows = this._filtered(program);
      if (!shows.length) body = `<div class="state">${esc(this._watchlistMode(program) ? t.emptyWatchlist : t.empty)}</div>`;
      else body = this._view === "list" ? this._renderList(shows, program) : this._renderFilms(shows, program);
    }

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <div class="title">${esc(title)}</div>
          <div class="actions">
          ${program?.logged_in && (program.accounts || []).length <= 1 ? (() => {
            const on = Boolean(this._watchlistMode(program));
            return `<button class="toggle ${on ? "active" : ""}" data-action="watchlist" aria-pressed="${on}"
              title="${esc(on ? t.allFilms : t.watchlistOnly)}">
              <ha-icon icon="${on ? "mdi:bookmark" : "mdi:bookmark-outline"}"></ha-icon></button>`;
          })() : ""}
          <div class="views" role="group">
            ${["films", "list"]
              .map(
                (v) => `<button class="view ${this._view === v ? "active" : ""}" data-action="view" data-value="${v}"
                   aria-pressed="${this._view === v}" title="${esc(t[v])}">
                   <ha-icon icon="${v === "films" ? "mdi:view-agenda-outline" : "mdi:format-list-bulleted"}"></ha-icon></button>`
              )
              .join("")}
          </div>
          </div>
        </div>
        <div class="days">${this._renderDays()}</div>
        ${program ? this._renderFilters(program) : ""}
        <div class="content">${body}</div>
      </ha-card>`;

    const strip = this.shadowRoot.querySelector(".days");
    if (strip) strip.scrollLeft = scrollLeft;
    const content = this.shadowRoot.querySelector(".content");
    if (content) content.scrollTop = scrollTop;
    this.shadowRoot.querySelector("ha-card").addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.querySelectorAll("select").forEach((s) => s.addEventListener("change", (e) => this._onChange(e)));
  }

  /** max_height from the config as a CSS length: 500 -> "500px"; anything unexpected -> "none". */
  _maxHeight() {
    const value = this._config.max_height;
    if (value === undefined || value === null || value === "") return "none";
    if (typeof value === "number" || /^\d+(\.\d+)?$/.test(String(value).trim())) return `${Number(value)}px`;
    const text = String(value).trim();
    return /^\d+(\.\d+)?(px|vh|em|rem)$/.test(text) ? text : "none";
  }

  _renderDays() {
    const days = [];
    for (let i = 0; i < this._config.days; i++) days.push(addDays(this._today, i));
    return days
      .map(
        (d) => `<button class="day ${d === this._day ? "active" : ""}" data-action="day" data-value="${d}"
          aria-pressed="${d === this._day}">${esc(this._dayLabel(d))}</button>`
      )
      .join("");
  }

  _renderFilters(program) {
    const t = this._t;
    const venues = new Map();
    program.showtimes.forEach((s) => venues.set(s.venue.id, s.venue.name));
    const sortedVenues = [...venues.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    if (this._venue && !venues.has(this._venue)) this._venue = "";
    const isToday = program.day === program.today;
    const from = this._from ?? (isToday ? "now" : "");
    const fromOptions = [
      ...(isToday ? [["now", t.fromNow]] : []),
      ["", t.allTimes],
      ...FROM_HOURS.map((h) => [String(h), `${t.from} ${this._fmtHour(h)}`]),
    ];
    return `<div class="filters">
      <select data-filter="venue" aria-label="${esc(t.allCinemas)}">
        <option value="">${esc(t.allCinemas)}</option>
        ${sortedVenues.map(([id, name]) => `<option value="${esc(id)}" ${id === this._venue ? "selected" : ""}>${esc(name)}</option>`).join("")}
      </select>
      <select data-filter="from" aria-label="${esc(t.from)}">
        ${fromOptions.map(([v, label]) => `<option value="${v}" ${v === from ? "selected" : ""}>${esc(label)}</option>`).join("")}
      </select>
      ${this._renderWatchlistSelect(program)}
    </div>`;
  }

  /** With several accounts: all films / anyone's / everyone's / one person's watchlist. */
  _renderWatchlistSelect(program) {
    const people = program.accounts || [];
    if (!program.logged_in || people.length < 2) return "";
    const t = this._t;
    const mode = this._watchlistMode(program);
    const options = [
      ["", t.allFilms],
      ["any", t.wlAny],
      ["all", t.wlEveryone],
      ...people.map((p) => [p.id, t.wlPerson.replace("{name}", p.name)]),
    ];
    return `<select data-filter="watchlist" aria-label="${esc(t.watchlist)}">
      ${options.map(([v, label]) => `<option value="${esc(v)}" ${v === mode ? "selected" : ""}>${esc(label)}</option>`).join("")}
    </select>`;
  }

  _poster(film, width, cls) {
    const src = posterUrl(film.poster_url, width * 2);
    return src
      ? `<img class="${cls}" src="${esc(src)}" alt="" loading="lazy">`
      : `<div class="${cls} placeholder"><ha-icon icon="mdi:filmstrip"></ha-icon></div>`;
  }

  _filmMeta(film) {
    const t = this._t;
    const parts = [];
    if (film.release_year) parts.push(film.release_year);
    if (film.duration) parts.push(`${film.duration} ${t.minutes}`);
    if (film.directors?.length) parts.push(`${t.by} ${film.directors.slice(0, 2).join(", ")}`);
    if (film.min_age != null) parts.push(`${t.ages} ${film.min_age}`);
    return parts.map(esc).join(" · ");
  }

  _badges(show, withLanguage = true) {
    const out = [];
    if (withLanguage && show.language_label) out.push(`<span class="badge lang">${esc(show.language_label)}</span>`);
    if (show.specials) out.push(`<span class="badge special">${esc(show.specials)}</span>`);
    return out.join("");
  }

  /** IMDb / Rotten Tomatoes badges (from the integration's ratings, if configured). */
  _ratingBadges(film, compact = false) {
    const r = film.ratings;
    if (!r) return "";
    const { language } = this._fmt;
    const out = [];
    if (r.imdb != null) {
      const score = new Intl.NumberFormat(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(r.imdb);
      const votes = r.imdb_votes != null ? ` · ${new Intl.NumberFormat(language).format(r.imdb_votes)} ${this._t.votes}` : "";
      const inner = `<b>IMDb</b> ${esc(score)}`;
      const href = r.imdb_id && /^tt\d+$/.test(r.imdb_id) ? `https://www.imdb.com/title/${r.imdb_id}/` : "";
      out.push(
        href
          ? `<a class="rating imdb" href="${href}" target="_blank" rel="noopener noreferrer" title="IMDb${esc(votes)}">${inner}</a>`
          : `<span class="rating imdb" title="IMDb${esc(votes)}">${inner}</span>`
      );
    }
    if (r.rotten_tomatoes != null && !(compact && out.length)) {
      const fresh = r.rotten_tomatoes >= 60;
      out.push(`<span class="rating rt ${fresh ? "fresh" : "rotten"}" title="Rotten Tomatoes">${fresh ? "🍅" : "🟢"} ${esc(r.rotten_tomatoes)}%</span>`);
    }
    return out.join("");
  }

  /** Classes and badges for a film's watchlist / seen state. */
  _filmState(film, program) {
    const t = this._t;
    const people = program?.accounts || [];
    const several = people.length > 1;
    const classes = [];
    const badges = [];
    if (film.on_watchlist) {
      classes.push("watchlisted");
      const markers = several ? this._markers(film.watchlist_by || [], people) : esc(t.watchlist);
      const who = several ? this._names(film.watchlist_by || [], people) : t.watchlist;
      badges.push(`<span class="badge wl" title="${esc(`${t.watchlist}: ${who}`)}"><ha-icon icon="mdi:bookmark"></ha-icon>${markers}</span>`);
    }
    if (this._config.seen !== "show") {
      if (film.seen) {
        // Seen by everyone
        if (this._config.seen === "dim") classes.push("seen");
        badges.push(`<span class="badge seen-badge">${esc(t.seen)}</span>`);
      } else if (several && film.seen_by?.length) {
        badges.push(`<span class="badge seen-badge" title="${esc(`${t.seenBy}: ${this._names(film.seen_by, people)}`)}">${esc(t.seen)} ${this._markers(film.seen_by, people)}</span>`);
      }
    }
    return { classes: classes.join(" "), badges: badges.join("") };
  }

  /** Coloured initials for account IDs (two letters when first letters clash). */
  _markers(ids, people) {
    const initials = (name) => {
      const first = (name || "?").trim().charAt(0).toUpperCase();
      const clash = people.filter((p) => (p.name || "?").trim().charAt(0).toUpperCase() === first).length > 1;
      return clash ? (name || "?").trim().slice(0, 2) : first;
    };
    return people
      .map((p, i) => ({ ...p, color: PERSON_COLORS[i % PERSON_COLORS.length] }))
      .filter((p) => ids.includes(p.id))
      .map((p) => `<span class="person" style="background:${p.color}">${esc(initials(p.name))}</span>`)
      .join("");
  }

  _names(ids, people) {
    return people.filter((p) => ids.includes(p.id)).map((p) => p.name).join(", ");
  }

  _chip(show) {
    const time = esc(this._fmtTime(show.start));
    const started = new Date(show.start).getTime() < Date.now();
    const lang = show.language_label ? `<span class="lang">${esc(show.language_label)}</span>` : "";
    // With a single cinema selected, repeating its name on every chip is noise
    const venue = this._venue ? "" : `<span class="venue">${esc(show.venue.name)}</span>`;
    const inner = `<span class="time">${time}</span>${venue}${lang}`;
    const cls = `chip ${started ? "started" : ""}`;
    const href = safeUrl(show.ticketing_url);
    const titleAttr = esc([show.specials, href ? this._t.tickets : ""].filter(Boolean).join(" · "));
    return href
      ? `<a class="${cls}" href="${esc(href)}" target="_blank" rel="noopener noreferrer" title="${titleAttr}">${inner}</a>`
      : `<span class="${cls}" title="${titleAttr}">${inner}</span>`;
  }

  _filmLink(film) {
    return film.slug ? `https://cineville.de/de-DE/filme/${encodeURIComponent(film.slug)}` : "";
  }

  _renderFilms(shows, program) {
    const groups = new Map();
    for (const s of shows) {
      if (!groups.has(s.film.id)) groups.set(s.film.id, { film: s.film, shows: [] });
      groups.get(s.film.id).shows.push(s);
    }
    const highlightLabels = HIGHLIGHT_LABELS[this._lang];
    return [...groups.values()]
      .map(({ film, shows: filmShows }) => {
        const link = this._filmLink(film);
        const title = link
          ? `<a class="film-title" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(film.title)}</a>`
          : `<span class="film-title">${esc(film.title)}</span>`;
        const highlight = film.highlight ? `<span class="badge highlight">${esc(highlightLabels[film.highlight] || film.highlight)}</span>` : "";
        const specials = [...new Set(filmShows.map((s) => s.specials).filter(Boolean))];
        const state = this._filmState(film, program);
        return `<div class="film ${state.classes}" data-film="${esc(film.id)}">
          ${this._poster(film, 60, "poster")}
          <div class="film-body">
            <div class="film-head">${title}${state.badges}${highlight}</div>
            <div class="meta">${this._filmMeta(film)}</div>
            <div class="ratings">${this._ratingBadges(film)}</div>
            ${specials.length ? `<div class="specials">${specials.map((s) => `<span class="badge special">${esc(s)}</span>`).join("")}</div>` : ""}
            ${film.short_description ? `<div class="desc">${esc(film.short_description)}</div>` : ""}
            <div class="chips">${filmShows.map((s) => this._chip(s)).join("")}</div>
          </div>
        </div>`;
      })
      .join("");
  }

  _renderList(shows, program) {
    return shows
      .map((s) => {
        const started = new Date(s.start).getTime() < Date.now();
        const href = safeUrl(s.ticketing_url);
        const end = s.end ? `–${esc(this._fmtTime(s.end))}` : "";
        const row = `
          <div class="row-time"><span class="time">${esc(this._fmtTime(s.start))}</span><span class="end">${end}</span></div>
          ${this._poster(s.film, 36, "thumb")}
          <div class="row-body">
            <div class="row-title">${s.film.on_watchlist ? '<ha-icon class="wl-icon" icon="mdi:bookmark"></ha-icon>' : ""}${esc(s.film.title)}</div>
            <div class="row-sub">${esc(s.venue.name)} ${this._badges(s)}${this._ratingBadges(s.film, true)}</div>
          </div>`;
        const cls = `row ${started ? "started" : ""} ${this._filmState(s.film, program).classes}`;
        return href
          ? `<a class="${cls}" href="${esc(href)}" target="_blank" rel="noopener noreferrer" title="${esc(this._t.tickets)}">${row}</a>`
          : `<div class="${cls}">${row}</div>`;
      })
      .join("");
  }
}

const STYLES = `
  /* In a sections dashboard the grid gives the card a height: fill it and scroll the program inside.
     In masonry dashboards the height is auto unless max_height is set. */
  :host { display: block; height: 100%; }
  ha-card { overflow: hidden; height: 100%; max-height: var(--cineville-max-height, none);
            display: flex; flex-direction: column; box-sizing: border-box; }
  .header, .days, .filters { flex: none; }
  button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }
  .header { display: flex; align-items: center; justify-content: space-between; padding: 16px 16px 8px; gap: 8px; }
  .title { font-size: 1.25rem; font-weight: 500; color: var(--primary-text-color); }
  .views { display: flex; gap: 2px; background: var(--secondary-background-color); border-radius: 18px; padding: 2px; }
  .view { width: 36px; height: 32px; border-radius: 16px; color: var(--secondary-text-color); display: grid; place-items: center; }
  .view.active { background: var(--card-background-color); color: var(--primary-color); box-shadow: 0 1px 2px rgba(0,0,0,.15); }
  .view ha-icon { --mdc-icon-size: 20px; }
  .days { display: flex; gap: 6px; overflow-x: auto; padding: 4px 16px 8px; scrollbar-width: none; }
  .days::-webkit-scrollbar { display: none; }
  .day { flex: none; padding: 6px 12px; border-radius: 16px; border: 1px solid var(--divider-color);
         color: var(--primary-text-color); white-space: nowrap; font-size: .9rem; }
  .day.active { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .filters { display: flex; gap: 8px; padding: 0 16px 8px; flex-wrap: wrap; }
  select { font: inherit; font-size: .9rem; color: var(--primary-text-color); background: var(--secondary-background-color);
           border: 1px solid var(--divider-color); border-radius: 8px; padding: 6px 8px; min-width: 0; max-width: 100%; }
  .content { padding: 0 8px 12px; flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
  .state { padding: 24px 16px; text-align: center; color: var(--secondary-text-color); }
  .state.error { color: var(--error-color); }
  .retry { margin-top: 12px; padding: 6px 14px; border-radius: 16px; border: 1px solid var(--divider-color); color: var(--primary-text-color); }
  .film { display: flex; gap: 12px; padding: 10px 8px; border-top: 1px solid var(--divider-color); }
  .film:first-child { border-top: 0; }
  .poster { width: 60px; height: 90px; border-radius: 6px; object-fit: cover; flex: none; background: var(--secondary-background-color); }
  .thumb { width: 36px; height: 54px; border-radius: 4px; object-fit: cover; flex: none; background: var(--secondary-background-color); }
  .placeholder { display: grid; place-items: center; color: var(--secondary-text-color); }
  .film-body { min-width: 0; flex: 1; }
  .film-head { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
  .film-title { font-weight: 500; font-size: 1rem; color: var(--primary-text-color); text-decoration: none; }
  a.film-title:hover { text-decoration: underline; }
  .meta { font-size: .8rem; color: var(--secondary-text-color); margin-top: 2px; }
  .ratings:empty { display: none; }
  .ratings { display: flex; gap: 6px; margin-top: 4px; flex-wrap: wrap; }
  .rating { display: inline-flex; align-items: center; gap: 4px; font-size: .75rem; padding: 1px 6px; border-radius: 4px;
            text-decoration: none; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .rating.imdb { background: #f5c518; color: #000; }
  .rating.imdb b { font-weight: 800; letter-spacing: -.02em; }
  a.rating.imdb:hover { filter: brightness(.95); }
  .rating.rt { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .rating.rt.fresh { color: #fa320a; }
  .desc { font-size: .85rem; color: var(--secondary-text-color); margin-top: 4px; display: -webkit-box;
          -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .specials { margin-top: 4px; display: flex; gap: 4px; flex-wrap: wrap; }
  .badge { display: inline-block; font-size: .7rem; font-weight: 500; padding: 1px 6px; border-radius: 4px; white-space: nowrap; }
  .badge.lang { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .badge.special { background: rgba(var(--rgb-primary-color, 3, 169, 244), .15); color: var(--primary-color); }
  .badge.highlight { background: var(--accent-color, #ff9800); color: var(--text-accent-color, #fff); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .chip { display: inline-flex; align-items: baseline; gap: 6px; padding: 4px 10px; border-radius: 14px;
          background: var(--secondary-background-color); color: var(--primary-text-color); text-decoration: none; font-size: .85rem; }
  a.chip:hover { background: var(--divider-color); }
  .chip .time { font-weight: 600; font-variant-numeric: tabular-nums; }
  .chip .venue { color: var(--secondary-text-color); }
  .chip .lang { font-size: .7rem; font-weight: 500; color: var(--primary-color); }
  .started { opacity: .45; }
  .actions { display: flex; align-items: center; gap: 6px; }
  .toggle { width: 36px; height: 36px; border-radius: 18px; display: grid; place-items: center; color: var(--secondary-text-color); }
  .toggle.active { color: var(--accent-color, #ff9800); background: var(--secondary-background-color); }
  .toggle ha-icon { --mdc-icon-size: 22px; }
  .watchlisted { box-shadow: inset 3px 0 0 var(--accent-color, #ff9800); }
  .seen { opacity: .55; }
  .seen.started { opacity: .35; }
  .badge ha-icon { --mdc-icon-size: 12px; margin-right: 2px; vertical-align: -1px; }
  .badge.wl { background: rgba(255, 152, 0, .16); color: var(--accent-color, #ff9800); }
  .badge.seen-badge { background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .person { display: inline-grid; place-items: center; min-width: 14px; height: 14px; padding: 0 3px; margin-left: 2px;
            border-radius: 7px; color: #fff; font-size: .62rem; font-weight: 700; line-height: 1; box-sizing: border-box; }
  .wl-icon { --mdc-icon-size: 14px; color: var(--accent-color, #ff9800); margin-right: 4px; vertical-align: -1px; }
  .row { display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-top: 1px solid var(--divider-color);
         color: inherit; text-decoration: none; }
  .row:first-child { border-top: 0; }
  a.row:hover { background: var(--secondary-background-color); }
  .row-time { width: 56px; flex: none; font-variant-numeric: tabular-nums; display: flex; flex-direction: column; white-space: nowrap; }
  .row-time .time { font-weight: 600; color: var(--primary-text-color); }
  .row-time .end { font-size: .75rem; color: var(--secondary-text-color); }
  .row-body { min-width: 0; flex: 1; }
  .row-title { font-weight: 500; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .row-sub { font-size: .8rem; color: var(--secondary-text-color); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
`;

customElements.define("cineville-card", CinevilleCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "cineville-card",
  name: "Cineville",
  description: "Today's Cineville program, by film or as a list, with day picker and filters.",
  preview: true,
  documentationURL: "https://github.com/thorbengrosser/cineville-ha",
});

console.info(`%c CINEVILLE-CARD %c ${CARD_VERSION} `, "color:#fff;background:#4c6ef5;font-weight:700", "color:#4c6ef5");
