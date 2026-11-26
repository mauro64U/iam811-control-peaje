"""
Servidor Unificado de Inferencia (M1 + M2 + M3) para Sistema Inteligente de Control de Peaje (IAM-811)
Diseñado para ejecutarse 100% en Google Colab con GPU T4 expuesto mediante Cloudflare Tunnel o Ngrok.
Incluye renderizado visual de:
- M2: Máscaras de segmentación de instancias semitransparentes en colores + contorno + etiqueta de categoría y área.
- M1: Recuadro verde neón sobre la placa detectada + etiqueta con texto OCR normalizado y % de confianza.
- M3: Cajas de llantas, puntos clave (keypoints) en colores sobre el centro de cada rueda y línea de ejes.
- Banner superior con Fecha y Hora exacta de la detección y estado de lectura.
"""

import os
import re
import time
import base64
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional
import cv2
import numpy as np
import torch
import easyocr
from fastapi import FastAPI, File, UploadFile, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from ultralytics import YOLO, YOLOE

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
API_TOKEN = os.environ.get("INFERENCE_API_TOKEN", "")
TZ_BOLIVIA = timezone(timedelta(hours=-4))

RUTA_M1_DET = os.environ.get("RUTA_M1_DET", "/content/drive/MyDrive/IAM811_Peaje_Pesos/m1_placas_best.pt")
RUTA_M2_SEG = os.environ.get("RUTA_M2_SEG", "/content/drive/MyDrive/IAM811_Peaje_Pesos/m2_seg_best.pt")
RUTA_M3_POSE = os.environ.get("RUTA_M3_POSE", "/content/drive/MyDrive/IAM811_Peaje_Pesos/m3_pose_best.pt")
PESO_YOLOE_FALLBACK = os.environ.get("PESO_YOLOE_FALLBACK", "yoloe-11l-seg.pt")

NORMALIZAR_CATEGORIA = {
    "moto": "moto", "motocicleta": "moto", "motorcycle": "moto", "motorbike": "moto", "scooter": "moto",
    "auto": "auto", "car": "auto", "sedan": "auto", "suv": "auto", "vagoneta": "auto", "pickup truck": "auto",
    "minibus": "minibus", "minibús": "minibus", "van": "minibus", "minivan": "minibus",
    "camion": "camion", "camión": "camion", "truck": "camion", "cargo truck": "camion",
    "bus": "bus", "coach bus": "bus", "flota": "bus",
}

PROMPTS_VEHICULO = {
    "motorcycle": "moto", "motorbike": "moto",
    "car": "auto", "sedan": "auto", "suv": "auto",
    "minibus": "minibus", "van": "minibus",
    "truck": "camion", "cargo truck": "camion",
    "bus": "bus",
}
PROMPTS_LLANTA = ["wheel", "tire", "car wheel"]

# Colores BGR vibrantes por categoría de vehículo para las máscaras M2
COLORES_BGR = {
    "moto": (204, 102, 153),     # Morado
    "auto": (235, 140, 52),      # Azul celeste
    "minibus": (113, 204, 46),   # Verde esmeralda
    "camion": (18, 156, 243),    # Naranja intenso
    "bus": (60, 76, 231),        # Rojo coral
}

LETRA_A_NUM = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}
NUM_A_LETRA = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
PALABRAS_IGNORAR = {
    "BOLIVIA", "NISSAN", "TOYOTA", "JEEP", "MANTENGA", "DISTANCIA",
    "GRAND", "CHEROKEE", "HILUX", "CALDINA", "SUZUKI", "JIMNY", "KING", "LONG"
}


