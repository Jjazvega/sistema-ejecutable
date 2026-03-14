import React from 'react'
import { FileText } from 'lucide-react'

export default function SearchResultItem({ hit }) {
  const score = typeof hit.score === 'number' ? (hit.score * 10).toFixed(1) : '0.0'

  return (
    <div className="search-result-card group bg-white p-6 rounded-2xl border border-gray-100 shadow-sm hover:shadow-xl hover:border-blue-200 transition-all duration-300">
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-50 text-blue-600 rounded-lg group-hover:bg-blue-600 group-hover:text-white transition-colors">
            <FileText size={22} />
          </div>
          <div>
            <h3 className="font-bold text-gray-900 text-lg">{hit.filename}</h3>
            <p className="text-xs text-gray-400 font-mono tracking-tighter">
              ID: {(hit.doc_id || hit.document_id || hit.id || '').toString().split('-')[0]}...
            </p>
          </div>
        </div>
        <div className="text-right">
          <span className="text-xs font-bold text-blue-500 bg-blue-50 px-2 py-1 rounded-md">
            MATCH: {score}%
          </span>
        </div>
      </div>

      <div className="search-highlight relative bg-gray-50 border-l-4 border-blue-400 p-4 rounded-r-xl">
        <span className="absolute -top-2 left-2 text-[10px] uppercase font-bold text-gray-400 bg-white px-1">
          Coincidencia de contenido
        </span>
        <p
          className="text-sm text-gray-600 leading-relaxed italic"
          dangerouslySetInnerHTML={{ __html: `"...${hit.highlight || 'No preview available'}..."` }}
        />
      </div>

      <div className="mt-5 flex items-center justify-end gap-3 border-t border-gray-50 pt-4">
        <button className="text-xs font-semibold text-gray-500 hover:text-blue-600 transition-colors">
          Metadatos
        </button>
        <button className="bg-blue-600 text-white text-xs font-bold px-4 py-2 rounded-lg hover:bg-blue-700 shadow-lg shadow-blue-100 transition-all">
          Abrir Documento
        </button>
      </div>
    </div>
  )
}
