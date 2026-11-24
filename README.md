# Sistema Inteligente de Control de Peaje (IAM-811)
**Asignatura:** IAM-811 Machine Learning y Aprendizaje Profundo  
**Docente:** Ing. Alvaro Pinto Mamani (`doc.alvaro.pinto.ma@unifranz.edu.bo`)  
**Autor:** Mauricio Vásquez Guillén  

Sistema integral de control de peaje basado en visión por computadora y aprendizaje profundo, desplegado **100% en la nube (cero recursos locales)** con inferencia unificada en **Google Colab (GPU T4)**, aplicación web en tiempo real publicada en subdominio HTTPS, agente conversacional con **Google Gemini Function Calling**, autenticación exclusiva mediante **Google OAuth 2.0** con lista blanca y aplicación móvil en **Flutter (Android)**.

---

## 1. Integrantes y Roles

| Integrante | Rol en el Proyecto | Responsabilidades Ejecutadas |
|---|---|---|
| **Mauricio Vásquez Guillén** | Arquitecto Full-Stack & Ingeniero de Machine Learning (Individual) | Recolección de dataset de placas bolivianas, etiquetado en Roboflow, entrenamiento de M2 (YOLO11-seg) y M3 (YOLO11-pose) en Google Colab, servidor unificado de inferencia M1+M2+M3, Backend FastAPI + PostgreSQL + SSE, Frontend React en Tiempo Real, Agente Conversacional Gemini y App Móvil Flutter. |

---

## 2. Arquitectura del Sistema

```
                  Google OAuth 2.0 (inicio de sesión Web y Android)
                       │                               │
App móvil (Flutter) ───┼── video/frames (2-5 fps) ───► Aplicación Web (Subdominio HTTPS)
  ├─ Modo Caseta       │                                 ├─ Panel Web en Tiempo Real (SSE / WS)
  └─ Modo Consulta ────┴── texto / foto de placa ──────► ├─ API REST (/api/v1/*) + PostgreSQL Cloud
                                                         └─ Agente Conversacional (Gemini + Tools BD)
                                                                  │
                                                                  ▼  INFERENCE_URL (Editable en vivo)
                                                       Google Colab (Endpoint Único POST /inferir)
                                                         ├─ M1: Detección de placas + EasyOCR (CLAHE + BoNorm)
                                                         ├─ M2: Segmentación de instancias (YOLO11-seg: 5 clases)
                                                         └─ M3: Keypoints sobre ruedas (YOLO11-pose → ejes)
```

---

## 3. Estructura del Repositorio

```text
/entrenamiento
  ├── M2_entrenamiento_segmentacion_vehiculos.ipynb              # Entrenamiento YOLO11-seg (moto, auto, minibus, camion, bus)
  └── M3_entrenamiento_keypoints_ruedas_y_validacion_M1.ipynb    # Entrenamiento YOLO11-pose (ruedas -> ejes) + Validación M1 OCR
/inferencia
  ├── Colab_Servidor_Unificado_M1_M2_M3.ipynb                    # Notebook listo para Google Colab con Cloudflare Tunnel
  └── servidor_inferencia_peaje.py                               # Script FastAPI del endpoint unificado POST /inferir
/web
  ├── Dockerfile                                                 # Contenedor unificado (Frontend + Backend en un solo subdominio)
  ├── backend/                                                   # FastAPI + SQLAlchemy + Seed 24 vehículos + Google Auth + SSE + Agente
  └── frontend/                                                  # React + Vite + TailwindCSS con las 6 páginas obligatorias
/movil
  ├── pubspec.yaml                                               # Dependencias Flutter (google_sign_in, camera, image_picker, http)
  └── lib/main.dart                                              # App móvil completa (Login Google, Modo Caseta, Modo Consulta)
/docs
  ├── postman_collection.json                                    # Colección Postman exportada con todas las rutas de la API REST
  ├── arquitectura_y_diagramas.md                                # Diagramas de arquitectura y secuencia en Mermaid
  └── INFORME_TECNICO_BASE.md                                    # Plantilla completa con métricas para exportar el Informe Técnico PDF
README.md
.env.example
.gitignore
GUIA_CONFIGURACION_MANUAL.md
```

---

## 4. Tecnologías Usadas

