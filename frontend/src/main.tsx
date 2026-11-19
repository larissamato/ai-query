import { App as AntApp, ConfigProvider, theme } from 'antd'
import ptBR from 'antd/locale/pt_BR'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('Elemento raiz do playground ausente.')

createRoot(root).render(
  <StrictMode>
    <ConfigProvider locale={ptBR} theme={{
      algorithm: theme.darkAlgorithm,
      token: {
        colorPrimary: '#5ee0b5', colorInfo: '#69b6ff', colorSuccess: '#70e0b1',
        colorBgBase: '#10131b', colorBgContainer: '#171c27', colorBgElevated: '#1b2230',
        colorText: '#edf2fc', colorTextSecondary: '#a4afc4', colorBorder: '#343e53',
        colorSplit: '#2a3345', borderRadius: 8, fontSize: 14,
        fontFamily: 'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      },
      components: { Button: { primaryColor: '#091c17', fontWeight: 650 } },
    }}>
      <AntApp><App /></AntApp>
    </ConfigProvider>
  </StrictMode>,
)
