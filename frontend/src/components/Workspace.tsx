import { ClockCircleOutlined, DatabaseOutlined, LinkOutlined, ReloadOutlined, TableOutlined } from '@ant-design/icons'
import { Alert, Button, Collapse, Skeleton, Tabs, Tag } from 'antd'
import type { HistoryEntry, Schema } from '../types'
import { traceUrl } from './Processing'

interface WorkspaceProps {
  schema: Schema | undefined
  loading: boolean
  error: string | undefined
  history: HistoryEntry[]
  onRetry: () => void
  onReuse: (entry: HistoryEntry) => void
}

const statuses = {
  ok: 'Concluída', failed: 'Falhou', ambiguous: 'Ambígua', unanswerable: 'Sem resposta',
}

export function Workspace({ schema, loading, error, history, onRetry, onReuse }: WorkspaceProps) {
  const schemaBody = loading ? <Skeleton active paragraph={{ rows: 5 }} />
    : error ? <Alert type="error" title={error} description={<Button size="small" onClick={onRetry}>Tentar novamente</Button>} />
      : !schema?.tables.length ? <p className="muted">Nenhuma tabela disponível.</p>
        : <>
          <div className="schema-name"><DatabaseOutlined /> {schema.schema_name} <span>{schema.tables.length}</span></div>
          <Collapse ghost size="small" items={schema.tables.map((table) => ({
            key: table.name, label: <span className="table-name"><TableOutlined /> {table.name}</span>,
            children: <>
              <ul className="columns-list">
                {table.columns.map((column) => (
                  <li key={column.name}>
                    <span title={column.nullable ? 'Aceita nulo' : 'Obrigatória'}>{column.name}</span>
                    {table.primary_key.includes(column.name) && <Tag color="gold">PK</Tag>}
                    <small>{column.data_type}</small>
                  </li>
                ))}
              </ul>
              {table.foreign_keys.map((key) => (
                <p className="foreign-key" key={key.name}>
                  <Tag color="cyan">FK</Tag> {key.columns.join(', ')} → {key.referenced_schema}.{key.referenced_table} ({key.referenced_columns.join(', ')})
                </p>
              ))}
            </>,
          }))} />
        </>

  return (
    <aside className="workspace panel" aria-label="Explorador de dados">
      <div className="panel-heading">
        <h2>Explorador</h2>
        <Button type="text" size="small" aria-label="Atualizar schema" icon={<ReloadOutlined />} onClick={onRetry} disabled={loading} />
      </div>
      <Tabs items={[
        { key: 'schema', label: <><DatabaseOutlined /> Schema</>, children: schemaBody },
        {
          key: 'history', label: <><ClockCircleOutlined /> Histórico</>,
          children: history.length ? <ul className="history-list">{history.map((entry) => {
            const trace = traceUrl(entry.traceId)
            return <li key={entry.traceId}>
              <button type="button" title="Reutilizar pergunta" onClick={() => onReuse(entry)}>
                <strong>{entry.question}</strong>
                <span>{statuses[entry.status]} · {new Date(entry.time).toLocaleString('pt-BR')}</span>
                <span>{entry.model}</span>
              </button>
              {trace && <a className="history-trace" href={trace} target="_blank" rel="noopener noreferrer"><LinkOutlined /> Trace no Langfuse</a>}
            </li>
          })}</ul> : <p className="muted">Consultas concluídas aparecem aqui.</p>,
        },
      ]} />
    </aside>
  )
}
