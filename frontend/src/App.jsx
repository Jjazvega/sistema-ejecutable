import React, { useMemo, useState } from 'react'
import axios from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, Upload, FileText, CheckCircle, Clock, AlertCircle, Shield } from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import SearchResultItem from './components/SearchResultItem'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const api = axios.create({ baseURL: API_URL })

function StatusBadge({ status }) {
  const map = {
    INDEXED: { text: 'Indexado', bg: 'bg-green-100', color: 'text-green-700', icon: <CheckCircle size={14} /> },
    PROCESSING: { text: 'Procesando', bg: 'bg-blue-100', color: 'text-blue-700', icon: <Clock size={14} /> },
    FAILED: { text: 'Error', bg: 'bg-red-100', color: 'text-red-700', icon: <AlertCircle size={14} /> },
    PENDING: { text: 'Pendiente', bg: 'bg-gray-100', color: 'text-gray-700', icon: <Clock size={14} /> }
  }
  const cfg = map[status] || map.PENDING
  return <span className={`inline-flex gap-1.5 items-center px-3 py-1 rounded-full text-xs font-semibold ${cfg.bg} ${cfg.color}`}>{cfg.icon}{cfg.text}</span>
}

function Login({ onSuccess }) {
  const [email, setEmail] = useState('admin@example.com')
  const [password, setPassword] = useState('admin123')
  const mutation = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      form.append('email', email)
      form.append('password', password)
      const { data } = await api.post('/auth/login', form)
      return data
    },
    onSuccess
  })

  return (
    <div className="max-w-md mx-auto mt-20 bg-white p-8 rounded-2xl shadow-xl">
      <div className="flex items-center gap-3 mb-5"><Shield /><h1 className="m-0 text-2xl font-bold">Acceso</h1></div>
      <input value={email} onChange={e=>setEmail(e.target.value)} className="w-full p-3 border border-gray-300 rounded-xl mb-3" />
      <input value={password} onChange={e=>setPassword(e.target.value)} type="password" className="w-full p-3 border border-gray-300 rounded-xl mb-3" />
      <button onClick={()=>mutation.mutate()} className="w-full p-3 border-0 rounded-xl bg-blue-600 text-white font-bold">
        {mutation.isPending ? 'Entrando...' : 'Entrar'}
      </button>
    </div>
  )
}

function Uploader({ token }) {
  const qc = useQueryClient()
  const [metadata, setMetadata] = useState('{"department":"legal"}')
  const [file, setFile] = useState(null)
  const onDrop = React.useCallback((accepted) => setFile(accepted[0] || null), [])
  const { getRootProps, getInputProps } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: false
  })

  const mutation = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      form.append('file', file)
      form.append('metadata', metadata)
      const { data } = await api.post('/upload', form, {
        headers: { Authorization: `Bearer ${token}` }
      })
      return data
    },
    onSuccess: () => {
      setFile(null)
      qc.invalidateQueries({ queryKey: ['documents'] })
    }
  })

  return (
    <div className="bg-white p-6 rounded-2xl border border-gray-100 mb-6 shadow-sm">
      <div {...getRootProps()} className="border-2 border-dashed border-slate-300 p-8 rounded-2xl text-center cursor-pointer">
        <input {...getInputProps()} />
        <Upload size={34} className="mx-auto opacity-70" />
        <p className="mt-2">Arrastra tu PDF aquí o haz clic</p>
      </div>
      <input value={metadata} onChange={e=>setMetadata(e.target.value)} className="w-full p-3 border border-gray-300 rounded-xl mt-3" />
      {file && <div className="mt-3 text-sm font-medium">{file.name}</div>}
      {file && (
        <button onClick={()=>mutation.mutate()} className="mt-3 px-4 py-3 rounded-xl bg-blue-600 text-white font-bold">
          {mutation.isPending ? 'Subiendo...' : 'Iniciar indexación'}
        </button>
      )}
    </div>
  )
}

