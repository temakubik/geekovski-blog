import json, urllib.request, pathlib

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
OUT = pathlib.Path('/Users/user/.hermes/profiles/geekovski/cache/scratch/steamshots')
OUT.mkdir(parents=True, exist_ok=True)

apps = {3280350: 'ds2', 801800: 'atomfall', 3061810: 'yakuza', 2701660: 'dq3',
        3875050: 'motogp26', 3240220: 'gtav', 1174180: 'rdr2'}

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read()

for appid, slug in apps.items():
    try:
        d = json.loads(get('https://store.steampowered.com/api/appdetails?appids=%d&l=english&cc=us' % appid))
        data = d[str(appid)]['data']
        shots = [s['path_full'] for s in data.get('screenshots', [])][:4]
        print(slug, data['name'], len(shots))
        for i, u in enumerate(shots):
            fn = OUT / ('%s-%d.jpg' % (slug, i))
            fn.write_bytes(get(u))
        # header image as extra option
        hn = OUT / ('%s-header.jpg' % slug)
        hn.write_bytes(get(data['header_image']))
    except Exception as e:
        print(slug, 'ERR', e)
print('done')
