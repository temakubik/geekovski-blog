import json, urllib.request, urllib.parse, pathlib

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read()

def search(term):
    u = 'https://store.steampowered.com/api/storesearch/?term=' + urllib.parse.quote(term) + '&l=english&cc=us'
    d = json.loads(get(u))
    return [(i['id'], i['name']) for i in d.get('items', [])][:3]

for t in ['Death Stranding 2', 'Atomfall', 'Like a Dragon Pirate Yakuza in Hawaii',
          'Dragon Quest III HD-2D Remake', 'MotoGP 26', 'Grand Theft Auto V',
          'Red Dead Redemption 2', 'Hell Let Loose']:
    try:
        print(t, '->', search(t))
    except Exception as e:
        print(t, 'ERR', e)
