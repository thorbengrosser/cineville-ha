/**
 * Cineville card for Home Assistant.
 *
 * Shows a day's program from the Cineville integration (service cineville.get_program),
 * either grouped by film or as a chronological list, with a day picker and cinema / time filters.
 * Dependency-free web component; served and registered by the integration itself.
 */

const CARD_VERSION = "0.1.1";
const REFRESH_MS = 10 * 60 * 1000;
const VIEW_STORAGE_KEY = "cineville-card-view";

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
    editor: {
      title: "Title",
      config_entry_id: "City (only needed if you set up several)",
      view: "Default view",
      days: "Days in the day picker",
      show_past: "Show screenings that have already started",
      max_height: "Maximum height (e.g. 500px; only for dashboards without a grid)",
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
    editor: {
      title: "Titel",
      config_entry_id: "Stadt (nur nötig bei mehreren Städten)",
      view: "Standardansicht",
      days: "Tage in der Tagesauswahl",
      show_past: "Bereits begonnene Vorstellungen anzeigen",
      max_height: "Maximale Höhe (z. B. 500px; nur für Dashboards ohne Raster)",
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
      ],
      computeLabel: (schema) => t[schema.name] || schema.name,
    };
  }

  setConfig(config) {
    this._config = { view: "films", days: 7, show_past: false, ...config };
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
  }

  _fmtTime(iso, tz) {
    return new Intl.DateTimeFormat(this._lang, { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(iso));
  }

  _hourInTz(iso, tz) {
    const parts = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz }).formatToParts(new Date(iso));
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
    return new Intl.DateTimeFormat(this._lang, { weekday: "short", day: "numeric", month: "numeric", timeZone: "UTC" }).format(
      new Date(Date.UTC(y, m - 1, d))
    );
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
      this._programs[day] = program;
      // The server knows the real Cineville "today"; realign if we guessed differently
      if (program.today && this._day === day && day !== program.day) this._day = program.day;
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
    return program.showtimes.filter((s) => {
      if (this._venue && s.venue.id !== this._venue) return false;
      if (from === "now" && !this._config.show_past && new Date(s.start).getTime() < now) return false;
      if (from && from !== "now" && this._hourInTz(s.start, program.timezone) < Number(from)) return false;
      return true;
    });
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
    } else if (action === "retry") {
      this._fetch(this._day);
    }
    this._render();
  }

  _onChange(ev) {
    const el = ev.target;
    if (el.dataset.filter === "venue") this._venue = el.value;
    if (el.dataset.filter === "from") this._from = el.value;
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
    const contentKey = [this._day, this._view, this._venue, this._from].join("|");
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
      if (!shows.length) body = `<div class="state">${esc(t.empty)}</div>`;
      else body = this._view === "list" ? this._renderList(shows, program) : this._renderFilms(shows, program);
    }

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <div class="title">${esc(title)}</div>
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
      ...FROM_HOURS.map((h) => [String(h), `${t.from} ${String(h).padStart(2, "0")}:00`]),
    ];
    return `<div class="filters">
      <select data-filter="venue" aria-label="${esc(t.allCinemas)}">
        <option value="">${esc(t.allCinemas)}</option>
        ${sortedVenues.map(([id, name]) => `<option value="${esc(id)}" ${id === this._venue ? "selected" : ""}>${esc(name)}</option>`).join("")}
      </select>
      <select data-filter="from" aria-label="${esc(t.from)}">
        ${fromOptions.map(([v, label]) => `<option value="${v}" ${v === from ? "selected" : ""}>${esc(label)}</option>`).join("")}
      </select>
    </div>`;
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

  _chip(show, tz) {
    const time = esc(this._fmtTime(show.start, tz));
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
        return `<div class="film" data-film="${esc(film.id)}">
          ${this._poster(film, 60, "poster")}
          <div class="film-body">
            <div class="film-head">${title}${highlight}</div>
            <div class="meta">${this._filmMeta(film)}</div>
            <div class="ratings" data-ratings="${esc(film.id)}"></div>
            ${specials.length ? `<div class="specials">${specials.map((s) => `<span class="badge special">${esc(s)}</span>`).join("")}</div>` : ""}
            ${film.short_description ? `<div class="desc">${esc(film.short_description)}</div>` : ""}
            <div class="chips">${filmShows.map((s) => this._chip(s, program.timezone)).join("")}</div>
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
        const end = s.end ? `–${esc(this._fmtTime(s.end, program.timezone))}` : "";
        const row = `
          <div class="row-time"><span class="time">${esc(this._fmtTime(s.start, program.timezone))}</span><span class="end">${end}</span></div>
          ${this._poster(s.film, 36, "thumb")}
          <div class="row-body">
            <div class="row-title">${esc(s.film.title)}</div>
            <div class="row-sub">${esc(s.venue.name)} ${this._badges(s)}</div>
          </div>`;
        const cls = `row ${started ? "started" : ""}`;
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
  .ratings { display: flex; gap: 6px; margin-top: 4px; }
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
