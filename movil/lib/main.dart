// ============================================================================
// Aplicación Móvil Oficial - Sistema Inteligente de Control de Peaje (IAM-811)
// Cumple la Sección 4.1 de la guía del laboratorio:
// 1. Inicio de sesión exclusivo con Google (Google Sign-In) validado contra
//    POST /api/v1/auth/google y lista blanca (rechaza cuentas no autorizadas).
// 2. Modo Caseta: captura video en vivo de la cámara y envía frames continuos
//    a POST /api/v1/pasos/frame. Muestra en pantalla placa leída, categoría,
//    ejes, tarifa y estado (y dispara la actualización en tiempo real en la web).
// 3. Modo Consulta: permite enviar al Agente Conversacional (POST /api/v1/agente/chat)
//    una foto de una placa (cámara o galería) o escribir la placa en texto.
// 4. Cero URLs locales hardcodeadas: lee API_BASE_URL desde --dart-define o
//    configuración persistente apuntando al subdominio HTTPS en producción.
// ============================================================================

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String kDefaultApiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'https://iam811-peaje-web.onrender.com/api/v1',
);

const String kGoogleServerClientId = String.fromEnvironment(
  'GOOGLE_WEB_CLIENT_ID',
  defaultValue: '159830757831-du48o4vm4c7uigujttelj58dvlktbhpq.apps.googleusercontent.com',
);

List<CameraDescription> _cameras = [];

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    _cameras = await availableCameras();
  } catch (_) {
    _cameras = [];
  }
  runApp(const PeajeMovilApp());
}

class PeajeMovilApp extends StatelessWidget {
  const PeajeMovilApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'IAM-811 Control de Peaje',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true).copyWith(
        scaffoldBackgroundColor: const Color(0xFF020617),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF2563EB),
          brightness: Brightness.dark,
        ),
      ),
      home: const HomeControllerScreen(),
    );
  }
}

class HomeControllerScreen extends StatefulWidget {
  const HomeControllerScreen({super.key});

  @override
  State<HomeControllerScreen> createState() => _HomeControllerScreenState();
}

class _HomeControllerScreenState extends State<HomeControllerScreen> {
  String _apiBaseUrl = kDefaultApiBaseUrl;
  String? _jwtToken;
  Map<String, dynamic>? _usuario;
  String? _authError;
  bool _cargandoAuth = false;
  int _tabIndex = 0; // 0 = Modo Caseta, 1 = Modo Consulta

  late final GoogleSignIn _googleSignIn;

  @override
  void initState() {
    super.initState();
    _googleSignIn = GoogleSignIn(
      scopes: ['email', 'profile'],
      serverClientId: kGoogleServerClientId.isNotEmpty ? kGoogleServerClientId : null,
    );
    _cargarSesionGuardada();
  }

