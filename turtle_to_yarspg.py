#!/usr/bin/env python3
"""Convert RDF 1.2 Turtle/RDF-star input to YARS-PG.

The CLI supports the three mapping variants described in spec.md. Variant 3 is
the default because it is the least lossy representation.
"""

from __future__ import annotations

import argparse
import re
import sys
import rdf_converter as rdf12
from dataclasses import dataclass
from typing import Iterable


# Namespace constants are used for semantic checks after the Turtle parser has
# expanded prefixes to absolute IRIs.
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
XSD_NS = "http://www.w3.org/2001/XMLSchema#"

RDF_REIFIES_IRI = RDF_NS + "reifies"
XSD_STRING_IRI = XSD_NS + "string"


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    col: int


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class Resource:
    value: str


@dataclass(frozen=True)
class Literal:
    value: str
    datatype: Resource | None = None
    lang: str | None = None
    direction: str | None = None


@dataclass(frozen=True)
class TripleTerm:
    subject: object
    predicate: Resource
    object: object
    reifier: object | None = None
    reified: bool = False


@dataclass(frozen=True)
class Triple:
    subject: object
    predicate: Resource
    object: object


# Legacy lightweight parser kept for local experimentation. The production
# conversion path uses the vendored RDF 1.2 parser in parse_turtle_rdf12().
class Lexer:
    TWO_CHAR = {"^^", "{|", "|}"}
    THREE_CHAR = {"<<(", ")>>"}
    ONE_CHAR = set(".;,[](){}~")

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.line = 1
        self.col = 1

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self.i < len(self.text):
            ch = self.text[self.i]
            if ch.isspace():
                self._advance()
                continue
            if ch == "#":
                self._skip_comment()
                continue

            line, col = self.line, self.col
            tri = self.text[self.i : self.i + 3]
            if tri in self.THREE_CHAR:
                tokens.append(Token("SYMBOL", tri, line, col))
                self._advance_n(3)
                continue
            if self.text.startswith("<<", self.i) or self.text.startswith(">>", self.i):
                value = self.text[self.i : self.i + 2]
                tokens.append(Token("SYMBOL", value, line, col))
                self._advance_n(2)
                continue
            two = self.text[self.i : self.i + 2]
            if two in self.TWO_CHAR:
                tokens.append(Token("SYMBOL", two, line, col))
                self._advance_n(2)
                continue
            if ch == "<":
                tokens.append(self._read_iriref())
                continue
            if ch in ('"', "'"):
                tokens.append(self._read_string())
                continue
            if ch in self.ONE_CHAR:
                tokens.append(Token("SYMBOL", ch, line, col))
                self._advance()
                continue

            tokens.append(self._read_word())

        tokens.append(Token("EOF", "", self.line, self.col))
        return tokens

    def _advance(self) -> str:
        ch = self.text[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _advance_n(self, n: int) -> None:
        for _ in range(n):
            self._advance()

    def _skip_comment(self) -> None:
        while self.i < len(self.text) and self.text[self.i] not in "\r\n":
            self._advance()

    def _read_iriref(self) -> Token:
        line, col = self.line, self.col
        out = [self._advance()]
        escaped = False
        while self.i < len(self.text):
            ch = self._advance()
            out.append(ch)
            if ch == ">" and not escaped:
                return Token("IRI", "".join(out), line, col)
            escaped = ch == "\\" and not escaped
            if ch != "\\":
                escaped = False
        raise ParseError(f"Unterminated IRI at {line}:{col}")

    def _read_string(self) -> Token:
        line, col = self.line, self.col
        quote = self.text[self.i]
        long = self.text.startswith(quote * 3, self.i)
        end = quote * 3 if long else quote
        out: list[str] = []
        self._advance_n(3 if long else 1)
        escaped = False
        while self.i < len(self.text):
            if not escaped and self.text.startswith(end, self.i):
                self._advance_n(len(end))
                return Token("STRING", "".join(out), line, col)
            ch = self._advance()
            if escaped:
                out.append("\\" + ch)
                escaped = False
            elif ch == "\\":
                escaped = True
            else:
                out.append(ch)
        raise ParseError(f"Unterminated string at {line}:{col}")

    def _read_word(self) -> Token:
        line, col = self.line, self.col
        out: list[str] = []
        while self.i < len(self.text):
            ch = self.text[self.i]
            if ch.isspace() or ch in '#;,[](){}~<>"\'':
                break
            if ch == ".":
                nxt = self.text[self.i + 1] if self.i + 1 < len(self.text) else ""
                if not nxt or nxt.isspace() or nxt in "#;,[](){}~<>":
                    break
            out.append(self._advance())
        if not out:
            raise ParseError(f"Unexpected character {self.text[self.i]!r} at {line}:{col}")
        value = "".join(out)
        if re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
            return Token("NUMBER", value, line, col)
        if value in {"true", "false"}:
            return Token("BOOLEAN", value, line, col)
        return Token("WORD", value, line, col)


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0
        self.prefixes: dict[str, str] = {}
        self.blank_counter = 0
        self.generated_triples: list[Triple] = []

    def parse(self) -> list[Triple]:
        triples: list[Triple] = []
        while not self._at("EOF"):
            if self._is_directive():
                self._parse_directive()
            else:
                triples.extend(self._parse_triples_statement())
        return self.generated_triples + triples

    def _parse_directive(self) -> None:
        tok = self._take()
        name = tok.value.lower()
        if name in {"@prefix", "prefix"}:
            prefix = self._expect_any("WORD").value
            iri = self._expect_any("IRI").value
            self.prefixes[prefix[:-1]] = iri[1:-1]
            if name == "@prefix":
                self._expect(".")
        elif name in {"@base", "base"}:
            self._expect_any("IRI")
            if name == "@base":
                self._expect(".")
        elif name in {"@version", "version"}:
            self._expect_any("STRING")
            if name == "@version":
                self._expect(".")
        else:
            self._fail(tok, f"Unsupported directive {tok.value!r}")

    def _parse_triples_statement(self) -> list[Triple]:
        triples = self._parse_triples()
        self._expect(".")
        return triples

    def _parse_triples(self) -> list[Triple]:
        if self._peek_value("["):
            subject = self._parse_blank_node_property_list()
            if self._peek_value("."):
                return []
            return self._parse_predicate_object_list(subject)
        if self._peek_value("<<"):
            subject = self._parse_reified_triple()
            if self._peek_value("."):
                return []
            return self._parse_predicate_object_list(subject)

        subject = self._parse_subject()
        return self._parse_predicate_object_list(subject)

    def _parse_predicate_object_list(self, subject: object) -> list[Triple]:
        triples: list[Triple] = []
        triples.extend(self._parse_verb_object_list(subject))
        while self._accept(";"):
            if self._peek_value(".") or self._peek_value("]"):
                break
            triples.extend(self._parse_verb_object_list(subject))
        return triples

    def _parse_verb_object_list(self, subject: object) -> list[Triple]:
        predicate = self._parse_verb()
        triples: list[Triple] = []
        while True:
            obj = self._parse_object()
            triple = Triple(subject, predicate, obj)
            triples.append(triple)
            triples.extend(self._parse_annotation(triple))
            if not self._accept(","):
                break
        return triples

    def _parse_annotation(self, triple: Triple) -> list[Triple]:
        triples: list[Triple] = []
        while self._peek_value("~") or self._peek_value("{|"):
            if self._accept("~"):
                if self._peek_value("{|") or self._peek_value(";") or self._peek_value(",") or self._peek_value("."):
                    continue
                reifier = self._parse_iri_or_blank()
                term = TripleTerm(triple.subject, triple.predicate, triple.object)
                triples.append(Triple(reifier, Resource("rdf:reifies"), term))
            elif self._accept("{|"):
                # Annotation blocks are Turtle predicate-object lists scoped to
                # the current triple. Represent them as properties of a blank
                # reifier to preserve the relation in YARS-PG.
                reifier = Resource(self._new_blank_id())
                triples.append(Triple(reifier, Resource("rdf:reifies"), TripleTerm(triple.subject, triple.predicate, triple.object)))
                triples.extend(self._parse_predicate_object_list(reifier))
                self._expect("|}")
        return triples

    def _parse_subject(self) -> object:
        if self._peek_value("("):
            return self._parse_collection()
        return self._parse_iri_or_blank()

    def _parse_object(self) -> object:
        if self._peek_value("<<("):
            return self._parse_triple_term()
        if self._peek_value("<<"):
            return self._parse_reified_triple()
        if self._peek_value("["):
            return self._parse_blank_node_property_list()
        if self._peek_value("("):
            return self._parse_collection()
        if self._peek_kind("STRING") or self._peek_kind("NUMBER") or self._peek_kind("BOOLEAN"):
            return self._parse_literal()
        return self._parse_iri_or_blank()

    def _parse_verb(self) -> Resource:
        tok = self._take()
        if tok.kind == "WORD" and tok.value == "a":
            return Resource("rdf:type")
        if tok.kind in {"WORD", "IRI"}:
            return Resource(tok.value)
        self._fail(tok, "Expected predicate")

    def _parse_iri_or_blank(self) -> Resource:
        tok = self._take()
        if tok.kind in {"WORD", "IRI"}:
            return Resource(tok.value)
        self._fail(tok, "Expected IRI, prefixed name, or blank node")

    def _parse_literal(self) -> Literal:
        tok = self._take()
        datatype = self._datatype_for_literal_token(tok)
        literal = Literal(tok.value, datatype=datatype)
        if self._peek_kind("WORD") and self._peek().value.startswith("@"):
            lang = self._take().value[1:]
            literal = Literal(tok.value, datatype=datatype, lang=lang)
        elif self._accept("^^"):
            literal = Literal(tok.value, datatype=self._parse_iri_or_blank())
        return literal

    def _datatype_for_literal_token(self, tok: Token) -> Resource:
        if tok.kind == "BOOLEAN":
            return Resource("xsd:boolean")
        if tok.kind == "NUMBER":
            if "e" in tok.value.lower():
                return Resource("xsd:double")
            if "." in tok.value:
                return Resource("xsd:decimal")
            return Resource("xsd:integer")
        return Resource("xsd:string")

    def _parse_blank_node_property_list(self) -> Resource:
        self._expect("[")
        node = Resource(self._new_blank_id())
        if not self._peek_value("]"):
            self.generated_triples.extend(self._parse_predicate_object_list(node))
        self._expect("]")
        return node

    def _parse_collection(self) -> Resource:
        self._expect("(")
        node = Resource(self._new_blank_id("list"))
        index = 0
        while not self._peek_value(")"):
            item = self._parse_object()
            cell = Resource(self._new_blank_id("list_item"))
            self.generated_triples.append(Triple(node, Resource("rdf:item"), cell))
            self.generated_triples.append(Triple(cell, Resource("rdf:index"), Literal(str(index))))
            self.generated_triples.append(Triple(cell, Resource("rdf:value"), item))
            index += 1
        self._expect(")")
        return node

    def _parse_triple_term(self) -> TripleTerm:
        self._expect("<<(")
        subject = self._parse_iri_or_blank()
        predicate = self._parse_verb()
        obj = self._parse_object()
        self._expect(")>>")
        return TripleTerm(subject, predicate, obj)

    def _parse_reified_triple(self) -> TripleTerm:
        self._expect("<<")
        subject = self._parse_reified_subject()
        predicate = self._parse_verb()
        obj = self._parse_reified_object()
        reifier = None
        if self._accept("~") and not self._peek_value(">>"):
            reifier = self._parse_iri_or_blank()
        self._expect(">>")
        return TripleTerm(subject, predicate, obj, reifier=reifier, reified=True)

    def _parse_reified_subject(self) -> object:
        if self._peek_value("<<"):
            return self._parse_reified_triple()
        return self._parse_iri_or_blank()

    def _parse_reified_object(self) -> object:
        if self._peek_value("<<("):
            return self._parse_triple_term()
        if self._peek_value("<<"):
            return self._parse_reified_triple()
        if self._peek_kind("STRING") or self._peek_kind("NUMBER") or self._peek_kind("BOOLEAN"):
            return self._parse_literal()
        return self._parse_iri_or_blank()

    def _new_blank_id(self, prefix: str = "b") -> str:
        self.blank_counter += 1
        return f"_:{prefix}{self.blank_counter}"

    def _is_directive(self) -> bool:
        if not self._peek_kind("WORD"):
            return False
        return self._peek().value.lower() in {"@prefix", "@base", "@version", "prefix", "base", "version"}

    def _peek(self) -> Token:
        return self.tokens[self.i]

    def _peek_kind(self, kind: str) -> bool:
        return self._peek().kind == kind

    def _peek_value(self, value: str) -> bool:
        return self._peek().value == value

    def _at(self, kind: str) -> bool:
        return self._peek_kind(kind)

    def _take(self) -> Token:
        tok = self._peek()
        self.i += 1
        return tok

    def _accept(self, value: str) -> bool:
        if self._peek_value(value):
            self.i += 1
            return True
        return False

    def _expect(self, value: str) -> Token:
        tok = self._take()
        if tok.value != value:
            self._fail(tok, f"Expected {value!r}")
        return tok

    def _expect_any(self, kind: str) -> Token:
        tok = self._take()
        if tok.kind != kind:
            self._fail(tok, f"Expected {kind}")
        return tok

    def _fail(self, tok: Token, message: str):
        raise ParseError(f"{message} at {tok.line}:{tok.col}, got {tok.value!r}")


class YarspgWriter:
    """Shared YARS-PG serialization helpers used by all mapping variants."""

    def __init__(self, prefixes: dict[str, str] | None = None) -> None:
        self.prefixes = {
            "rdf": RDF_NS,
            "rdfs": RDFS_NS,
            "xsd": XSD_NS,
        }
        if prefixes:
            self.prefixes.update(prefixes)
        self.nodes: dict[str, tuple[set[str], dict[str, str]]] = {}
        self.edges: list[tuple[str, str, str, str, dict[str, str]]] = []
        self.edge_counter = 0
        self.literal_ids: dict[Literal, str] = {}
        self.literal_counter = 0
        self.tripleterm_counter = 0

    def write(self, triples: Iterable[Triple]) -> str:
        for triple in triples:
            self._encode_triple(triple)
        return self._serialize()

    def _serialize(self) -> str:
        lines = ["# Nodes"]
        for node_id in sorted(self.nodes):
            labels, props = self.nodes[node_id]
            lines.append(self._format_node(node_id, labels, props))
        lines.append("")
        lines.append("# Edges")
        for edge_id, source, label, target, props in self.edges:
            lines.append(self._format_edge(edge_id, source, label, target, props))
        return "\n".join(lines) + "\n"

    def _encode_triple(self, triple: Triple, in_id: str | None = None) -> None:
        source = self._node_for_term(triple.subject)
        target = self._node_for_object(triple.object)
        props = {"in": in_id} if in_id else {}
        self._add_edge(source, self._label_for_resource(triple.predicate), target, props)

    def _node_for_object(self, term: object) -> str:
        if isinstance(term, TripleTerm):
            return self._materialize_tripleterm(term)
        return self._node_for_term(term)

    def _node_for_term(self, term: object) -> str:
        if isinstance(term, Resource):
            node_id = self._node_id_for_resource(term)
            labels, _ = self.nodes.setdefault(node_id, (set(), {}))
            # RDF terms are typed explicitly in YARS-PG so IRI and blank nodes
            # remain distinguishable after local-name based ID shortening.
            if not labels.intersection({"Statement", "TripleTerm"}):
                labels.add(self._node_label_for_resource(term))
            return node_id
        if isinstance(term, Literal):
            return self._node_for_literal(term)
        if isinstance(term, TripleTerm):
            return self._materialize_tripleterm(term)
        raise TypeError(f"Unsupported term: {term!r}")

    def _materialize_tripleterm(self, term: TripleTerm) -> str:
        if term.reified and term.reifier is not None:
            reifier_id = self._node_for_term(term.reifier)
            tripleterm_id = self._display_term(term.reifier)
            tt_node = self._create_tripleterm_node(tripleterm_id)
            self._add_edge(reifier_id, "reifies", tt_node, {})
            self._encode_triple(Triple(term.subject, term.predicate, term.object), in_id=tripleterm_id)
            return reifier_id

        # Variant 3 represents quoted triple terms as separate nodes and marks
        # the internal edge with an "in" property pointing back to that node.
        tripleterm_id = self._next_tripleterm_id()
        tt_node = self._create_tripleterm_node(tripleterm_id)
        self._encode_triple(Triple(term.subject, term.predicate, term.object), in_id=tripleterm_id)
        return tt_node

    def _create_tripleterm_node(self, tripleterm_id: str) -> str:
        base = self._sanitize_id(tripleterm_id)
        node_id = base if base.startswith("tt_") else f"tt_{base}"
        while node_id in self.nodes and self.nodes[node_id][1].get("tripleterm_id") != tripleterm_id:
            node_id = f"{node_id}_"
        labels, props = self.nodes.setdefault(node_id, (set(), {}))
        labels.add("TripleTerm")
        props["tripleterm_id"] = tripleterm_id
        return node_id

    def _node_for_literal(self, literal: Literal) -> str:
        if literal not in self.literal_ids:
            self.literal_counter += 1
            node_id = f"lit_{self.literal_counter}"
            self.literal_ids[literal] = node_id
            labels, props = self.nodes.setdefault(node_id, (set(), {}))
            labels.add("Literal")
            props["value"] = literal.value
            if literal.datatype is not None:
                props["datatype"] = self._display_resource(literal.datatype)
            if literal.lang is not None:
                props["lang"] = literal.lang
            if literal.direction is not None:
                props["dir"] = literal.direction
        return self.literal_ids[literal]

    def _next_tripleterm_id(self) -> str:
        self.tripleterm_counter += 1
        return f"tt_{self.tripleterm_counter}"

    def _node_id_for_resource(self, resource: Resource) -> str:
        return self._sanitize_id(self._display_resource(resource))

    def _node_label_for_resource(self, resource: Resource) -> str:
        return "BNode" if resource.value.startswith("_:") else "IRI"

    def _label_for_resource(self, resource: Resource) -> str:
        iri = self._resource_iri(resource)
        if iri is not None:
            for namespace in (RDF_NS, RDFS_NS, XSD_NS):
                if iri.startswith(namespace):
                    return iri[len(namespace) :]
        value = self._display_resource(resource)
        if ":" in value:
            prefix, local = value.split(":", 1)
            if prefix in {"", "rdf", "rdfs", "xsd"} and local:
                return local
        return value

    def _display_term(self, term: object) -> str:
        if isinstance(term, Resource):
            return self._display_resource(term)
        if isinstance(term, Literal):
            return term.value
        if isinstance(term, TripleTerm):
            return self._next_tripleterm_id()
        raise TypeError(f"Unsupported term: {term!r}")

    def _display_resource(self, resource: Resource) -> str:
        value = resource.value
        if value.startswith("<") and value.endswith(">"):
            inner = value[1:-1]
            # Prefer declared prefixes for readable node IDs and properties,
            # but keep default-prefix values as plain local names.
            for prefix, base in self.prefixes.items():
                if inner.startswith(base):
                    local = inner[len(base) :]
                    return local if prefix == "" else f"{prefix}:{local}"
            return inner.rsplit("/", 1)[-1].rsplit("#", 1)[-1] or inner
        return value

    def _resource_iri(self, resource: Resource) -> str | None:
        value = resource.value
        if value.startswith("<") and value.endswith(">"):
            return value[1:-1]
        if ":" in value and not value.startswith("_:"):
            prefix, local = value.split(":", 1)
            if prefix in self.prefixes:
                return self.prefixes[prefix] + local
        return None

    def _resource_is(self, resource: Resource, iri: str) -> bool:
        return self._resource_iri(resource) == iri

    def _sanitize_id(self, value: str) -> str:
        if value.startswith("_:"):
            value = "_" + value[2:]
        if ":" in value:
            prefix, local = value.split(":", 1)
            value = local if prefix in {"", "rdf", "rdfs", "xsd"} else f"{prefix}_{local}"
        value = re.sub(r"[^a-zA-Z0-9_]", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        if not value:
            value = "node"
        if not re.match(r"[a-zA-Z_]", value):
            value = "_" + value
        return value

    def _format_node(self, node_id: str, labels: set[str], props: dict[str, str]) -> str:
        label_part = ""
        if labels:
            label_part = " {" + ", ".join(self._q(label) for label in sorted(labels)) + "}"
        prop_part = self._format_props(props)
        return f"({node_id}{label_part}{prop_part})"

    def _add_edge(self, source: str, label: str, target: str, props: dict[str, str]) -> None:
        self.edge_counter += 1
        self.edges.append((f"e{self.edge_counter}", source, label, target, props))

    def _format_edge(self, edge_id: str, source: str, label: str, target: str, props: dict[str, str]) -> str:
        return f"({source})-({edge_id} {{{self._q(label)}}}{self._format_props(props)})->({target})"

    def _format_props(self, props: dict[str, str]) -> str:
        if not props:
            return ""
        pairs = [f"{self._q(key)}: {self._q(value)}" for key, value in sorted(props.items())]
        return "[" + ", ".join(pairs) + "]"

    def _q(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'


class Variant1Writer(YarspgWriter):
    """Lossy mapping from spec.md Variant 1."""

    def write(self, triples: Iterable[Triple]) -> str:
        triple_list = list(triples)
        reference_ids: set[object] = set()
        # Keep mutable property dictionaries for asserted-false edges so a
        # later asserted RDF triple can upgrade them to asserted:true in place.
        asserted_false_edges: dict[tuple[object, Resource, object], list[dict[str, str]]] = {}
        for triple in triple_list:
            if self._is_reifies(triple.predicate) and self._is_plain_tripleterm(triple.object):
                reference_ids.add(triple.subject)

        for triple in triple_list:
            # rdf:reifies <<(s p o)>> becomes the LPG-like s-p-o edge with a
            # reference to the reifier resource.
            if self._is_reifies(triple.predicate) and self._is_plain_tripleterm(triple.object):
                term = triple.object
                assert isinstance(term, TripleTerm)
                self._encode_simple_edge(
                    term.subject,
                    term.predicate,
                    term.object,
                    {"asserted": "false", "reference_id": self._display_term(triple.subject)},
                    asserted_false_edges,
                )
                continue

            # A non-reifies triple with a triple-term object gets an auxiliary
            # TripleTermRef node because Variant 1 does not embed triple terms.
            if not self._is_reifies(triple.predicate) and self._is_plain_tripleterm(triple.object):
                term = triple.object
                assert isinstance(term, TripleTerm)
                tripleterm_id = self._next_tripleterm_id()
                self._encode_simple_edge(
                    term.subject,
                    term.predicate,
                    term.object,
                    {"asserted": "false", "tripleterm_id": tripleterm_id},
                    asserted_false_edges,
                )
                target = self._create_in_node(tripleterm_id)
                source = self._node_for_term(triple.subject)
                self._add_edge(source, self._label_for_resource(triple.predicate), target, {})
                continue

            if isinstance(triple.subject, TripleTerm) or isinstance(triple.object, TripleTerm):
                continue

            key = (triple.subject, triple.predicate, triple.object)
            if key in asserted_false_edges:
                for props in asserted_false_edges[key]:
                    props["asserted"] = "true"
                continue

            # Reifier resources are exposed through Statement nodes when they
            # participate in ordinary RDF triples.
            if triple.subject in reference_ids:
                statement = self._statement_node(triple.subject)
                self._encode_simple_edge(Resource(statement), triple.predicate, triple.object, {})
            elif triple.object in reference_ids:
                statement = self._statement_node(triple.object)
                self._encode_simple_edge(triple.subject, triple.predicate, Resource(statement), {})
            else:
                self._encode_simple_edge(triple.subject, triple.predicate, triple.object, {})

        return self._serialize()

    def _statement_node(self, reference: object) -> str:
        reference_id = self._display_term(reference)
        node_id = "statement_" + self._sanitize_id(reference_id)
        labels, props = self.nodes.setdefault(node_id, (set(), {}))
        labels.add("Statement")
        props["references"] = reference_id
        return node_id

    def _create_in_node(self, tripleterm_id: str) -> str:
        node_id = "ttref_" + self._sanitize_id(tripleterm_id)
        labels, props = self.nodes.setdefault(node_id, (set(), {}))
        labels.add("TripleTermRef")
        props["in"] = tripleterm_id
        return node_id

    def _encode_simple_edge(
        self,
        subject: object,
        predicate: Resource,
        obj: object,
        props: dict[str, str],
        asserted_false_edges: dict[tuple[object, Resource, object], list[dict[str, str]]] | None = None,
    ) -> None:
        if isinstance(subject, TripleTerm) or isinstance(obj, TripleTerm):
            return
        source = self._node_for_term(subject)
        target = self._node_for_term(obj)
        self._add_edge(source, self._label_for_resource(predicate), target, props)
        if asserted_false_edges is not None and props.get("asserted") == "false":
            asserted_false_edges.setdefault((subject, predicate, obj), []).append(props)

    def _is_plain_tripleterm(self, term: object) -> bool:
        return (
            isinstance(term, TripleTerm)
            and not isinstance(term.subject, TripleTerm)
            and not isinstance(term.object, TripleTerm)
        )

    def _is_reifies(self, predicate: Resource) -> bool:
        return self._resource_is(predicate, RDF_REIFIES_IRI) or self._label_for_resource(predicate) == "reifies"


class Variant2Writer(YarspgWriter):
    """Lossy LPG-oriented mapping from spec.md Variant 2."""

    def write(self, triples: Iterable[Triple]) -> str:
        triple_list = list(triples)
        tripleterm_triples = [
            triple for triple in triple_list if isinstance(triple.object, TripleTerm)
        ]

        # Without triple terms, Variant 2 is just a direct RDF-to-edge mapping.
        if not tripleterm_triples:
            for triple in triple_list:
                self._encode_simple_edge(triple.subject, triple.predicate, triple.object, {})
            return self._serialize()

        emitted_regular: set[tuple[object, Resource, object]] = set()
        emitted_reference: set[tuple[object, Resource, object, tuple[tuple[str, str], ...]]] = set()
        for t1 in tripleterm_triples:
            term = t1.object
            assert isinstance(term, TripleTerm)
            for t2 in triple_list:
                # Same subject: t2 describes the same resource that points at
                # the triple term, so t2.object becomes the reference target.
                if t1 != t2 and t1.subject == t2.subject:
                    props = {
                        "asserted": "false",
                        "reference_property": self._label_for_resource(t2.predicate),
                        "references": self._display_term(t2.object),
                    }
                    self._mark_reference_target(t2.object)
                    self._encode_reference_edge(term, props, emitted_reference)
                # t2 points to t1.subject, so t2.subject becomes the reference.
                elif t1 != t2 and t1.subject == t2.object:
                    props = {
                        "asserted": "false",
                        "reference_property": self._label_for_resource(t2.predicate),
                        "references": self._display_term(t2.subject),
                    }
                    self._mark_reference_target(t2.subject)
                    self._encode_reference_edge(term, props, emitted_reference)
                # The triple-term triple itself also contributes a reference.
                # The algorithm calls this reference_id, but the agreed YARS-PG
                # property name is "references".
                elif t1 == t2:
                    props = {
                        "asserted": "false",
                        "reference_property": self._label_for_resource(t2.predicate),
                        "references": self._display_term(t2.subject),
                    }
                    self._mark_reference_target(t2.subject)
                    self._encode_reference_edge(term, props, emitted_reference)
                else:
                    self._encode_regular_once(t2, emitted_regular)

        return self._serialize()

    def _encode_reference_edge(
        self,
        term: TripleTerm,
        props: dict[str, str],
        emitted_reference: set[tuple[object, Resource, object, tuple[tuple[str, str], ...]]],
    ) -> None:
        key = (term.subject, term.predicate, term.object, tuple(sorted(props.items())))
        if key in emitted_reference:
            return
        emitted_reference.add(key)
        self._encode_simple_edge(term.subject, term.predicate, term.object, props)

    def _encode_regular_once(self, triple: Triple, emitted_regular: set[tuple[object, Resource, object]]) -> None:
        # The nested loops can encounter unrelated regular triples many times;
        # emit each ordinary edge only once.
        if isinstance(triple.subject, TripleTerm) or isinstance(triple.object, TripleTerm):
            return
        key = (triple.subject, triple.predicate, triple.object)
        if key in emitted_regular:
            return
        emitted_regular.add(key)
        self._encode_simple_edge(triple.subject, triple.predicate, triple.object, {})

    def _mark_reference_target(self, term: object) -> None:
        # When a references value names an IRI node, put the same value on that
        # node so the edge can point to a concrete graph element.
        if not isinstance(term, Resource) or term.value.startswith("_:"):
            return
        node_id = self._node_for_term(term)
        _, props = self.nodes[node_id]
        props["reference_id"] = self._display_term(term)

    def _encode_simple_edge(self, subject: object, predicate: Resource, obj: object, props: dict[str, str]) -> None:
        if isinstance(subject, TripleTerm) or isinstance(obj, TripleTerm):
            return
        source = self._node_for_term(subject)
        target = self._node_for_term(obj)
        self._add_edge(source, self._label_for_resource(predicate), target, props)

    def _is_reifies(self, predicate: Resource) -> bool:
        return self._resource_is(predicate, RDF_REIFIES_IRI) or self._label_for_resource(predicate) == "reifies"


class Variant3Writer(YarspgWriter):
    """Round-tripping mapping from spec.md Variant 3."""

    def write(self, triples: Iterable[Triple]) -> str:
        # Variant 3 delegates recursion to YarspgWriter._encode_triple(), which
        # materializes every nested triple term as its own TripleTerm node.
        for triple in triples:
            self._encode_triple(triple)
        return self._serialize()


def parse_turtle_rdf12(text: str, source: str = "<string>") -> tuple[list[Triple], dict[str, str]]:
    # Use the full RDF 1.2 Turtle parser from rdf12conv, then adapt its typed
    # AST to the smaller internal model used by the YARS-PG writers.
    parser = rdf12.TurtleParser(text=text, source=source, base_iri=None)
    rdf_triples = parser.parse()
    triples = [
        Triple(
            _from_rdf12_resource(subject),
            _from_rdf12_resource(predicate),
            _from_rdf12_node(obj),
        )
        for subject, predicate, obj in rdf_triples
    ]
    prefixes = {
        "rdf": RDF_NS,
        "rdfs": RDFS_NS,
        "xsd": XSD_NS,
    }
    prefixes.update(parser.prefixes)
    return triples, prefixes


def _from_rdf12_node(node: object) -> object:
    if isinstance(node, rdf12.IRI):
        return Resource(f"<{node.value}>")
    if isinstance(node, rdf12.BNode):
        return Resource(f"_:{node.label}")
    if isinstance(node, rdf12.Literal):
        datatype = node.datatype or XSD_STRING_IRI
        return Literal(
            value=node.value,
            datatype=Resource(f"<{datatype}>"),
            lang=node.lang,
            direction=node.direction,
        )
    if isinstance(node, rdf12.TripleTerm):
        return TripleTerm(
            subject=_from_rdf12_node(node.subject),
            predicate=_from_rdf12_resource(node.predicate),
            object=_from_rdf12_node(node.object),
        )
    raise TypeError(f"Unsupported RDF 1.2 node: {node!r}")


def _from_rdf12_resource(node: object) -> Resource:
    if isinstance(node, rdf12.IRI):
        return Resource(f"<{node.value}>")
    if isinstance(node, rdf12.BNode):
        return Resource(f"_:{node.label}")
    raise TypeError(f"Expected RDF 1.2 IRI or blank node, got {node!r}")


def convert(text: str, variant: int = 3, source: str = "<string>") -> str:
    triples, prefixes = parse_turtle_rdf12(text, source=source)
    writers = {
        1: Variant1Writer,
        2: Variant2Writer,
        3: Variant3Writer,
    }
    return writers[variant](prefixes).write(triples)


def main(argv: list[str] | None = None) -> int:
    argp = argparse.ArgumentParser(description="Convert Turtle/RDF-star to YARS-PG.")
    argp.add_argument("input", nargs="?", help="Turtle input file. Reads stdin when omitted.")
    argp.add_argument("-o", "--output", help="YARS-PG output file. Writes stdout when omitted.")
    argp.add_argument(
        "--variant",
        type=int,
        choices=(1, 2, 3),
        default=3,
        help="Mapping variant from spec.md: 1, 2, or 3 (default: 3).",
    )
    args = argp.parse_args(argv)

    try:
        if args.input:
            with open(args.input, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            text = sys.stdin.read()
        source = args.input or "<stdin>"
        result = convert(text, args.variant, source=source)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(result)
        else:
            sys.stdout.write(result)
        return 0
    except (ParseError, rdf12.ParseError) as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
