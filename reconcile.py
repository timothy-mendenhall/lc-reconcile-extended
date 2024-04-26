"""
An OpenRefine reconciliation service for the id.loc.gov LCNAF/LCSH suggest API.
"""
from flask import Flask, request, jsonify
from fuzzywuzzy import fuzz
import getopt
import json
from operator import itemgetter
import rdflib
from rdflib.namespace import SKOS
import requests
from sys import version_info
import urllib
import xml.etree.ElementTree as ET
# Help text processing
import text

app = Flask(__name__)

# See if Python 3 for unicode/str use decisions
PY3 = version_info > (3,)

# If it's installed, use the requests_cache library to
# cache calls to the FAST API.
try:
    import requests_cache
    requests_cache.install_cache('lc_cache')
except ImportError:
    app.logger.debug("No request cache found.")
    pass

# Map the LoC query indexes to service types
default_query = {
    "id": "LoC",
    "name": "LCNAF & LCSH",
    "index": "/authorities"
}

refine_to_lc = [
    {
        "id": "Names",
        "name": "Library of Congress Name Authority File",
        "index": "/authorities/names",
        "member": "http://id.loc.gov/authorities/names/collection_NamesAuthorizedHeadings",
        "type": ""
    },
    {
        "id": "Names--Personal",
        "name": "Library of Congress Name Authority File--Personal names only",
        "index": "/authorities/names",
        "member": "http://id.loc.gov/authorities/names/collection_NamesAuthorizedHeadings",
        "type": "rdftype:PersonalName"
    },
    {
        "id": "Names--Corporate",
        "name": "Library of Congress Name Authority File--Corporate names only",
        "index": "/authorities/names",
        "member": "http://id.loc.gov/authorities/names/collection_NamesAuthorizedHeadings",
        "type": "rdftype:CorporateName"
    },
    {
        "id": "Names--Conference",
        "name": "Library of Congress Name Authority File--Conference names only",
        "index": "/authorities/names",
        "member": "http://id.loc.gov/authorities/names/collection_NamesAuthorizedHeadings",
        "type": "rdftype:ConferenceName"
    },
    {
        "id": "Names--Geographic",
        "name": "Library of Congress Name Authority File--Geographic names only",
        "index": "/authorities/names",
        "member": "http://id.loc.gov/authorities/names/collection_NamesAuthorizedHeadings",
        "type": "rdftype:Geographic"
    },
    {
        "id": "Names--Titles",
        "name": "Library of Congress Name Authority File--Titles only",
        "index": "/authorities/names",
        "member": "http://id.loc.gov/authorities/names/collection_NamesAuthorizedHeadings",
        "type": "rdftype:Title"
    },
    {
        "id": "Names--Name-Titles",
        "name": "Library of Congress Name Authority File--Name-Titles only",
        "index": "/authorities/names",
        "member": "http://id.loc.gov/authorities/names/collection_NamesAuthorizedHeadings",
        "type": "rdftype:NameTitle"
    },
    {
        "id": "Subjects",
        "name": "Library of Congress Subject Headings",
        "index": "/authorities/subjects",
        "member": "http://id.loc.gov/authorities/subjects/collection_LCSHAuthorizedHeadings",
        "type": ""
    },
    {
        "id": "LCGFT",
        "name": "Library of Congress Genre/Form Terms",
        "index": "/authorities/genreForms",
        "member": "",
        "type": ""
    },
    {
        "id": "TGM",
        "name": "Thesaurus for Graphic Materials",
        "index": "/vocabulary/graphicMaterials",
        "member": "",
        "type": ""
    },
    {
        "id": "RBMSCV",
        "name": "RBMS Controlled Vocabulary for Rare Materials Cataloging",
        "index": "/vocabulary/rbmscv",
        "member": "",
        "type": ""
    },
    {
        "id": "LCDGT",
        "name": "Library of Congress Demographic Group Terms",
        "index": "/authorities/demographicTerms",
        "member": "",
        "type": ""
    },
    {
        "id": "MARCLang",
        "name": "MARC Languages",
        "index": "/vocabulary/languages",
        "member": "",
        "type": ""
    },
    {
        "id": "ISO639-2Lang",
        "name": "ISO 639-2 Languages",
        "index": "/vocabulary/iso639-2",
        "member": "",
        "type": ""
    },
    {
        "id": "Relators",
        "name": "MARC relators",
        "index": "/vocabulary/relators",
        "member": "",
        "type": ""
    },
    {
        "id": "RBMS-Relators",
        "name": "Rare Books and Manuscripts Relationship Designators",
        "index": "/vocabulary/rbmsrel",
        "member": "",
        "type": ""
    },
    {
        "id": "LCMPT",
        "name": "Library of Congress Medium of Performance Thesaurus for Music",
        "index": "/authorities/performanceMediums",
        "member": "",
        "type": ""
    }
]
refine_to_lc.append(default_query)

