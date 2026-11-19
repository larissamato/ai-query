import { CodeOutlined, MessageOutlined, TableOutlined } from '@ant-design/icons'
import { Skeleton, Tabs, Tag } from 'antd'
import { lazy, Suspense } from 'react'
import type { QueryResponse } from '../types'

const ResultData = lazy(() => import('./ResultData'))
const SqlView = lazy(() => import('./SqlView'))

function Placeholder({ kind, text }: { kind: 'table' | 'sql' | 'prompt'; text: string }) {
  const Icon = { table: TableOutlined, sql: CodeOutlined, prompt: MessageOutlined }[kind]
  return <div className="output-empty"><span aria-hidden><Icon /></span><p>{text}</p></div>
}

export function QueryOutput({ response, running }: { response: QueryResponse | null; running: boolean }) {
  const generation = response?.generation
  const validation = response?.stages.find((item) => item.name === 'validation')
  return (
    <section className="panel output">
      <div className="panel-heading">
        <h2><TableOutlined /> Saída da consulta</h2>
        {validation?.status === 'ok' && <Tag color="success">SQL aprovado</Tag>}
        {validation?.status === 'failed' && <Tag color="error">SQL rejeitado</Tag>}
        {validation?.status === 'skipped' && <Tag>Validação pulada</Tag>}
      </div>
      {generation && <div className="generation-summary">
        <strong>{generation.status === 'ambiguous' ? 'Pergunta ambígua' : generation.status === 'unanswerable' ? 'Pergunta sem resposta no schema' : generation.model}</strong>
        <p>{generation.explanation}</p>
        {generation.assumptions.length > 0 && <ul aria-label="Premissas">{generation.assumptions.map((text, index) => <li key={index}>{text}</li>)}</ul>}
      </div>}
      <Tabs items={[
        { key: 'results', label: <><TableOutlined /> Resultados</>, children: response?.result
          ? <Suspense fallback={<Skeleton active />}><ResultData result={response.result} /></Suspense>
          : <Placeholder kind="table" text={running ? 'Aguardando resultado da consulta.' : response ? 'Nenhum resultado de execução.' : 'Execute uma consulta para ver os resultados.'} /> },
        { key: 'sql', label: <><CodeOutlined /> SQL gerado</>, children: generation?.sql
          ? <Suspense fallback={<Skeleton active />}><SqlView sql={generation.sql} /></Suspense>
          : <Placeholder kind="sql" text="O SQL gerado será exibido aqui." /> },
        { key: 'prompt', label: <><MessageOutlined /> Prompt</>, children: response?.prompt?.length
          ? <div className="prompt-view">{response.prompt.map((item, index) => (
            <div className="code-view" key={index}>
              <div className="code-toolbar"><span>{item.role === 'system' ? 'Sistema' : 'Usuário'}</span><span>{generation?.prompt_version}</span></div>
              <pre tabIndex={0}>{item.content}</pre>
            </div>
          ))}</div>
          : <Placeholder kind="prompt" text="As mensagens enviadas ao modelo serão exibidas aqui." /> },
      ]} />
    </section>
  )
}
