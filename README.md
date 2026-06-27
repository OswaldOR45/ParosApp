# ⏱️ ParosApp — Registro y Análisis de Confiabilidad de Paros de Producción

Sistema para registrar **paros de producción** en piso y convertirlos en decisiones de mantenimiento. Tiene dos componentes que comparten la misma fuente de datos (Google Sheets):

1. **App Streamlit (en vivo, mobile-first)** — captura de paros por operador, cierre de ACR por mantenimiento y tableros gerenciales.
2. **Motor de análisis de confiabilidad (offline)** — audita los datos, calcula Pareto y MTBF/MTTR, y ajusta un **modelo Weibull por componente** para proponer intervalos óptimos de mantenimiento preventivo.

![Status](https://img.shields.io/badge/status-en%20producción-success)
![Python](https://img.shields.io/badge/Python-3.11-3776AB)
![Streamlit](https://img.shields.io/badge/Streamlit-1.40%2B-FF4B4B)
![Plotly](https://img.shields.io/badge/Plotly-viz-3F4F75)
![Reliability](https://img.shields.io/badge/Weibull-reliability%20%2F%20scipy-008080)
![Data](https://img.shields.io/badge/datos-Google%20Sheets%20API-0F9D58)
![Telegram](https://img.shields.io/badge/notificaciones-Telegram%20Bot-26A5E4)

---

## 📌 El problema

Los paros de línea se anotaban de forma dispersa, sin un formato común ni trazabilidad entre quién reportó el paro y quién lo atendió. Eso impedía responder preguntas clave: ¿qué equipos y motivos cuestan más horas?, ¿cuánto tiempo está la línea caída *esperando* vs. *reparando*?, ¿cuándo conviene intervenir un componente *antes* de que falle?

**ParosApp** estandariza la captura en piso (rápida, a prueba de guantes), enruta cada paro al equipo de mantenimiento correcto, y acumula un histórico limpio que alimenta un análisis de confiabilidad para construir un plan de mantenimiento preventivo basado en datos.

---

## ✨ Características principales

### 👷 Captura en piso (vista Operador)
- **Mobile-first y a prueba de guantes**: sin menús desplegables; usa `segmented_control` y `pills` con áreas táctiles grandes.
- **Clasificación automática** del paro como *Programado* / *No Programado* derivada del motivo.
- **Descripción contextual del motivo**: al seleccionar el motivo de paro, se muestra automáticamente una descripción breve que orienta al operador sobre cuándo aplica cada categoría. Las descripciones viven en `config/settings.py` como fuente única de verdad y no se persisten en Sheets.
- **Enrutamiento de apoyo (ACR)**: el operador indica a quién llamó (RSI / STEO / AMBOS / NO); eso manda el paro a la cola de mantenimiento correcta.
- Cálculo de duración en formato `H:MM` con manejo de cruce de medianoche.

### 🔧 Cierre de paros (vista Mantenimiento)
- **Cola filtrada por empresa**: cada proveedor ve solo los paros que le tocan.
- Registro de causa raíz, componente, tipo de intervención, acción y refacción.
- **Catálogo dinámico de componentes por equipo** con deduplicación normalizada (evita fragmentar el dato por acentos/mayúsculas).
- **Firma digital del supervisor de producción** (contraseña) obligatoria para cerrar el ACR.

### 📊 Tableros (Dashboard y Dashboard de Mantenimiento)
- Dashboard gerencial: horas perdidas por equipo, top de motivos y *programado vs. no programado*, con filtros de periodo y comparación entre líneas.
- Dashboard de mantenimiento con una métrica propia: **Tiempo Muerto Administrativo** = tiempo de paro (producción) − tiempo de intervención (mantenimiento). Separa la *tardanza de reparación* de la *espera administrativa*. Incluye MTTR por tipo de intervención y por componente, y comparativa RSI vs. STEO.

### 📤 Exportación
- Descarga a CSV con filtros por equipo y rango de fechas (insumo directo del motor de análisis).
- Sincronización con Excel de planta vía Power Query desde una pestaña `vista_ricardo`.

### 🔔 Notificaciones automáticas (Telegram Bot)
- Al guardar un paro, se dispara automáticamente una notificación vía **Telegram Bot API** al grupo correspondiente según el apoyo solicitado.
- **Enrutamiento inteligente por grupo**: RSI → grupo RSI, STEO → grupo STEO, AMBOS → ambos grupos. Si no se solicitó apoyo (`NO`), no se envía notificación.
- El mensaje incluye: línea, área, equipo, motivo, tipo de paro, horario, turno y notas del operador.
- **Falla silenciosa**: si la notificación falla por cualquier razón, el paro ya quedó guardado en Sheets y el operador no ve ningún error — el flujo de captura nunca se interrumpe.
- Implementado en `utils/telegram_notify.py`; las credenciales (token y chat IDs) se configuran en `secrets.toml` bajo la sección `[telegram]`.

### 📈 Motor de confiabilidad (offline, `analisis/`)
- **Auditoría de calidad** de datos (cobertura de campos críticos).
- **Pareto 80/20** por motivo y por componente.
- **MTBF / MTTR** por equipo-componente, usando *horas operativas* (calendario − downtime) como proxy hasta integrar el OEE.
- **Ajuste Weibull 2P** por componente (`reliability`, con *fallback* a `scipy`) e **intervalo óptimo de preventivo** por minimización de costo (modelo de reemplazo por edad).
- Diagnóstico por parámetro de forma β (mortalidad infantil / falla aleatoria / desgaste).
- Teoría de confiabilidad correcta: distingue **reemplazos** (renuevan la vida → Weibull), **reparaciones** (sistema reparable → análisis aparte) y **ajustes** (excluidos).

---

## 👥 Roles y flujo de trabajo

```
OPERADOR                MANTENIMIENTO (RSI / STEO / ADMIN)        PRODUCCIÓN
   │                              │                                   │
   │ registra el paro             │                                   │
   │ (motivo, tiempos, ACR) ─────▶│ ve su cola de pendientes          │
   │                              │ captura causa raíz, componente,   │
   │                              │ tipo de intervención, tiempos     │
   │                              │ ───────────── pide firma ────────▶│ firma (contraseña)
   │                              │ cierra el ACR ◀───────────────────│
   ▼                              ▼                                   ▼
                       Google Sheet (PAROSV2)  ──▶  Dashboards + Motor Weibull
```

El control de acceso es por contraseña y por empresa (`RSI` / `STEO` / `ADMIN`), con comparación en tiempo constante (`hmac.compare_digest`) y estado por sesión.

---

## 🧱 Stack tecnológico

| Componente | Tecnología |
|-----------|-----------|
| App / UI | Streamlit 1.40+ (navegación `st.navigation` + `st.Page`) |
| Visualización | Plotly Express |
| Datos | Google Sheets API (gspread + google-auth, Service Account) |
| Procesamiento | pandas |
| Confiabilidad | numpy, scipy, `reliability` (Weibull) |
| Notificaciones | Telegram Bot API (requests) — enrutamiento por grupo RSI / STEO |
| Despliegue | Streamlit Community Cloud · Dev Container (GitHub Codespaces) |
| Zona horaria | `zoneinfo` (America/Mexico_City) + `tzdata` |

---

## 🏗️ Arquitectura

Aplicación **por capas**, con la lógica de negocio y los catálogos centralizados, y el acceso a datos aislado en una sola capa.

```
app.py  (navegación)
   │
   ├── views/            Capa de presentación (5 vistas)
   │     ├── operador.py                 captura en piso
   │     ├── mantenimiento.py            cierre de ACR
   │     ├── dashboard.py                tablero gerencial
   │     ├── mantenimiento_dashboard.py  tiempo muerto admin. + MTTR
   │     └── exportacion.py              descarga CSV
   │
   ├── data/sheets.py    Capa de datos: CRUD a Google Sheets por NOMBRE de
   │                     encabezado (inmune a reordenar columnas), con caché
   │                     y escritura segura ante concurrencia.
   │
   ├── utils/
   │     ├── auth.py               Control de acceso por empresa (hmac.compare_digest)
   │     ├── tiempo.py             Duraciones H:MM (maneja cruce de medianoche)
   │     └── telegram_notify.py    Notificaciones al grupo RSI / STEO / AMBOS vía Bot API
   │
   └── config/settings.py   Catálogos, mapeo campo→encabezado, reglas de negocio

analisis/                  Sistema OFFLINE independiente (misma fuente de datos)
   └── analisis_paros.py    ETL + auditoría + Pareto + MTBF/MTTR + Weibull
```

**Decisiones de diseño destacadas:**
- **Mapeo por nombre de encabezado** (no por posición), normalizando acentos/mayúsculas: la hoja puede reordenarse o tener columnas extra sin romper la app.
- **Separación app en vivo / análisis offline**: dos sistemas con cadencias distintas que comparten datos; el modelo Weibull se re-ejecuta a demanda sin afectar la app.
- **Configuración en un solo lugar** (`config/settings.py`): catálogos y reglas se cambian sin tocar las vistas.
- **Caché por capa** (`st.cache_resource` para conexión, `st.cache_data` con TTL para lecturas) e invalidación explícita al escribir.

---

## 🧮 Métrica destacada: Tiempo Muerto Administrativo

```
Tiempo de paro (lo que reporta producción)
   − Tiempo de intervención (lo que reporta mantenimiento)
   = Tiempo Muerto Administrativo  (línea caída sin reparación activa:
                                    espera de técnico, de refacción, diagnóstico…)
```

Esta separación permite atribuir con justicia la *tardanza de reparación* (responsabilidad de mantenimiento) frente a la *espera administrativa*, y es la base del Dashboard de Mantenimiento.

---

## 🚀 Instalación y despliegue

### Local
```bash
git clone https://github.com/OswaldOR45/ParosApp.git
cd ParosApp/ParosApp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # y completarlo
streamlit run app.py
```

### Streamlit Community Cloud
Pega el contenido de `secrets.toml.example` (con tus valores reales) en *Settings → Secrets*: el bloque `[gcp_service_account]`, la `spreadsheet_key`, las contraseñas por empresa (`rsi_password`, `steo_password`, `mantenimiento_password`, `produccion_password`) y el bloque `[telegram]` con el `token` del bot y los `chat_id_rsi` / `chat_id_steo` de cada grupo.

### GitHub Codespaces
El repo incluye un **Dev Container** que instala dependencias y levanta la app automáticamente.

### Motor de análisis (offline)
```bash
cd ParosApp/analisis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python analisis_paros.py --csv paros.csv          # desde un CSV exportado
# o
python analisis_paros.py --sheets                 # leyendo directo del Sheet
```
Más detalle (parámetros y entregables) en [`ParosApp/analisis/README.md`](ParosApp/analisis/README.md).

---

## 🗃️ Modelo de datos

Hoja principal `PAROSV2` (una fila por paro). Campos clave: timestamp, área, turno, línea, equipo, motivo, duración (programado / no programado), `ID_PARO`, `¿necesita ACR?`, atendido por, causa raíz, componente, tipo de intervención, duración de intervención y firma de producción. Pestañas opcionales de catálogo (`cat_motivos`, `cat_equipos`, `cat_componentes`) que, de no existir, caen a valores por defecto.

---

## 🛣️ Roadmap

- [ ] Integrar **horas reales de operación (OEE)** para sustituir el TBF operativo provisional.
- [ ] Análisis de **sistema reparable** (Crow-AMSAA / NHPP) para las reparaciones.
- [ ] Programación automática del preventivo a partir de los intervalos Weibull.
- [ ] Limpieza de estructura: aplanar el doble nivel `ParosApp/ParosApp/` y remover los archivos legacy de la raíz (`paros.py`, `operador.py`).
- [ ] Pruebas automatizadas de la capa de datos y de los cálculos de confiabilidad.

---

## 🔒 Seguridad

Las credenciales (`secrets.toml`, JSON de la cuenta de servicio) están excluidas por `.gitignore` y se leen desde `st.secrets`. **Pendiente de higiene del repo**: la carpeta `.idea/` quedó versionada pese a estar en `.gitignore` (se subió antes de ignorarla); conviene removerla con `git rm -r --cached .idea`.

---

## 👤 Autor

**Oswaldo Reynoso Robles** — diseño e implementación completa: arquitectura por capas, UX de piso, control de acceso por empresa, tableros y motor de confiabilidad (Weibull). Proyecto desarrollado como practicante de IT para soportar el plan maestro de mantenimiento preventivo de la planta.