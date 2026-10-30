"""Prepara perfiles locales para una URL Render sin publicar las claves."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from bridge import validate_url
from server import load_rooms


def configure(url, root, room='PRUEBA01'):
    p = urlsplit(url.strip())
    if p.scheme == 'https' and p.path in ('', '/'):
        url = urlunsplit(('wss', p.netloc, '/relay', p.query, p.fragment))
    url = validate_url(url)
    rooms = load_rooms(root / 'data/rooms.json')
    if room not in rooms:
        raise ValueError('La sala no existe en el archivo local')
    (root / 'data/render-url.txt').write_text(url + '\n', encoding='ascii')
    for role in ('player', 'coach'):
        profile = root / 'data/render-profiles' / room / role / 'Mods/torneo_relay.cfg'
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(
            f'ip=127.0.0.1\nport=27017\nroom={room}\nrole={role}\ntoken={rooms[room][role]}\n',
            encoding='ascii',
        )
    return url


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--room', default='PRUEBA01')
    args = parser.parse_args()
    configure(args.url, Path(__file__).resolve().parent, args.room)
    print('URL guardada. Perfiles privados en data/render-profiles.')
