"""GUI Qt6 (PySide6) para MeRGBW — estilo OpenRGB, tema oscuro.

Cada acción BLE abre su propia sesión (conectar → bind → enviar →
desconectar), igual que el CLI verificado. Sin conexiones persistentes:
la tira solo admite una conexión a la vez.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading

try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSlider, QComboBox, QTextEdit, QColorDialog,
        QGridLayout, QMessageBox, QLineEdit, QFrame, QSizePolicy,
        QListWidget, QListWidgetItem, QSpinBox, QTabWidget,
    )
    from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer
    from PySide6.QtGui import QColor, QIcon
except ImportError:
    print("ERROR: falta PySide6. Instala con: pip install PySide6", file=sys.stderr)
    sys.exit(1)

from mergbw import protocol as P
from mergbw.device import scan as ble_scan, MeRGBWDevice

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "mergbw")
COLORES_PATH = os.path.join(CONFIG_DIR, "colores.json")
DEVICE_PATH = os.path.join(CONFIG_DIR, "device.json")
MAX_PERSONALIZADOS = 8

PRESETS = [
    ("Rojo", "FF0000"), ("Naranja", "FF8000"), ("Amarillo", "FFFF00"),
    ("Verde", "00FF00"), ("Cian", "00FFFF"), ("Azul", "0077FF"),
    ("Violeta", "8B7BFF"), ("Magenta", "FF00FF"), ("Blanco", "FFFFFF"),
    ("Cálido", "FFE9B8"),
]

ESCENAS = [  # nombre, índice CMD 6
    ("Sinfonía", 2), ("Energía", 3), ("Salto", 4), ("Vitalidad", 7),
    ("Persecución", 23), ("Bosque", 13), ("Neón", 48), ("Arcoíris", 26),
    ("Fiesta", 6), ("Discoteca", 4),
]

MUSICA = [("Espectro 1", 2), ("Espectro 2", 5), ("Espectro 3", 6),
          ("Fluido", 3), ("Rodante", 1), ("Ritmo", 4)]

# -- tema OpenRGB: fondo casi negro + acento azul --
FONDO = "#0d1117"
TARJETA = "#161b22"
BORDE = "#2a3340"
TEXTO = "#e6edf3"
APAGADO = "#8b949e"
ACENTO = "#3399ff"
PELIGRO = "#ff5f6b"

QSS = f"""
* {{ font-size: 13px; }}
QMainWindow, QWidget#central {{ background: {FONDO}; }}
QTabWidget::pane {{ background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 12px; }}
QTabBar::tab {{ background: transparent; color: {APAGADO}; padding: 8px 16px; }}
QTabBar::tab:selected {{ color: {TEXTO}; border-bottom: 2px solid {ACENTO}; }}
QLabel {{ color: {TEXTO}; background: transparent; }}
QLabel#titulo {{ font-size: 16px; font-weight: 700; }}
QLabel#sub {{ color: {APAGADO}; font-size: 12px; }}
QLabel#seccion {{ color: {APAGADO}; font-size: 11px; font-weight: 700; }}
QLabel#estado {{ font-size: 12px; }}
QFrame#tarjeta {{ background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 14px; }}
QLabel#vista {{
  border-radius: 36px;
  border: 2px solid {BORDE};
}}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QListWidget {{
  background: #0a0d12; color: {TEXTO};
  border: 1px solid {BORDE}; border-radius: 9px; padding: 7px 10px;
}}
QLineEdit:focus {{ border: 1px solid {ACENTO}; }}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: #1c2b45; color: {TEXTO}; }}
QListWidget::item:hover {{ background: #182130; }}
QPushButton {{
  color: {TEXTO}; background: #1c2330;
  border: 1px solid {BORDE}; border-radius: 10px; padding: 9px 14px;
}}
QPushButton:hover {{ border: 1px solid {ACENTO}; }}
QPushButton:disabled {{ color: #555c66; }}
QPushButton#primario {{
  background: {ACENTO}; border: 1px solid {ACENTO};
  color: #04121f; font-weight: 700;
}}
QPushButton#primario:hover {{ background: #5cabff; }}
QPushButton#peligro {{ color: {PELIGRO}; }}
QPushButton#dot {{
  border-radius: 15px; padding: 0px; min-width: 30px; max-width: 30px;
  min-height: 30px; max-height: 30px; border: 2px solid {BORDE};
}}
QPushButton#dot:hover {{ border: 2px solid white; }}
QPushButton#mini {{ background: transparent; border: none; color: {APAGADO}; padding: 4px; }}
QPushButton#mini:hover {{ color: {TEXTO}; }}
QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: #232c3b; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0;
  border-radius: 8px; background: white; border: none; }}
