<?php

// Cineville moved from cineville.de/api/graphql to a REST API (CultureKit) in 2026.
const CINEVILLE_API = 'https://api.cineville.de';
const CINEVILLE_VENUE_IDS = [
    '800f1df6-26e9-43b9-9995-8fc48f71cdf1', // 3001 Kino
    'c9737ff8-be52-4f9b-a183-5eb8794e9944', // Abaton-Kino
    '7978be1e-4989-4f84-9e2a-69ec059a05d0', // B-Movie
    'db1fee7e-3f5d-4f2b-9c4e-9bcd5db83867', // Metropolis Kino Hamburg
    '88beb28b-cec3-43f8-b1f2-eeb7d58c1a6b', // Studio Kino
    '6da13ac1-5b70-40db-b917-ed61202a9960', // zeise kinos
];

function postJson($url, $body) {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:138.0) Gecko/20100101 Firefox/138.0',
        'Accept: application/json',
        'Content-Type: application/json',
        'Origin: https://cineville.de',
        'Referer: https://cineville.de/'
    ]);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body));
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 20);

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);

    if ($response === false || $httpCode !== 200) {
        error_log("cinevillepreview: request to $url failed (HTTP $httpCode) $error");
        return null;
    }

    $data = json_decode($response, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        error_log('cinevillepreview: invalid JSON from API');
        return null;
    }
    return $data;
}

/**
 * Returns the list of raw event objects (with embedded production + venue),
 * or null if the API could not be reached.
 */
function fetchCinevilleData() {
    // Get current time in Hamburg timezone, then convert to UTC
    $hamburgTime = new DateTime('now', new DateTimeZone('Europe/Berlin'));

    // Convert to UTC for API
    $currentTimeUTC = clone $hamburgTime;
    $currentTimeUTC->setTimezone(new DateTimeZone('UTC'));
    $startTimeStr = $currentTimeUTC->format('Y-m-d\TH:i:s.000\Z');

    // End time is 2am next day in Hamburg time, converted to UTC
    $endTimeHamburg = (clone $hamburgTime)->setTime(2, 0, 0)->modify('+1 day');
    $endTimeUTC = clone $endTimeHamburg;
    $endTimeUTC->setTimezone(new DateTimeZone('UTC'));
    $endTimeStr = $endTimeUTC->format('Y-m-d\TH:i:s.000\Z');

    $body = [
        'productionId' => ['isNull' => false],
        'startDate' => [
            'gte' => $startTimeStr,
            'lt' => $endTimeStr
        ],
        'venueId' => ['in' => CINEVILLE_VENUE_IDS],
        'isHidden' => ['eq' => false],
        'embed' => ['production' => true, 'venue' => true],
        'sort' => ['startDate' => 'asc'],
        'page' => ['limit' => 100]
    ];

    // Follow the cursor pagination (POSTing the same body to the "next" link)
    $events = [];
    $url = CINEVILLE_API . '/events/search';
    for ($i = 0; $i < 10 && $url; $i++) {
        $data = postJson($url, $body);
        if ($data === null) {
            return $i === 0 ? null : $events;
        }
        foreach ($data['_embedded']['events'] ?? [] as $event) {
            $events[] = $event;
        }
        $next = $data['_links']['next']['href'] ?? null;
        $url = $next ? CINEVILLE_API . $next : null;
    }
    return $events;
}

// Mirrors the label logic of cineville.de for country DE
function languageLabel($languageVersion, $subtitles) {
    $subtitles = $subtitles ?? [];
    if ($languageVersion === 'original') {
        if (empty($subtitles)) {
            return 'OV';
        }
        foreach ($subtitles as $sub) {
            if (strpos($sub, 'en') !== false) {
                return 'OmeU';
            }
        }
        return 'OmU';
    }
    if (is_string($languageVersion) && strpos($languageVersion, 'de') !== false) {
        return 'DF';
    }
    return '';
}

function truncateText($text, $length = 120) {
    if (strlen($text) <= $length) {
        return $text;
    }
    return substr($text, 0, $length) . '...';
}

