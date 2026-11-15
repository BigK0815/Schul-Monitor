"""Calendar feed and fullscreen display for the staff room."""
from datetime import date, datetime, time, timedelta
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

from flask import jsonify, render_template
from icalendar import Calendar
import recurring_ical_events
import requests

from monitorprofile import monitor_colors

BERLIN = ZoneInfo('Europe/Berlin')
REFRESH_SECONDS = 300
MAX_FEED = 4 * 1024 * 1024
feeds = {}
feed_lock = Lock()


def load_calendar(url):
    with feed_lock:
        now = monotonic()
        previous, calendar, stale = feeds.get(url, (float('-inf'), None, False))
        if now - previous < (60 if stale else REFRESH_SECONDS):
            return calendar, stale
        try:
            with requests.get(url, timeout=(4, 8), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError('Kalenderabruf fehlgeschlagen.')
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > MAX_FEED or monotonic() - now > 15:
                        raise ValueError('Kalendergrenze überschritten.')
            calendar = Calendar.from_ical(bytes(body))
            stale = False
        except (requests.RequestException, ValueError):
            stale = True
        feeds[url] = (monotonic(), calendar, stale)
        return calendar, stale


def local_datetime(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(BERLIN)
    if isinstance(value, datetime):
        return value.replace(tzinfo=BERLIN)
    return datetime.combine(value, time.min, BERLIN)


def date_label(value):
    weekdays = ('Mo.', 'Di.', 'Mi.', 'Do.', 'Fr.', 'Sa.', 'So.')
    return f'{weekdays[value.weekday()]}, {value:%d.%m.}'


def event_label(start, end, monday):
    if not isinstance(start, datetime):
        last = max(start, end - timedelta(days=1))
        if start < monday:
            return f'Läuft bis {date_label(last)} · ganztägig'
        period = date_label(start) if last == start else f'{date_label(start)} bis {date_label(last)}'
        return f'{period} · ganztägig'
    if start.date() < monday and end.date() > start.date():
        return f'Läuft bis {date_label(end)}, {end:%H:%M}'
    if start.date() != end.date():
        return f'{date_label(start)}, {start:%H:%M} bis {date_label(end)}, {end:%H:%M}'
    times = f'{start:%H:%M}–{end:%H:%M}' if end > start else f'{start:%H:%M}'
    return f'{date_label(start)} · {times}'


def upcoming(calendar, weeks, now):
    monday = now.date() - timedelta(days=now.weekday())
    limit = monday + timedelta(weeks=weeks + 1)
    groups = [[] for _ in range(weeks + 1)]
    events = []
    for event in recurring_ical_events.of(calendar, skip_bad_series=True).between(
            local_datetime(monday), local_datetime(limit)):
        if str(event.get('STATUS', '')).upper() == 'CANCELLED' or 'DTSTART' not in event:
            continue
        start = event.decoded('DTSTART')
        end = event.decoded('DTEND', None)
        all_day = isinstance(start, date) and not isinstance(start, datetime)
        if end is None:
            end = start + event.decoded('DURATION', timedelta(days=1 if all_day else 0))
        first, last = local_datetime(start), local_datetime(end)
        if (max(first, last) < now or (first < last and last <= now)
                or first.date() >= limit):
            continue
        events.append((first, str(event.get('SUMMARY') or 'Termin'),
                       event_label(start if all_day else first, end if all_day else last, monday)))
    for first, title, label in sorted(events):
        week = max(0, (first.date() - monday).days // 7)
        groups[week].append({'title': title, 'when': label})
    result = []
    for week, entries in enumerate(groups):
        if not entries:
            continue
        first = monday + timedelta(weeks=week)
        last = first + timedelta(days=6)
        name = ('Diese Woche', 'Nächste Woche')[week] if week < 2 else 'Kalenderwoche ' + str(first.isocalendar().week)
        result.append({'title': f'{name} · {first:%d.%m.}–{last:%d.%m.}', 'entries': entries})
    return result


def calendar_response(settings):
    calendar, stale = load_calendar(settings['teacher_calendar'])
    try:
        groups = upcoming(calendar, int(settings['calendar_weeks']), datetime.now(BERLIN)) if calendar else []
    except (ValueError, TypeError, KeyError, OverflowError):
        groups, stale = [], True
    return jsonify(groups=groups, stale=stale), 200, {'Cache-Control': 'no-store'}


def teacher_board(settings):
    return render_template('lehrerzimmer.html', profile=settings['name'], school=settings['school_name'],
                           colors=monitor_colors(settings), today=settings['teacher_today'],
                           tomorrow=settings['teacher_tomorrow'], size=settings['calendar_size'],
                           mode=settings['calendar_mode'], wait=int(settings['calendar_wait']),
                           speed={'Langsam': 12, 'Mittel': 25, 'Schnell': 45}[settings['calendar_speed']]), 200, {
                               'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                               'Content-Security-Policy': ('frame-src https://plan.schule https://www.plan.schule '
                                                           'https://beste.schule https://www.beste.schule; '
                                                           "frame-ancestors 'none'") }
