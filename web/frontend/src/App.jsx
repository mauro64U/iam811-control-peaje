import React, { useState, useEffect, useRef } from "react";
import {
  Activity,
  Car,
  History,
  AlertTriangle,
  MessageSquare,
  Server,
  LogOut,
  CheckCircle2,
  XCircle,
  Upload,
  Plus,
  Trash2,
  Edit3,
  RefreshCw,
  Send,
  ShieldAlert,
  Camera,
  DollarSign,
} from "lucide-react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");
const ORIGIN_BASE = API_BASE.startsWith("http") ? new URL(API_BASE).origin : "";
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

function urlEvidencia(path) {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return `${ORIGIN_BASE}${path}`;
}

function BadgeEstado({ estado }) {
  const map = {
    APROBADO: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    SIN_SALDO: "bg-amber-500/20 text-amber-300 border-amber-500/40",
    NO_REGISTRADO: "bg-rose-500/20 text-rose-300 border-rose-500/40",
    PLACA_ILEGIBLE: "bg-purple-500/20 text-purple-300 border-purple-500/40",
  };
  return (
    <span className={`px-2.5 py-0.5 text-xs font-semibold rounded-full border ${map[estado] || "bg-slate-700 text-slate-200"}`}>
      {estado}
    </span>
  );
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem("peaje_jwt") || "");
  const [usuario, setUsuario] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("peaje_user") || "null");
    } catch {
      return null;
    }
  });
  const [authError, setAuthError] = useState("");
  const [activeTab, setActiveTab] = useState("tiempo_real");
  const [sseConectado, setSseConectado] = useState(false);

  // Estado del Dashboard en Tiempo Real
  const [kpis, setKpis] = useState({
    total_pasos: 0,
    recaudacion_total_bs: 0,
    alertas_pendientes: 0,
    total_vehiculos: 0,
  });
  const [pasos, setPasos] = useState([]);
  const [alertas, setAlertas] = useState([]);
  const [vehiculos, setVehiculos] = useState([]);
  const [casetas, setCasetas] = useState([]);

  // Estado de Filtros en Historial de Pasos
  const [filtroPlaca, setFiltroPlaca] = useState("");
  const [filtroCategoria, setFiltroCategoria] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("");

  // Estado para Prueba de Caseta desde Web (Subir Frame a /api/v1/pasos/frame)
  const [casetaActiva, setCasetaActiva] = useState(1);
  const [subiendoFrame, setSubiendoFrame] = useState(false);
  const [ultimoResultadoCaseta, setUltimoResultadoCaseta] = useState(null);

  // Estado CRUD de Vehículos
  const [formVehiculo, setFormVehiculo] = useState({
    id: null,
    placa: "",
    propietario: "",
    categoria: "auto",
    ejes: 2,
    saldo: 100,
    activo: true,
  });

  // Estado del Agente Conversacional
  const [mensajesChat, setMensajesChat] = useState([
    {
      rol: "agente",
      texto:
        "Hola, soy el Agente Conversacional de Control de Peaje (IAM-811). Escribe una placa (ej. 3034DUS, 2481KLM, 9988EVA o con error OCR como 3O34DUS) o sube la foto de un vehículo para consultar su estado entre los 4 estados oficiales.",
      estado: "Listo",
    },
  ]);
  const [inputChat, setInputChat] = useState("");
  const [imagenChat, setImagenChat] = useState(null);
  const [enviandoChat, setEnviandoChat] = useState(false);

  // Estado del Servidor de Inferencia en Google Colab
  const [estadoColab, setEstadoColab] = useState({
    online: false,
    inference_url: "",
    latencia_ms: null,
    detalle: "",
    remoto: null,
  });
  const [nuevaUrlColab, setNuevaUrlColab] = useState("");
  const [nuevoTokenColab, setNuevoTokenColab] = useState("");
  const [verificandoColab, setVerificandoColab] = useState(false);

  const googleBtnRef = useRef(null);

  // Helper de peticiones autenticadas
  async function apiFetch(endpoint, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const resp = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
    if (resp.status === 401) {
      cerrarSesion();
      throw new Error("Sesión expirada. Inicie sesión con Google nuevamente.");
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || `Error HTTP ${resp.status}`);
    }
    return data;
  }

  function cerrarSesion() {
    localStorage.removeItem("peaje_jwt");
    localStorage.removeItem("peaje_user");
    setToken("");
    setUsuario(null);
    setSseConectado(false);
  }

  // Inicializar botón oficial de Google Sign-In (OAuth 2.0)
  useEffect(() => {
    if (token) return;
    const timer = setInterval(() => {
      if (window.google && window.google.accounts && googleBtnRef.current) {
        clearInterval(timer);
        if (!GOOGLE_CLIENT_ID) return;
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: async (response) => {
            setAuthError("");
            try {
              const res = await fetch(`${API_BASE}/auth/google`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: response.credential }),
              });
              const data = await res.json();
              if (!res.ok) {
                setAuthError(data.detail || "Acceso denegado (403): Cuenta no autorizada en la lista blanca.");
                return;
              }
              localStorage.setItem("peaje_jwt", data.access_token);
              localStorage.setItem("peaje_user", JSON.stringify(data.usuario));
              setToken(data.access_token);
              setUsuario(data.usuario);
            } catch (err) {
              setAuthError(err.message);
            }
          },
        });
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: "filled_blue",
          size: "large",
          text: "signin_with",
          shape: "pill",
          width: 320,
        });
      }
    }, 300);
    return () => clearInterval(timer);
  }, [token]);

  // Cargar datos iniciales y conectar stream SSE en tiempo real
  useEffect(() => {
    if (!token) return;
    cargarTodo();

    const sseUrl = `${API_BASE}/stream/eventos?token=${encodeURIComponent(token)}`;
    const es = new EventSource(sseUrl);

    es.onopen = () => setSseConectado(true);
    es.onerror = () => setSseConectado(false);
    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.evento === "conectado") {
          setSseConectado(true);
        } else if (msg.evento === "nuevo_paso") {
          const { paso, alerta } = msg.datos;
          setPasos((prev) => [paso, ...prev.filter((p) => p.id !== paso.id)]);
          setKpis((prev) => ({
            ...prev,
            total_pasos: prev.total_pasos + 1,
            recaudacion_total_bs:
              paso.estado === "APROBADO"
                ? Number((prev.recaudacion_total_bs + paso.monto).toFixed(2))
                : prev.recaudacion_total_bs,
            alertas_pendientes: alerta ? prev.alertas_pendientes + 1 : prev.alertas_pendientes,
          }));
          if (alerta) {
            setAlertas((prev) => [alerta, ...prev]);
          }
          cargarVehiculos();
        } else if (msg.evento === "alerta_atendida") {
          setAlertas((prev) => prev.map((a) => (a.id === msg.datos.id ? { ...a, atendida: true } : a)));
          setKpis((prev) => ({ ...prev, alertas_pendientes: Math.max(0, prev.alertas_pendientes - 1) }));
        }
      } catch {
        // Ignorar keep-alive
      }
    };

    return () => es.close();
  }, [token]);

  async function cargarTodo() {
    try {
      const [dash, listaVeh, listaCas, estColab] = await Promise.all([
        apiFetch("/dashboard/resumen"),
        apiFetch("/vehiculos"),
        apiFetch("/casetas"),
        apiFetch("/estado/inferencia"),
      ]);
      setKpis(dash.kpis);
      setPasos(dash.pasos);
      setAlertas(dash.alertas);
      setVehiculos(listaVeh);
      setCasetas(listaCas);
      setEstadoColab(estColab);
      setNuevaUrlColab(estColab.inference_url || "");
    } catch (e) {
      console.error(e);
    }
  }

  async function cargarVehiculos() {
    try {
      const listaVeh = await apiFetch("/vehiculos");
      setVehiculos(listaVeh);
    } catch (e) {
      console.error(e);
    }
  }

  async function filtrarHistorialPasos() {
    const params = new URLSearchParams();
    if (filtroPlaca) params.set("placa", filtroPlaca);
    if (filtroCategoria) params.set("categoria", filtroCategoria);
    if (filtroEstado) params.set("estado", filtroEstado);
    const data = await apiFetch(`/pasos?${params.toString()}`);
    setPasos(data);
  }

  async function enviarFrameCaseta(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setSubiendoFrame(true);
    setUltimoResultadoCaseta(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("caseta_id", String(casetaActiva));
      const res = await apiFetch("/pasos/frame", { method: "POST", body: fd });
      setUltimoResultadoCaseta(res);
    } catch (err) {
      alert(err.message);
    } finally {
      setSubiendoFrame(false);
      e.target.value = "";
    }
  }

  async function guardarVehiculo(e) {
    e.preventDefault();
    try {
      if (formVehiculo.id) {
        await apiFetch(`/vehiculos/${formVehiculo.id}`, {
          method: "PUT",
          body: JSON.stringify(formVehiculo),
        });
      } else {
        await apiFetch("/vehiculos", {
          method: "POST",
          body: JSON.stringify(formVehiculo),
        });
      }
      setFormVehiculo({ id: null, placa: "", propietario: "", categoria: "auto", ejes: 2, saldo: 100, activo: true });
      await cargarTodo();
    } catch (err) {
      alert(err.message);
    }
  }

  async function borrarVehiculo(id) {
    try {
      await apiFetch(`/vehiculos/${id}`, { method: "DELETE" });
      await cargarTodo();
    } catch (err) {
      alert(err.message);
    }
  }

  async function marcarAlertaAtendida(id) {
    try {
      await apiFetch(`/alertas/${id}/atender`, { method: "PATCH" });
    } catch (err) {
      alert(err.message);
    }
  }

  async function enviarMensajeAgente(e) {
    e.preventDefault();
    if (!inputChat.trim() && !imagenChat) return;
    const textoUsuario = inputChat.trim() || (imagenChat ? `[Imagen: ${imagenChat.name}]` : "");
    setMensajesChat((prev) => [...prev, { rol: "usuario", texto: textoUsuario }]);
    setInputChat("");
    setEnviandoChat(true);
    try {
      const fd = new FormData();
      if (inputChat.trim()) fd.append("mensaje", inputChat.trim());
      if (imagenChat) fd.append("file", imagenChat);
      const res = await apiFetch("/agente/chat", { method: "POST", body: fd });
      setMensajesChat((prev) => [
        ...prev,
        {
          rol: "agente",
          texto: res.respuesta,
          estado: res.estado,
          placa: res.placa_normalizada,
          sugerencias: res.sugerencias || [],
        },
      ]);
    } catch (err) {
      setMensajesChat((prev) => [
        ...prev,
        { rol: "agente", texto: `Error al consultar al agente: ${err.message}`, estado: "Error" },
      ]);
    } finally {
      setImagenChat(null);
      setEnviandoChat(false);
    }
  }

  async function probarYGuardarColab(e) {
    e.preventDefault();
    setVerificandoColab(true);
    try {
      if (usuario?.rol === "admin" && nuevaUrlColab.trim()) {
        await apiFetch("/estado/inferencia", {
          method: "PUT",
          body: JSON.stringify({
            inference_url: nuevaUrlColab.trim(),
            inference_api_token: nuevoTokenColab.trim(),
          }),
        });
      }
      const est = await apiFetch("/estado/inferencia");
      setEstadoColab(est);
    } catch (err) {
      alert(err.message);
    } finally {
      setVerificandoColab(false);
    }
  }

  // ==================== PANTALLA DE LOGIN CON GOOGLE OAUTH 2.0 ====================
  if (!token || !usuario) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 rounded-xl bg-blue-600/20 border border-blue-500/40 text-blue-400">
              <Car className="w-7 h-7" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">Control Inteligente de Peaje</h1>
              <p className="text-xs text-slate-400">IAM-811 Machine Learning y Aprendizaje Profundo</p>
            </div>
          </div>

          <p className="text-sm text-slate-300 mb-6 leading-relaxed">
            Acceso exclusivo mediante <strong>Google OAuth 2.0</strong>. Solo las cuentas autorizadas en la lista blanca
            (Roles: <code className="text-blue-400">Administrador</code> y <code className="text-emerald-400">Operador</code>)
            pueden ingresar al sistema.
          </p>

          {authError && (
            <div className="mb-6 p-4 rounded-xl bg-rose-500/15 border border-rose-500/40 text-rose-200 text-sm flex items-start gap-3">
              <ShieldAlert className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-rose-300">Acceso Denegado (Lista Blanca)</p>
                <p className="text-xs mt-1">{authError}</p>
              </div>
            </div>
          )}

          <div className="flex flex-col items-center justify-center py-4 bg-slate-950/60 rounded-xl border border-slate-800">
            <div ref={googleBtnRef} />
            {!GOOGLE_CLIENT_ID && (
              <p className="text-xs text-amber-400 px-4 text-center mt-2">
                Configure <code>VITE_GOOGLE_CLIENT_ID</code> en variables de entorno para renderizar el botón de Google Identity Services.
              </p>
            )}
          </div>

          <div className="mt-6 pt-5 border-t border-slate-800 text-xs text-slate-400 space-y-1">
            <p>• Admin Docente: <code className="text-slate-200">doc.alvaro.pinto.ma@unifranz.edu.bo</code></p>
            <p>• Admin Estudiante: <code className="text-slate-200">lpze.mauriciosebastian.vasquez.gu@unifranz.edu.bo</code></p>
            <p>• Inferencia en la nube: <code className="text-slate-200">M1 (EasyOCR) + M2 (YOLO-seg) + M3 (YOLO-pose)</code></p>
          </div>
        </div>
      </div>
    );
  }

  // ==================== PANEL WEB PRINCIPAL CON LAS 6 PÁGINAS OBLIGATORIAS ====================
  const navItems = [
    { id: "tiempo_real", label: "Panel en Tiempo Real", icon: Activity },
    { id: "vehiculos", label: "Vehículos (CRUD)", icon: Car },
    { id: "pasos", label: "Pasos e Historial", icon: History },
    { id: "alertas", label: `Alertas (${kpis.alertas_pendientes})`, icon: AlertTriangle },
    { id: "chat", label: "Chat Agente IA", icon: MessageSquare },
    { id: "estado", label: "Estado Inferencia", icon: Server },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Barra superior */}
      <header className="bg-slate-900/90 backdrop-blur border-b border-slate-800 px-6 py-3.5 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-20">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-blue-600/20 border border-blue-500/40 text-blue-400">
            <Car className="w-6 h-6" />
          </div>
          <div>
            <h1 className="font-bold text-base text-white">IAM-811 · Sistema Inteligente de Control de Peaje</h1>
            <div className="flex items-center gap-3 text-xs text-slate-400">
              <span className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${sseConectado ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
                {sseConectado ? "Tiempo Real SSE Conectado" : "Reconectando stream..."}
              </span>
              <span>•</span>
              <span className="flex items-center gap-1">
                Colab M1+M2+M3:{" "}
                <strong className={estadoColab.online ? "text-emerald-400" : "text-rose-400"}>
                  {estadoColab.online ? `ONLINE (${estadoColab.latencia_ms} ms)` : "OFFLINE"}
                </strong>
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-sm font-medium text-white">{usuario.nombre}</p>
            <p className="text-xs text-slate-400">
              {usuario.email_google} ·{" "}
              <span className="uppercase font-semibold text-blue-400">{usuario.rol}</span>
            </p>
          </div>
          <button
            onClick={cerrarSesion}
            className="p-2 rounded-lg bg-slate-800 hover:bg-rose-500/20 hover:text-rose-300 text-slate-300 transition"
            title="Cerrar sesión"
          >
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* Navegación de las 6 páginas obligatorias */}
      <nav className="bg-slate-900 border-b border-slate-800 px-6 flex gap-2 overflow-x-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition whitespace-nowrap ${
                active
                  ? "border-blue-500 text-blue-400 bg-blue-500/10"
                  : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Icon className="w-4 h-4" />
              {item.label}
            </button>
          );
        })}
      </nav>

      {/* Contenido de la página activa */}
      <main className="flex-1 p-6 max-w-7xl w-full mx-auto space-y-6">
        {/* ==================== PÁGINA 1: PANEL EN TIEMPO REAL ==================== */}
        {activeTab === "tiempo_real" && (
          <div className="space-y-6">
            {/* Tarjetas de KPIs en Tiempo Real */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <p className="text-xs text-slate-400 uppercase">Pasos Registrados</p>
                <p className="text-3xl font-bold text-white mt-1">{kpis.total_pasos}</p>
                <p className="text-xs text-emerald-400 mt-1">Actualización instantánea vía SSE</p>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <p className="text-xs text-slate-400 uppercase">Recaudación Acumulada</p>
                <p className="text-3xl font-bold text-emerald-400 mt-1">
                  Bs {Number(kpis.recaudacion_total_bs).toFixed(2)}
                </p>
                <p className="text-xs text-slate-400 mt-1">Descuento automático de saldo</p>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <p className="text-xs text-slate-400 uppercase">Alertas Activas</p>
                <p className="text-3xl font-bold text-rose-400 mt-1">{kpis.alertas_pendientes}</p>
                <p className="text-xs text-slate-400 mt-1">Placas no registradas o sin saldo</p>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <p className="text-xs text-slate-400 uppercase">Padrón de Vehículos</p>
                <p className="text-3xl font-bold text-blue-400 mt-1">{kpis.total_vehiculos}</p>
                <p className="text-xs text-slate-400 mt-1">5 categorías tarifarias activas</p>
              </div>
            </div>

            {/* Captura directa / Prueba de Caseta hacia Colab */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-white flex items-center gap-2">
                  <Camera className="w-5 h-5 text-blue-400" />
                  Capturar / Enviar Frame de Caseta a Inferencia en Google Colab
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Envía una fotografía a <code>POST /api/v1/pasos/frame</code> → Colab M1+M2+M3 → Registra el paso y actualiza este panel en vivo sin recargar.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <select
                  value={casetaActiva}
                  onChange={(e) => setCasetaActiva(Number(e.target.value))}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
                >
                  {casetas.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
                <label className="cursor-pointer inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition">
                  <Upload className="w-4 h-4" />
                  {subiendoFrame ? "Inferencia en Colab..." : "Enviar Frame de Vehículo"}
                  <input type="file" accept="image/*" onChange={enviarFrameCaseta} disabled={subiendoFrame} className="hidden" />
                </label>
              </div>
            </div>

            {ultimoResultadoCaseta && (
              <div className="bg-blue-950/30 border border-blue-500/40 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-xs text-blue-300 uppercase font-semibold">Último Frame Procesado por Google Colab</p>
                  <p className="text-sm text-white mt-1">
                    Placa: <strong className="font-mono text-base">{ultimoResultadoCaseta.paso.placa_normalizada}</strong> · Categoría:{" "}
                    <strong className="uppercase">{ultimoResultadoCaseta.paso.categoria_detectada}</strong> · Ejes:{" "}
                    <strong>{ultimoResultadoCaseta.paso.ejes_detectados}</strong> · Tarifa:{" "}
                    <strong className="text-emerald-400">Bs {ultimoResultadoCaseta.paso.monto.toFixed(2)}</strong> · Latencia GPU:{" "}
                    <strong>{ultimoResultadoCaseta.inferencia.latencia_ms} ms</strong>
                  </p>
                </div>
                <BadgeEstado estado={ultimoResultadoCaseta.paso.estado} />
              </div>
            )}

            {/* Grilla en Tiempo Real: Últimos Pasos con Imagen de Evidencia + Alertas Recientes */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h3 className="text-base font-semibold text-white mb-4">
                  Flujo de Vehículos en Tiempo Real (Sin recargar la página)
                </h3>
                <div className="space-y-3">
                  {pasos.slice(0, 10).map((p) => (
                    <div
                      key={p.id}
                      className="flex flex-wrap sm:flex-nowrap items-center justify-between gap-4 p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/80"
                    >
                      <div className="flex items-center gap-3.5">
                        {p.imagen_url ? (
                          <img
                            src={urlEvidencia(p.imagen_url)}
                            alt={p.placa_normalizada}
                            className="w-20 h-14 object-cover rounded-lg border border-slate-700 shrink-0"
                          />
                        ) : (
                          <div className="w-20 h-14 rounded-lg bg-slate-800 flex items-center justify-center text-xs text-slate-400">
                            Sin foto
                          </div>
                        )}
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold text-base text-white bg-slate-800 px-2.5 py-0.5 rounded border border-slate-700">
                              {p.placa_normalizada}
                            </span>
                            <BadgeEstado estado={p.estado} />
                            <span className="text-xs text-slate-400">OCR {(p.confianza_ocr * 100).toFixed(0)}%</span>
                          </div>
                          <p className="text-xs text-slate-300 mt-1">
                            <span className="uppercase font-semibold text-blue-400">{p.categoria_detectada}</span> ·{" "}
                            {p.ejes_detectados} ejes · Propietario: {p.propietario}
                          </p>
                          <p className="text-xs text-slate-500">
                            {p.caseta_nombre} · {new Date(p.created_at).toLocaleString()}
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-lg font-bold text-emerald-400">Bs {Number(p.monto).toFixed(2)}</p>
                        {p.saldo_restante !== null && (
                          <p className="text-xs text-slate-400">Saldo: Bs {Number(p.saldo_restante).toFixed(2)}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Columna de Alertas en Tiempo Real */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
                <h3 className="text-base font-semibold text-white mb-4 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-rose-400" />
                  Alertas en Vivo
                </h3>
                <div className="space-y-3">
                  {alertas.slice(0, 8).map((a) => (
                    <div
                      key={a.id}
                      className={`p-3.5 rounded-xl border ${
                        a.atendida
                          ? "bg-slate-950/40 border-slate-800 opacity-60"
                          : "bg-rose-950/25 border-rose-500/40"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-bold uppercase text-rose-400">{a.tipo}</span>
                        <span className="font-mono text-xs bg-slate-800 px-2 py-0.5 rounded text-white">
                          {a.placa}
                        </span>
                      </div>
                      <p className="text-xs text-slate-200 mt-1.5">{a.mensaje}</p>
                      <div className="flex items-center justify-between mt-2.5">
                        <span className="text-[11px] text-slate-400">
                          {new Date(a.created_at).toLocaleTimeString()}
                        </span>
                        {!a.atendida && (
                          <button
                            onClick={() => marcarAlertaAtendida(a.id)}
                            className="text-xs px-2.5 py-1 rounded bg-emerald-600/20 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-600/30"
                          >
                            Marcar atendida
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ==================== PÁGINA 2: VEHÍCULOS (CRUD) ==================== */}
        {activeTab === "vehiculos" && (
          <div className="space-y-6">
            {usuario.rol === "admin" && (
              <form
                onSubmit={guardarVehiculo}
                className="bg-slate-900 border border-slate-800 rounded-xl p-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-4 items-end"
              >
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Placa (Bolivia)</label>
                  <input
                    type="text"
                    required
                    placeholder="3034DUS"
                    value={formVehiculo.placa}
                    onChange={(e) => setFormVehiculo({ ...formVehiculo, placa: e.target.value.toUpperCase() })}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono uppercase"
                  />
                </div>
                <div className="lg:col-span-2">
                  <label className="block text-xs text-slate-400 mb-1">Propietario</label>
                  <input
                    type="text"
                    required
                    placeholder="Nombre completo o empresa"
                    value={formVehiculo.propietario}
                    onChange={(e) => setFormVehiculo({ ...formVehiculo, propietario: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Categoría (M2)</label>
                  <select
                    value={formVehiculo.categoria}
                    onChange={(e) => setFormVehiculo({ ...formVehiculo, categoria: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  >
                    <option value="moto">moto</option>
                    <option value="auto">auto</option>
                    <option value="minibus">minibus</option>
                    <option value="camion">camion</option>
                    <option value="bus">bus</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Ejes (M3) / Saldo (Bs)</label>
                  <div className="flex gap-2">
                    <input
                      type="number"
                      min="2"
                      max="8"
                      value={formVehiculo.ejes}
                      onChange={(e) => setFormVehiculo({ ...formVehiculo, ejes: Number(e.target.value) })}
                      className="w-16 bg-slate-950 border border-slate-700 rounded-lg px-2 py-2 text-sm"
                    />
                    <input
                      type="number"
                      step="0.5"
                      value={formVehiculo.saldo}
                      onChange={(e) => setFormVehiculo({ ...formVehiculo, saldo: Number(e.target.value) })}
                      className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2 py-2 text-sm"
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    className="w-full flex items-center justify-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium"
                  >
                    <Plus className="w-4 h-4" />
                    {formVehiculo.id ? "Actualizar" : "Registrar"}
                  </button>
                </div>
              </form>
            )}

            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
                <h3 className="font-semibold text-white">
                  Padrón de Vehículos Registrados ({vehiculos.length} vehículos)
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="bg-slate-950 text-slate-400 text-xs uppercase">
                    <tr>
                      <th className="px-4 py-3">Placa</th>
                      <th className="px-4 py-3">Propietario</th>
                      <th className="px-4 py-3">Categoría</th>
                      <th className="px-4 py-3">Ejes</th>
                      <th className="px-4 py-3">Saldo (Bs)</th>
                      {usuario.rol === "admin" && <th className="px-4 py-3 text-right">Acciones</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {vehiculos.map((v) => (
                      <tr key={v.id} className="hover:bg-slate-800/40">
                        <td className="px-4 py-3 font-mono font-bold text-white">{v.placa}</td>
                        <td className="px-4 py-3 text-slate-200">{v.propietario}</td>
                        <td className="px-4 py-3 uppercase text-blue-400 font-semibold">{v.categoria}</td>
                        <td className="px-4 py-3">{v.ejes}</td>
                        <td className={`px-4 py-3 font-semibold ${v.saldo <= 5 ? "text-rose-400" : "text-emerald-400"}`}>
                          Bs {v.saldo.toFixed(2)}
                        </td>
                        {usuario.rol === "admin" && (
                          <td className="px-4 py-3 text-right space-x-2">
                            <button
                              onClick={() => setFormVehiculo(v)}
                              className="p-1.5 rounded bg-slate-800 hover:bg-blue-600/20 text-blue-400"
                              title="Editar"
                            >
                              <Edit3 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => borrarVehiculo(v.id)}
                              className="p-1.5 rounded bg-slate-800 hover:bg-rose-600/20 text-rose-400"
                              title="Eliminar"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ==================== PÁGINA 3: PASOS (HISTORIAL CON IMAGEN DE EVIDENCIA) ==================== */}
        {activeTab === "pasos" && (
          <div className="space-y-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap gap-3 items-end">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Buscar Placa</label>
                <input
                  type="text"
                  placeholder="Ej. 3034DUS"
                  value={filtroPlaca}
                  onChange={(e) => setFiltroPlaca(e.target.value)}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono uppercase"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Categoría</label>
                <select
                  value={filtroCategoria}
                  onChange={(e) => setFiltroCategoria(e.target.value)}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">Todas</option>
                  <option value="moto">moto</option>
                  <option value="auto">auto</option>
                  <option value="minibus">minibus</option>
                  <option value="camion">camion</option>
                  <option value="bus">bus</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Estado</label>
                <select
                  value={filtroEstado}
                  onChange={(e) => setFiltroEstado(e.target.value)}
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">Todos</option>
                  <option value="APROBADO">APROBADO</option>
                  <option value="SIN_SALDO">SIN_SALDO</option>
                  <option value="NO_REGISTRADO">NO_REGISTRADO</option>
                </select>
              </div>
              <button
                onClick={filtrarHistorialPasos}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
              >
                Filtrar Historial
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {pasos.map((p) => (
                <div key={p.id} className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden flex flex-col">
                  {p.imagen_url ? (
                    <img
                      src={urlEvidencia(p.imagen_url)}
                      alt={p.placa_normalizada}
                      className="w-full h-44 object-cover border-b border-slate-800"
                    />
                  ) : (
                    <div className="w-full h-44 bg-slate-950 flex items-center justify-center text-slate-500 text-xs">
                      Sin imagen de evidencia
                    </div>
                  )}
                  <div className="p-4 space-y-2 flex-1 flex flex-col justify-between">
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-mono font-bold text-lg text-white">{p.placa_normalizada}</span>
                        <BadgeEstado estado={p.estado} />
                      </div>
                      <p className="text-xs text-slate-300 mt-1">
                        Categoría: <strong className="uppercase text-blue-400">{p.categoria_detectada}</strong> · Ejes:{" "}
                        <strong>{p.ejes_detectados}</strong> · Tarifa:{" "}
                        <strong className="text-emerald-400">Bs {p.monto.toFixed(2)}</strong>
                      </p>
                      <p className="text-xs text-slate-400 mt-1">Propietario: {p.propietario}</p>
                    </div>
                    <div className="pt-2 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-400">
                      <span>{p.caseta_nombre}</span>
                      <span>{new Date(p.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ==================== PÁGINA 4: ALERTAS ==================== */}
        {activeTab === "alertas" && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <h3 className="text-base font-semibold text-white">
              Registro de Alertas por Placa No Registrada (Evasión) o Sin Saldo
            </h3>
            <div className="space-y-3">
              {alertas.map((a) => (
                <div
                  key={a.id}
                  className={`p-4 rounded-xl border flex flex-wrap items-center justify-between gap-4 ${
                    a.atendida ? "bg-slate-950/50 border-slate-800" : "bg-rose-950/20 border-rose-500/40"
                  }`}
                >
                  <div className="flex items-center gap-4">
                    {a.imagen_url && (
                      <img
                        src={urlEvidencia(a.imagen_url)}
                        alt={a.placa}
                        className="w-20 h-14 object-cover rounded-lg border border-slate-700"
                      />
                    )}
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold uppercase px-2 py-0.5 rounded bg-rose-500/20 text-rose-300">
                          {a.tipo}
                        </span>
                        <span className="font-mono font-bold text-white">{a.placa}</span>
                        <span className="text-xs text-slate-400">{new Date(a.created_at).toLocaleString()}</span>
                      </div>
                      <p className="text-sm text-slate-200 mt-1">{a.mensaje}</p>
                    </div>
                  </div>
                  <div>
                    {a.atendida ? (
                      <span className="text-xs text-emerald-400 flex items-center gap-1">
                        <CheckCircle2 className="w-4 h-4" /> Atendida
                      </span>
                    ) : (
                      <button
                        onClick={() => marcarAlertaAtendida(a.id)}
                        className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium"
                      >
                        Marcar como Atendida
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ==================== PÁGINA 5: CHAT (AGENTE CONVERSACIONAL) ==================== */}
        {activeTab === "chat" && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-[640px]">
            <div className="p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="font-semibold text-white">Agente Conversacional de Placas (Texto e Imagen)</h3>
                <p className="text-xs text-slate-400">
                  Responde los 4 estados oficiales · Normaliza placas · Sugiere coincidencias OCR (O↔0, I↔1, B↔8, S↔5)
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5 text-xs">
                {[
                  { label: "1. Con paso (3034DUS)", q: "3034DUS" },
                  { label: "2. Sin paso (2481KLM)", q: "2481KLM" },
                  { label: "3. No registrada (9988EVA)", q: "9988EVA" },
                  { label: "4. Error OCR (3O34DUS)", q: "3O34DUS" },
                ].map((ej) => (
                  <button
                    key={ej.q}
                    onClick={() => setInputChat(ej.q)}
                    className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-blue-300 border border-slate-700"
                  >
                    {ej.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {mensajesChat.map((m, i) => (
                <div key={i} className={`flex ${m.rol === "usuario" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-2xl rounded-2xl px-4 py-3 text-sm whitespace-pre-line ${
                      m.rol === "usuario"
                        ? "bg-blue-600 text-white"
                        : "bg-slate-950 border border-slate-800 text-slate-100"
                    }`}
                  >
                    {m.estado && m.rol === "agente" && (
                      <div className="mb-1.5">
                        <span className="text-[11px] font-bold uppercase px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                          {m.estado}
                        </span>
                      </div>
                    )}
                    {m.texto}
                    {m.sugerencias && m.sugerencias.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-slate-800 flex items-center gap-2">
                        <span className="text-xs text-amber-300">Consultar sugerencia:</span>
                        {m.sugerencias.map((s) => (
                          <button
                            key={s}
                            onClick={() => setInputChat(s)}
                            className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40"
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <form onSubmit={enviarMensajeAgente} className="p-4 border-t border-slate-800 flex items-center gap-3">
              <label className="cursor-pointer p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700">
                <Camera className="w-5 h-5" />
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => setImagenChat(e.target.files?.[0] || null)}
                  className="hidden"
                />
              </label>
              {imagenChat && (
                <span className="text-xs bg-blue-500/20 text-blue-300 px-2.5 py-1 rounded-lg border border-blue-500/40">
                  📷 {imagenChat.name}
                </span>
              )}
              <input
                type="text"
                placeholder="Escribe una placa (ej. 3034-DUS, 1651FUL, 9988EVA) o sube una foto..."
                value={inputChat}
                onChange={(e) => setInputChat(e.target.value)}
                className="flex-1 bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white"
              />
              <button
                type="submit"
                disabled={enviandoChat}
                className="px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium flex items-center gap-2"
              >
                <Send className="w-4 h-4" />
                {enviandoChat ? "Consultando..." : "Enviar"}
              </button>
            </form>
          </div>
        )}

        {/* ==================== PÁGINA 6: ESTADO (ENDPOINT DE INFERENCIA EN GOOGLE COLAB) ==================== */}
        {activeTab === "estado" && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-white">
                  Estado del Endpoint de Inferencia en Google Colab (M1 + M2 + M3)
                </h3>
                <p className="text-xs text-slate-400">
                  La aplicación web no depende de dónde corre la inferencia. Aquí puedes verificar la salud de{" "}
                  <code>INFERENCE_URL</code> y actualizar la URL del túnel de Colab en caliente.
                </p>
              </div>
              <div className="flex items-center gap-2">
                {estadoColab.online ? (
                  <span className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-sm font-semibold">
                    <CheckCircle2 className="w-4 h-4" /> ONLINE ({estadoColab.latencia_ms} ms)
                  </span>
                ) : (
                  <span className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40 text-sm font-semibold">
                    <XCircle className="w-4 h-4" /> OFFLINE
                  </span>
                )}
              </div>
            </div>

            <form onSubmit={probarYGuardarColab} className="space-y-4 max-w-2xl">
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  URL Pública del Servidor de Inferencia (Cloudflare Tunnel / Ngrok en Google Colab)
                </label>
                <input
                  type="url"
                  placeholder="https://xxxx-xxxx.trycloudflare.com"
                  value={nuevaUrlColab}
                  onChange={(e) => setNuevaUrlColab(e.target.value)}
                  disabled={usuario.rol !== "admin"}
                  className="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm font-mono text-white"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Token de API de Inferencia (Opcional - X-API-Token)
                </label>
                <input
                  type="text"
                  placeholder="Dejar vacío si no se fijó INFERENCE_API_TOKEN en Colab"
                  value={nuevoTokenColab}
                  onChange={(e) => setNuevoTokenColab(e.target.value)}
                  disabled={usuario.rol !== "admin"}
                  className="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm font-mono text-white"
                />
              </div>
              <button
                type="submit"
                disabled={verificandoColab}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
              >
                <RefreshCw className={`w-4 h-4 ${verificandoColab ? "animate-spin" : ""}`} />
                {usuario.rol === "admin" ? "Guardar INFERENCE_URL y Verificar Salud" : "Verificar Salud del Endpoint"}
              </button>
            </form>

            {estadoColab.remoto && (
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-4">
                <p className="text-xs text-slate-400 uppercase font-semibold mb-2">
                  Respuesta JSON de <code>{estadoColab.inference_url}/health</code>
                </p>
                <pre className="text-xs font-mono text-emerald-300 overflow-x-auto">
                  {JSON.stringify(estadoColab.remoto, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
