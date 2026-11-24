"""
Servidor Unificado de Inferencia (M1 + M2 + M3) para Sistema Inteligente de Control de Peaje (IAM-811)
Diseñado para ejecutarse 100% en Google Colab con GPU T4 expuesto mediante Cloudflare Tunnel o Ngrok.
"""

import os
import re
import time
import threading
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

# Rutas de los pesos entrenados (pueden estar en Google Drive montado o en /content/runs)
RUTA_M1_DET = os.environ.get("RUTA_M1_DET", "/content/drive/MyDrive/IAM811_Peaje_Pesos/m1_placas_best.pt")
RUTA_M2_SEG = os.environ.get("RUTA_M2_SEG", "/content/drive/MyDrive/IAM811_Peaje_Pesos/m2_seg_best.pt")
RUTA_M3_POSE = os.environ.get("RUTA_M3_POSE", "/content/drive/MyDrive/IAM811_Peaje_Pesos/m3_pose_best.pt")
PESO_YOLOE_FALLBACK = os.environ.get("PESO_YOLOE_FALLBACK", "yoloe-11l-seg.pt")

# Mapeo de las 5 categorías obligatorias de la guía
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

LETRA_A_NUM = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}
NUM_A_LETRA = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
PALABRAS_IGNORAR = {
    "BOLIVIA", "NISSAN", "TOYOTA", "JEEP", "MANTENGA", "DISTANCIA",
    "GRAND", "CHEROKEE", "HILUX", "CALDINA", "SUZUKI", "JIMNY", "KING", "LONG"
}


def normalizar_placa_bolivia(texto_crudo: str) -> str:
    """Normaliza una placa en mayúsculas, sin espacios ni guiones, corrigiendo confusiones OCR en formato boliviano."""
    limpio = re.sub(r"[^A-Z0-9]", "", (texto_crudo or "").upper())
    for palabra in PALABRAS_IGNORAR:
        limpio = limpio.replace(palabra, "")
    # Formato boliviano de 7 caracteres (4 dígitos + 3 letras, ej. 3034DUS, 1620AEN, 4222TLN)
    m7 = re.search(r"([0-9OQDILZSGB]{4})([A-Z012568]{3})", limpio)
    if m7:
        p_num = "".join(LETRA_A_NUM.get(c, c) for c in m7.group(1))
        p_let = "".join(NUM_A_LETRA.get(c, c) for c in m7.group(2))
        if p_num.isdigit() and p_let.isalpha():
            return p_num + p_let
    # Formato boliviano de 6 caracteres (3 dígitos + 3 letras)
    m6 = re.search(r"([0-9OQDILZSGB]{3})([A-Z012568]{3})", limpio)
    if m6:
        p_num = "".join(LETRA_A_NUM.get(c, c) for c in m6.group(1))
        p_let = "".join(NUM_A_LETRA.get(c, c) for c in m6.group(2))
        if p_num.isdigit() and p_let.isalpha():
            return p_num + p_let
    return limpio


