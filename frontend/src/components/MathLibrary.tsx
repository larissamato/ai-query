import { useState } from 'react'
import { VennDiagram } from './VennDiagram'
import type { SetOperation } from './VennDiagram'

interface Example {
  question: string
  a: string
  b?: string
}

interface Concept {
  operation: SetOperation
  name: string
  logical: string
  notation: string
  description: string
  sql: string
  examples: Example[]
}

const concepts: [Concept, ...Concept[]] = [
  {
    operation: 'intersection', name: 'Interseção', logical: 'AND', notation: 'A ∩ B',
    description: 'Elementos que pertencem simultaneamente a A e B.',
    sql: 'AND aceita uma linha quando os dois predicados são verdadeiros. INTERSECT, na álgebra relacional, corresponde à interseção das linhas retornadas por duas consultas com colunas compatíveis.',
    examples: [
      {
        question: 'Retorne o nome e o preço dos produtos que custam mais de R$ 100 e menos de R$ 500.',
        a: 'Produtos com preço acima de R$ 100.', b: 'Produtos com preço abaixo de R$ 500.',
      },
      {
        question: 'Retorne o nome e o preço dos produtos cujo nome contém a palavra Notebook e cujo preço é superior a R$ 500.',
        a: 'Produtos cujo nome contém Notebook.', b: 'Produtos com preço acima de R$ 500.',
      },
      {
        question: 'Retorne o nome e o preço dos produtos que pertencem à categoria Eletrônicos e custam mais de R$ 500.',
        a: 'Produtos da categoria Eletrônicos.', b: 'Produtos com preço acima de R$ 500.',
      },
    ],
  },
  {
    operation: 'union', name: 'União', logical: 'OR', notation: 'A ∪ B',
    description: 'Elementos que pertencem a pelo menos um dos conjuntos.',
    sql: 'OR aceita uma linha quando pelo menos um dos predicados é verdadeiro. UNION combina as linhas de duas consultas com colunas compatíveis e elimina duplicatas por padrão.',
    examples: [
      {
        question: 'Retorne o nome e o preço dos produtos que custam menos de R$ 100 ou mais de R$ 1.000.',
        a: 'Produtos com preço abaixo de R$ 100.', b: 'Produtos com preço acima de R$ 1.000.',
      },
      {
        question: 'Retorne o nome e o preço dos produtos cujo nome contém Notebook ou Monitor.',
        a: 'Produtos cujo nome contém Notebook.', b: 'Produtos cujo nome contém Monitor.',
      },
      {
        question: 'Retorne os produtos que pertencem à categoria Eletrônicos ou à categoria Informática.',
        a: 'Produtos da categoria Eletrônicos.', b: 'Produtos da categoria Informática.',
      },
    ],
  },
  {
    operation: 'complement', name: 'Complemento', logical: 'NOT', notation: 'U − A',
    description: 'Elementos do universo U que não pertencem a A.',
    sql: 'NOT nega um predicado e preserva o estado desconhecido de NULL. NOT IN verifica ausência em uma lista ou subconsulta, mas um NULL pode tornar o resultado desconhecido e a linha é descartada pelo WHERE. NOT EXISTS verifica se a subconsulta retorna alguma linha e depende do critério usado para encontrar correspondências.',
    examples: [
      {
        question: 'Retorne o nome e o preço dos produtos que não custam mais de R$ 500.',
        a: 'Produtos com preço acima de R$ 500.',
      },
      {
        question: 'Retorne o nome e o preço dos produtos que não custam entre R$ 100 e R$ 500.',
        a: 'Produtos com preço de R$ 100 a R$ 500, incluindo os limites.',
      },
      {
        question: 'Retorne os produtos que não pertencem à categoria Eletrônicos.',
        a: 'Produtos da categoria Eletrônicos.',
      },
    ],
  },
  {
    operation: 'symmetricDifference', name: 'Diferença simétrica', logical: 'XOR', notation: '(A − B) ∪ (B − A)',
    description: 'Elementos que pertencem exclusivamente a um dos conjuntos.',
    sql: 'Combine os predicados com (A AND NOT B) OR (B AND NOT A). Se um predicado puder resultar em NULL, defina como tratar o valor desconhecido antes de aplicar a lógica de pertencimento.',
    examples: [
      {
        question: 'Retorne o nome e o preço dos produtos que custam mais de R$ 500 ou pertencem à categoria Eletrônicos, mas não atendem às duas condições simultaneamente.',
        a: 'Produtos com preço acima de R$ 500.', b: 'Produtos da categoria Eletrônicos.',
      },
      {
        question: 'Retorne os produtos cujo nome contém Notebook ou cujo preço é superior a R$ 1.000, mas não satisfazem ambas as condições.',
        a: 'Produtos cujo nome contém Notebook.', b: 'Produtos com preço acima de R$ 1.000.',
      },
    ],
  },
  {
    operation: 'difference', name: 'Diferença de conjuntos', logical: 'AND NOT', notation: 'A − B',
    description: 'Elementos de A que não pertencem a B.',
    sql: 'EXCEPT retorna as linhas da primeira consulta ausentes na segunda e elimina duplicatas por padrão. NOT EXISTS permite excluir linhas de A para as quais existe uma correspondência em B.',
    examples: [
      {
        question: 'Retorne o nome e o preço dos produtos que custam mais de R$ 100, exceto os da categoria Eletrônicos.',
        a: 'Produtos com preço acima de R$ 100.', b: 'Produtos da categoria Eletrônicos.',
      },
    ],
  },
]

