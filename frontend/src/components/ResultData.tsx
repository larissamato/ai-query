import { BarChartOutlined } from '@ant-design/icons'
import { Alert, Table } from 'antd'
import type { Cell, QueryResult } from '../types'

export function formatCell(value: Cell | undefined): string {
  if (value === null) return 'NULL'
  if (value === undefined) return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function numeric(value: Cell | undefined) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined
  if (typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value)) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
}

export function chartData(result: QueryResult) {
  if (result.truncated || result.columns.length !== 2 || result.rows.length < 2 || result.rows.length > 20) return
  const labels = new Set<string>()
  const points: { label: string; value: number; display: string }[] = []
  for (const [label, raw] of result.rows) {
    const value = numeric(raw)
    if (typeof label !== 'string' || !label.trim() || numeric(label) !== undefined || labels.has(label) || value === undefined) return
    labels.add(label)
    points.push({ label, value, display: formatCell(raw) })
  }
  return points
}

function ResultChart({ result }: { result: QueryResult }) {
  const points = chartData(result)
  if (!points) return null
  const high = Math.max(0, ...points.map((point) => point.value))
  const low = Math.min(0, ...points.map((point) => point.value))
  const range = high - low || 1
  return (
    <figure className="chart" aria-label={`${result.columns[1]} por ${result.columns[0]}`}>
      <figcaption><BarChartOutlined /> {result.columns[1]} por {result.columns[0]}</figcaption>
      <ul>
        {points.map(({ label, value, display }) => (
          <li key={label}>
            <span title={label}>{label}</span>
            <div className="bar-track" aria-hidden>
              <div className={value < 0 ? 'chart-bar negative' : 'chart-bar'} style={{
                left: `${(Math.min(0, value) - low) / range * 100}%`,
                width: `${Math.abs(value) / range * 100}%`,
              }} />
            </div>
            <code>{display}</code>
          </li>
        ))}
      </ul>
    </figure>
  )
}

export default function ResultData({ result }: { result: QueryResult }) {
  const records = result.rows.map((cells, index) => ({ cells, index }))
  return (
    <>
      <div className="result-count">{result.rows.length} {result.rows.length === 1 ? 'linha' : 'linhas'} · {result.columns.length} {result.columns.length === 1 ? 'coluna' : 'colunas'}</div>
      {result.truncated && <Alert type="info" showIcon title="Resultado limitado a 100 linhas." />}
      <Table
        size="small" rowKey="index" dataSource={records}
        columns={result.columns.map((title, index) => ({
          key: index, title, render: (_value: unknown, row) => <span className={row.cells[index] === null ? 'muted' : ''}>{formatCell(row.cells[index])}</span>,
        }))}
        locale={{ emptyText: 'A consulta retornou zero linhas.' }}
        pagination={records.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
        scroll={{ x: 'max-content' }}
      />
      <ResultChart result={result} />
    </>
  )
}

