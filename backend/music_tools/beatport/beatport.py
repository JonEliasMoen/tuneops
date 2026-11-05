import requests
import pandas as pd
import requests_cache

# https://gist.github.com/kemo/506ca56e35b9506ee5233bc4d773c1c8
# Notice how it has pagination. I default is 25 per page. do not over request!

session = requests_cache.CachedSession('demo_cache')

body = requests.get("https://www.beatport.com/api/auth/refresh-anon-token?")
auth = body.json()["access_token"] # 600 it says in the validty time. i guess seconds ?

# Get genres
body = requests.get("https://api.beatport.com/v4/catalog/genres/?page=1&per_page=100", headers={"Authorization": "Bearer "+auth})
res = body.json()

genres = {v["name"] : v["id"] for v in res["results"]}

toGetGenre = ["Organic House", "Progressive House", "Melodic House & Techno"]
# QUERIES
def chartsResponse(query):
    body = requests.get(query, headers={"Authorization": "Bearer "+auth})
    res = body.json()
    print(res["results"][0])
    data = {
        "p" : [i for i in range(len(res["results"]))],
        "title" : [t["name"] for t in res["results"]],
        "bpm" : [t["bpm"] for t in res["results"]],
        "release_date": [t["new_release_date"] for t in res["results"]],
        "length": [t["length"] for t in res["results"]],
        "artists": [", ".join(a["name"] for a in t["artists"]) for t in res["results"]],
        "isrc" : [t["isrc"] for t in res["results"]],
        "mix" : [t["mix_name"] for t in res["results"]],
        "exclusive" : [t["exclusive"] for t in res["results"]],
        "genre" : [t["genre"]["name"] for t in res["results"]],
    }
    return pd.DataFrame.from_dict(data)
def releasesResponse(query):
    body = requests.get(query, headers={"Authorization": "Bearer "+auth})
    res = body.json()
    print(res["results"][0])
    data = {
        "p" : [i for i in range(len(res["results"]))],
        "title" : [t["name"] for t in res["results"]],
        "release_date": [t["new_release_date"] for t in res["results"]],
        "artists": [", ".join(a["name"] for a in t["artists"]) for t in res["results"]],
        "exclusive" : [t["exclusive"] for t in res["results"]],
    }
    return pd.DataFrame.from_dict(data)

# HELPERS
def search(query):
    body = requests.get(f'https://api.beatport.com/v4/catalog/search/?q={query}', headers={"Authorization": "Bearer "+auth})
    return body.json()
def searchType(type, query):
    body = requests.get(f'https://api.beatport.com/v4/catalog/search/?q={query}&type={type}', headers={"Authorization": "Bearer "+auth})
    return body.json()[type]

def findId(type, query):
    return searchType(type, query)[0]["id"]

# LIST RESPONSES
# type=genres,labels,artists,sub-genres,tracks
def getChart(type, id, n=10):
    return chartsResponse(f'https://api.beatport.com/v4/catalog/{type}/{id}/top/{n}')
def getReleases(type, id):
    return releasesResponse(f'https://api.beatport.com/v4/catalog/{type}/{id}/releases')
def getNewestTracks(type, id):
    return chartsResponse(f'https://api.beatport.com/v4/catalog/tracks/?order_by=-publish_date&{type}_id={id}')

id = findId("artists", "Nora En Pure")
print(getChart("artists", id))
print(searchType("tracks", "Sense of Comfort")[0])
"""

def getTopChartGenre(id, n=10):
    return  chartsResponse(f'https://api.beatport.com/v4/catalog/genres/{id}/top/{n}')

for k in toGetGenre:
    print(k)
    print(getTopChartGenre(genres[k]))




  
def findLabelId(label):
    body = search(label)["labels"]
    return body[0]["id"]

def getLabelChart(id, n=10):
    return chartsResponse(f'https://api.beatport.com/v4/catalog/labels/{id}/top/{n}')

def getLabelReleases(id):
    return releasesResponse(f'https://api.beatport.com/v4/catalog/labels/{id}/releases')
def getLabelTracks(id):
    return chartsResponse(f'https://api.beatport.com/v4/catalog/tracks/?order_by=-publish_date&label_id={id}')

id = findLabelId("Colorize")
print(getLabelChart(id))
print(getLabelReleases(id))
print(getLabelTracks(id))


def findArtistId(artist):
    body = search(artist)["artists"]
    return body[0]["id"]

def getLabelChart(id, n=10):
    return chartsResponse(f'https://api.beatport.com/v4/catalog/labels/{id}/top/{n}')

def getLabelReleases(id):
    return releasesResponse(f'https://api.beatport.com/v4/catalog/labels/{id}/releases')
def getLabelTracks(id):
    return chartsResponse(f'https://api.beatport.com/v4/catalog/tracks/?order_by=-publish_date&label_id={id}')

id = findArtistId("Nora En Pure")
print(getLabelChart(id))
print(getLabelReleases(id))
print(getLabelTracks(id))
"""