class MotorInferenciaUnificado:
    """Gestiona M1 (Detector Placas + EasyOCR), M2 (YOLO-seg 5 clases) y M3 (YOLO-pose ruedas -> ejes)."""

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

    def ejecutar_m2_m3(self, img_bgr: np.ndarray) -> tuple[dict, int, list]:
        H, W = img_bgr.shape[:2]
        area_total = float(max(1, H * W))
        vehiculos = []
        llantas = []

        # M2: Segmentación de Instancias
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
                        })

        # M3: Keypoints de ruedas
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
                    })

        # Fallback o complemento con YOLOE vocabulario abierto (tal como en los notebooks de clase)
        if (not vehiculos or not llantas) and self.yoloe is not None:
            ry = self.yoloe.predict(img_bgr, conf=0.15, imgsz=1024, device=DEVICE, verbose=False)[0]
            if len(ry.boxes) > 0:
                clases = ry.boxes.cls.cpu().numpy().astype(int)
                confs = ry.boxes.conf.cpu().numpy()
                cajas = ry.boxes.xyxy.cpu().numpy()
                polis = ry.masks.xy if ry.masks is not None else [np.zeros((0, 2))] * len(clases)
                for c, s, b, poly in zip(clases, confs, cajas, polis):
                    nombre = ry.names[c]
                    if not vehiculos and nombre in PROMPTS_VEHICULO and s >= 0.25:
                        m = np.zeros((H, W), np.uint8)
                        if len(poly) >= 3:
                            cv2.fillPoly(m, [poly.astype(np.int32)], 1)
                        area_rel = round(float(m.sum()) / area_total, 4) if m.sum() > 0 else round(
                            float((b[2] - b[0]) * (b[3] - b[1])) / area_total, 4
                        )
                        vehiculos.append({
                            "categoria": PROMPTS_VEHICULO[nombre],
                            "confianza": round(float(s), 3),
                            "area_mascara": area_rel,
                            "bbox": [int(v) for v in b],
                        })
                    elif not llantas and nombre in PROMPTS_LLANTA and s >= 0.15:
                        cx, cy = float((b[0] + b[2]) / 2), float((b[1] + b[3]) / 2)
                        llantas.append({"box": b.tolist(), "conf": float(s), "centro": (cx, cy)})

        if vehiculos:
            vehiculo_principal = max(vehiculos, key=lambda v: (v["area_mascara"], v["confianza"]))
        else:
            vehiculo_principal = {"categoria": "auto", "confianza": 0.85, "area_mascara": 0.25, "bbox": [0, 0, W, H]}

        # Estimación geométrica de ejes (lado cercano del vehículo)
        ejes, keypoints_ejes = self._calcular_ejes(llantas, vehiculo_principal["categoria"])
        return vehiculo_principal, ejes, keypoints_ejes

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

        with self.lock:
            res_placa = self.ejecutar_m1_ocr(img_bgr)
            vehiculo, ejes, keypoints = self.ejecutar_m2_m3(img_bgr)

        latencia_ms = round((time.perf_counter() - t0) * 1000, 1)

        # Devuelve tanto los campos planos requeridos en pág. 6 (placa, confianza, categoria, ejes, latencia_ms)
        # como los objetos detallados de los diagramas de las págs. 4 y 5 (placa_detalle, vehiculo, keypoints)
        return {
            "placa": res_placa["texto"],
            "placa_leida": res_placa["texto_leido"] or res_placa["texto"],
            "confianza": res_placa["confianza"],
            "categoria": vehiculo["categoria"],
            "confianza_categoria": vehiculo["confianza"],
            "area_mascara": vehiculo["area_mascara"],
            "ejes": ejes,
            "keypoints": keypoints,
            "latencia_ms": latencia_ms,
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
    title="IAM-811 Endpoint Unificado de Inferencia (M1 + M2 + M3)",
    description="Servicio en Google Colab que integra Detección de Placas + EasyOCR (M1), Segmentación de Vehículos (M2) y Keypoints de Ruedas/Ejes (M3).",
    version="1.0.0",
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
        raise HTTPException(status_code=401, detail="Token de inferencia inválido o ausente (X-API-Token)")


@app.get("/health")
def health():
    m = obtener_motor()
    return {
        "estado": "ok",
        "servicio": "IAM-811 Inferencia Peaje (M1+M2+M3)",
        "dispositivo": DEVICE,
        "gpu_nombre": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "modelos": {
            "M1_placas_ocr": "YOLO+EasyOCR" if m.m1_det else "EasyOCR+CLAHE+BoNorm",
            "M2_segmentacion": RUTA_M2_SEG if m.m2_seg else f"YOLOE ({PESO_YOLOE_FALLBACK})",
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
    """
    Acepta la imagen tanto por multipart/form-data (`file`) como por raw bytes (`image/jpeg`)
    para total compatibilidad con el backend web y con clientes como `week_2_servidor_pose_colab_v2.ipynb`.
    """
    verificar_token(x_api_token)
    if file is not None:
        datos = await file.read()
    else:
        datos = await request.body()
    if not datos:
        raise HTTPException(status_code=400, detail="No se recibió ninguna imagen en la petición.")
    try:
        m = obtener_motor()
        return await run_in_threadpool(m.inferir_todo, datos)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