  Future<void> _cargarSesionGuardada() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _apiBaseUrl = prefs.getString('api_base_url') ?? kDefaultApiBaseUrl;
      _jwtToken = prefs.getString('jwt_token');
      final userStr = prefs.getString('usuario_json');
      if (userStr != null) {
        _usuario = jsonDecode(userStr) as Map<String, dynamic>;
      }
    });
  }

  Future<void> _iniciarSesionConGoogle() async {
    setState(() {
      _cargandoAuth = true;
      _authError = null;
    });
    try {
      await _googleSignIn.signOut();
      final account = await _googleSignIn.signIn();
      if (account == null) {
        setState(() => _cargandoAuth = false);
        return;
      }
      final auth = await account.authentication;
      final tokenGoogle = auth.idToken ?? auth.accessToken;
      if (tokenGoogle == null) {
        throw Exception('Google no devolvió idToken ni accessToken. Verifique SHA-1 y Client ID en Google Cloud.');
      }

      final resp = await http.post(
        Uri.parse('$_apiBaseUrl/auth/google'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'token': tokenGoogle}),
      );
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      if (resp.statusCode != 200) {
        throw Exception(data['detail'] ?? 'Acceso denegado (403): Cuenta no autorizada en la lista blanca.');
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('jwt_token', data['access_token'] as String);
      await prefs.setString('usuario_json', jsonEncode(data['usuario']));

      setState(() {
        _jwtToken = data['access_token'] as String;
        _usuario = data['usuario'] as Map<String, dynamic>;
      });
    } catch (e) {
      setState(() {
        _authError = e.toString().replaceAll('Exception: ', '');
      });
    } finally {
      setState(() => _cargandoAuth = false);
    }
  }

  Future<void> _cerrarSesion() async {
    await _googleSignIn.signOut();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('jwt_token');
    await prefs.remove('usuario_json');
    setState(() {
      _jwtToken = null;
      _usuario = null;
    });
  }

  Future<void> _configurarSubdominioDialog() async {
    final ctrl = TextEditingController(text: _apiBaseUrl);
    final nuevo = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Subdominio HTTPS de la API'),
        content: TextField(
          controller: ctrl,
          decoration: const InputDecoration(
            labelText: 'URL Base (/api/v1)',
            hintText: 'https://peaje.tudominio.com/api/v1',
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, ctrl.text.trim()), child: const Text('Guardar')),
        ],
      ),
    );
    if (nuevo != null && nuevo.isNotEmpty) {
      final limpio = nuevo.endsWith('/') ? nuevo.substring(0, nuevo.length - 1) : nuevo;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('api_base_url', limpio);
      setState(() => _apiBaseUrl = limpio);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_jwtToken == null || _usuario == null) {
      return Scaffold(
        appBar: AppBar(
          title: const Text('IAM-811 · Peaje Inteligente'),
          actions: [
            IconButton(
              icon: const Icon(Icons.cloud_outlined),
              tooltip: 'Configurar subdominio HTTPS',
              onPressed: _configurarSubdominioDialog,
            ),
          ],
        ),
        body: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.directions_car_filled, size: 72, color: Color(0xFF3B82F6)),
                const SizedBox(height: 16),
                const Text(
                  'Sistema Inteligente de Control de Peaje',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                Text(
                  'Endpoint nube: $_apiBaseUrl',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 12, color: Colors.white60),
                ),
                const SizedBox(height: 24),
                if (_authError != null)
                  Container(
                    padding: const EdgeInsets.all(14),
                    margin: const EdgeInsets.only(bottom: 20),
                    decoration: BoxDecoration(
                      color: Colors.red.withOpacity(0.15),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.redAccent),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.gpp_bad, color: Colors.redAccent),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            _authError!,
                            style: const TextStyle(color: Colors.redAccent, fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: FilledButton.icon(
                    onPressed: _cargandoAuth ? null : _iniciarSesionConGoogle,
                    icon: const Icon(Icons.login),
                    label: Text(_cargandoAuth ? 'Validando cuenta con Google...' : 'Iniciar sesión con Google'),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('IAM-811 · Peaje Móvil', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            Text(
              '${_usuario!['email_google']} (${_usuario!['rol']})',
              style: const TextStyle(fontSize: 11, color: Colors.white70),
            ),
          ],
        ),
        actions: [
          IconButton(icon: const Icon(Icons.cloud_sync), onPressed: _configurarSubdominioDialog),
          IconButton(icon: const Icon(Icons.logout), onPressed: _cerrarSesion),
        ],
      ),
      body: _tabIndex == 0
          ? ModoCasetaScreen(apiBaseUrl: _apiBaseUrl, jwtToken: _jwtToken!)
          : ModoConsultaScreen(apiBaseUrl: _apiBaseUrl, jwtToken: _jwtToken!),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tabIndex,
        onDestinationSelected: (idx) => setState(() => _tabIndex = idx),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.videocam_outlined),
            selectedIcon: Icon(Icons.videocam),
            label: 'Modo Caseta (En Vivo)',
          ),
          NavigationDestination(
            icon: Icon(Icons.chat_bubble_outline),
            selectedIcon: Icon(Icons.chat_bubble),
            label: 'Modo Consulta (Agente)',
          ),
        ],
      ),
    );
  }
}

// ============================================================================
// MODO CASETA: Captura de video y envío continuo de frames a /api/v1/pasos/frame
// ============================================================================
class ModoCasetaScreen extends StatefulWidget {
  final String apiBaseUrl;
  final String jwtToken;

  const ModoCasetaScreen({super.key, required this.apiBaseUrl, required this.jwtToken});

  @override
  State<ModoCasetaScreen> createState() => _ModoCasetaScreenState();
}

class _ModoCasetaScreenState extends State<ModoCasetaScreen> {
  CameraController? _cameraController;
  bool _capturaContinuaActiva = false;
  bool _procesandoFrame = false;
  Timer? _timerFrames;
  int _casetaId = 1;
  Map<String, dynamic>? _ultimoPaso;
  String? _errorCaseta;

  @override
  void initState() {
    super.initState();
    _inicializarCamara();
  }

  Future<void> _inicializarCamara() async {
    if (_cameras.isEmpty) return;
    final ctrl = CameraController(_cameras.first, ResolutionPreset.medium, enableAudio: false);
    await ctrl.initialize();
    if (mounted) {
      setState(() => _cameraController = ctrl);
    }
  }