# Make a copy of the LC mappings.
query_types = [{'id': item['id'], 'name': item['name']} for item in refine_to_lc]

# Basic service metadata.
metadata = {
    "name": "LoC Reconciliation Service",
    "defaultTypes": query_types,
    "identifierSpace" : "http://localhost/identifier",
    "schemaSpace" : "http://localhost/schema",
    "view": {
        "url": "{{id}}"
    },
}


def jsonpify(obj):
    """
    Helper to support JSONP
    """
    try:
        callback = request.args['callback']
        response = app.make_response("%s(%s)" % (callback, json.dumps(obj)))
        response.mimetype = "text/javascript"
        return response
    except KeyError:
        return jsonify(obj)


def search(raw_query, query_type='/lc'):
    out = []
    query = text.normalize(raw_query, PY3).strip()
    query_type_meta = [i for i in refine_to_lc if i['id'] == query_type]
    if query_type_meta == []:
        query_type_meta = default_query
    query_index = query_type_meta[0]['index']
    query_member = query_type_meta[0]['member']
    query_class = query_type_meta[0]['type']
    # Get the results for the primary Suggest API (primary headings, no cross-refs)
    # try:
    #    url = "http://id.loc.gov" + query_index + '/suggest/?q=' + urllib.parse.quote(query.encode('utf8'))
    #    app.logger.debug("LC Authorities API url is " + url)
    #    resp = requests.get(url)
    #    results = resp.json()
    # except getopt.GetoptError as e:
    #    app.logger.warning(e)
    #    return out
    # for n in range(0, len(results[1])):
    #    match = False
    #    name = results[1][n]
    #    uri = results[3][n]
    #    score = fuzz.token_sort_ratio(query, name)
    #    if score > 95:
    #        match = True
    #    app.logger.debug("Label is " + name + " Score is " + str(score) + " URI is " + uri)
    #    resource = {
    #        "id": uri,
    #        "name": name,
    #        "score": score,
    #        "match": match,
    #        "type": query_type_meta
    #    }
    #    out.append(resource)
    
    # Get the results for the Suggest2 API (searches authorized headings AND variant headings)
    try:
        if query_member == "":
            url = "http://id.loc.gov" + query_index + '/suggest2?q=' + urllib.parse.quote(query.encode('utf8'))
        else:
            url = "http://id.loc.gov" + query_index + '/suggest2?q=' + urllib.parse.quote(query.encode('utf8')) + '&q=memberOf:' + query_member
        app.logger.debug("LC Authorities API url is " + url)
        resp = requests.get(url)
        results = resp.json()
        hits = results['hits']
    except getopt.GetoptError as e:
        app.logger.warning(e)
        return out
    for n in hits:
        match = False
        name = n.get('aLabel')
        uri = n.get('uri')
        score = fuzz.token_sort_ratio(query, name)
        if score > 95:
            match = True
        app.logger.debug("Label is " + name + " Score is " + str(score) + " URI is " + uri)
        resource = {
            "id": uri,
            "name": name,
            "score": score,
            "match": match,
            "type": query_type_meta
        }
        out.append(resource)
   
    # Sort this list containing preflabels and crossrefs by score
    sorted_out = sorted(out, key=itemgetter('score'), reverse=True)
    # Limit results returned--LC might return MANY results for common names / words
    return sorted_out[:20]


@app.route("/", methods=['POST', 'GET'])
def reconcile():
    # If a 'queries' parameter is supplied then it is a dictionary
    # of (key, query) pairs representing a batch of queries. We
    # should return a dictionary of (key, results) pairs.
    queries = request.form.get('queries')
    if queries:
        queries = json.loads(queries)
        results = {}
        for (key, query) in queries.items():
            qtype = query.get('type')
            if qtype is None:
                return jsonpify(metadata)
            data = search(query['query'], query_type=qtype)
            results[key] = {"result": data}
        return jsonpify(results)
    # If neither a 'query' nor 'queries' parameter is supplied then
    # we should return the service metadata.
    return jsonpify(metadata)


if __name__ == '__main__':
    from optparse import OptionParser

    oparser = OptionParser()
    oparser.add_option('-d', '--debug', action='store_true', default=False)
    opts, args = oparser.parse_args()
    app.debug = opts.debug
    app.run(host='0.0.0.0')
