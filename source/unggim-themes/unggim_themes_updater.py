from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DC, DCTERMS, FOAF, RDF, SDO, SKOS, XSD
from datetime import datetime

# preprocess data-themes my moving all newline-broken strings to single-line strings
g = Graph().parse("data-themes.orig.ttl")

for t in g.triples((URIRef("http://osi.ie/prime2"), None, None)):
    g.remove(t)

# add VocPub metadata to the ConceptScheme
CS = None
for cs in g.subjects(RDF.type, SKOS.ConceptScheme):
    CS = cs

title = g.value(CS, DCTERMS.title)
g.remove((CS, DCTERMS.title, None))
g.add((CS, SKOS.prefLabel, title))

description = g.value(CS, DC.description)
g.remove((CS, DC.description, None))
g.add((CS, SKOS.definition, description))

modified = g.value(CS, DCTERMS.modified)
g.remove((CS, DCTERMS.modified, None))
g.add((CS, SDO.dateCreated, modified))

g.add((CS, SDO.dateModified, Literal(datetime.now().isoformat().split("T")[0], datatype=XSD.date)))

# g.add((CS, SDO.dateModified, Literal("2021-04-27", datatype=XSD.date)))  # from the GitHub repo last commit

history_note = (
        "This vocabulary is a slightly reformatted version of the original obtained " +
        "from https://linkeddataops.adaptcentre.ie/vocabularies/unggim-data-themes.\n\n" +
        "The only changes have been to remove the top-level 'Data Theme' Concept and to add ConceptScheme and Concept "
        "elements required for the VocPub profile of SKOS "
        "(https://linked.data.gov.au/def/vocpub/spec)"
)
g.add((CS, SKOS.historyNote, Literal(history_note)))
g.add((
    CS,
    SDO.citation,
    Literal("https://linkeddataops.adaptcentre.ie/vocabularies/unggim-data-themes", datatype=XSD.anyURI)
))

g.add((CS, SDO.license, URIRef("http://purl.org/NET/rdflicense/cc-by4.0")))

# creator
g.parse(data=f"""
PREFIX schema: <{SDO}>
PREFIX xsd: <{XSD}>

<https://orcid.org/0000-0003-2130-0312>
    a schema:Person ;
    schema:name "Beyza Yaman" ;
    schema:email "beyza.yaman@adaptcentre.ie"^^xsd:anyURI ;
    schema:url "https://dblp.org/pers/y/Yaman:Beyza.html" ;
.

<{CS}> schema:creator <https://orcid.org/0000-0003-2130-0312> .
""")
for t in g.triples((CS, DCTERMS.creator, None)):
    g.remove(t)
for s in g.subjects(FOAF.homepage, URIRef("https://dblp.org/pers/y/Yaman:Beyza.html")):
    for t in g.triples((s, None, None)):
        g.remove(t)

# publisher
g.parse(data=f"""
PREFIX schema: <{SDO}>
PREFIX xsd: <{XSD}>

<https://linked.data.gov.au/org/icsm>
    a schema:Organization ;
    schema:name "Intergovernmental Committee on Surveying & Mapping" ;
    schema:url "https://icsm.gov.au"^^xsd:anyURI ;
.

<{CS}> schema:publisher <https://linked.data.gov.au/org/icsm> .
""")


for t in g.triples((URIRef(CS + "DataTheme"), None, None)):
    g.remove(t)

# update each Concept
for concept in g.subjects(RDF.type, SKOS.Concept):
    if (concept, SKOS.broader, URIRef(str(CS) + "DataTheme")) in g:
        g.remove((concept, SKOS.broader, URIRef(str(CS) + "DataTheme")))
    g.add((concept, SKOS.inScheme, CS))

    for note in g.objects(concept, SKOS.note):
        g.remove((concept, SKOS.note, note))
        g.add((concept, SKOS.definition, note))

    if not g.value(concept, SKOS.broader, None):
        g.add((concept, SKOS.topConceptOf, CS))
        g.add((CS, SKOS.hasTopConcept, concept))


# add in FSDF matches
g.parse(data=f"""
PREFIX : <https://linkeddataops.adaptcentre.ie/vocabularies/unggim-data-themes#>
PREFIX fsdf: <https://linked.data.gov.au/def/fsdf/themes/>
PREFIX skos: <{SKOS}>

:Addresses 
    skos:exactMatch fsdf:geocoded-addressing ;
    skos:altLabel "Geocoded Addressing" ;
.

:Buildings-Settlements
    skos:exactMatch fsdf:buildings-and-settlements ;
.

:Elevation-Depth
    skos:exactMatch fsdf:elevation-and-depth ;
.

:FunctionalAreas
    skos:exactMatch fsdf:administrative-boundaries ;
    skos:altLabel "Administrative Boundaries" ;
.

:GeographicalNames 
    skos:exactMatch fsdf:place-names ;
    skos:altLabel "Place Names" ;
.

:GCRF
    skos:exactMatch fsdf:positioning ;
.

:LandCover-LandUse
    skos:exactMatch fsdf:land-cover-and-land-use ;
.

:LandParcels
    skos:exactMatch fsdf:land-parcel-and-property ;
    skos:altLabel "Place Names" ;
.

:Orthoimagery 
    skos:exactMatch fsdf:imagery ;
    skos:altLabel "Imagery" ;
.

:TransportNetworks 
    skos:exactMatch fsdf:transport ;
    skos:altLabel "Transport" ;
.

:Water 
    skos:exactMatch fsdf:water ;
.
""")

# add in FSDF sub-themes
g.parse("fsdf-themes-non-top.ttl")

# alter CS IRI
NEW_CS = URIRef("https://linked.data.gov.au/def/unggim-themes")
for t in g.triples((CS, None, None)):
    g.remove(t)
    g.add((NEW_CS, t[1], t[2]))
for t in g.triples((None, None, CS)):
    g.remove(t)
    g.add((t[0], t[1], NEW_CS))
g.bind("cs", NEW_CS)

g.bind("", CS, override=True)
g.serialize(destination="../../unggim-themes.ttl", format="longturtle")

# switch CS IRI
ttl = open("../../vocabs/unggim-themes.ttl").read()
open("../../vocabs/unggim-themes.ttl", "w").write(
    ttl.replace("PREFIX : <https://linkeddataops.adaptcentre.ie/vocabularies/unggim-data-themes#>",
                f"PREFIX : <{NEW_CS}/>")
)