  @override
  void dispose() {
    _timerFrames?.cancel();
    _cameraController?.dispose();
    super.dispose();
  }

  void _alternarCapturaContinua() {
    if (_capturaContinuaActiva) {
      _timerFrames?.cancel();
      setState(() => _capturaContinuaActiva = false);
    } else {
      setState(() => _capturaContinuaActiva = true);
      _capturarYEnviarFrame();
      _timerFrames = Timer.periodic(const Duration(milliseconds: 2200), (_) {
        _capturarYEnviarFrame();
      });
    }
  }

  Future<void> _capturarYEnviarFrame() async {
    if (_procesandoFrame || _cameraController == null || !_cameraController!.value.isInitialized) return;
    setState(() {
      _procesandoFrame = true;
      _errorCaseta = null;
    });
    try {
      final XFile foto = await _cameraController!.takePicture();
      await _enviarArchivoAlPeaje(File(foto.path));
    } catch (e) {
      setState(() => _errorCaseta = e.toString());
    } finally {
      if (mounted) setState(() => _procesandoFrame = false);
    }
  }

  Future<void> _enviarArchivoAlPeaje(File archivo) async {
    final req = http.MultipartRequest('POST', Uri.parse('${widget.apiBaseUrl}/pasos/frame'));
    req.headers['Authorization'] = 'Bearer ${widget.jwtToken}';
    req.fields['caseta_id'] = _casetaId.toString();
    req.files.add(await http.MultipartFile.fromPath('file', archivo.path));

    final streamed = await req.send();
    final resp = await http.Response.fromStream(streamed);
    final data = jsonDecode(resp.body) as Map<String, dynamic>;
    if (resp.statusCode != 200) {
      throw Exception(data['detail'] ?? 'Error al procesar el frame en la caseta.');
    }
    if (mounted) {
      setState(() => _ultimoPaso = data['paso'] as Map<String, dynamic>);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Vista previa de cámara en vivo
        Expanded(
          flex: 3,
          child: Container(
            width: double.infinity,
            color: Colors.black,
            child: _cameraController != null && _cameraController!.value.isInitialized
                ? Stack(
                    fit: StackFit.expand,
                    children: [
                      CameraPreview(_cameraController!),
                      Positioned(
                        top: 12,
                        left: 12,
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                          decoration: BoxDecoration(
                            color: Colors.black87,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Row(
                            children: [
                              Icon(
                                Icons.circle,
                                size: 10,
                                color: _capturaContinuaActiva ? Colors.greenAccent : Colors.amber,
                              ),
                              const SizedBox(width: 6),
                              Text(
                                _capturaContinuaActiva
                                    ? 'MODO CASETA ACTIVO · Enviando frames'
                                    : 'Cámara lista · Caseta #$_casetaId',
                                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  )
                : const Center(child: Text('Inicializando cámara del dispositivo...')),
          ),
        ),

        // Panel de resultado en vivo (Placa, categoría, ejes, tarifa y estado)
        Expanded(
          flex: 2,
          child: Container(
            padding: const EdgeInsets.all(16),
            color: const Color(0xFF0F172A),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: _alternarCapturaContinua,
                        style: FilledButton.styleFrom(
                          backgroundColor: _capturaContinuaActiva ? Colors.redAccent : const Color(0xFF2563EB),
                        ),
                        icon: Icon(_capturaContinuaActiva ? Icons.stop : Icons.play_arrow),
                        label: Text(_capturaContinuaActiva ? 'Detener Stream Caseta' : 'Iniciar Stream Caseta'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    OutlinedButton.icon(
                      onPressed: _procesandoFrame ? null : _capturarYEnviarFrame,
                      icon: const Icon(Icons.camera_alt),
                      label: const Text('1 Frame'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                if (_errorCaseta != null)
                  Text(_errorCaseta!, style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
                if (_ultimoPaso != null)
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E293B),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.blueAccent.withOpacity(0.5)),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'PLACA: ${_ultimoPaso!['placa_normalizada']}',
                              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'Categoría: ${_ultimoPaso!['categoria_detectada'].toString().toUpperCase()} · Ejes: ${_ultimoPaso!['ejes_detectados']}',
                              style: const TextStyle(fontSize: 13, color: Colors.white70),
                            ),
                          ],
                        ),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(
                              'Bs ${_ultimoPaso!['monto']}',
                              style: const TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.bold,
                                color: Colors.greenAccent,
                              ),
                            ),
                            Text(
                              '${_ultimoPaso!['estado']}',
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.bold,
                                color: _ultimoPaso!['estado'] == 'APROBADO' ? Colors.greenAccent : Colors.amberAccent,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  )
                else
                  const Expanded(
                    child: Center(
                      child: Text(
                        'Apunte la cámara al vehículo en la caseta para detectar placa (M1), categoría (M2), ejes (M3) y tarifa en tiempo real.',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: 12, color: Colors.white60),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

// ============================================================================
// MODO CONSULTA: Chat con el Agente Conversacional por Texto o Fotografía
// ============================================================================
class ModoConsultaScreen extends StatefulWidget {
  final String apiBaseUrl;
  final String jwtToken;

  const ModoConsultaScreen({super.key, required this.apiBaseUrl, required this.jwtToken});

  @override
  State<ModoConsultaScreen> createState() => _ModoConsultaScreenState();
}

class _ModoConsultaScreenState extends State<ModoConsultaScreen> {
  final TextEditingController _inputCtrl = TextEditingController();
  final ImagePicker _picker = ImagePicker();
  bool _enviando = false;
  final List<Map<String, String>> _mensajes = [
    {
      'rol': 'agente',
      'texto':
          'Modo Consulta activo. Escribe una placa (ej. 3034DUS, 2481KLM, 9988EVA) o toma una foto para conocer su estado en el peaje.',
      'estado': 'Agente IA',
    },
  ];

  Future<void> _enviarConsulta({File? imagenFile}) async {
    final texto = _inputCtrl.text.trim();
    if (texto.isEmpty && imagenFile == null) return;

    setState(() {
      _mensajes.add({
        'rol': 'usuario',
        'texto': imagenFile != null ? '📷 [Foto enviada] $texto' : texto,
      });
      _inputCtrl.clear();
      _enviando = true;
    });

    try {
      final req = http.MultipartRequest('POST', Uri.parse('${widget.apiBaseUrl}/agente/chat'));
      req.headers['Authorization'] = 'Bearer ${widget.jwtToken}';
      if (texto.isNotEmpty) req.fields['mensaje'] = texto;
      if (imagenFile != null) {
        req.files.add(await http.MultipartFile.fromPath('file', imagenFile.path));
      }

      final streamed = await req.send();
      final resp = await http.Response.fromStream(streamed);
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      setState(() {
        _mensajes.add({
          'rol': 'agente',
          'texto': (data['respuesta'] ?? data['detail'] ?? 'Sin respuesta').toString(),
          'estado': (data['estado'] ?? 'Resultado').toString(),
        });
      });
    } catch (e) {
      setState(() {
        _mensajes.add({'rol': 'agente', 'texto': 'Error de conexión: $e', 'estado': 'Error'});
      });
    } finally {
      setState(() => _enviando = false);
    }
  }

  Future<void> _tomarFotoPlaca(ImageSource source) async {
    final XFile? picked = await _picker.pickImage(source: source, imageQuality: 85);
    if (picked != null) {
      await _enviarConsulta(imagenFile: File(picked.path));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: _mensajes.length,
            itemBuilder: (ctx, i) {
              final m = _mensajes[i];
              final esUser = m['rol'] == 'usuario';
              return Align(
                alignment: esUser ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(14),
                  constraints: const BoxConstraints(maxWidth: 320),
                  decoration: BoxDecoration(
                    color: esUser ? const Color(0xFF2563EB) : const Color(0xFF1E293B),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!esUser && m['estado'] != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: Text(
                            m['estado']!.toUpperCase(),
                            style: const TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              color: Colors.lightBlueAccent,
                            ),
                          ),
                        ),
                      Text(m['texto'] ?? '', style: const TextStyle(fontSize: 13.5)),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          color: const Color(0xFF0F172A),
          child: Row(
            children: [
              IconButton(
                icon: const Icon(Icons.camera_alt_outlined),
                tooltip: 'Tomar foto de placa',
                onPressed: _enviando ? null : () => _tomarFotoPlaca(ImageSource.camera),
              ),
              IconButton(
                icon: const Icon(Icons.photo_library_outlined),
                tooltip: 'Subir imagen de galería',
                onPressed: _enviando ? null : () => _tomarFotoPlaca(ImageSource.gallery),
              ),
              Expanded(
                child: TextField(
                  controller: _inputCtrl,
                  decoration: const InputDecoration(
                    hintText: 'Escribir placa (ej. 3034DUS)...',
                    isDense: true,
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _enviarConsulta(),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                onPressed: _enviando ? null : () => _enviarConsulta(),
                icon: const Icon(Icons.send),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
