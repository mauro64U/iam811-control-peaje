# Guía Paso a Paso de Configuración Manual y Despliegue en la Nube (IAM-811)

Esta guía detalla exactamente **cada clic, comando y configuración externa** que debes realizar para dejar todo el sistema funcionando 100% en la nube y obtener los **100 puntos de la rúbrica** sin ninguna penalización.

---

## PASO 1: Crear tu Base de Datos PostgreSQL Gratis en la Nube (Neon.tech)

1. Entra a [https://neon.tech](https://neon.tech) e inicia sesión con tu cuenta de GitHub o Google.
2. Haz clic en **"New Project"**:
   - **Project name:** `iam811-peaje`
   - **Database name:** `peaje_db`
   - **Region:** `US East (Ohio)` o `South America (São Paulo)`
3. Al crearse, copia el **Connection string** que empieza con:
   ```text
   postgresql://neondb_owner:xxxx@ep-xxxx.us-east-2.aws.neon.tech/peaje_db?sslmode=require
   ```
4. Guarda ese enlace: será tu variable de entorno `DATABASE_URL`.
   > **Nota:** No necesitas crear tablas a mano. Al iniciar el backend (`web/backend/main.py`), `seed.py` creará automáticamente todas las tablas, tarifas, casetas, los **24 vehículos de prueba** (incluyendo tus 16 placas de `Placas_en_mi_caso`) y autorizará a `doc.alvaro.pinto.ma@unifranz.edu.bo` y tu propio correo (definido en `ADMIN_EMAILS`) como **Administradores**.

---

## PASO 2: Configurar Google Cloud Console para Google OAuth 2.0 (Web y Android)

1. Ve a [https://console.cloud.google.com/](https://console.cloud.google.com/) y crea un proyecto llamado **`IAM811-Control-Peaje`**.
2. En el menú izquierdo ve a **APIs y servicios > Pantalla de consentimiento de OAuth**:
   - Selecciona **Externo (External)** y haz clic en **Crear**.
   - **Nombre de la aplicación:** `Sistema Inteligente de Control de Peaje IAM-811`.
   - **Correo de asistencia del usuario y del desarrollador:** Tu correo de Gmail.
   - Guarda y continúa. En **Público (Audience)**, pulsa **"Publicar aplicación" (Publish App)** para que tanto tú como el docente (`doc.alvaro.pinto.ma@unifranz.edu.bo`) puedan iniciar sesión sin bloqueo de modo prueba.
3. Ve a **APIs y servicios > Credenciales > + Crear credenciales > ID de cliente de OAuth**:
   - **Cliente 1 (Para la Aplicación Web y validación del Backend):**
     - **Tipo de aplicación:** `Aplicación web`
     - **Nombre:** `Peaje Web Client`
     - **Orígenes de JavaScript autorizados:** Agrega la URL HTTPS de tu subdominio (por ejemplo `https://peaje-iam811.onrender.com` o `https://peaje.tudominio.com`).
     - Haz clic en **Crear** y copia el **ID de cliente** (`xxxx.apps.googleusercontent.com`). Este valor irá en `GOOGLE_CLIENT_ID` y en `VITE_GOOGLE_CLIENT_ID`.
   - **Cliente 2 (Para la Aplicación Móvil Android en Flutter):**
     - Primero obtén la huella **SHA-1** de tu llave de Android ejecutando en PowerShell:
       ```powershell
       keytool -list -v -keystore "$env:USERPROFILE\.android\debug.keystore" -alias androiddebugkey -storepass android -keypass android
       ```
     - En Google Cloud Console crea otro **ID de cliente de OAuth**:
       - **Tipo de aplicación:** `Android`
       - **Nombre del paquete:** `com.iam811.peaje_movil` (o el package name configurado en tu proyecto Flutter)
       - **Huella digital del certificado SHA-1:** Pega el SHA-1 obtenido.
     - Copia el ID de cliente Android generado y colócalo en `GOOGLE_ANDROID_CLIENT_ID`.

---

## PASO 3: Obtener tu API Key de Google Gemini para el Agente Conversacional

1. Entra a [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
2. Haz clic en **"Create API key"**.
3. Copia la clave generada y guárdala para la variable de entorno `GEMINI_API_KEY`.

---

## PASO 4: Etiquetar en Roboflow y Entrenar M2 y M3 en Google Colab

1. Crea una cuenta gratuita en [https://roboflow.com](https://roboflow.com).
2. Sube a Google Colab los dos notebooks de la carpeta `/entrenamiento`:
   - [M2_entrenamiento_segmentacion_vehiculos.ipynb](file:///C:/Users/USUARIO/Desktop/8vo%20sem/Inteligencia%20Artificial%20ll/LAB_3/LAB_3_placas/entrenamiento/M2_entrenamiento_segmentacion_vehiculos.ipynb)
   - [M3_entrenamiento_keypoints_ruedas_y_validacion_M1.ipynb](file:///C:/Users/USUARIO/Desktop/8vo%20sem/Inteligencia%20Artificial%20ll/LAB_3/LAB_3_placas/entrenamiento/M3_entrenamiento_keypoints_ruedas_y_validacion_M1.ipynb)
3. Si deseas pre-etiquetar tus imágenes automáticamente antes de subirlas a Roboflow:
   - En la sección 3 de `M2_entrenamiento_segmentacion_vehiculos.ipynb`, cambia `PREETIQUETAR_PROPIAS = True`, sube tus fotos de vehículos y descarga el `.zip` con los polígonos listos para importar en tu proyecto *Instance Segmentation* de Roboflow (`moto`, `auto`, `minibus`, `camion`, `bus`).
4. En el panel izquierdo de Google Colab, haz clic en el ícono de **Llave 🔑 (Secrets)** y agrega:
   - `ROBOFLOW_API_KEY`: Tu Private API Key de Roboflow.
   - `ROBOFLOW_WORKSPACE`: El ID de tu workspace en Roboflow.
   - `ROBOFLOW_PROJECT_M2`: El ID de tu proyecto de segmentación.
   - `ROBOFLOW_PROJECT_M3`: El ID de tu proyecto de keypoints de ruedas.
5. Ejecuta las celdas de entrenamiento y validación con **GPU T4**, toma capturas de pantalla de la tabla de métricas (`mAP@50`, matriz de confusión, error MAE de ejes y validación de tus 16 placas bolivianas) para tu Informe Técnico PDF y activa `GUARDAR_EN_DRIVE = True` en la última celda para guardar `m2_seg_best.pt` y `m3_pose_best.pt` en tu Google Drive (`/MyDrive/IAM811_Peaje_Pesos`).

---

## PASO 5: Levantar el Endpoint Único de Inferencia en Google Colab (`/inferencia`)

1. Abre Google Colab y sube el notebook [Colab_Servidor_Unificado_M1_M2_M3.ipynb](file:///C:/Users/USUARIO/Desktop/8vo%20sem/Inteligencia%20Artificial%20ll/LAB_3/LAB_3_placas/inferencia/Colab_Servidor_Unificado_M1_M2_M3.ipynb).
2. Ve a **Entorno de ejecución > Cambiar tipo de entorno de ejecución** y selecciona **GPU T4**.
3. Si guardaste tus pesos `.pt` en Google Drive, pon `MONTAR_DRIVE = True` en la celda 3. (Si lo dejas en `False`, el servidor funcionará igualmente de inmediato utilizando `EasyOCR + CLAHE + Normalizador Boliviano` para M1 y `YOLOE-11l-seg` para M2 y M3).
4. Ejecuta todas las celdas hasta la **Celda 5**.
5. Al final de la Celda 5 verás impreso en consola:
   ```text
   ======================================================================
   URL PUBLICA DE INFERENCIA (INFERENCE_URL): https://xxxx-xxxx.trycloudflare.com
   Health check: https://xxxx-xxxx.trycloudflare.com/health
   Endpoint unificado: https://xxxx-xxxx.trycloudflare.com/inferir
   ======================================================================
   ```
6. **Mantén esa pestaña de Google Colab abierta** durante tu demostración y durante la revisión del docente.

---

## PASO 6: Desplegar la Aplicación Web + API REST en un Subdominio HTTPS (Render / Railway / VPS)

El archivo [web/Dockerfile](file:///C:/Users/USUARIO/Desktop/8vo%20sem/Inteligencia%20Artificial%20ll/LAB_3/LAB_3_placas/web/Dockerfile) empaqueta automáticamente el Frontend React compilado y el Backend FastAPI en un solo servicio HTTPS:

1. Sube esta carpeta `LAB_3_placas` a tu repositorio en **GitHub / GitLab**:
   ```powershell
   cd "C:\Users\USUARIO\Desktop\8vo sem\Inteligencia Artificial ll\LAB_3\LAB_3_placas"
   git init
   git add .
   git status   # Verifica que .gitignore bloqueó cualquier .env o .pt
   git commit -m "feat: Sistema Inteligente de Control de Peaje IAM-811 completo"
   ```
2. Entra a [https://render.com](https://render.com) (o **Railway.app** / **Koyeb** / tu **VPS con subdominio propio**):
   - Crea un **New Web Service** conectado a tu repositorio Git.
   - **Root Directory:** `web`
   - **Runtime:** `Docker`
3. En la sección **Environment Variables** del servicio web, agrega:
   - `DATABASE_URL` = *(Tu cadena PostgreSQL de Neon del Paso 1)*
   - `GOOGLE_CLIENT_ID` = *(Tu Client ID Web de Google del Paso 2)*
   - `GOOGLE_ANDROID_CLIENT_ID` = *(Tu Client ID Android del Paso 2)*
   - `JWT_SECRET_KEY` = *(Una cadena aleatoria larga, ej. `iam811_super_secret_jwt_2026_unifranz_bolivia`)*
   - `ADMIN_EMAILS` = `doc.alvaro.pinto.ma@unifranz.edu.bo,lpze.mauriciosebastian.vasquez.gu@unifranz.edu.bo`
   - `INFERENCE_URL` = *(La URL `https://xxxx.trycloudflare.com` de tu Google Colab del Paso 5)*
   - `GEMINI_API_KEY` = *(Tu API key de Gemini del Paso 3)*
   - `VITE_GOOGLE_CLIENT_ID` = *(Tu Client ID Web de Google del Paso 2)*
   - `VITE_API_BASE_URL` = `/api/v1`
4. Una vez desplegado en tu subdominio HTTPS (por ejemplo `https://peaje.tudominio.com`):
   - Entra al subdominio e inicia sesión con tu cuenta de Google.
   - Ve a la pestaña **"Estado"**. Si en algún momento reinicias Google Colab y cambia la URL de `trycloudflare.com`, simplemente pégala ahí y pulsa **"Guardar INFERENCE_URL y Verificar Salud"** (se actualiza en vivo en la base de datos sin redesplegar).

---

## PASO 7: Compilar el APK de la Aplicación Móvil Flutter (`/movil`)

1. Si tienes Flutter SDK instalado en tu computadora, abre una terminal en `LAB_3_placas/movil`:
   ```powershell
   cd "C:\Users\USUARIO\Desktop\8vo sem\Inteligencia Artificial ll\LAB_3\LAB_3_placas\movil"
   flutter create . --project-name iam811_peaje_movil --org com.iam811
   flutter pub get
   flutter build apk --release `
     --dart-define=API_BASE_URL=https://peaje.tudominio.com/api/v1 `
     --dart-define=GOOGLE_WEB_CLIENT_ID=tu-google-client-id-web.apps.googleusercontent.com
   ```
   *(El comando `flutter create .` genera las carpetas nativas `android/` e `ios/` respetando el `pubspec.yaml` y `lib/main.dart` que ya creamos).*
2. Asegúrate de que en `movil/android/app/src/main/AndroidManifest.xml` estén declarados los permisos de Internet y Cámara:
   ```xml
   <uses-permission android:name="android.permission.INTERNET"/>
   <uses-permission android:name="android.permission.CAMERA"/>
   ```
3. El archivo APK integrable en tu carpeta de Google Drive se generará en:
   `movil/build/app/outputs/flutter-apk/app-release.apk`.

---

## PASO 8: Guion Exacto para Grabar tu Video Demostración (8 a 12 minutos — Sección 8 del PDF)

Sigue exactamente este orden al grabar tu pantalla para cubrir los 8 puntos obligatorios del video:

1. **Minuto 0:00 - 1:00 | Presentación y Arquitectura:** Muestra el diagrama de [docs/arquitectura_y_diagramas.md](file:///C:/Users/USUARIO/Desktop/8vo%20sem/Inteligencia%20Artificial%20ll/LAB_3/LAB_3_placas/docs/arquitectura_y_diagramas.md) explicando cómo la App Móvil envía frames al Subdominio Web, este consulta `INFERENCE_URL` en Google Colab (M1+M2+M3) y actualiza el panel en tiempo real por SSE.
2. **Minuto 1:00 - 2:30 | Login con Google OAuth 2.0 y Lista Blanca:**
   - Intenta iniciar sesión con una cuenta de Google **no autorizada** y muestra en cámara el mensaje rojo de **Acceso Denegado (403 - Lista Blanca)**.
   - Luego inicia sesión con tu cuenta autorizada en la Web y en la App Móvil.
3. **Minuto 2:30 - 4:30 | Pantalla Dividida (App Móvil en Modo Caseta + Panel Web en Tiempo Real):**
   - Coloca la App Móvil (Modo Caseta) a un lado y el Panel Web ("Panel en Tiempo Real") al otro.
   - Apunta la cámara a una de tus placas registradas con saldo (ej. `3034DUS`, `4222TLN` o `1857NTE`).
   - Muestra cómo la app recibe la placa, categoría, ejes, tarifa y estado `APROBADO`, y **al mismo instante, sin recargar la página**, aparece el paso con su foto de evidencia en el Panel Web y sube el contador de Recaudación.
4. **Minuto 4:30 - 5:30 | Alerta en Tiempo Real por Placa No Registrada o Sin Saldo:**
   - Captura una placa no registrada (o `1651FUL` que tiene saldo `Bs 0.00`) y muestra cómo aparece al instante una **Alerta Roja en Tiempo Real** en el panel web. Entra a la pestaña **Alertas** y márcala como atendida.
5. **Minuto 5:30 - 7:30 | Agente Conversacional respondiendo los 4 Estados (Texto e Imagen):**
   - Abre la pestaña **Chat Agente IA** (o el **Modo Consulta** en la app móvil) y realiza estas 5 pruebas rápidas:
     1. **Estado 1 (Registrada y con paso):** Escribe `3034-DUS` → muestra fecha, caseta, categoría y monto.
     2. **Estado 2 (Registrada sin paso):** Escribe `2481KLM` → muestra que está registrada pero nunca pasó por el peaje.
     3. **Estado 3 (Identificada no registrada):** Escribe `9988EVA` → muestra la alerta de posible evasión.
     4. **Estado 4 (No existe + Corrección OCR):** Escribe `3O34DUS` (con letra O en vez de cero) → muestra el estado *No existe* y la sugerencia *"¿Quisiste decir **3034DUS**?"*.
     5. **Consulta por Imagen:** Sube una de las fotos de `Placas_en_mi_caso` (por ejemplo `photo_3_2026-11-24_12-03-30.jpg` de la placa `4222TLN`) y muestra cómo el agente lee la placa con M1+OCR y devuelve su historial.
6. **Minuto 7:30 - 8:30 | Consola de Google Colab en Ejecución:** Muestra la pestaña de Google Colab con `Colab_Servidor_Unificado_M1_M2_M3.ipynb` procesando las peticiones `POST /inferir` en la GPU T4 y la pestaña **Estado** del panel web mostrando `ONLINE` con la latencia en milisegundos.
7. **Minuto 8:30 - 9:30 | Conclusiones y Métricas Principales:** Muestra las tablas de métricas de M1, M2 (`mAP@50`) y M3 (`MAE de conteo de ejes`) de tu Informe Técnico.
