# MVP — Budgeting + Versículo del día (Streamlit)

## 🚀 Ejecutar en local
```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## ☁️ Deploy en Streamlit Cloud
1. Sube este folder a un repositorio de GitHub.
2. En Streamlit Cloud, crea una app seleccionando este repo y `app.py` como archivo principal.
3. (Opcional) Configura el archivo `requirements.txt` si cambias librerías.

## 📂 Estructura
```
app.py
requirements.txt
data/verses.json
```

## ✨ Alcance del MVP
- Registrar transacciones (ingreso/gasto).
- Ver totales y resumen por categoría.
- Mostrar **versículo del día** (determinista por fecha, desde dataset local).

## 🧭 Siguientes pasos (después del MVP)
- Presupuestos por categoría + alertas (80%/100%).
- Recomendación de artículos (JSON local).
- Exportación a CSV.
- Autenticación básica.
```