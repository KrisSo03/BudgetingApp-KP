import streamlit as st
import sqlite3
from datetime import date, datetime
import pandas as pd
import json, hashlib

DB_PATH = "budget.db"

# ---------- DB helpers ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # transacciones
    conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        category TEXT NOT NULL,
        type TEXT CHECK(type IN ('ingreso','gasto')) NOT NULL,
        amount REAL NOT NULL,
        note TEXT
    )""")
    # presupuestos
    conn.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        amount REAL NOT NULL,
        UNIQUE(category, month, year)
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
    df = pd.read_sql_query(
        "SELECT id, date, category, type, amount, note FROM transactions ORDER BY date DESC, id DESC", conn
    )
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
    today = date.today().isoformat()
    h = int(hashlib.sha256(today.encode()).hexdigest(), 16)
    v = verses[h % len(verses)]
    return f"{v['text']} — {v['book']} {v['chapter']}:{v['verse']}"

# ---------- Presupuestos ----------
def upsert_budget(conn, category, month, year, amount):
    cur = conn.cursor()
    cur.execute("""
        UPDATE budgets SET amount=? WHERE category=? AND month=? AND year=?
    """, (float(amount), category, int(month), int(year)))
    if cur.rowcount == 0:
        cur.execute("""
            INSERT INTO budgets(category, month, year, amount) VALUES (?,?,?,?)
        """, (category, int(month), int(year), float(amount)))
    conn.commit()

def delete_budget(conn, bid):
    conn.execute("DELETE FROM budgets WHERE id = ?", (bid,))
    conn.commit()

def fetch_budgets(conn, month, year):
    df = pd.read_sql_query(
        "SELECT id, category, month, year, amount FROM budgets WHERE month=? AND year=? ORDER BY category",
        conn, params=(int(month), int(year))
    )
    return df

def monthly_spend_by_category(conn, month, year):
    q = """
    SELECT category, SUM(amount) as spent
    FROM transactions
    WHERE type='gasto' AND strftime('%m', date)=? AND strftime('%Y', date)=?
    GROUP BY category
    """
    mm = f"{int(month):02d}"
    yy = str(int(year))
    df = pd.read_sql_query(q, conn, params=(mm, yy))
    if df.empty:
        return pd.DataFrame(columns=["category","spent"])
    return df

def usage_with_alerts(conn, month, year):
    budgets = fetch_budgets(conn, month, year)
    spent = monthly_spend_by_category(conn, month, year)
    merged = budgets.merge(spent, on="category", how="left").fillna({"spent":0.0})
    if merged.empty:
        return merged
    merged["pct"] = merged["spent"] / merged["amount"]
    def status(p):
        if p >= 1.0: return "🔴 100%+ (superado)"
        if p >= 0.8: return "🟠 80%+ (casi al límite)"
        return "🟢 OK"
    merged["status"] = merged["pct"].apply(status)
    return merged[["id","category","amount","spent","pct","status"]].sort_values("pct", ascending=False)

# ---------- UI ----------
st.set_page_config(page_title="Budgeting App", page_icon="📊", layout="wide")
st.title("📊 Budgeting + 🙏 Versículo del día")
st.caption("Milestone 2: Presupuestos con alertas y exportación CSV.")

conn = get_conn()

# Sidebar: periodo + export
st.sidebar.header("🗓️ Periodo y Exportación")
today = date.today()
s_month = st.sidebar.number_input("Mes", 1, 12, value=today.month)
s_year  = st.sidebar.number_input("Año", 2000, 2100, value=today.year)

export_option = st.sidebar.selectbox("Exportar", ["Transacciones", "Presupuestos"])
if st.sidebar.button("Descargar CSV"):
    if export_option == "Transacciones":
        df_export = fetch_df(conn)
    else:
        df_export = fetch_budgets(conn, s_month, s_year)
    csv_bytes = df_export.to_csv(index=False).encode("utf-8")
    st.sidebar.download_button("Descargar", data=csv_bytes, file_name=f"{export_option.lower()}_{s_year}-{s_month:02d}.csv", mime="text/csv")

col1, col2 = st.columns([1,2])

# --- Columna izquierda: agregar + versículo + presupuesto
with col1:
    st.subheader("➕ Agregar transacción")
    with st.form("add_tx"):
        t_date = st.date_input("Fecha", value=today)
        t_cat = st.text_input("Categoría", "Comida")
        t_type = st.radio("Tipo", ["ingreso","gasto"], horizontal=True)
        t_amount = st.number_input("Monto", min_value=0.0, step=0.01, format="%.2f")
        t_note = st.text_input("Nota", "")
        if st.form_submit_button("Guardar"):
            if t_cat.strip() and t_amount > 0:
                add_tx(conn, t_date.isoformat(), t_cat.strip(), t_type, t_amount, t_note.strip())
                st.success("✅ Transacción guardada")
            else:
                st.error("Por favor ingresa categoría y un monto > 0.")

    st.subheader("🙏 Versículo del día")
    st.info(verse_of_the_day())

    st.subheader("📥 Presupuesto (crear/actualizar)")
    tx_df = fetch_df(conn)
    cat_sugeridas = sorted(set(tx_df["category"].tolist())) if not tx_df.empty else ["Vivienda","Comida","Transporte","Salud","Ocio","Ahorro","Donaciones"]
    b_cat = st.selectbox("Categoría", cat_sugeridas)
    b_amount = st.number_input("Monto mensual", min_value=0.0, step=1.0, format="%.2f")
    if st.button("Guardar presupuesto"):
        if b_cat.strip() and b_amount > 0:
            upsert_budget(conn, b_cat.strip(), s_month, s_year, b_amount)
            st.success(f"💾 Presupuesto guardado para {b_cat} ({s_month}/{s_year}).")
        else:
            st.error("Categoría y monto deben ser válidos.")

# --- Columna derecha: historial, KPIs, presupuestos y alertas
with col2:
    st.subheader("🧾 Historial de transacciones")
    df = fetch_df(conn)
    if df.empty:
        st.write("Sin transacciones aún.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        with st.expander("🗑️ Eliminar transacción"):
            ids = df["id"].tolist()
            if ids:
                rid = st.selectbox("ID a eliminar", ids)
                if st.button("Eliminar selección"):
                    delete_tx(conn, int(rid))
                    st.success(f"Eliminada ID {rid}. Recarga para ver cambios.")

    st.subheader("📈 KPIs")
    total_ing, total_gas, balance, by_cat = kpis(conn)
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", f"{total_ing:,.2f}")
    c2.metric("Gastos", f"{total_gas:,.2f}")
    c3.metric("Balance", f"{balance:,.2f}")
    if len(by_cat) > 0:
        st.bar_chart(by_cat, use_container_width=True)

    st.subheader(f"💰 Presupuestos {s_month:02d}/{s_year}")
    bdf = fetch_budgets(conn, s_month, s_year)
    if bdf.empty:
        st.info("No hay presupuestos para este periodo. Crea uno en la columna izquierda.")
    else:
        usage = usage_with_alerts(conn, s_month, s_year)
        st.dataframe(
            usage.assign(pct=(usage["pct"]*100).round(1)),
            use_container_width=True, hide_index=True
        )

        for _, r in usage.iterrows():
            pct_txt = f"{r.pct*100:,.1f}%"
            if r.pct >= 1.0:
                st.error(f"🔴 {r.category}: {pct_txt} del presupuesto gastado (límite {r.amount:,.2f})")
            elif r.pct >= 0.8:
                st.warning(f"🟠 {r.category}: {pct_txt} del presupuesto gastado (límite {r.amount:,.2f})")

        with st.expander("🗑️ Eliminar presupuesto"):
            bid_list = usage["id"].tolist()
            if bid_list:
                bid = st.selectbox("ID de presupuesto", bid_list)
                if st.button("Eliminar presupuesto"):
                    delete_budget(conn, int(bid))
                    st.success(f"Presupuesto {bid} eliminado. Recarga para ver cambios.")

st.caption("RVA 1909 (dominio público) para versículos. Milestone 2 listo: presupuestos + alertas + export.")
