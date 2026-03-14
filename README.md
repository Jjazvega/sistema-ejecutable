# Enterprise Document System v4

Mejoras integradas:
- JWT login y roles `admin`, `editor`, `viewer`
- Versionado de documentos
- Metadatos sanitizados con Pydantic
- Upload individual PDF y upload masivo ZIP
- Protección contra path traversal en ZIP
- Health endpoint
- Reindexación masiva
- Indexación asíncrona con Celery + Redis
- Búsqueda full-text con ngram, facets y highlights en Elasticsearch
- Dashboard React con upload, listado, búsqueda y filtros

Arranque:
docker compose up --build

Credenciales seed:
- admin@example.com / admin123
- editor@example.com / editor123
- viewer@example.com / viewer123

Pruebas unitarias:
cd backend && pytest

Mejoras recientes:
- WebSocket de notificaciones por usuario
- Procesamiento seguro de ZIP con validación de límites y extracción segura
- Tarea Celery para procesar paquetes ZIP


Pruebas alineadas:
- test_zip_utils actualizado para coincidir con los mensajes actuales de seguridad ZIP
- runner incluido: `cd backend && ./run_tests.sh`