export function MathLibrary({ onQuestion }: { onQuestion: (value: string) => void }) {
  const [concept, setConcept] = useState(concepts[0])
  const [example, setExample] = useState<Example>()

  return (
    <details className="panel math-library">
      <summary>Explorando a matemática por meio do SQL</summary>
      <div className="math-library-body">
        <div className="math-cards" role="group" aria-label="Operações matemáticas">
          {concepts.map((item) => (
            <button type="button" key={item.operation} aria-label={`${item.logical} — ${item.name}`}
              aria-pressed={concept === item}
              onClick={() => {
                if (concept === item) return
                setConcept(item)
                setExample(undefined)
              }}>
              <span className="math-logical">{item.logical}</span>
              <strong>{item.name}</strong>
              <VennDiagram operation={item.operation} />
              <span className="math-notation">{item.notation}</span>
              <span className="math-description">{item.description}</span>
            </button>
          ))}
        </div>
        <div className="math-explanation">
          <h3>{concept.name} · {concept.notation}</h3>
          <p>{concept.description}</p>
          <p>{concept.sql}</p>
        </div>
        <div>
          <h3>Perguntas para testar</h3>
          <p className="math-description">Escolha uma pergunta para preencher o campo de consulta. Você pode editá-la antes de executar e comparar o SQL gerado com a operação acima.</p>
          <ul className="math-questions">
            {concept.examples.map((item) => (
              <li key={item.question}>
                <button type="button" aria-pressed={example === item} onClick={() => {
                  setExample(item)
                  onQuestion(item.question)
                }}>{item.question}</button>
              </li>
            ))}
          </ul>
          {example && <dl className="math-sets" aria-label="Conjuntos da pergunta de exemplo">
            {concept.operation === 'complement' && <div><dt>U</dt><dd>Todos os produtos.</dd></div>}
            <div><dt>A</dt><dd>{example.a}</dd></div>
            {example.b && <div><dt>B</dt><dd>{example.b}</dd></div>}
          </dl>}
          <p className="math-description">Na carga sintética padrão, os nomes seguem o formato “Produto 1”, os preços ficam abaixo de R$ 500 e a categoria Informática está ausente. Algumas perguntas podem retornar um conjunto vazio.</p>
        </div>
      </div>
    </details>
  )
}
