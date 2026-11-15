"""Stable monitor identities and profile settings."""
from pathlib import Path
import re
from ipaddress import IPv4Address
from urllib.parse import urlsplit

FIELDS = (
    ('port', 'Port', 5001, 1024, 65535),
    ('board_width', 'Breite (Pixel)', 1920, 320, 16384),
    ('board_height', 'Höhe (Pixel)', 1080, 240, 16384),
    ('info_width', 'Infobreite (%)', 33, 10, 60),
    ('display_rows', 'Jahrgänge nebeneinander', 2, 1, 3),
    ('start_grade', 'Start-Jahrgang', 5, 1, 13),
    ('switch_seconds', 'Jahrgangswechsel (Sek.)', 15, 0, 3600),
    ('course_seconds', 'Kurswechsel (Sek.)', 4, 1, 3600),
    ('pdf_seconds', 'Aushangwechsel (Sek.)', 12, 2, 3600),
    ('cutoff_hour', 'Frühester Tageswechsel (Uhr)', 15, 0, 23),
)


TEACHER_FIELDS = (
    ('teacher_today', 'Vertretungsplan Heute', '', ()),
    ('teacher_tomorrow', 'Vertretungsplan Morgen', '', ()),
    ('teacher_calendar', 'OPAL-Kalenderadresse', '', ()),
    ('teacher_client', 'IP-Adresse des Lehrerzimmer-PCs', '', ()),
    ('calendar_weeks', 'Kommende Wochen zusätzlich', '1', ('1', '2', '3', '4')),
    ('calendar_mode', 'Anzeige bei Platzmangel', 'Blättern', ('Blättern', 'Scrollen', 'Statisch')),
    ('calendar_wait', 'Wartezeit pro Seite (Sek.)', '15', ()),
    ('calendar_speed', 'Scrolltempo', 'Langsam', ('Langsam', 'Mittel', 'Schnell')),
    ('calendar_size', 'Größe der Termineinträge', 'Mittel', ('Klein', 'Mittel', 'Groß')),
)


def validate_teacher_profile(profile):
    for key, label, default, choices in TEACHER_FIELDS:
        value = str(profile.get(key, default)).strip()
        if choices and value not in choices:
            raise ValueError(f'Ungültige Einstellung: {label}.')
        profile[key] = value
    if not profile.get('teacher_mode'):
        return
    for key in ('teacher_today', 'teacher_tomorrow', 'teacher_calendar'):
        url = urlsplit(profile[key])
        calendar = key == 'teacher_calendar'
        domains = {'www.opal-schule.de', 'opal-schule.de'} if calendar else {
            'plan.schule', 'www.plan.schule', 'beste.schule', 'www.beste.schule'}
        if (url.scheme != 'https' or not url.hostname or url.port not in (None, 443)
                or url.username or url.password or url.fragment
                or any(c.isspace() or c == chr(92) for c in profile[key])
                or url.hostname not in domains
                or (calendar and not (url.path.startswith('/olat/ical/') and url.path.endswith('.ics')))):
            raise ValueError(f'Bitte einen gültigen HTTPS-Link für {key.removeprefix("teacher_")} eingeben.')
    if profile['teacher_client']:
        profile['teacher_client'] = str(IPv4Address(profile['teacher_client']))
    if not 1 <= int(profile['calendar_wait']) <= 3600:
        raise ValueError('Die Wartezeit muss zwischen 1 und 3600 Sekunden liegen.')


DEFAULT_COLORS = {
    'title_bg': '#073c60', 'title_fg': '#ffffff',
    'class_bg': '#103d61', 'class_fg': '#ffffff',
    'day_bg': '#103d61', 'day_fg': '#ffffff',
    'changed': '#ffedbf', 'coupled': '#cdebf8', 'current': '#79e64e',
}


def monitor_colors(profile):
    stored = profile.get('colors')
    if not isinstance(stored, dict):
        return DEFAULT_COLORS.copy()
    colors = DEFAULT_COLORS.copy()
    for key in colors:
        value = stored.get(key)
        if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            colors[key] = value.lower()
    return colors


def default_profile(number):
    return {**{key: default for key, _, default, _, _ in FIELDS},
            'id': number, 'name': f'Monitor {number}', 'port': 5000 + number,
            'visible_periods': list(range(1, 9)), 'hidden_grades': [], 'pdf_folder': '',
            'hide_info': False, 'teacher_mode': False,
            **{key: default for key, _, default, _ in TEACHER_FIELDS}}


def load_profiles(config):
    if 'monitors' in config:
        return config['monitors']
    profile = default_profile(1)
    for key in profile.keys() - {'id', 'name'}:
        if key in config:
            profile[key] = config[key]
    return [profile]


def validate_profiles(profiles, editor_port=None):
    if not 1 <= len(profiles) <= 10:
        raise ValueError('Bitte 1 bis 10 Monitore auswählen.')
    ports = {editor_port} if editor_port is not None else set()
    names = set()
    for item in profiles:
        name = item['name'].strip()
        if not name or name.casefold() in names:
            raise ValueError('Jeder Monitor benötigt einen eindeutigen Namen.')
        names.add(name.casefold())
        item['name'] = name
        for key, label, _, lower, upper in FIELDS:
            value = int(item[key])
            if not lower <= value <= upper:
                raise ValueError(f'{name}: {label} muss zwischen {lower} und {upper} liegen.')
            item[key] = value
        if item['port'] in ports:
            raise ValueError(f"{name}: Port {item['port']} ist bereits vergeben.")
        ports.add(item['port'])
        validate_teacher_profile(item)
        if not item.get('teacher_mode') and not item['visible_periods']:
            raise ValueError(f'{name}: Bitte mindestens eine Stunde auswählen.')
        folder = item['pdf_folder'].strip()
        item['pdf_folder'] = str(Path(folder).expanduser().resolve()) if folder else ''