function parseShowtimes($events) {
    if (empty($events)) {
        return [];
    }

    // Get current time in Hamburg timezone for filtering
    $currentHamburgTime = new DateTime('now', new DateTimeZone('Europe/Berlin'));

    $futureShowtimes = [];
    $uniqueShowtimes = []; // Track unique combinations to avoid duplicates

    foreach ($events as $event) {
        $film = $event['_embedded']['production'] ?? null;
        $venue = $event['_embedded']['venue'] ?? null;
        if (!$film || !$venue || empty($event['startDate'])) {
            continue;
        }

        // Dates come in UTC from the API; convert to Hamburg timezone for display
        $startTime = new DateTime($event['startDate'], new DateTimeZone('UTC'));
        $startTime->setTimezone(new DateTimeZone('Europe/Berlin'));

        // Skip movies that have already started
        if ($startTime < $currentHamburgTime) {
            continue;
        }

        // endDate is sometimes null; fall back to the film duration
        $endTime = null;
        if (!empty($event['endDate'])) {
            $endTime = new DateTime($event['endDate'], new DateTimeZone('UTC'));
            $endTime->setTimezone(new DateTimeZone('Europe/Berlin'));
        } elseif (!empty($film['attributes']['duration'])) {
            $endTime = (clone $startTime)->modify('+' . (int)$film['attributes']['duration'] . ' minutes');
        }

        // Create unique key to avoid duplicates (same movie, time, theater)
        $uniqueKey = $film['title'] . '|' . $startTime->format('Y-m-d H:i') . '|' . $venue['name'];

        // Skip if we already have this exact showtime
        if (isset($uniqueShowtimes[$uniqueKey])) {
            continue;
        }

        $uniqueShowtimes[$uniqueKey] = true;

        $attributes = $event['attributes'] ?? [];
        $futureShowtimes[] = [
            'title' => $film['title'],
            'poster_url' => $film['assets']['poster']['url'] ?? '',
            'poster_alt' => $film['title'],
            'start_time' => $startTime,
            'end_time' => $endTime,
            'theater' => $venue['name'],
            'language' => languageLabel($attributes['languageVersion'] ?? null, $attributes['subtitles'] ?? []),
            'description' => $film['localizableAttributes']['shortDescription'] ?? ''
        ];
    }

    // Sort by start time
    usort($futureShowtimes, function($a, $b) {
        return $a['start_time'] <=> $b['start_time'];
    });

    // Limit to 50 items
    return array_slice($futureShowtimes, 0, 50);
}

// Get current Hamburg time
$hamburgTime = new DateTime('now', new DateTimeZone('Europe/Berlin'));

// Fetch data from Cineville API
$events = fetchCinevilleData();
$fetchFailed = $events === null;
$showtimes = parseShowtimes($events);

// If no showtimes, show a message
$hasShowtimes = !empty($showtimes);

