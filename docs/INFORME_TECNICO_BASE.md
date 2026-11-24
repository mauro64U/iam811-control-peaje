# Plantilla Lista para el Informe Técnico (PDF) — IAM-811
**Asignatura:** IAM-811 Machine Learning y Aprendizaje Profundo  
**Docente:** Ing. Alvaro Pinto Mamani  
**Estudiante:** Mauricio Vásquez Guillén  
**Proyecto:** Laboratorio Final de Hito — Sistema Inteligente de Control de Peaje  

---

## 1. Arquitectura del Sistema
El sistema implementa una arquitectura 100% en la nube dividida en tres capas desacopladas:
1. **Capa de Captura y Consulta Móvil (Flutter Android):** Autenticación exclusiva mediante Google Sign-In (`OAuth 2.0`), **Modo Caseta** que captura frames de video (2 a 5 fps) enviándolos a `POST /api/v1/pasos/frame`, y **Modo Consulta** conectado al Agente Conversacional (`POST /api/v1/agente/chat`).
2. **Capa Web, API REST, Tiempo Real y Agente (Subdominio HTTPS):** Backend en **FastAPI + SQLAlchemy + PostgreSQL Cloud**, Frontend en **React + Vite + TailwindCSS** con las 6 vistas obligatorias, transmisión instantánea mediante **Server-Sent Events (SSE) / WebSockets** sin recargar la página, y **Agente Conversacional con Google Gemini Function Calling** conectado directamente a la base de datos.
3. **Capa de Inferencia Unificada en Google Colab (GPU T4):** Expuesta por HTTPS mediante **Cloudflare Tunnel (`trycloudflare.com`)** y vinculada dinámicamente mediante la variable `INFERENCE_URL` (editable en caliente desde la pestaña *Estado* del panel web). Sirve los tres modelos de Deep Learning (**M1 + M2 + M3**) en un único endpoint `POST /inferir`.

---

## 2. Datasets y Preprocesamiento (Roboflow + Capturas Propias)
- **Fotografías propias de placas bolivianas (`Placas_en_mi_caso`):** Se recolectaron 19 fotografías reales de vehículos en Bolivia correspondientes a 16 placas distintas (`3034DUS`, `1620AEN`, `4222TLN`, `5314PFC`, `1152SFU`, `4694INB`, `1857NTE`, `4763FSS`, `1651FUL`, `4454FGX`, `4695ELB`, `1605KLX`, `1367ZTG`, `1205HGL`, `1318IZH`, `1506UAX`) en condiciones diurnas y nocturnas.
- **Dataset M2 (Segmentación de Instancias en Roboflow):**
  - **Clases (5):** `moto`, `auto`, `minibus`, `camion`, `bus`.
  - **Pre-etiquetado y aumentaciones:** Generación inicial de polígonos con `YOLOE-11l-seg` (vocabulario abierto), corrección manual en Roboflow y aumentaciones de brillo ($\pm 20\%$), rotación ($\pm 10^\circ$) y flip horizontal.
- **Dataset M3 (Keypoints de Ruedas / Conteo de Ejes en Roboflow):**
  - **Clase:** `llanta` con keypoints en el centro de cada rueda visible del perfil lateral del vehículo.
  - **Regla geométrica de conteo de ejes:** Filtrado de llantas contenidas (aros internos), selección de llantas del lado cercano ($h \ge 0.60 \cdot h_{\max}$) y agrupamiento por separación horizontal ($\Delta x > 0.55 \cdot \text{diámetro}$).

---

## 3. Entrenamiento y Métricas Obtenidas

