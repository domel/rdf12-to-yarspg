from pyoxigraph import parse, RdfFormat, Triple, NamedNode, BlankNode, Literal


def prefixize_uri_if_possible(target_uri: str, namespaces_prefix_dict: dict):
    best_match = None
    for a_namespace in namespaces_prefix_dict:  # Prefixed element (all literals are prefixed elements)
        if target_uri.startswith(a_namespace):
            if "/" not in target_uri[len(a_namespace):] and \
                    "#" not in target_uri[len(a_namespace):]:
                best_match = a_namespace
                break
        a = target_uri[len(a_namespace):]
        b = "/" not in target_uri[len(a_namespace):]
        c = "#" not in target_uri[len(a_namespace):]
        d = None
    return target_uri if best_match is None else target_uri.replace(best_match,
                                                                    namespaces_prefix_dict[best_match] + ":")


class RdfToLpg(object):
    def translate(self, rdf_data_content: str, format: RdfFormat, base_iri: str):
        raise NotImplementedError()


class Variant3(RdfToLpg):
    _BNODE_ID = "BNode"
    _IRI_ID = "IRI"
    _LITERAL_ID = "LITERAL"

    _TRIPLE_TEMPLATE = '({})-({})-> ({})'
    _NODE_DECLARATION_TEMPLATE = '({} {{"{}"}})'
    _TT_DECLARATION_TEMPLATE = '({} {{"{}"}}["tripleterm_id": "{}"])'

    _LITERAL_DECLARATION_TEMPLATE = '({} {{"'+ _LITERAL_ID +'"}}[{}])'
    _TT_ID_TEMPLATE = "_tt{}"
    _BNODE_MARK = "_"
    _IN_KEY = "in"


    _ID_KEY_INTERNAL = "i"
    _TYPE_KEY_INTERNAL = "t"

    # HANDLING LITERALS
    _KEY_DATATYPE = "datatype"
    _KEY_DIRECTION = "direction"
    _KEY_LANGUAGE = "language"
    _KEY_VALUE = "value"

    _LIT_KEYS = [_KEY_DATATYPE, _KEY_DIRECTION, _KEY_LANGUAGE, _KEY_VALUE]

    def __init__(self):
        self._namespaces_dict = {}
        self._tt_count = 0
        self._nodes_dict = {}
        self._edges = []
        self._lit_count = 0


    def translate(self, rdf_data_content: str,
                  format: RdfFormat = RdfFormat.TURTLE,
                  base_iri: str = "http://example.org/",
                  namespaces_dict: dict = None):
        if namespaces_dict is not None:
            self._namespaces_dict = namespaces_dict

        for triple in parse(
                input=rdf_data_content,
                format=format,
                base_iri=base_iri
        ):
            self._visit_triple(triple)

        self._serialize()

    def _serialize(self):
        self._write_node_declarations()
        self._write_line("\n")
        self._write_edges()

    def _write_node_declarations(self):
        self._write_line("# Node declarations\n")
        for a_node in self._nodes_dict:
            if self._nodes_dict[a_node][self._TYPE_KEY_INTERNAL] == "TripleTerm":
                self._write_line(self._TT_DECLARATION_TEMPLATE.format(
                    self._nodes_dict[a_node][self._ID_KEY_INTERNAL],
                    self._nodes_dict[a_node][self._TYPE_KEY_INTERNAL],
                    a_node
                ))
            elif self._nodes_dict[a_node][self._TYPE_KEY_INTERNAL] == self._LITERAL_ID:
                self._write_line(self._gen_literal_node_declaration(a_node))
            else:
                self._write_line(self._NODE_DECLARATION_TEMPLATE.format(
                    self._nodes_dict[a_node][self._ID_KEY_INTERNAL],
                    self._nodes_dict[a_node][self._TYPE_KEY_INTERNAL]
                ))

    def _gen_literal_node_declaration(self, literal_key):
        declarations = []
        for a_key in self._LIT_KEYS:
            if a_key in self._nodes_dict[literal_key]:
                declarations.append(f'"{a_key}":"{self._nodes_dict[literal_key][a_key]}"')
        return self._LITERAL_DECLARATION_TEMPLATE.format(self._nodes_dict[literal_key][self._ID_KEY_INTERNAL],
                                                         ",".join(declarations))

    def _write_edges(self):
        self._write_line("# Edges\n")
        for an_edge in self._edges:
            self._write_line(an_edge)

    def _write_line(self, str_line: str):
        print(str_line)

    def _visit_triple(self, triple: Triple, in_tt: str | None = None):
        if not isinstance(triple.object, Triple):
            self._generate_good_old_fashion_triple(triple, in_tt)
        else:
            self._generate_triple_with_tt(triple, in_tt)

    def _generate_triple_with_tt(self, triple: Triple, in_tt: str | None):
        tt_id = self._get_tt_id()
        self._add_edge(self._TRIPLE_TEMPLATE.format(
            self._visit_subject(triple.subject),
            self._visit_predicate(triple.predicate),
            tt_id
        ))
        self._visit_triple(triple.object, in_tt=tt_id)

    def _add_edge(self, str_line: str):
        self._edges.append(str_line)

    def _get_tt_id(self):
        self._tt_count += 1
        identifier = self._TT_ID_TEMPLATE.format(str(self._tt_count))
        self._nodes_dict[identifier] = {
            self._TYPE_KEY_INTERNAL: "TripleTerm",
            self._ID_KEY_INTERNAL: identifier
        }
        return identifier

    def _generate_good_old_fashion_triple(self, triple: Triple, in_tt: str | None = None):
        self._add_edge(self._TRIPLE_TEMPLATE.format(
            self._visit_subject(triple.subject),
            self._visit_predicate(triple.predicate, in_tt),
            self._visit_object(triple.object)
        ))
        a = 2

    def _visit_subject(self, term):
        return self._visit_plain_s_o(term)

    def _visit_plain_s_o(self, term):
        if isinstance(term, Literal):
            return self._visit_literal(term)
        candidate = prefixize_uri_if_possible(target_uri=term.value, namespaces_prefix_dict=self._namespaces_dict)
        t = "IRI"
        if isinstance(term, BlankNode):
            candidate = self._BNODE_MARK + candidate
            t = "BNode"
        if candidate in self._nodes_dict:
            return self._nodes_dict[candidate][self._ID_KEY_INTERNAL]
        self._nodes_dict[candidate] = {
            self._TYPE_KEY_INTERNAL: t,
            self._ID_KEY_INTERNAL: self._gen_node_id(candidate)
        }


        return self._nodes_dict[candidate][self._ID_KEY_INTERNAL]

    def _visit_literal(self, term):
        self._lit_count += 0
        lit_id = "LIT_" + str(self._lit_count)
        self._nodes_dict[lit_id] = {
            self._TYPE_KEY_INTERNAL: self._LITERAL_ID,
            self._ID_KEY_INTERNAL: lit_id
        }
        if term.datatype is not None:
            self._nodes_dict[lit_id][self._KEY_DATATYPE] = term.datatype
        if term.direction is not None:
            self._nodes_dict[lit_id][self._KEY_DIRECTION] = term.direction
        if term.language is not None:
            self._nodes_dict[lit_id][self._KEY_LANGUAGE] = term.language
        if term.value is not None:
            self._nodes_dict[lit_id][self._KEY_VALUE] = term.value
        return lit_id

    def _gen_node_id(self, node_target: str):
        candidate = node_target.rsplit(":", 1)[-1]
        if candidate not in self._nodes_dict:
            return candidate
        counter = 1
        original = candidate
        while candidate in self._nodes_dict:
            counter += 1
            candidate = original + str(counter)
        return candidate

    def _visit_predicate(self, term, in_tt: str | None = None):
        result = f'{{"{prefixize_uri_if_possible(term.value, self._namespaces_dict)}"}}'
        if in_tt is not None:
            result += f'["{self._IN_KEY}": "{in_tt}"]'
        return result

    def _visit_object(self, term):
        return self._visit_plain_s_o(term)
