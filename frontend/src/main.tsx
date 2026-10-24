import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { App } from './app/App'
import './styles/app.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 },
  },
})
queryClient.setQueryDefaults(['settings'], { staleTime: 5 * 60_000 })
queryClient.setQueryDefaults(['dimensions'], { staleTime: Infinity, gcTime: Infinity })
queryClient.setQueryDefaults(['playlist-options'], { staleTime: 5 * 60_000 })
queryClient.setQueryDefaults(['watched-mixes'], { staleTime: 5 * 60_000 })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
