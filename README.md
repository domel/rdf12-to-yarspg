# RDF 1.2 Turtle to YARS-PG

This repository contains a Python command-line converter from RDF 1.2 Turtle
to [YARS-PG](https://github.com/lszeremeta/yarspg), with special handling for
RDF 1.2 quoted triple terms, reifiers, and statement annotations.

The converter implements three mapping variants for RDF statements involving
triple terms. The variants are selected with a CLI switch, so the same Turtle
input can be serialized in a compact lossy form or in a more explicit
round-tripping form.

## Files

- `turtle_to_yarspg.py` - main converter CLI and YARS-PG writers.
- `rdf_converter.py` - vendored RDF 1.2 Turtle parser from `rdf12conv`.
- `examples/` - Turtle inputs covering basic RDF and RDF 1.2 features.
- `CLI-examples.txt` - ready-to-run commands focused on RDF 1.2 features.
- `results.txt` - generated outputs for examples `06` through `15`, for all
  three variants.
- `LICENSE.txt` - MIT license for the vendored parser and this code.

## Requirements

Python 3.10 or newer is required. The converter is self-contained and does not
depend on `rdflib` or other third-party packages.

## Quick Start

Show CLI help:

```bash
python3 turtle_to_yarspg.py --help
```

Convert a Turtle file with the default mapping variant:

```bash
python3 turtle_to_yarspg.py examples/06-rdf-reifies.ttl
```

Select a mapping variant explicitly:

```bash
python3 turtle_to_yarspg.py --variant 1 examples/06-rdf-reifies.ttl
python3 turtle_to_yarspg.py --variant 2 examples/06-rdf-reifies.ttl
python3 turtle_to_yarspg.py --variant 3 examples/06-rdf-reifies.ttl
```

Write the result to a file:

```bash
python3 turtle_to_yarspg.py --variant 3 examples/09-nested-triple-terms.ttl -o output.yarspg
```

Read Turtle from standard input:

```bash
cat examples/10-reifier-label.ttl | python3 turtle_to_yarspg.py --variant 3
```

## Mapping Variants

### Variant 1

Variant 1 is a lossy LPG-oriented representation. It maps simple
`rdf:reifies <<(s p o)>>` statements into an edge from `s` to `o`, with
properties such as `asserted` and `reference_id`.

For non-`rdf:reifies` triples whose object is a triple term, Variant 1 creates
an auxiliary `TripleTermRef` node and links to it with an `in` property. If the
same RDF triple later appears as an asserted triple, the previously generated
edge is upgraded from `asserted: "false"` to `asserted: "true"`.

### Variant 2

Variant 2 is also lossy and LPG-oriented. When the document contains at least
one triple term, it uses surrounding triples to create reference properties on
the embedded statement edge. The edge property is named `references`.

If a reference points to an IRI resource, the referenced node also receives a
`reference_id` property so the reference can be resolved to a graph node.

Example shape:

```yarspg
(bob {"IRI"}["reference_id": "bob"])
(moon)-(e1 {"made_of"}["asserted": "false", "reference_property": "said", "references": "bob"])->(cheese)
```

### Variant 3

Variant 3 is the most explicit mapping and is intended for round-tripping.
Every triple term is materialized as a `TripleTerm` node with a
`tripleterm_id`. The triple inside the term is emitted as a normal YARS-PG edge
with an `in` property pointing back to that triple-term identifier.

Example shape:

```yarspg
(tt_1 {"TripleTerm"}["tripleterm_id": "tt_1"])
(moon)-(e1 {"made_of"}["in": "tt_1"])->(cheese)
```

## Example

Input Turtle:

```turtle
@prefix : <http://example.org/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

_:claim1 rdf:reifies <<( :moon :made_of :cheese )>> .
:bob :said _:claim1 .
:bob :played :basketball .
```

Run Variant 3:

```bash
python3 turtle_to_yarspg.py --variant 3 examples/06-rdf-reifies.ttl
```

Output:

```yarspg
# Nodes
(basketball {"IRI"})
(bob {"IRI"})
(cheese {"IRI"})
(claim1 {"BNode"})
(moon {"IRI"})
(tt_1 {"TripleTerm"}["tripleterm_id": "tt_1"])

# Edges
(moon)-(e1 {"made_of"}["in": "tt_1"])->(cheese)
(claim1)-(e2 {"reifies"})->(tt_1)
(bob)-(e3 {"said"})->(claim1)
(bob)-(e4 {"played"})->(basketball)
```

## RDF 1.2 Features Covered by Examples

The `examples/` directory includes:

- `06-rdf-reifies.ttl` - `rdf:reifies` and triple terms.
- `07-asserted-and-reified.ttl` - asserted and reified form of the same triple.
- `08-triple-term-object.ttl` - triple term as an object of an ordinary triple.
- `09-nested-triple-terms.ttl` - nested triple terms.
- `10-reifier-label.ttl` - RDF 1.2 reifier label syntax.
- `11-multiple-reifies.ttl` - multiple reifiers for the same proposition.
- `12-one-reifier-many-propositions.ttl` - one reifier for multiple propositions.
- `13-annotation-block.ttl` - annotation blocks with `{| ... |}`.
- `15-mixed-rdf12.ttl` - mixed RDF 1.2 constructs.

Run all RDF 1.2 examples manually with the commands listed in
`CLI-examples.txt`, or inspect the pre-generated outputs in `results.txt`.

## Validation

A simple smoke test for all examples and variants:

```bash
python3 -m py_compile turtle_to_yarspg.py rdf_converter.py
for f in examples/*.ttl; do
  for v in 1 2 3; do
    python3 turtle_to_yarspg.py --variant "$v" "$f" >/tmp/out.yarspg
  done
done
```

## Parser Source

The RDF 1.2 Turtle parser is vendored from
[`domel/rdf12conv`](https://github.com/domel/rdf12conv). It parses RDF 1.2
Turtle into a typed model, which `turtle_to_yarspg.py` adapts into the internal
model used by the YARS-PG writers.

## License

This repository is distributed under the MIT License. See `LICENSE.txt`.
