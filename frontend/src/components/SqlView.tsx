import { CopyOutlined } from '@ant-design/icons'
import { App, Button } from 'antd'
import hljs from 'highlight.js/lib/core'
import pgsql from 'highlight.js/lib/languages/pgsql'
import { useMemo } from 'react'

hljs.registerLanguage('pgsql', pgsql)

export default function SqlView({ sql }: { sql: string }) {
  const { message } = App.useApp()
  const html = useMemo(() => hljs.highlight(sql, { language: 'pgsql' }).value, [sql])
  async function copy() {
    try {
      await navigator.clipboard.writeText(sql)
      void message.success('SQL copiado.')
    } catch {
      void message.error('Não foi possível copiar o SQL.')
    }
  }

  return (
    <div className="code-view">
      <div className="code-toolbar"><span>PostgreSQL · Somente leitura</span><Button size="small" onClick={() => void copy()} icon={<CopyOutlined />}>Copiar</Button></div>
      <pre tabIndex={0} aria-label="SQL gerado, somente leitura"><code className="hljs" dangerouslySetInnerHTML={{ __html: html }} /></pre>
    </div>
  )
}

