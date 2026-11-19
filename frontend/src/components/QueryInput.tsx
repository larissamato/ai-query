import { CaretRightOutlined, CodeOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Alert, Button, Input, Select } from 'antd'
import type { FormEvent } from 'react'
import type { Models } from '../types'

const examples = [
  'Quantos pedidos foram registrados?',
  'Quantos pedidos foram registrados por mês?',
  'Quais cidades têm mais clientes?',
]

interface QueryInputProps {
  question: string
  onQuestion: (value: string) => void
  selected: string | undefined
  onModel: (value: string) => void
  models: Models | undefined
  modelLoading: boolean
  modelError: string | undefined
  onRetryModels: () => void
  running: boolean
  onRun: () => void
}

export function QueryInput(props: QueryInputProps) {
  const canRun = Boolean(props.question.trim() && !props.running
    && (props.selected || (!props.modelLoading && props.modelError)))
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (canRun) props.onRun()
  }

  return (
    <section className="panel composer">
      <div className="panel-heading">
        <h2><CodeOutlined /> Nova consulta</h2>
        <span className="dialect">PostgreSQL · Somente leitura</span>
      </div>
      <form onSubmit={submit}>
        <label htmlFor="question">Pergunta em linguagem natural</label>
        <Input.TextArea
          id="question" value={props.question} onChange={(event) => props.onQuestion(event.target.value)}
          maxLength={1000} rows={4} placeholder="Ex.: Quantos pedidos foram registrados por mês?"
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
              event.preventDefault()
              if (canRun) props.onRun()
            }
          }}
        />
        <div className="examples" aria-label="Perguntas de exemplo">
          <ThunderboltOutlined />
          {examples.map((example) => <button type="button" key={example} onClick={() => props.onQuestion(example)}>{example}</button>)}
        </div>
        <div className="composer-toolbar">
          <div className="model-field">
            <label htmlFor="model">Modelo</label>
            <Select
              id="model" aria-label="Modelo" value={props.selected} onChange={props.onModel}
              options={props.models?.models.map((value) => ({ value, label: value })) ?? []}
              loading={props.modelLoading} disabled={props.running || !props.models?.models.length}
              placeholder={props.modelError ? 'Padrão do backend' : 'Selecione um modelo'}
              showSearch
            />
            <Button type="text" aria-label="Atualizar modelos" onClick={props.onRetryModels} disabled={props.modelLoading || props.running} icon={<ReloadOutlined />} />
          </div>
          <div className="submit-field">
            <kbd>Ctrl / ⌘ + Enter</kbd>
            <Button type="primary" htmlType="submit" icon={<CaretRightOutlined />} disabled={!canRun} loading={props.running}>Executar consulta</Button>
          </div>
        </div>
        {props.modelError && <Alert type="warning" showIcon title={props.modelError} description="A execução pode tentar o modelo padrão do backend." />}
        {props.models && props.models.models.length === 0 && <Alert type="warning" showIcon title="Nenhum modelo instalado no Ollama." description="Instale um modelo e atualize a lista." />}
      </form>
    </section>
  )
}
