# RDF 1.2 to YARS-PG

This repository collects experiments and prototype implementations for
converting RDF 1.2 / RDF-star Turtle data into
[YARS-PG](https://github.com/lszeremeta/yarspg).

## Current State

The repository contains shared Turtle examples, generated YARS-PG outputs, and
three implementation directories. The previous Python implementation from the
repository root has been moved into `implementations/dominik/`; there is no
converter implementation kept directly in the root directory.

Top-level shared files:

- `examples/` - RDF and RDF 1.2 Turtle inputs used for comparison.
- `out/` - generated YARS-PG outputs for examples and mapping variants.
- `results.txt` - collected generated outputs for RDF 1.2 examples.
- `CLI-examples.txt` - example commands for running the converter scenarios.
- `LICENSE.txt` - repository license.

## Implementations

- `implementations/dominik/` - Python CLI converter with a vendored RDF 1.2
  parser. It supports three mapping variants and handles quoted triple terms,
  `rdf:reifies`, reifier labels, and annotation blocks.
- `implementations/dani/prototype_rdf_to_yarspg/` - Dani's Python prototype.
- `implementations/rubent/` - Rubent's JavaScript implementation.

## Running Dominik's Implementation

From the repository root:

```bash
python3 implementations/dominik/turtle_to_yarspg.py --help
python3 implementations/dominik/turtle_to_yarspg.py --variant 3 examples/06-rdf-reifies.ttl
```

Smoke test for the Python implementation:

```bash
python3 -m py_compile implementations/dominik/turtle_to_yarspg.py implementations/dominik/rdf_converter.py
for f in examples/*.ttl; do
  for v in 1 2 3; do
    python3 implementations/dominik/turtle_to_yarspg.py --variant "$v" "$f" >/tmp/out.yarspg
  done
done
```
