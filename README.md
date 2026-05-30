# Registro de Paros de Producción

App Streamlit (mobile-first) para registrar paros en piso. BD: Google Sheets.
Ricardo sincroniza su Excel vía Power Query desde la pestaña `vista_ricardo`.

## Correr localmente
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` y llénalo.
4. `streamlit run app.py`

## Estructura
- `app.py` — navegación (st.navigation)
- `config/settings.py` — catálogos, columnas, mapeo programado/no programado
- `data/sheets.py` — conexión y CRUD a Google Sheets
- `utils/tiempo.py` — cálculo de duración
- `views/` — las 4 vistas

## Seguridad
NUNCA subir `secrets.toml` ni el `.json` de la cuenta de servicio (ver .gitignore).