- **Modelos de Deep Learning (Google Colab GPU T4):**
  - **M1:** Detector de Placas + `EasyOCR` con preprocesamiento `CLAHE` y normalización posicional para placas bolivianas (`3-4 dígitos + 3 letras`).
  - **M2:** `Ultralytics YOLO11s-seg` (Segmentación de instancias para `moto`, `auto`, `minibus`, `camion`, `bus` y cálculo de `area_mascara`).
  - **M3:** `Ultralytics YOLO11s-pose` / `YOLOE-WheelPose` (Keypoints sobre el centro de ruedas visibles y estimación geométrica del número de `ejes`).
- **Datasets:** Roboflow (Instance Segmentation y Keypoint Detection) + 19 fotografías propias de placas bolivianas (`Placas_en_mi_caso`).
- **Backend Web y API REST:** Python 3.11, FastAPI, SQLAlchemy 2.0, PostgreSQL Cloud (Neon / Supabase / Render), Swagger/OpenAPI en `/api/docs`.
- **Tiempo Real:** Server-Sent Events (SSE) nativo en `/api/v1/stream/eventos`, WebSockets en `/api/v1/ws/eventos` y soporte integrable con Pusher.
- **Autenticación:** Google OAuth 2.0 (`google-auth` + Google Identity Services + `google_sign_in` en Android) con lista blanca en base de datos y roles `admin` y `operador`.
- **Agente Conversacional:** `google-genai` (Gemini 2.5 Flash) con Function Calling determinístico sobre la base de datos y corrección inteligente de confusiones típicas de OCR (`O↔0`, `I↔1`, `B↔8`, `S↔5`).
- **Frontend Web:** React 18, Vite, TailwindCSS, Lucide Icons.
- **Aplicación Móvil:** Flutter 3 (Android).

---

## 5. Instrucciones de Despliegue de Cada Componente

1. **Base de Datos PostgreSQL en la Nube:** Crear base de datos en **Neon.tech** o **Supabase** y copiar la cadena de conexión en la variable de entorno `DATABASE_URL`. Al arrancar el backend, `seed.py` crea las tablas y precarga automáticamente las tarifas, 3 casetas, **24 vehículos de prueba** (incluyendo las 16 placas bolivianas fotografiadas) y autoriza en la lista blanca al docente `doc.alvaro.pinto.ma@unifranz.edu.bo` con rol `admin`.
2. **Servidor de Inferencia en Google Colab:** Abrir `inferencia/Colab_Servidor_Unificado_M1_M2_M3.ipynb` en Google Colab con entorno **GPU T4**, ejecutar todas las celdas y copiar la URL HTTPS impresa por **Cloudflare Tunnel** (`https://xxxx.trycloudflare.com`).
3. **Aplicación Web y API REST en Subdominio HTTPS:** Desplegar la carpeta `/web` usando el `Dockerfile` incluido en **Render / Railway / Koyeb / VPS** configurando las variables de `.env.example`. Una vez desplegado, iniciar sesión con Google, abrir la pestaña **"Estado"** y pegar la URL del túnel de Google Colab (`INFERENCE_URL`).
4. **Aplicación Móvil Flutter:** Compilar el APK apuntando al subdominio HTTPS en producción:
   ```bash
   cd movil
   flutter pub get
   flutter build apk --release \
     --dart-define=API_BASE_URL=https://peaje.tudominio.com/api/v1 \
     --dart-define=GOOGLE_WEB_CLIENT_ID=tu-client-id-web.apps.googleusercontent.com
   ```

---

## 6. Enlaces de Entrega (Completar antes de subir a Moodle)

- **Subdominio de la Aplicación Web en Producción (HTTPS):** `https://peaje.tudominio.com`
- **Documentación Swagger / OpenAPI en Vivo:** `https://peaje.tudominio.com/api/docs`
- **Dataset M2 (Segmentación de Vehículos) en Roboflow:** `https://app.roboflow.com/tu-workspace/vehiculos-peaje-seg`
- **Dataset M3 (Keypoints de Ruedas/Ejes) en Roboflow:** `https://app.roboflow.com/tu-workspace/ruedas-ejes-pose`
- **Notebook del Endpoint de Inferencia en Google Colab:** `https://colab.research.google.com/drive/TU_ID_COLAB_INFERENCIA`
- **Carpeta en la Nube (Google Drive / OneDrive con Video, Informe PDF, APK y Capturas):** `https://drive.google.com/drive/folders/TU_ID_CARPETA`
