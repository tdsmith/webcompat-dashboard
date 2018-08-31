import json
import xml.etree.ElementTree as ET

flags = {
    "china": "🇨🇳",
    "france": "🇫🇷",
    "germany": "🇩🇪",
    "global": "🌎",
    "usa": "🇺🇸",
    "russia": "🇷🇺",
}

internet_users = {
    "global": 3000,
    "china": 721,
    "usa": 287,
    "russia": 102,
    "france": 56,
    "germany": 71,

}

NS = {"ats": "http://ats.amazonaws.com/doc/2005-07-11"}

ranks = {}

for country in flags:
    tree = ET.parse(f"{country}.xml")
    sites = tree.findall(".//ats:TopSites/ats:Country/ats:Sites/*", NS)
    for site in sites:
        domain = site.find("ats:DataUrl", NS).text
        rank = site.find("ats:Country/ats:Rank", NS).text
        reach = site.find("ats:Country/ats:Reach/ats:PerMillion", NS).text
        ranks.setdefault(domain, {})[country] = (int(rank), float(reach)*internet_users[country])

condensed = {}
for domain in ranks:
    highest = sorted(ranks[domain].items(), key=lambda x: x[1][1], reverse=True)[0]
    condensed[domain] = "{} #{}".format(flags[highest[0]], highest[1][0])

print(json.dumps(condensed))
