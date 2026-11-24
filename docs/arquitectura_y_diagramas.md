# Diagramas de Arquitectura y Flujo del Sistema Inteligente de Control de Peaje (IAM-811)

## 1. Arquitectura General Cloud-Native (100% Nube sin Recursos Locales)

```mermaid
flowchart TD
    subgraph GoogleCloud["Google Cloud Platform (Identity & AI)"]
        OAuth["Google OAuth 2.0 (Web & Android Sign-In)"]
        Gemini["Google Gemini API (Function Calling)"]
    end

    subgraph Mobile["Aplicación Móvil (Flutter Android)"]
        LoginMovil["Google Sign-In"]
        ModoCaseta["Modo Caseta (Cámara en Vivo 2-5 fps)"]
        ModoConsulta["Modo Consulta (Texto o Foto)"]
    end

    subgraph WebCloud["Subdominio Público HTTPS (Panel Web + API REST + Tiempo Real)"]
        Frontend["Panel Web React + Tailwind (6 Vistas)"]
        Backend["API REST FastAPI (/api/v1/*)"]
        SSE["Motor Tiempo Real (SSE / WebSockets / Pusher)"]
        Agent["Agente Conversacional (4 Estados + Corrección OCR)"]
        DB[("PostgreSQL Cloud (Neon / Supabase)\nusuarios, vehiculos, casetas,\ntarifas, pasos, alertas, configuracion")]
    end

    subgraph Colab["Google Colab (GPU T4) + Cloudflare Tunnel"]
        Endpoint["POST /inferir (Endpoint Único)"]
        M1["M1: Detección de Placas + EasyOCR (CLAHE + Normalización Bo)"]
        M2["M2: Segmentación de Instancias (YOLO11-seg: moto, auto, minibus, camion, bus)"]
        M3["M3: Keypoints sobre Ruedas (YOLO11-pose -> Conteo de Ejes)"]
    end

    subgraph RoboflowCloud["Roboflow"]
        Datasets["Datasets Etiquetados (M2 Máscaras y M3 Keypoints)"]
    end

    LoginMovil -->|Valida id_token| OAuth
    Frontend -->|Valida credential| OAuth
    ModoCaseta -->|POST /api/v1/pasos/frame| Backend
    ModoConsulta -->|POST /api/v1/agente/chat| Agent
    Backend <-->|SQLAlchemy| DB
    Backend -->|INFERENCE_URLEditable en vivo| Endpoint
    Endpoint --> M1
    Endpoint --> M2
    Endpoint --> M3
    Backend -->|Emite nuevo_paso / alerta| SSE
    SSE -->|Actualización instantánea sin recargar| Frontend
    Agent <-->|Tools sobre BD| DB
    Agent <-->|Redacción estricta| Gemini
    Datasets -->|Descarga YOLOv11| Colab
```

---

## 2. Diagrama de Secuencia: Registro de Vehículo en Caseta y Tiempo Real

```mermaid
sequenceDiagram
    actor Op as Operador (App Móvil)
    participant API as Backend Web (/api/v1/pasos/frame)
    participant Colab as Google Colab (POST /inferir)
    participant DB as Base de Datos (PostgreSQL)
    participant Panel as Panel Web (Stream SSE)

    Op->>API: Envía frame JPEG + Bearer JWT + caseta_id
    API->>DB: Lee INFERENCE_URL activa
    API->>Colab: Envía imagen al único endpoint /inferir
    Colab->>Colab: Ejecuta M1 (Placa + EasyOCR)
    Colab->>Colab: Ejecuta M2 (YOLO-seg -> categoría y área máscara)
    Colab->>Colab: Ejecuta M3 (YOLO-pose -> keypoints ruedas -> ejes)
    Colab-->>API: JSON {placa, confianza, categoria, ejes, latencia_ms}
    API->>DB: Consulta vehículo por placa normalizada y calcula tarifa(categoria, ejes)
    alt Vehículo registrado y con saldo suficiente
        API->>DB: Descuenta saldo y guarda Paso (estado = APROBADO)
    else Placa no registrada o sin saldo
        API->>DB: Guarda Paso (NO_REGISTRADO / SIN_SALDO) y crea Alerta
    end
    API-->>Panel: Emite evento SSE "nuevo_paso" (paso + alerta + imagen_url)
    Panel->>Panel: Actualiza tabla, recaudación y alertas sin recargar la página
    API-->>Op: Devuelve JSON con placa, categoría, ejes, tarifa y estado
```