?>
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="900">
    <title>Heute bei Cineville</title>
    <style>
        /* CSS Reset and Base */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        html, body {
            height: 100%;
            overflow-y: auto;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #1e1e2e;
            color: #eee;
            padding: 12px;
            line-height: 1.4;
        }
        
        /* Header */
        .header {
            margin-bottom: 12px;
        }
        
        .header h1 {
            font-size: 1.4rem;
            font-weight: 600;
            color: #eee;
            margin-bottom: 4px;
        }
        
        .header .meta-info {
            font-size: 0.85rem;
            color: #888;
        }
        
        /* Grid Layout */
        .grid {
            display: grid;
            grid-template-columns: 1fr;
            grid-gap: 12px;
            margin-top: 12px;
        }
        
        @media (min-width: 900px) {
            .grid {
                grid-template-columns: 1fr 1fr;
            }
        }
        
        /* Card Design */
        .card {
            background: #27293d;
            border-radius: 4px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.4);
            padding: 8px;
            display: flex;
            align-items: flex-start;
            transition: transform 0.2s ease;
        }
        
        .card:hover {
            transform: translateY(-1px);
            box-shadow: 0 2px 6px rgba(0,0,0,0.5);
        }
        
        /* Poster */
        .poster {
            width: 50px;
            height: 75px;
            object-fit: cover;
            border-radius: 3px;
            flex-shrink: 0;
            background: #1e1e2e;
        }
        
        /* Details */
        .details {
            flex: 1;
            margin-left: 8px;
            min-width: 0; /* Allow text truncation */
        }
        
        .details h2 {
            font-size: 1rem;
            font-weight: 500;
            color: #fff;
            margin-bottom: 4px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        /* Meta Badges */
        .meta {
            margin-bottom: 4px;
        }
        
        .badge {
            display: inline-block;
            font-size: 0.7rem;
            font-weight: 500;
            padding: 1px 4px;
            border-radius: 4px;
            margin-right: 4px;
        }
        
        .badge.time {
            background: #444;
            color: #eee;
        }
        
        .badge.lang {
            background: #ffcc00;
            color: #111;
            text-transform: uppercase;
        }
        
        /* Theater Info */
        .theater {
            font-size: 0.8rem;
            color: #ccc;
            margin-bottom: 4px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        /* Description */
        .description {
            font-size: 0.8rem;
            color: #bbb;
            line-height: 1.2;
            display: -webkit-box;
            -webkit-line-clamp: 1;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #888;
        }
        
        .empty-state p {
            font-size: 1rem;
            margin-bottom: 8px;
        }
        
        .empty-state .emoji {
            font-size: 2rem;
            margin-bottom: 12px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Heute bei Cineville</h1>
    </div>
    
    <?php if ($hasShowtimes): ?>
        <div class="grid">
            <?php foreach ($showtimes as $showtime): ?>
                <div class="card">
                    <?php if (!empty($showtime['poster_url'])): ?>
                        <img 
                            src="<?= htmlspecialchars($showtime['poster_url']) ?>" 
                            alt="Poster: <?= htmlspecialchars($showtime['poster_alt']) ?>"
                            class="poster"
                            loading="lazy"
                        >
                    <?php else: ?>
                        <div class="poster"></div>
                    <?php endif; ?>
                    
                    <div class="details">
                        <h2><?= htmlspecialchars($showtime['title']) ?></h2>
                        <div class="meta">
                            <?php if ($showtime['end_time']): ?>
                                <span class="badge time" aria-label="Showtime: <?= $showtime['start_time']->format('H:i') ?> to <?= $showtime['end_time']->format('H:i') ?>">
                                    <?= $showtime['start_time']->format('H:i') ?>&ndash;<?= $showtime['end_time']->format('H:i') ?>
                                </span>
                            <?php else: ?>
                                <span class="badge time" aria-label="Showtime: <?= $showtime['start_time']->format('H:i') ?>">
                                    <?= $showtime['start_time']->format('H:i') ?>
                                </span>
                            <?php endif; ?>
                            <?php if ($showtime['language'] !== ''): ?>
                                <span class="badge lang" aria-label="Language: <?= htmlspecialchars($showtime['language']) ?>">
                                    <?= htmlspecialchars($showtime['language']) ?>
                                </span>
                            <?php endif; ?>
                        </div>
                        <div class="theater">🎬 <?= htmlspecialchars($showtime['theater']) ?></div>
                        <?php if (!empty($showtime['description'])): ?>
                            <p class="description"><?= htmlspecialchars(truncateText($showtime['description'], 120)) ?></p>
                        <?php endif; ?>
                    </div>
                </div>
            <?php endforeach; ?>
        </div>
    <?php else: ?>
        <div class="empty-state">
            <div class="emoji">🎬</div>
            <?php if ($fetchFailed): ?>
                <p>Cineville-Programm konnte nicht geladen werden.</p>
                <p>Die API ist gerade nicht erreichbar oder hat sich geändert.</p>
            <?php else: ?>
                <p>Keine Filme für heute gefunden.</p>
                <p>Schau morgen wieder vorbei!</p>
            <?php endif; ?>
        </div>
    <?php endif; ?>
</body>
</html>
