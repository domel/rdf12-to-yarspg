#!/usr/bin/env node
const { rdfParser } = require('rdf-parse');
const { RdfStore } = require('rdf-stores');

let tripleterm_counter = 0;
async function main() {
  // Read and index quads
  const store = RdfStore.createDefault({ indexNodes: true });
  await new Promise((resolve, reject) => {
    rdfParser.parse(process.stdin, { contentType: 'application/n-triples', baseIRI: 'http://example.org' })
        .on('data', (quad) => store.addQuad(quad))
        .on('error', reject)
        .on('end', resolve);
  });

  // Encode quads
  lines = [];
  for (const quad of store.getQuads()) {
    encodeTriple(lines, quad);
  }

  // Serialize nodes
  console.log('# Nodes');
  for (const [_g, node] of store.getNodes(store.dataFactory.variable('g'))) {
    switch (node.termType) {
      case 'NamedNode':
        console.log(`(${termToNode(node)} {"IRI"}[value: "${node.value}"])`);
        break;
      case 'BlankNode':
        console.log(`(${node.value} {"Bnode"})`);
        break;
      case 'Literal':
        console.log(`(${termToNode(node)} {"Literal"}["datatype": "${node.datatype.value}", value: "${node.value}"])`);
        break;
    }
  }
  // Serialize edges
  console.log('');
  console.log('# Edges');
  console.log(lines.join('\n'));
}

function encodeTriple(lines, quad, identifier) {
  const p = identifier ? `({"${quad.predicate.value}"} [ in: "${identifier}" ])` : `({"${quad.predicate.value}"})`;
  if (quad.object.termType === 'Quad') {
    lines.push(`(${termToNode(quad.subject)})-${p}->({ tripleterm_id: "${ tripleterm_counter++ }" })`);
    encodeTriple(lines, quad.object, tripleterm_counter);
  } else {
    // TODO: this does not distinguish between IRIs, BNodes, and Literals
    lines.push(`(${termToNode(quad.subject)})-${p}->(${termToNode(quad.object)})`);
  }
}

function termToNode(term) {
  if (term.termType === 'NamedNode') {
    const pos = Math.max(term.value.lastIndexOf('/'), term.value.lastIndexOf('#'));
    return term.value.substring(pos + 1);
  } else if (term.termType === 'Literal') {
    return term.value.replaceAll(' ', '_');
  }
  return term.value;
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
