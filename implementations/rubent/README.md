# rdf12-to-lpg

Small proof of concept to convert RDF 1.2 (N-Triples) to a labeled property graph (LPG) format.

## Install and test

```bash
npm install
```

## Usage

Pipe a file into the CLI:

```bash
cat uc8.ttl | node main.js
```

This will do the following conversion:
```ttl
PREFIX : <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

_:1 :generatedBy :source1 .
_:2 :generatedBy :source2 .
_:1 rdf:reifies <<( :moon :made_of :cheese )>> .
_:2 rdf:reifies <<( :moon :made_of :cheese )>> .
```

Output:
```txt
# Nodes
(b0_1 {"Bnode"})
(http://example.org/source1 {"IRI"})
(b0_2 {"Bnode"})
(http://example.org/source2 {"IRI"})

# Edges
(b0_1)-({"http://example.org/generatedBy"})->(http://example.org/source1)
(b0_1)-({"http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies"})->({ tripleterm_id: "0" })
(http://example.org/moon)-({"http://example.org/made_of"} [ in: "1" ])->(http://example.org/cheese)
(b0_2)-({"http://example.org/generatedBy"})->(http://example.org/source2)
(b0_2)-({"http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies"})->({ tripleterm_id: "1" })
(http://example.org/moon)-({"http://example.org/made_of"} [ in: "2" ])->(http://example.org/cheese)
```