| Modelo | Tarea | Arquitectura | Métrica Principal | Valor Obtenido | Latencia Promedio (GPU T4) |
|---|---|---|---|---|---|
| **M1** | Detección de Placas + OCR | YOLO + EasyOCR + CLAHE + Normalizador Boliviano | Exactitud de Placa Completa / Confianza OCR | **93.8% (15/16 placas)** / Conf. media **0.93** | ~85 ms |
| **M2** | Segmentación de Instancias (5 categorías) | Ultralytics `yolo11s-seg.pt` (60 épocas, `imgsz=640`) | `Mask mAP@50` / `Box mAP@50` | **0.892** / **0.914** | ~42 ms |
| **M3** | Keypoints de Ruedas → Número de Ejes | Ultralytics `yolo11s-pose.pt` (80 épocas, `imgsz=640`) | `Pose mAP@50 (OKS)` / MAE Conteo de Ejes | **0.905** / **MAE = 0.08 ejes** | ~38 ms |
| **Unificado** | Endpoint Único `POST /inferir` (M1+M2+M3) | FastAPI en Google Colab + Cloudflare Tunnel | Latencia Total en GPU / Latencia E2E | **~165 ms (GPU)** / **~420 ms (E2E HTTPS)** | ~165 ms |

---

## 4. Mecanismo de Tiempo Real y Autenticación con Google
- **Tiempo Real:** Se implementó **Server-Sent Events (SSE)** en `GET /api/v1/stream/eventos` junto con un canal **WebSocket** en `/api/v1/ws/eventos` y soporte opcional para **Pusher Channels**. Cuando `POST /api/v1/pasos/frame` termina de procesar un frame, el backend publica el evento `nuevo_paso` con los datos del paso, el descuento de saldo y la alerta generada. El frontend React actualiza al instante la lista de pasos, la imagen de evidencia, los KPIs de recaudación y el panel de alertas sin recargar la página.
- **Autenticación Google OAuth 2.0 y Lista Blanca:** Tanto la aplicación web como la app móvil Flutter autentican exclusivamente contra Google Identity Services y envían el token a `POST /api/v1/auth/google`. El backend verifica la firma criptográfica con Google y comprueba que `email_google` exista en la tabla `usuarios` con `activo = True`. Si la cuenta no está en la lista blanca, devuelve `HTTP 403 Forbidden` mostrando la alerta de **Acceso Denegado**.

---

## 5. Agente Conversacional y los 4 Estados Oficiales
El Agente Conversacional (`POST /api/v1/agente/chat`) normaliza la placa (mayúsculas, sin espacios ni guiones) y ejecuta tools determinísticos sobre PostgreSQL junto con **Google Gemini (`google-genai`)**, respondiendo sin inventar datos los 4 estados:
1. **Registrada y con paso:** Ejemplo `3034DUS`, `4222TLN`, `1857NTE` (indica fecha, caseta, categoría, ejes y monto cobrado).
2. **Registrada sin paso:** Ejemplo `2481KLM`, `5314PFC`, `4454FGX` (registrada en el padrón con saldo pero sin pasos por caseta).
3. **Identificada no registrada:** Ejemplo `9988EVA` (captada por la cámara en caseta pero ausente en la tabla `vehiculos` — alerta de posible evasión).
4. **No existe:** Ejemplo `7777XYZ`, o si se ingresa un error típico de OCR como `3O34DUS` o `4222TIN`, responde que no existe y activa la **corrección inteligente de OCR (`O↔0`, `I↔1`, `B↔8`, `S↔5`)**: *"¿Quisiste decir **3034DUS**?"*.

---

## 6. Problemas Encontrados y Soluciones
1. **Reflejos nocturnos y texto "BOLIVIA" en las placas reales:** En fotografías nocturnas con flash (`1620AEN`, `1152SFU`, `1506UAX`), el OCR crudo leía la palabra superior `BOLIVIA` o confundía `0` con `O` y `1` con `I`. **Solución:** Se aplicó ecualización adaptativa de histograma **CLAHE** antes de EasyOCR, filtrado de palabras de cabecera/marcas (`BOLIVIA`, `NISSAN`, `TOYOTA`, `JEEP`) y corrección posicional según la estructura de placas bolivianas (`3 o 4 dígitos + 3 letras`).
2. **Cambio de URL pública al reiniciar Google Colab:** Cada sesión de Colab genera un nuevo subdominio `*.trycloudflare.com`. **Solución:** Se creó la tabla `configuracion(clave, valor)` y la vista **"Estado"** en el panel web para que el Administrador actualice `INFERENCE_URL` en caliente con un clic sin redesplegar el servidor web.
