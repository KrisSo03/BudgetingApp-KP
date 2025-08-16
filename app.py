
import streamlit as st
import sqlite3
from datetime import date
import pandas as pd
import json, hashlib, datetime

DB_PATH = "budget.db"

# ---------- DB helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        category TEXT NOT NULL,
        type TEXT CHECK(type IN ('ingreso','gasto')) NOT NULL,
        amount REAL NOT NULL,
        note TEXT
    )""")
    return conn

def add_tx(conn, d, category, ttype, amount, note):
    conn.execute("INSERT INTO transactions(date, category, type, amount, note) VALUES (?,?,?,?,?)",
                 (d, category, ttype, float(amount), note))
    conn.commit()

def delete_tx(conn, row_id):
    conn.execute("DELETE FROM transactions WHERE id = ?", (row_id,))
    conn.commit()

def fetch_df(conn):
    df = pd.read_sql_query("SELECT id, date, category, type, amount, note FROM transactions ORDER BY date DESC, id DESC", conn)
    # Tipos
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df

def kpis(conn):
    df = fetch_df(conn)
    total_ing = float(df[df["type"]=="ingreso"]["amount"].sum()) if not df.empty else 0.0
    total_gas = float(df[df["type"]=="gasto"]["amount"].sum()) if not df.empty else 0.0
    balance = total_ing - total_gas
    by_cat = df[df["type"]=="gasto"].groupby("category")["amount"].sum().sort_values(ascending=False) if not df.empty else pd.Series(dtype=float)
    return total_ing, total_gas, balance, by_cat

# ---------- Versículo del día ----------
def verse_of_the_day(path="data/verses.json"):
    with open(path, "r", encoding="utf-8") as f:
        verses = json.load(f)
    # determinista por día
    today = datetime.date.today().isoformat()
    h = int(hashlib.sha256(today.encode()).hexdigest(), 16)
    idx = h % len(verses)
    v = verses[idx]
    return f"{v['text']} — {v['book']} {v['chapter']}:{v['verse']}"

# ---------- UI ----------
st.set_page_config(page_title="Budgeting MVP", page_icon="📊", layout="wide")
st.title("📊 Budgeting MVP + 🙏 Versículo del día")
st.caption("MVP: transacciones básicas, KPIs y versículo del día (dataset local).")

conn = get_conn()

col1, col2 = st.columns([1,2])

with col1:
    st.subheader("Agregar transacción")
    with st.form("add_tx"):
        t_date = st.date_input("Fecha", value=date.today())
        t_cat = st.text_input("Categoría", "Comida")
        t_type = st.radio("Tipo", ["ingreso","gasto"], horizontal=True)
        t_amount = st.number_input("Monto", min_value=0.0, step=0.01, format="%.2f")
        t_note = st.text_input("Nota", "")
        if st.form_submit_button("Guardar"):
            if t_cat.strip() and t_amount > 0:
                add_tx(conn, t_date.isoformat(), t_cat.strip(), t_type, t_amount, t_note.strip())
                st.success("✅ Transacción guardada")
            else:
                st.error("Por favor ingresa categoría y un monto mayor a 0.")

    st.subheader("Versículo del día")
    st.info(verse_of_the_day())

with col2:
    st.subheader("Historial")
    df = fetch_df(conn)
    if df.empty:
        st.write("Sin transacciones aún. Agrega la primera 👉")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Borrar
        with st.expander("🗑️ Eliminar transacción"):
            ids = df["id"].tolist()
            if ids:
                rid = st.selectbox("ID a eliminar", ids)
                if st.button("Eliminar"):
                    delete_tx(conn, int(rid))
                    st.success(f"Eliminada ID {rid}. Actualiza la página para ver cambios.")

    st.subheader("KPIs")
    total_ing, total_gas, balance, by_cat = kpis(conn)
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"{total_ing:,.2f}")
    c2.metric("Gastos", f"{total_gas:,.2f}")
    c3.metric("Balance", f"{balance:,.2f}")

    if len(by_cat) > 0:
        st.bar_chart(by_cat, use_container_width=True)

st.caption("RVA 1909 (dominio público) para versículos. Este es un MVP educativo.")