QSlider#slR::groove:horizontal {{ background: #4a2430; }}
QSlider#slG::groove:horizontal {{ background: #1f4030; }}
QSlider#slB::groove:horizontal {{ background: #233a55; }}
QSlider#slR::handle:horizontal {{ background: #ff6b7a; }}
QSlider#slG::handle:horizontal {{ background: #4ade80; }}
QSlider#slB::handle:horizontal {{ background: #60a5fa; }}
QToolTip {{ background: #0a0d12; color: {TEXTO}; border: 1px solid {BORDE}; }}
"""


def cargar_personalizados() -> list[str]:
    try:
        with open(COLORES_PATH, "r", encoding="utf-8") as f:
            lista = json.loads(f.read().strip() or "[]")
        out = []
        for h in lista[:MAX_PERSONALIZADOS]:
            h = str(h).lstrip("#").upper()
            if len(h) == 6 and all(c in "0123456789ABCDEF" for c in h):
                out.append(h)
        return out
    except (OSError, ValueError):
        return []


def guardar_personalizados(colores: list[str]):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = COLORES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(colores[:MAX_PERSONALIZADOS], f)
    os.replace(tmp, COLORES_PATH)


def cargar_device() -> dict:
    """Recuerda el último equipo y el marcado como predeterminado.
    Devuelve {"mac","tipo","nombre"} efectivos (predeterminado si lo hay)
    más las claves "predeterminado" (bool) y "def_mac"."""
    d: dict = {}
    try:
        with open(DEVICE_PATH, "r", encoding="utf-8") as f:
            d = json.loads(f.read().strip() or "{}")
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    if d.get("def_mac"):
        return {"mac": str(d["def_mac"]).upper(),
                "tipo": int(d.get("def_tipo", 1)),
                "nombre": str(d.get("def_nombre", "")),
                "predeterminado": True, "def_mac": str(d["def_mac"]).upper()}
    if d.get("mac"):
        return {"mac": str(d["mac"]).upper(),
                "tipo": int(d.get("tipo", 1)),
                "nombre": str(d.get("nombre", "")),
                "predeterminado": False, "def_mac": ""}
    return {}


def _leer_raw() -> dict:
    try:
        with open(DEVICE_PATH, "r", encoding="utf-8") as f:
            d = json.loads(f.read().strip() or "{}")
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_device(mac: str, tipo: int, nombre: str = "") -> dict:
    """Guarda el último equipo usado (no toca el predeterminado)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    d = _leer_raw()
    d.update({"mac": mac.upper(), "tipo": int(tipo), "nombre": nombre})
    tmp = DEVICE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, DEVICE_PATH)
    return cargar_device()


def fijar_default(mac: str | None, tipo: int = 1, nombre: str = "") -> dict:
    """Fija (o con None, quita) el equipo predeterminado."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    d = _leer_raw()
    if mac:
        d.update({"def_mac": mac.upper(), "def_tipo": int(tipo), "def_nombre": nombre,
                  "mac": mac.upper(), "tipo": int(tipo), "nombre": nombre})
    else:
        for k in ("def_mac", "def_tipo", "def_nombre"):
            d.pop(k, None)
    tmp = DEVICE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, DEVICE_PATH)
    return cargar_device()


def icono_app() -> QIcon:
    ic = QIcon.fromTheme("mergbw")
    if not ic.isNull():
        return ic
    for p in (os.path.join(REPO_DIR, "assets", "mergbw.png"),
              os.path.join(REPO_DIR, "assets", "mergbw.svg"),
              os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/mergbw.png")):
        if os.path.exists(p):
            ic2 = QIcon(p)
            if not ic2.isNull():
                return ic2
    return QIcon()


class Puente(QObject):
    log = Signal(str)
    estado = Signal(dict)
    scan = Signal(list)
    busy = Signal(bool, str)


class HiloBLE(threading.Thread):
    def __init__(self, coro_fn, puente: Puente, etiqueta: str):
        super().__init__(daemon=True)
        self._coro_fn = coro_fn
        self._puente = puente
        self._etiqueta = etiqueta

    def run(self):
        self._puente.busy.emit(True, self._etiqueta)
        try:
            asyncio.run(self._coro_fn())
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self._puente.log.emit(f"ERROR en {self._etiqueta}: {type(e).__name__}: {e}")
        finally:
            self._puente.busy.emit(False, "")


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MeRGBW")
        self.setWindowIcon(icono_app())
        self.resize(720, 760)
        self.puente = Puente()
        self.puente.log.connect(self._anadir_log)
        self.puente.estado.connect(self._mostrar_estado)
        self.puente.scan.connect(self._mostrar_scan)
        self.puente.busy.connect(self._mostrar_busy)
        self.color = (255, 128, 0)
        self.personales = cargar_personalizados()
        self.guardado = cargar_device()
        self.hilo: threading.Thread | None = None
        self._construir_ui()
        if self.guardado:
            self.txt_mac.setText(self.guardado.get("mac", ""))
            try:
                self.cmb_tipo.setCurrentText(str(self.guardado.get("tipo", 1)))
            except Exception:
                pass
            self._refrescar_def()
            if self.guardado.get("predeterminado"):
                # lectura automática del predeterminado al abrir
                QTimer.singleShot(800, self._leer_estado)

    # ---------- construcción ----------
    def _tarjeta(self) -> tuple[QFrame, QVBoxLayout]:
        f = QFrame()
        f.setObjectName("tarjeta")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        return f, lay

    def _seccion(self, lay, texto: str):
        lab = QLabel(texto)
        lab.setObjectName("seccion")
        lay.addWidget(lab)

    def _construir_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        # Cabecera
        cab = QHBoxLayout()
        self.lbl_dot = QLabel("●")
        self.lbl_dot.setStyleSheet(f"color: {APAGADO}; font-size: 14px;")
        titulo = QLabel("MeRGBW")
        titulo.setObjectName("titulo")
        sub = QLabel("control LED · Bluetooth LE")
        sub.setObjectName("sub")
        cab.addWidget(self.lbl_dot)
        cab.addWidget(titulo)
        cab.addWidget(sub)
        cab.addStretch(1)
        self.lbl_busy = QLabel("")
        self.lbl_busy.setStyleSheet(f"color: {ACENTO};")
        cab.addWidget(self.lbl_busy)
        lay.addLayout(cab)

        # Dispositivos
        t_dev, l_dev = self._tarjeta()
        self._seccion(l_dev, "DISPOSITIVOS")
        self.lst = QListWidget()
        self.lst.setMaximumHeight(130)
        self.lst.itemClicked.connect(self._elegir_dev)
        l_dev.addWidget(self.lst)
        fila = QHBoxLayout()
        fila.addWidget(QLabel("MAC"))
        self.txt_mac = QLineEdit()
        self.txt_mac.setPlaceholderText("AA:BB:CC:DD:EE:FF")
        fila.addWidget(self.txt_mac, 1)
        fila.addWidget(QLabel("Tipo"))
        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItems([str(i) for i in range(1, 9)])
        fila.addWidget(self.cmb_tipo)
        self.btn_scan = QPushButton("Escanear")
        self.btn_scan.clicked.connect(self._escanear)
        fila.addWidget(self.btn_scan)
        self.btn_estado = QPushButton("Leer estado")
        self.btn_estado.setObjectName("primario")
        self.btn_estado.clicked.connect(self._leer_estado)
        fila.addWidget(self.btn_estado)
        l_dev.addLayout(fila)
        self.lbl_dev = QLabel("Sin equipo seleccionado.")
        self.lbl_dev.setObjectName("sub")
        self.lbl_dev.setWordWrap(True)
        l_dev.addWidget(self.lbl_dev)
        fila_def = QHBoxLayout()
        self.btn_def = QPushButton("☆ Marcar predeterminado")
        self.btn_def.setObjectName("mini")
        self.btn_def.setToolTip("Fija este equipo como predeterminado: se rellena solo al abrir.")
        self.btn_def.clicked.connect(self._toggle_default)
        fila_def.addWidget(self.btn_def)
        self.lbl_def = QLabel("")
        self.lbl_def.setObjectName("sub")
        fila_def.addWidget(self.lbl_def)
        fila_def.addStretch(1)
        l_dev.addLayout(fila_def)
        lay.addWidget(t_dev)

        # Estado
        t_st, l_st = self._tarjeta()
        self._seccion(l_st, "ESTADO")
        self.lbl_estado = QLabel("Pulsa «Leer estado» tras seleccionar el equipo.")
        self.lbl_estado.setObjectName("estado")
        self.lbl_estado.setWordWrap(True)
        l_st.addWidget(self.lbl_estado)
        lay.addWidget(t_st)

        # Pestañas
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._tab_color()
        self._tab_escenas()
        self._tab_mas()

        # Registro colapsable
        self.btn_log = QPushButton("Registro ▸")
        self.btn_log.setObjectName("mini")
        self.btn_log.clicked.connect(self._toggle_log)
        lay.addWidget(self.btn_log)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setVisible(False)
        lay.addWidget(self.log)

    def _tab_color(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        centro = QHBoxLayout()
        centro.addStretch(1)
        self.vista = QLabel()
        self.vista.setObjectName("vista")
        self.vista.setFixedSize(72, 72)
        self.vista.setAlignment(Qt.AlignCenter)
        centro.addWidget(self.vista)
        centro.addStretch(1)
        lay.addLayout(centro)

        fila_hex = QHBoxLayout()
        self.txt_hex = QLineEdit("FF8000")
        self.txt_hex.setMaxLength(7)
        self.txt_hex.setAlignment(Qt.AlignCenter)
        self.txt_hex.editingFinished.connect(self._desde_hex)
        self.btn_paleta = QPushButton("Paleta")
        self.btn_paleta.clicked.connect(self._elegir_color)
        fila_hex.addWidget(self.txt_hex)
        fila_hex.addWidget(self.btn_paleta)
        lay.addLayout(fila_hex)

        self.sliders: dict[str, tuple[QSlider, QLabel]] = {}
        for nombre, canal, obj in (("R", "r", "slR"), ("G", "g", "slG"), ("B", "b", "slB")):
            fila = QHBoxLayout()
            tag = QLabel(nombre)
            tag.setFixedWidth(14)
            fila.addWidget(tag)
            sl = QSlider(Qt.Horizontal)
            sl.setObjectName(obj)
            sl.setRange(0, 255)
            sl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            sl.valueChanged.connect(self._desde_sliders)
            fila.addWidget(sl)
            val = QLabel("0")
            val.setFixedWidth(30)
            val.setAlignment(Qt.AlignRight)
            val.setStyleSheet(f"color: {APAGADO};")
            fila.addWidget(val)
            lay.addLayout(fila)
            self.sliders[canal] = (sl, val)

        lab = QLabel("PRESETS")
        lab.setObjectName("seccion")
        lay.addWidget(lab)
        gp = QGridLayout()
        gp.setSpacing(8)
        for i, (nombre, hexv) in enumerate(PRESETS):
            b = QPushButton()
            b.setObjectName("dot")
            b.setFixedSize(30, 30)
            b.setToolTip(nombre)
            b.setStyleSheet(f"#dot {{ background: #{hexv}; }}")
            b.clicked.connect(lambda _=False, h=hexv: self._fijar_hex(h))
            gp.addWidget(b, i // 5, i % 5)
        lay.addLayout(gp)

        fila_m = QHBoxLayout()
        lab3 = QLabel("MIS COLORES")
        lab3.setObjectName("seccion")
        fila_m.addWidget(lab3)
        fila_m.addStretch(1)
        self.lbl_cuenta = QLabel("")
        self.lbl_cuenta.setStyleSheet(f"color: {APAGADO}; font-size: 11px;")
        fila_m.addWidget(self.lbl_cuenta)
        lay.addLayout(fila_m)
        gm = QGridLayout()
        gm.setSpacing(8)
        self.slot_btns: list[QPushButton] = []
        for i in range(MAX_PERSONALIZADOS):
            b = QPushButton()
            b.setObjectName("dot")
            b.setFixedSize(30, 30)
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.clicked.connect(lambda _=False, idx=i: self._click_slot(idx))
            b.customContextMenuRequested.connect(lambda _=None, idx=i: self._borrar_slot(idx))
            gm.addWidget(b, i // 5, i % 5)
            self.slot_btns.append(b)
        lay.addLayout(gm)
        self._refrescar_slots()

        fila_btn = QHBoxLayout()
        self.btn_on = QPushButton("Encender")
        self.btn_on.setObjectName("primario")
        self.btn_on.clicked.connect(lambda: self._sesion([P.cmd_power(True)]))
        fila_btn.addWidget(self.btn_on)
        self.btn_off = QPushButton("Apagar")
        self.btn_off.setObjectName("peligro")
        self.btn_off.clicked.connect(lambda: self._sesion([P.cmd_power(False)]))
        fila_btn.addWidget(self.btn_off)
        self.btn_color = QPushButton("Aplicar color")
        self.btn_color.clicked.connect(self._aplicar_color)
        fila_btn.addWidget(self.btn_color)
        lay.addLayout(fila_btn)
        lay.addStretch(1)
        self.tabs.addTab(tab, "  Color  ")
        self._refrescar_vista()

    def _tab_escenas(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        self._seccion(lay, "BRILLO")
        fb = QHBoxLayout()
        self.sl_bri = QSlider(Qt.Horizontal)
        self.sl_bri.setRange(0, 100)
        self.sl_bri.setValue(80)
        self.sl_bri.valueChanged.connect(lambda v: self.lbl_bri.setText(f"{v}%"))
        fb.addWidget(self.sl_bri, 1)
        self.lbl_bri = QLabel("80%")
        self.lbl_bri.setFixedWidth(44)
        fb.addWidget(self.lbl_bri)
        btn_bri = QPushButton("Aplicar")
        btn_bri.clicked.connect(self._aplicar_brillo)
        fb.addWidget(btn_bri)
        lay.addLayout(fb)

        self._seccion(lay, "ESCENAS")
        self.lst_esc = QListWidget()
        for nombre, idx in ESCENAS:
            QListWidgetItem(f"{nombre}  ·  modo {idx}", self.lst_esc)
        self.lst_esc.setCurrentRow(0)
        self.lst_esc.setMaximumHeight(170)
        lay.addWidget(self.lst_esc)
        fv = QHBoxLayout()
        fv.addWidget(QLabel("Velocidad"))
        self.spin_vel = QSpinBox()
        self.spin_vel.setRange(0, 255)
        self.spin_vel.setValue(50)
        fv.addWidget(self.spin_vel)
        btn_esc = QPushButton("Enviar escena")
        btn_esc.setObjectName("primario")
        btn_esc.clicked.connect(self._aplicar_escena)
        fv.addWidget(btn_esc)
        lay.addLayout(fv)

        self._seccion(lay, "MÚSICA")
        fm = QHBoxLayout()
        self.cmb_mus = QComboBox()
        for nombre, idx in MUSICA:
            self.cmb_mus.addItem(nombre, idx)
        fm.addWidget(self.cmb_mus, 1)
        fm.addWidget(QLabel("Sens."))
        self.spin_sens = QSpinBox()
        self.spin_sens.setRange(0, 100)
        self.spin_sens.setValue(80)
        fm.addWidget(self.spin_sens)
        btn_mus = QPushButton("Enviar")
        btn_mus.clicked.connect(self._aplicar_musica)
        fm.addWidget(btn_mus)
        lay.addLayout(fm)
        lay.addStretch(1)
        self.tabs.addTab(tab, " Escenas ")

    def _tab_mas(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        self._seccion(lay, "BLANCO Y LEDS")
        fw = QHBoxLayout()
        fw.addWidget(QLabel("Blanco"))
        self.spin_white = QSpinBox()
        self.spin_white.setRange(0, 100)
        self.spin_white.setValue(70)
        fw.addWidget(self.spin_white)
        btn_w = QPushButton("Enviar")
        btn_w.clicked.connect(lambda: self._sesion([P.cmd_white_brightness(int(self.spin_white.value()))]))
        fw.addWidget(btn_w)
        fw.addWidget(QLabel("Nº LEDs"))
        self.spin_led = QSpinBox()
        self.spin_led.setRange(1, 1000)
        self.spin_led.setValue(40)
        fw.addWidget(self.spin_led)
        btn_l = QPushButton("Fijar")
        btn_l.clicked.connect(lambda: self._sesion([P.cmd_led_num(int(self.spin_led.value()))]))
        fw.addWidget(btn_l)
        lay.addLayout(fw)

        self._seccion(lay, "TEMPORIZADOR")
        ft = QHBoxLayout()
        ft.addWidget(QLabel("On"))
        self.txt_on = QLineEdit("07:30")
        self.txt_on.setFixedWidth(70)
        ft.addWidget(self.txt_on)
        ft.addWidget(QLabel("Off"))
        self.txt_off = QLineEdit("23:00")
        self.txt_off.setFixedWidth(70)
        ft.addWidget(self.txt_off)
        btn_t = QPushButton("Programar")
        btn_t.clicked.connect(self._aplicar_timer)
        ft.addWidget(btn_t)
        lay.addLayout(ft)
        lay.addWidget(QLabel("Repite todos los días. Formato HH:MM."))

        self._seccion(lay, "SISTEMA")
        fs = QHBoxLayout()
        btn_hora = QPushButton("Sincronizar hora")
        btn_hora.clicked.connect(lambda: self._sesion([P.cmd_sync_time()]))
        fs.addWidget(btn_hora)
        btn_fw = QPushButton("Versión firmware")
        btn_fw.clicked.connect(lambda: self._sesion([P.cmd_firmware_info()]))
        fs.addWidget(btn_fw)
        lay.addLayout(fs)
        lay.addStretch(1)
        self.tabs.addTab(tab, "  Más  ")

    # ---------- BLE ----------
    def _params(self):
        mac = self.txt_mac.text().strip()
        if not mac:
            QMessageBox.warning(self, "MeRGBW", "Selecciona un equipo (o escríbe la MAC).")
            return None, None
        try:
            dtype = int(self.cmb_tipo.currentText())
        except ValueError:
            dtype = 1
        return mac, dtype

    def _lanzar(self, etiqueta: str, coro_fn):
        if self.hilo and self.hilo.is_alive():
            QMessageBox.warning(self, "MeRGBW", "Ocupado, espera a que termine.")
            return
        self.hilo = HiloBLE(coro_fn, self.puente, etiqueta)
        self.hilo.start()

    async def _sesion_bg(self, mac: str, dtype: int, paquetes: list[bytes]):
        self.guardado = guardar_device(mac, dtype)
        d = MeRGBWDevice(mac, device_type=dtype)
        notas: list[tuple[int, str]] = []
        d.on_notify = lambda cmd, pkt: notas.append((cmd, P.hexs(pkt)))
        await d.connect()
        try:
            if dtype in (1, 4):
                await d.write(P.cmd_check_bind_android_id_hex12("010203040506"))
                await asyncio.sleep(1.0)
            elif dtype in (6, 7):
                await d.write(P.cmd_check_bind_android_id_hex12(None))
                await asyncio.sleep(1.0)
            for pkt in paquetes:
                self.puente.log.emit(f"-> {P.hexs(pkt)}")
                await d.write(pkt)
                await asyncio.sleep(0.6)
            await asyncio.sleep(1.0)
            for cmd, hx in notas:
                self.puente.log.emit(f"<- CMD={cmd} {hx}")
            if d.last_status:
                self.puente.estado.emit(d.last_status)
        finally:
            await d.disconnect()

    def _sesion(self, paquetes: list[bytes]):
        par = self._params()
        if not par[0]:
            return
        mac, dtype = par
        self._lanzar("Enviando", lambda: self._sesion_bg(mac, dtype, list(paquetes)))

    # ---------- acciones ----------
    def _escanear(self):
        async def coro():
            devs = await ble_scan(8.0)
            self.puente.scan.emit(devs)
        self._lanzar("Escaneando", coro)

    def _leer_estado(self):
        par = self._params()
        if not par[0]:
            return
        mac, dtype = par
        self._lanzar("Leyendo estado",
                     lambda: self._sesion_bg(mac, dtype, [P.cmd_sync_status(), P.cmd_sync_time()]))

    def _elegir_dev(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if data:
            mac, dtype = data
            self.txt_mac.setText(mac)
            try:
                self.cmb_tipo.setCurrentText(str(dtype))
            except Exception:
                pass
            nombre = item.text().split("·")[1].strip() if "·" in item.text() else ""
            self.guardado = guardar_device(mac, dtype, nombre)
            self._refrescar_def()

    def _refrescar_def(self):
        self.guardado = cargar_device()
        g = self.guardado or {}
        mac_actual = self.txt_mac.text().strip().upper()
        if g.get("predeterminado") and g.get("mac") == mac_actual:
            self.btn_def.setText("★ Predeterminado")
            self.lbl_def.setText(f"Fijo: {g['mac']}" + (f" · {g['nombre']}" if g.get("nombre") else ""))
        elif g.get("mac"):
            self.btn_def.setText("☆ Marcar predeterminado")
            extra = " (predeterminado)" if g.get("predeterminado") else " (recordado)"
            self.lbl_def.setText(f"{g['mac']}{extra}")
        else:
            self.btn_def.setText("☆ Marcar predeterminado")
            self.lbl_def.setText("")

    def _toggle_default(self):
        mac = self.txt_mac.text().strip()
        if not mac:
            QMessageBox.warning(self, "MeRGBW", "Primero selecciona o escribe un equipo.")
            return
        try:
            dtype = int(self.cmb_tipo.currentText())
        except ValueError:
            dtype = 1
        actual = self.guardado or {}
        if actual.get("predeterminado") and actual.get("mac") == mac.upper():
            self.guardado = fijar_default(None)
            self.puente.log.emit("Predeterminado quitado.")
        else:
            self.guardado = fijar_default(mac, dtype)
            self.puente.log.emit(f"Predeterminado: {mac.upper()}")
        self._refrescar_def()

    # color
    def _rgb_actual(self) -> tuple[int, int, int]:
        return self.color

    def _fijar_hex(self, h: str):
        h = h.lstrip("#")
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return
        self.color = (r, g, b)
        self._refrescar_vista()

    def _refrescar_vista(self):
        r, g, b = self.color
        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        fg = "#000000" if lum > 0.6 else "#e6edf3"
        hx = f"{r:02X}{g:02X}{b:02X}"
        self.vista.setStyleSheet(
            f"#vista {{ background: #{hx}; color: {fg}; font-weight: 700; }}")
        self.vista.setText(f"#{hx}")
        if self.txt_hex.text().strip("#").upper() != hx:
            self.txt_hex.setText(hx)
        for canal, val in (("r", r), ("g", g), ("b", b)):
            sl, lab = self.sliders[canal]
            sl.blockSignals(True)
            sl.setValue(val)
            sl.blockSignals(False)
            lab.setText(str(val))

    def _desde_hex(self):
        try:
            h = self.txt_hex.text().strip().lstrip("#")
            self.color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            self._refrescar_vista()
        except (ValueError, IndexError):
            self.txt_hex.setText(f"{self.color[0]:02X}{self.color[1]:02X}{self.color[2]:02X}")

    def _desde_sliders(self):
        self.color = (self.sliders["r"][0].value(),
                      self.sliders["g"][0].value(),
                      self.sliders["b"][0].value())
        self._refrescar_vista()

    def _elegir_color(self):
        c = QColorDialog.getColor(QColor(f"#{self.txt_hex.text().lstrip('#')}"),
                                  self, "Elegir color")
        if c.isValid():
            self.color = (c.red(), c.green(), c.blue())
            self._refrescar_vista()

    def _aplicar_color(self):
        r, g, b = self.color
        dtype = int(self.cmb_tipo.currentText() or 1)
        if dtype == 1:
            pkt = P.cmd_color_hsv((r << 16) | (g << 8) | b)
        else:
            pkt = P.cmd_color_rgb(r, g, b)
        self._sesion([pkt])

    def _refrescar_slots(self):
        for i, b in enumerate(self.slot_btns):
            if i < len(self.personales):
                h = self.personales[i]
                b.setText("")
                b.setStyleSheet(f"#dot {{ background: #{h}; }}")
                b.setToolTip(f"#{h} — clic: usar · derecho: borrar")
            else:
                b.setText("+")
                b.setStyleSheet(f"#dot {{ background: transparent; border: 2px dashed #333a47; "
                                f"color: #666e7a; font-size: 16px; }}")
                b.setToolTip("Guardar el color actual aquí")
        self.lbl_cuenta.setText(f"{len(self.personales)}/{MAX_PERSONALIZADOS}")

    def _click_slot(self, i: int):
        if i < len(self.personales):
            self._fijar_hex(self.personales[i])
        else:
            h = f"{self.color[0]:02X}{self.color[1]:02X}{self.color[2]:02X}"
            if h in self.personales:
                return
            self.personales.append(h)
            guardar_personalizados(self.personales)
            self._refrescar_slots()

    def _borrar_slot(self, i: int):
        if i < len(self.personales):
            self.personales.pop(i)
            guardar_personalizados(self.personales)
            self._refrescar_slots()

    def _aplicar_brillo(self):
        v = int(self.sl_bri.value())
        dtype = int(self.cmb_tipo.currentText() or 1)
        pkt = P.cmd_brightness_type1(v) if dtype in (1, 2, 4) else P.cmd_brightness_simple(v)
        self._sesion([pkt])

    def _aplicar_escena(self):
        row = self.lst_esc.currentRow()
        idx = ESCENAS[row][1] if 0 <= row < len(ESCENAS) else 4
        self._sesion([P.cmd_scene_index_byte(idx),
                      P.cmd_scene_speed(int(self.spin_vel.value()))])

    def _aplicar_musica(self):
        self._sesion([P.cmd_music_mode(int(self.cmb_mus.currentData())),
                      P.cmd_music_sens(int(self.spin_sens.value()))])

    def _aplicar_timer(self):
        def hm(s):
            h, m = s.split(":")
            return int(h), int(m)
        try:
            oh, om = hm(self.txt_on.text().strip())
            ch, cm = hm(self.txt_off.text().strip())
        except (ValueError, IndexError):
            QMessageBox.warning(self, "MeRGBW", "Horas HH:MM, ej. 07:30.")
            return
        wm = P.weekmask(True, True, True, True, True, True, True)
        self._sesion([P.cmd_timer(True, oh, om, wm, True, ch, cm, wm)])

    # ---------- slots de señales ----------
    @Slot(str)
    def _anadir_log(self, s: str):
        self.log.append(s)
        if not self.log.isVisible():
            self.btn_log.setText("Registro ▸ •")

    @Slot(dict)
    def _mostrar_estado(self, st: dict):
        self._anadir_log(f"Estado: {st}")
        try:
            on = "🟢 ON" if st.get("open") else "⚫ OFF"
            bri = st.get("brightness", "—")
            led = st.get("led_num", st.get("star_brightness", "—"))
            al = st.get("open_alarm", {}) or {}
            ah, am = al.get("h", "—"), al.get("m", "—")
            am = f"{am:02d}" if isinstance(am, int) else am
            self.lbl_estado.setText(
                f"{on}   ·   Brillo {bri}%   ·   LEDs {led}   ·   "
                f"Tipo {st.get('device_type')}   ·   Sens {st.get('sensitive', '—')}   ·   "
                f"Timer on {ah}:{am}")
            self.lbl_dot.setStyleSheet("color: #4ade80; font-size: 14px;")
            if isinstance(led, int):
                try:
                    self.spin_led.setValue(led)
                except Exception:
                    pass
        except Exception:
            pass

    @Slot(list)
    def _mostrar_scan(self, devs):
        self.lst.clear()
        sel_row = -1
        saved_mac = (self.guardado or {}).get("mac", "")
        for d in devs:
            mark = "★ " if d.probable_mergbw else ""
            extra = f"  [tipo {d.device_type} · {d.model}]" if d.device_type else ""
            it = QListWidgetItem(f"{mark}{d.address}  ·  {d.name}  ·  {d.rssi} dBm{extra}")
            it.setData(Qt.UserRole, (d.address, d.device_type or 1))
            self.lst.addItem(it)
            if d.probable_mergbw and d.device_type:
                self.cmb_tipo.setCurrentText(str(d.device_type))
            if saved_mac and d.address.upper() == saved_mac:
                sel_row = self.lst.count() - 1
        self._anadir_log(f"{len(devs)} dispositivos.")
        if sel_row >= 0:
            self.lst.setCurrentRow(sel_row)
            self._elegir_dev(self.lst.item(sel_row))
        elif devs:
            self.lst.setCurrentRow(0)

    @Slot(bool, str)
    def _mostrar_busy(self, on: bool, etiqueta: str):
        self.lbl_busy.setText(("⏳ " + etiqueta) if on else "")
        for w in (self.btn_scan, self.btn_estado, self.btn_on,
                  self.btn_off, self.btn_color):
            w.setDisabled(on)
        if not on:
            self._refrescar_def()

    def _toggle_log(self):
        vis = not self.log.isVisible()
        self.log.setVisible(vis)
        self.btn_log.setText("Registro ▾" if vis else "Registro ▸")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setWindowIcon(icono_app())
    v = Ventana()
    v.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