export default function App() {
  const [auth, setAuth] = useState(() => {
    const raw = localStorage.getItem('enterprise-auth')
    return raw ? JSON.parse(raw) : null
  })
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')

  const headers = useMemo(() => auth ? { Authorization: `Bearer ${auth.access_token}` } : {}, [auth])

  const documentsQuery = useQuery({
    queryKey: ['documents', auth?.access_token],
    enabled: !!auth,
    queryFn: async () => {
      const { data } = await api.get('/documents', { headers })
      return data
    },
    refetchInterval: (queryObj) => {
      const docs = queryObj?.state?.data || []
      return docs.some(d => d.status === 'PENDING' || d.status === 'PROCESSING') ? 3000 : false
    }
  })

  const searchQuery = useQuery({
    queryKey: ['search', auth?.access_token, query, status],
    enabled: !!auth && query.length > 0,
    queryFn: async () => {
      const { data } = await api.get('/documents/search', { headers, params: { q: query, status } })
      return data
    }
  })

  if (!auth) {
    return <Login onSuccess={(data) => { localStorage.setItem('enterprise-auth', JSON.stringify(data)); setAuth(data) }} />
  }

  const docs = query ? (searchQuery.data?.items || []) : (documentsQuery.data || [])

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="m-0 mb-1 text-3xl font-bold">Gestión Documental Enterprise</h1>
          <p className="m-0 text-slate-500">Búsqueda, versiones, estados y seguridad por roles</p>
        </div>
        <button onClick={() => { localStorage.removeItem('enterprise-auth'); setAuth(null) }} className="px-4 py-2 rounded-xl border border-gray-300 bg-white">Salir</button>
      </div>

      {(auth.role === 'admin' || auth.role === 'editor') && <Uploader token={auth.access_token} />}

      <div className="grid grid-cols-1 md:grid-cols-[1fr_180px] gap-3 mb-5">
        <div className="relative">
          <Search size={18} className="absolute left-3 top-3.5 text-slate-500" />
          <input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Buscar por contenido, nombre o metadatos" className="w-full pl-10 pr-4 py-3 rounded-xl border border-gray-300" />
        </div>
        <select value={status} onChange={e=>setStatus(e.target.value)} className="px-3 py-3 rounded-xl border border-gray-300 bg-white">
          <option value="all">Todos</option>
          <option value="PENDING">Pendiente</option>
          <option value="PROCESSING">Procesando</option>
          <option value="INDEXED">Indexado</option>
          <option value="FAILED">Error</option>
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">
        <div>
          {!query && docs.map((doc) => (
            <div key={doc.id} className="bg-white border border-gray-200 rounded-2xl p-4 mb-3 flex justify-between items-center shadow-sm">
              <div className="flex gap-4 items-center">
                <div className="p-3 rounded-xl bg-blue-50 text-blue-600"><FileText size={22} /></div>
                <div>
                  <div className="font-bold">{doc.filename}</div>
                  <div className="text-xs text-slate-500">v{doc.version || 1}</div>
                  {(doc.status === 'PENDING' || doc.status === 'PROCESSING') && (
                    <div className="mt-2 h-1.5 w-28 rounded indexing-pulse"></div>
                  )}
                </div>
              </div>
              <StatusBadge status={doc.status} />
            </div>
          ))}

          {query && docs.map((hit) => (
            <SearchResultItem
              key={hit.id || hit.doc_id || hit.document_id}
              hit={{
                ...hit,
                doc_id: hit.document_id || hit.doc_id || hit.id,
                highlight: hit.highlight?.content?.[0] || hit.highlight?.filename?.[0] || hit.highlight || 'No preview available'
              }}
            />
          ))}
        </div>

        <div className="bg-white border border-gray-200 rounded-2xl p-4 h-fit shadow-sm">
          <h3 className="mt-0 mb-4 text-lg font-bold">Facetas</h3>
          {searchQuery.data?.facets?.statuses?.buckets?.map((b) => (
            <div key={b.key} className="flex justify-between mb-2 text-sm">
              <span>{b.key}</span><strong>{b.doc_count}</strong>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