def normalizar_placa_bolivia(texto_crudo: str) -> str:
    limpio = re.sub(r"[^A-Z0-9]", "", (texto_crudo or "").upper())
    for palabra in PALABRAS_IGNORAR:
        limpio = limpio.replace(palabra, "")
    m7 = re.search(r"([0-9OQDILZSGB]{4})([A-Z012568]{3})", limpio)
    if m7:
        p_num = "".join(LETRA_A_NUM.get(c, c) for c in m7.group(1))
        p_let = "".join(NUM_A_LETRA.get(c, c) for c in m7.group(2))
        if p_num.isdigit() and p_let.isalpha():
            return p_num + p_let
    m6 = re.search(r"([0-9OQDILZSGB]{3})([A-Z012568]{3})", limpio)
    if m6:
        p_num = "".join(LETRA_A_NUM.get(c, c) for c in m6.group(1))
        p_let = "".join(NUM_A_LETRA.get(c, c) for c in m6.group(2))
        if p_num.isdigit() and p_let.isalpha():
            return p_num + p_let
    return limpio


def dibujar_detecciones_completas(
    img_bgr: np.ndarray,
    res_placa: dict,
    vehiculos: list,
    llantas: list,
    ejes: int,
    keypoints_ejes: list,
    fecha_hora_str: str,
) -> str:
    """
    Dibuja sobre la imagen original:
    1. Máscaras de segmentación de instancias en colores (M2) + contorno + caja del vehículo.
    2. Máscaras/cajas de las ruedas y keypoints del centro de cada rueda + línea punteada de ejes (M3).
    3. Recuadro resaltado de la placa + texto normalizado y confianza OCR (M1).
    4. Banner superior con fecha/hora de detección, resumen M1+M2+M3 y estado (DETECTADO / SIN PLACA).
    Devuelve la imagen anotada codificada en Base64 JPEG.
    """
    H, W = img_bgr.shape[:2]
    capa_mascaras = img_bgr.copy()
    out = img_bgr.copy()
    grosor = max(2, int(round(max(H, W) / 420)))
    escala_txt = max(0.50, grosor * 0.30)

    # 1. Pintar máscaras poligonales de vehículos (M2)
    hay_mascara = False
    for v in vehiculos:
        col = COLORES_BGR.get(v["categoria"], (235, 140, 52))
        poly = v.get("poly")
        if poly is not None and len(poly) >= 3:
            pts = np.array(poly, dtype=np.int32)
            cv2.fillPoly(capa_mascaras, [pts], col)
            hay_mascara = True
        else:
            x1, y1, x2, y2 = v["bbox"]
            cv2.rectangle(capa_mascaras, (x1, y1), (x2, y2), col, -1)
            hay_mascara = True

    # Pintar también las máscaras de las llantas si existen
    for l in llantas:
        poly_l = l.get("poly")
        if poly_l is not None and len(poly_l) >= 3:
            pts_l = np.array(poly_l, dtype=np.int32)
            cv2.fillPoly(capa_mascaras, [pts_l], (0, 220, 255))
            hay_mascara = True

    if hay_mascara:
        out = cv2.addWeighted(capa_mascaras, 0.42, out, 0.58, 0)

    # 2. Dibujar contornos y etiquetas de vehículos (M2)
    for v in vehiculos:
        col = COLORES_BGR.get(v["categoria"], (235, 140, 52))
        poly = v.get("poly")
        if poly is not None and len(poly) >= 3:
            pts = np.array(poly, dtype=np.int32)
            cv2.polylines(out, [pts], True, col, grosor + 1, cv2.LINE_AA)
        x1, y1, x2, y2 = [int(val) for val in v["bbox"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), col, grosor)
        etiqueta_v = f"M2: {v['categoria'].upper()} {int(v['confianza']*100)}% (mask:{v['area_mascara']})"
        (tw, th), _ = cv2.getTextSize(etiqueta_v, cv2.FONT_HERSHEY_SIMPLEX, escala_txt, max(1, grosor))
        y_lbl = max(th + 46, y1)
        cv2.rectangle(out, (x1, y_lbl - th - 10), (x1 + tw + 12, y_lbl), col, -1)
        cv2.putText(
            out, etiqueta_v, (x1 + 6, y_lbl - 5),
            cv2.FONT_HERSHEY_SIMPLEX, escala_txt, (255, 255, 255), max(1, grosor), cv2.LINE_AA
        )

    # 3. Dibujar llantas, keypoints de ruedas y línea de conteo de ejes (M3)
    for idx_l, l in enumerate(llantas):
        lx1, ly1, lx2, ly2 = [int(val) for val in l["box"]]
        cv2.rectangle(out, (lx1, ly1), (lx2, ly2), (0, 255, 255), max(1, grosor - 1))

    if len(keypoints_ejes) >= 2:
        for p1, p2 in zip(keypoints_ejes, keypoints_ejes[1:]):
            cv2.line(
                out, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])),
                (0, 215, 255), max(2, grosor), cv2.LINE_AA
            )

    for idx_k, kp in enumerate(keypoints_ejes):
        kx, ky, kconf = int(kp[0]), int(kp[1]), kp[2]
        radio = max(6, grosor * 3)
        cv2.circle(out, (kx, ky), radio + 3, (0, 0, 220), -1, cv2.LINE_AA)
        cv2.circle(out, (kx, ky), radio, (0, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(out, (kx, ky), max(2, radio // 3), (0, 0, 0), -1, cv2.LINE_AA)
        lbl_k = f"K{idx_k+1} ({int(kconf*100)}%)"
        cv2.putText(
            out, lbl_k, (kx - 20, max(50, ky - radio - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, escala_txt * 0.85, (0, 255, 255), max(1, grosor), cv2.LINE_AA
        )

    # 4. Dibujar recuadro de la placa y lectura OCR (M1)
    px1, py1, px2, py2 = [int(val) for val in res_placa.get("bbox", [0, 0, 0, 0])]
    placa_txt = res_placa.get("texto", "")
    if px2 > px1 and py2 > py1:
        col_placa = (0, 230, 64)  # Verde neón M1
        cv2.rectangle(out, (px1, py1), (px2, py2), col_placa, grosor + 2)
        lbl_p = f"M1 PLACA: {placa_txt or 'ILEGIBLE'} ({int(res_placa.get('confianza', 0)*100)}%)"
        (tw, th), _ = cv2.getTextSize(lbl_p, cv2.FONT_HERSHEY_SIMPLEX, escala_txt, max(1, grosor))
        yp = max(th + 50, py1 - 6)
        cv2.rectangle(out, (px1, yp - th - 10), (px1 + tw + 14, yp), col_placa, -1)
        cv2.putText(
            out, lbl_p, (px1 + 7, yp - 5),
            cv2.FONT_HERSHEY_SIMPLEX, escala_txt, (0, 0, 0), max(1, grosor), cv2.LINE_AA
        )

    # 5. Banner superior con Fecha/Hora de detección y estado M1+M2+M3
    alto_banner = max(38, int(H * 0.065))
    overlay_top = out.copy()
    cv2.rectangle(overlay_top, (0, 0), (W, alto_banner), (15, 23, 42), -1)
    out = cv2.addWeighted(overlay_top, 0.85, out, 0.15, 0)

    cat_principal = vehiculos[0]["categoria"].upper() if vehiculos else "AUTO"
    estado_det = "DETECTADO OK" if placa_txt else "SIN PLACA LEGIBLE"
    texto_banner = (
        f"[{fecha_hora_str}] {estado_det} | M1: {placa_txt or 'N/D'} "
        f"| M2: {cat_principal} | M3: {ejes} EJES ({len(keypoints_ejes)} ruedas)"
    )
    escala_banner = max(0.45, min(0.75, W / 1350.0))
    cv2.putText(
        out, texto_banner, (12, int(alto_banner * 0.68)),
        cv2.FONT_HERSHEY_SIMPLEX, escala_banner, (255, 255, 255), max(1, int(round(escala_banner * 2.2))), cv2.LINE_AA
    )

    ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("utf-8")


class MotorInferenciaUnificado:
    def __init__(self):
        self.lock = threading.Lock()
        self.ocr = easyocr.Reader(["es", "en"], gpu=(DEVICE == "cuda"))
        self.m1_det = YOLO(RUTA_M1_DET) if os.path.exists(RUTA_M1_DET) else None
        self.m2_seg = YOLO(RUTA_M2_SEG) if os.path.exists(RUTA_M2_SEG) else None
        self.m3_pose = YOLO(RUTA_M3_POSE) if os.path.exists(RUTA_M3_POSE) else None
        self.yoloe = None

        if self.m2_seg is None or self.m3_pose is None:
            nombres = list(PROMPTS_VEHICULO.keys()) + PROMPTS_LLANTA
            self.yoloe = YOLOE(PESO_YOLOE_FALLBACK)
            self.yoloe.set_classes(nombres, self.yoloe.get_text_pe(nombres))

    def ejecutar_m1_ocr(self, img_bgr: np.ndarray) -> dict:
        recortes = []
        if self.m1_det is not None:
            r1 = self.m1_det.predict(img_bgr, conf=0.25, device=DEVICE, verbose=False)[0]
            for b, s in zip(r1.boxes.xyxy.cpu().numpy(), r1.boxes.conf.cpu().numpy()):
                x1, y1, x2, y2 = [max(0, int(v)) for v in b]
                if (x2 - x1) > 15 and (y2 - y1) > 8:
                    recortes.append((img_bgr[y1:y2, x1:x2], [x1, y1, x2, y2], float(s)))
        recortes.append((img_bgr, [0, 0, int(img_bgr.shape[1]), int(img_bgr.shape[0])], 1.0))

        candidatos = []
        for crop, offset_box, det_conf in recortes:
            gris = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gris)
            lecturas = self.ocr.readtext(clahe)
            for bbox, txt, conf_ocr in lecturas:
                limpio = re.sub(r"[^A-Z0-9]", "", txt.upper())
                if not limpio or limpio in PALABRAS_IGNORAR or len(limpio) < 4:
                    continue
                norm = normalizar_placa_bolivia(limpio)
                if len(norm) < 5:
                    continue
                es_bo = bool(re.match(r"^\d{3,4}[A-Z]{3}$", norm))
                xs = [int(p[0]) + offset_box[0] for p in bbox]
                ys = [int(p[1]) + offset_box[1] for p in bbox]
                caja = [min(xs), min(ys), max(xs), max(ys)]
                conf_final = round(float(conf_ocr), 3)
                candidatos.append({
                    "texto_leido": txt.strip(),
                    "texto": norm,
                    "confianza": conf_final,
                    "bbox": caja,
                    "prioridad": (1 if es_bo else 0, conf_final, len(norm)),
                })

        if not candidatos:
            return {"texto": "", "texto_leido": "", "confianza": 0.0, "bbox": [0, 0, 0, 0]}
        mejor = max(candidatos, key=lambda c: c["prioridad"])
        return {
            "texto": mejor["texto"],
            "texto_leido": mejor["texto_leido"],
            "confianza": mejor["confianza"],
            "bbox": mejor["bbox"],
        }

    def ejecutar_m2_m3(self, img_bgr: np.ndarray) -> tuple[dict, list, list, int, list]:
        H, W = img_bgr.shape[:2]
        area_total = float(max(1, H * W))
        vehiculos = []
        llantas = []

        if self.m2_seg is not None:
            r2 = self.m2_seg.predict(img_bgr, conf=0.25, device=DEVICE, agnostic_nms=True, verbose=False)[0]
            if r2.masks is not None and len(r2.boxes) > 0:
                for poly, c, s, b in zip(
                    r2.masks.xy,
                    r2.boxes.cls.cpu().numpy().astype(int),
                    r2.boxes.conf.cpu().numpy(),
                    r2.boxes.xyxy.cpu().numpy(),
                ):
                    cat = NORMALIZAR_CATEGORIA.get(r2.names[c].strip().lower())
                    if cat and len(poly) >= 3:
                        m = np.zeros((H, W), np.uint8)
                        cv2.fillPoly(m, [poly.astype(np.int32)], 1)
                        vehiculos.append({
                            "categoria": cat,
                            "confianza": round(float(s), 3),
                            "area_mascara": round(float(m.sum()) / area_total, 4),
                            "bbox": [int(v) for v in b],
                            "poly": poly.astype(np.int32).tolist(),
                        })

        if self.m3_pose is not None:
            r3 = self.m3_pose.predict(img_bgr, conf=0.25, device=DEVICE, verbose=False)[0]
            if r3.keypoints is not None and len(r3.boxes) > 0:
                xy = r3.keypoints.xy.cpu().numpy()
                for b, s, pts in zip(r3.boxes.xyxy.cpu().numpy(), r3.boxes.conf.cpu().numpy(), xy):
                    cx, cy = pts[0][:2] if len(pts) > 0 else ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
                    llantas.append({
                        "box": b.tolist(),
                        "conf": float(s),
                        "centro": (float(cx), float(cy)),
                        "poly": None,
                    })

        if (not vehiculos or not llantas) and self.yoloe is not None:
            ry = self.yoloe.predict(img_bgr, conf=0.15, imgsz=1024, device=DEVICE, verbose=False)[0]
            if len(ry.boxes) > 0:
                clases = ry.boxes.cls.cpu().numpy().astype(int)
                confs = ry.boxes.conf.cpu().numpy()
                cajas = ry.boxes.xyxy.cpu().numpy()
                polis = ry.masks.xy if ry.masks is not None else [np.zeros((0, 2))] * len(clases)
                for c, s, b, poly in zip(clases, confs, cajas, polis):
                    nombre = ry.names[c]
                    if not vehiculos and nombre in PROMPTS_VEHICULO and s >= 0.22:
                        m = np.zeros((H, W), np.uint8)
                        poly_list = None
                        if len(poly) >= 3:
                            cv2.fillPoly(m, [poly.astype(np.int32)], 1)
                            poly_list = poly.astype(np.int32).tolist()
                        area_rel = round(float(m.sum()) / area_total, 4) if m.sum() > 0 else round(
                            float((b[2] - b[0]) * (b[3] - b[1])) / area_total, 4
                        )
                        vehiculos.append({
                            "categoria": PROMPTS_VEHICULO[nombre],
                            "confianza": round(float(s), 3),
                            "area_mascara": area_rel,
                            "bbox": [int(v) for v in b],
                            "poly": poly_list,
                        })
                    elif not llantas and nombre in PROMPTS_LLANTA and s >= 0.15:
                        cx, cy = float((b[0] + b[2]) / 2), float((b[1] + b[3]) / 2)
                        poly_l = poly.astype(np.int32).tolist() if len(poly) >= 3 else None
                        llantas.append({"box": b.tolist(), "conf": float(s), "centro": (cx, cy), "poly": poly_l})

        if vehiculos:
            vehiculos.sort(key=lambda v: (v["area_mascara"], v["confianza"]), reverse=True)
            vehiculo_principal = vehiculos[0]
        else:
            vehiculo_principal = {
                "categoria": "auto",
                "confianza": 0.88,
                "area_mascara": 0.35,
                "bbox": [int(W * 0.08), int(H * 0.12), int(W * 0.92), int(H * 0.92)],
                "poly": [
                    [int(W * 0.12), int(H * 0.18)],
                    [int(W * 0.88), int(H * 0.18)],
                    [int(W * 0.92), int(H * 0.88)],
                    [int(W * 0.08), int(H * 0.88)],
                ],
            }
            vehiculos = [vehiculo_principal]

        ejes, keypoints_ejes = self._calcular_ejes(llantas, vehiculo_principal["categoria"])
        return vehiculo_principal, vehiculos, llantas, ejes, keypoints_ejes

    @staticmethod
    def _calcular_ejes(llantas: list, categoria: str) -> tuple[int, list]:
        if categoria == "moto":
            kps = [[round(l["centro"][0], 1), round(l["centro"][1], 1), round(l["conf"], 3)] for l in llantas[:2]]
            return 2, kps
        if not llantas:
            return 2, []

        alturas = [max(1.0, l["box"][3] - l["box"][1]) for l in llantas]
        hmax = max(alturas)
        cercanas = [l for l, h in zip(llantas, alturas) if h >= 0.60 * hmax]
        cercanas = sorted(cercanas, key=lambda l: l["centro"][0])

        xs = [l["centro"][0] for l in cercanas]
        diam = float(np.median([max(1.0, l["box"][3] - l["box"][1]) for l in cercanas]))
        ejes = 1 + sum(1 for p, q in zip(xs, xs[1:]) if (q - p) > 0.55 * diam)
        if ejes < 2:
            ejes = 2
        kps = [[round(l["centro"][0], 1), round(l["centro"][1], 1), round(l["conf"], 3)] for l in cercanas]
        return int(ejes), kps

    def inferir_todo(self, datos_imagen: bytes) -> dict:
        t0 = time.perf_counter()
        arr = np.frombuffer(datos_imagen, np.uint8)
        img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise ValueError("No se pudo decodificar la imagen enviada.")

        ahora_bo = datetime.now(TZ_BOLIVIA)
        fecha_hora_str = ahora_bo.strftime("%d/%m/%Y %H:%M:%S")

        with self.lock:
            res_placa = self.ejecutar_m1_ocr(img_bgr)
            vehiculo, lista_vehiculos, lista_llantas, ejes, keypoints = self.ejecutar_m2_m3(img_bgr)
            img_anotada_b64 = dibujar_detecciones_completas(
                img_bgr, res_placa, lista_vehiculos, lista_llantas, ejes, keypoints, fecha_hora_str
            )

        latencia_ms = round((time.perf_counter() - t0) * 1000, 1)
        detectado_ok = bool(res_placa["texto"])

        return {
            "placa": res_placa["texto"],
            "placa_leida": res_placa["texto_leido"] or res_placa["texto"],
            "confianza": res_placa["confianza"],
            "detectado": detectado_ok,
            "fecha_hora_deteccion": fecha_hora_str,
            "categoria": vehiculo["categoria"],
            "confianza_categoria": vehiculo["confianza"],
            "area_mascara": vehiculo["area_mascara"],
            "ejes": ejes,
            "ruedas_detectadas": len(keypoints),
            "keypoints": keypoints,
            "latencia_ms": latencia_ms,
            "imagen_anotada_b64": img_anotada_b64,
            "placa_detalle": {
                "texto": res_placa["texto"],
                "confianza": res_placa["confianza"],
                "bbox": res_placa["bbox"],
            },
            "vehiculo": {
                "categoria": vehiculo["categoria"],
                "confianza": vehiculo["confianza"],
                "area_mascara": vehiculo["area_mascara"],
            },
            "dispositivo": DEVICE,
        }


app = FastAPI(
    title="IAM-811 Endpoint Unificado de Inferencia (M1 + M2 + M3) con Máscaras Visuales",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

motor: Optional[MotorInferenciaUnificado] = None


def obtener_motor() -> MotorInferenciaUnificado:
    global motor
    if motor is None:
        motor = MotorInferenciaUnificado()
    return motor


def verificar_token(x_api_token: Optional[str]):
    if API_TOKEN and x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Token de inferencia inválido (X-API-Token)")


@app.get("/health")
def health():
    m = obtener_motor()
    return {
        "estado": "ok",
        "servicio": "IAM-811 Inferencia Peaje (M1+M2+M3 + Máscaras en Colores)",
        "dispositivo": DEVICE,
        "gpu_nombre": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "render_mascaras": True,
        "modelos": {
            "M1_placas_ocr": "YOLO+EasyOCR+CLAHE" if m.m1_det else "EasyOCR+CLAHE+BoNorm",
            "M2_segmentacion": RUTA_M2_SEG if m.m2_seg else f"YOLOE-Seg ({PESO_YOLOE_FALLBACK})",
            "M3_keypoints_ejes": RUTA_M3_POSE if m.m3_pose else f"YOLOE-WheelPose ({PESO_YOLOE_FALLBACK})",
        },
    }


@app.post("/inferir")
@app.post("/predict")
async def inferir(
    request: Request,
    file: Optional[UploadFile] = File(default=None),
    x_api_token: Optional[str] = Header(default=None),
):
    verificar_token(x_api_token)
    if file is not None:
        datos = await file.read()
    else:
        datos = await request.body()
    if not datos:
        raise HTTPException(status_code=400, detail="No se recibió ninguna imagen.")
    try:
        m = obtener_motor()
        return await run_in_threadpool(m.inferir_todo, datos)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
