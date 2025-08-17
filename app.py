import streamlit as st
import sqlite3
from datetime import date, datetime, timedelta
import pandas as pd
import json, hashlib, os
import babel 



# --- Monedas globales ---
from babel.numbers import format_currency, get_currency_symbol
import pycountry

DB_PATH = "budget.db"

# ===================== Utilidades de moneda / locale =====================
def list_all_currencies():
    items, seen = [], set()
    try:
        # pycountry expone un iterable de monedas
        for cur in list(pycountry.currencies):
            code = getattr(cur, "alpha_3", None)
            if not code or code in seen:
                continue
            seen.add(code)
            name = getattr(cur, "name", code)
            try:
                sym = get_currency_symbol(code, locale="en_US")
            except Exception:
                sym = ""
            items.append((code, name, sym))
    except Exception:
        # Fallback pequeño por si pycountry no está disponible o falla el iterable
        items = [("USD", "US Dollar", "$"), ("EUR", "Euro", "€"), ("CRC", "Costa Rican Colón", "₡")]

    items.sort(key=lambda x: x[0])
    return items

ALL_CURRENCIES = list_all_currencies()

def money(amount: float, code: str, locale: str) -> str:
    try:
        return format_currency(amount, code, locale=locale)
    except Exception:
        sym = ""
        try: sym = get_currency_symbol(code)
        except Exception: pass
        return f"{sym}{amount:,.2f}"

# ===================== DB helpers =====================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # transacciones (agregamos columna regular INTEGER 0/1)
    conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        category TEXT NOT NULL,
        type TEXT CHECK(type IN ('ingreso','gasto')) NOT NULL,
        amount REAL NOT NULL,
        note TEXT
    )""")
    # budgets
    conn.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        amount REAL NOT NULL,
        UNIQUE(category, month, year)
    )""")
    ensure_schema(conn)
    return conn

def ensure_schema(conn):
    # añade columna 'regular' si no existe (0/1)
    cur = conn.execute("PRAGMA table_info(transactions)")
    cols = [r[1] for r in cur.fetchall()]
    if "regular" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN regular INTEGER DEFAULT 0")
        conn.commit()

def add_tx(conn, d, category, ttype, amount, note, regular=False):
    conn.execute("""INSERT INTO transactions(date, category, type, amount, note, regular)
                    VALUES (?,?,?,?,?,?)""",
                 (d, category, ttype, float(amount), note, 1 if regular else 0))
    conn.commit()

def delete_tx(conn, row_id):
    conn.execute("DELETE FROM transactions WHERE id = ?", (row_id,))
    conn.commit()

def fetch_df(conn):
    df = pd.read_sql_query(
        "SELECT id, date, category, type, amount, note, regular FROM transactions ORDER BY date DESC, id DESC", conn
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["regular"] = df["regular"].fillna(0).astype(int)
    return df

def kpis(conn):
    df = fetch_df(conn)
    total_ing = float(df[df["type"]=="ingreso"]["amount"].sum()) if not df.empty else 0.0
    total_gas = float(df[df["type"]=="gasto"]["amount"].sum()) if not df.empty else 0.0
    balance = total_ing - total_gas
    by_cat = df[df["type"]=="gasto"].groupby("category")["amount"].sum().sort_values(ascending=False) if not df.empty else pd.Series(dtype=float)
    return total_ing, total_gas, balance, by_cat

# ===================== Versículo del día =====================
def verse_of_the_day(path="data/verses.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            verses = json.load(f)
        if not verses:
            return "No hay versículos en data/verses.json."
        today = date.today().isoformat()
        h = int(hashlib.sha256(today.encode()).hexdigest(), 16)
        v = verses[h % len(verses)]
        return f"{v['text']} — {v['book']} {v['chapter']}:{v['verse']}"
    except FileNotFoundError:
        return "No se encontró data/verses.json."
    except Exception:
        return "No fue posible cargar el versículo del día."

# ===================== Presupuestos =====================
def upsert_budget(conn, category, month, year, amount):
    cur = conn.cursor()
    cur.execute("UPDATE budgets SET amount=? WHERE category=? AND month=? AND year=?",
                (float(amount), category, int(month), int(year)))
    if cur.rowcount == 0:
        cur.execute("INSERT INTO budgets(category, month, year, amount) VALUES (?,?,?,?)",
                    (category, int(month), int(year), float(amount)))
    conn.commit()

def delete_budget(conn, bid):
    conn.execute("DELETE FROM budgets WHERE id = ?", (bid,))
    conn.commit()

def fetch_budgets(conn, month, year):
    return pd.read_sql_query(
        "SELECT id, category, month, year, amount FROM budgets WHERE month=? AND year=? ORDER BY category",
        conn, params=(int(month), int(year))
    )

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

# ===================== Recomendaciones =====================
def load_articles(path="data/articles.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            if not raw: return []
            arts = json.loads(raw)
    except FileNotFoundError:
        st.warning("No se encontró `data/articles.json`. Crea el archivo para habilitar recomendaciones.")
        return []
    except json.JSONDecodeError:
        st.error("`data/articles.json` no es JSON válido. Revisa comas, llaves y comillas.")
        return []

    norm = []
    for a in arts:
        try:
            a["created_at"] = datetime.fromisoformat(str(a.get("created_at")))
        except Exception:
            a["created_at"] = datetime(2000,1,1)
        a["popularity"] = float(a.get("popularity", 50))
        a["tags"] = [str(t).lower() for t in a.get("tags", [])]
        a["topics"] = [str(t).lower() for t in a.get("topics", [])]
        norm.append(a)
    return norm

def hot_categories(conn, month, year):
    usage = usage_with_alerts(conn, month, year)
    hot = set(usage.loc[usage["pct"]>=0.7, "category"].tolist())

    df = fetch_df(conn)
    if not df.empty:
        cutoff = date.today() - timedelta(days=30)
        recent = df[(df["type"]=="gasto") & (df["date"]>=cutoff)]
        if not recent.empty:
            top_recent = recent.groupby("category")["amount"].sum().sort_values(ascending=False).head(3).index.tolist()
            hot.update(top_recent)
    return {c.lower() for c in hot}

def recommend_articles(conn, month, year, k=5):
    arts = load_articles()
    if len(arts)==0: return []
    hot = hot_categories(conn, month, year)
    now = datetime.now()
    max_days = max(1, max((now - a["created_at"]).days for a in arts))
    max_pop  = max(1.0, max(a["popularity"] for a in arts))
    scored = []
    for a in arts:
        match_tags = 1.0 if any(t in hot for t in a["tags"]) else 0.0
        recency    = 1.0 - ((now - a["created_at"]).days / max_days)
        popularity = a["popularity"] / max_pop
        score = 0.5*match_tags + 0.3*recency + 0.2*popularity
        scored.append((score, a, {"match_tags":match_tags, "recency":recency, "popularity":popularity}))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]

# ===================== UI =====================
st.set_page_config(page_title="Budgeting + Versículo + Recos", page_icon="📊", layout="wide")
st.title("📊 Budgeting + 🙏 Versículo del día + 🧠 Recomendaciones")
st.caption("M1–M3 con: toggle de versículo, todas las monedas (Babel/pycountry) y campo ‘regular’ en transacciones.")

conn = get_conn()

# ---- Sidebar ----
st.sidebar.header("⚙️ Preferencias")

# Locale
if "locale" not in st.session_state: st.session_state.locale = "es-CR"
st.session_state.locale = st.sidebar.text_input("Locale (ej. es-CR, es-MX, en-US)", value=st.session_state.locale)

# Moneda global
if "currency" not in st.session_state: st.session_state.currency = "CRC"
labels = [f"{c} — {n}" + (f" ({s})" if s else "") for c, n, s in ALL_CURRENCIES]
codes  = [c for c, _, _ in ALL_CURRENCIES]
default_index = codes.index(st.session_state.currency) if st.session_state.currency in codes else (codes.index("CRC") if "CRC" in codes else 0)
sel = st.sidebar.selectbox("Moneda", options=list(range(len(codes))), index=default_index, format_func=lambda i: labels[i])
st.session_state.currency = codes[sel]

show_verse = st.sidebar.checkbox("Mostrar versículo del día", value=True)

st.sidebar.header("🗓️ Periodo / Exportación / Recomendaciones")
today = date.today()
s_month = st.sidebar.number_input("Mes", 1, 12, value=today.month)
s_year  = st.sidebar.number_input("Año", 2000, 2100, value=today.year)

export_option = st.sidebar.selectbox("Exportar", ["Transacciones", "Presupuestos"])
if st.sidebar.button("Descargar CSV"):
    df_export = fetch_df(conn) if export_option=="Transacciones" else fetch_budgets(conn, s_month, s_year)
    csv_bytes = df_export.to_csv(index=False).encode("utf-8")
    st.sidebar.download_button("Descargar", data=csv_bytes, file_name=f"{export_option.lower()}_{s_year}-{s_month:02d}.csv", mime="text/csv")

col1, col2 = st.columns([1,2])

# ---- Columna izquierda ----
with col1:
    st.subheader("➕ Agregar transacción")
    with st.form("add_tx"):
        t_date = st.date_input("Fecha", value=today)
        t_cat  = st.text_input("Categoría", "Comida")
        t_type = st.radio("Tipo", ["ingreso","gasto"], horizontal=True)
        t_amount = st.number_input(f"Monto ({st.session_state.currency})", min_value=0.0, step=0.01, format="%.2f")
        t_note = st.text_input("Nota", "")
        t_regular = st.radio("¿Es regular?", ["No","Sí"], horizontal=True)
        if st.form_submit_button("Guardar"):
            if t_cat.strip() and t_amount > 0:
                add_tx(conn, t_date.isoformat(), t_cat.strip(), t_type, t_amount, t_note.strip(), regular=(t_regular=="Sí"))
                st.success(f"✅ {t_type} de {money(t_amount, st.session_state.currency, st.session_state.locale)} en {t_cat} · regular: {t_regular}")
            else:
                st.error("Por favor ingresa categoría y un monto > 0.")

    if show_verse:
        st.subheader("🙏 Versículo del día")
        st.info(verse_of_the_day())

    st.subheader("📥 Presupuesto (crear/actualizar)")
    tx_df = fetch_df(conn)
    cat_sugeridas = sorted(set(tx_df["category"].tolist())) if not tx_df.empty else ["Vivienda","Comida","Transporte","Salud","Ocio","Ahorro","Donaciones"]
    b_cat = st.selectbox("Categoría", cat_sugeridas)
    b_amount = st.number_input(f"Monto mensual ({st.session_state.currency})", min_value=0.0, step=1.0, format="%.2f")
    if st.button("Guardar presupuesto"):
        if b_cat.strip() and b_amount > 0:
            upsert_budget(conn, b_cat.strip(), s_month, s_year, b_amount)
            st.success(f"💾 Presupuesto guardado para {b_cat} ({s_month}/{s_year}): {money(b_amount, st.session_state.currency, st.session_state.locale)}")
        else:
            st.error("Categoría y monto deben ser válidos.")

# ---- Columna derecha ----
with col2:
    st.subheader("🧾 Historial de transacciones")
    df = fetch_df(conn)
    if df.empty:
        st.write("Sin transacciones aún.")
    else:
        show = df.copy()
        show["amount"] = show["amount"].apply(lambda x: money(float(x), st.session_state.currency, st.session_state.locale))
        show["regular"] = show["regular"].map({0:"No",1:"Sí"})
        st.dataframe(show.drop(columns=["id"]), use_container_width=True, hide_index=True)

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
    c1.metric("Ingresos", money(total_ing, st.session_state.currency, st.session_state.locale))
    c2.metric("Gastos",  money(total_gas, st.session_state.currency, st.session_state.locale))
    c3.metric("Balance", money(balance,   st.session_state.currency, st.session_state.locale))
    if len(by_cat) > 0:
        st.bar_chart(by_cat, use_container_width=True)

    st.subheader(f"💰 Presupuestos {s_month:02d}/{s_year}")
    bdf = fetch_budgets(conn, s_month, s_year)
    if bdf.empty:
        st.info("No hay presupuestos para este periodo. Crea uno en la columna izquierda.")
    else:
        usage = usage_with_alerts(conn, s_month, s_year)
        disp = usage.copy()
        disp["budget"] = disp["amount"].apply(lambda x: money(float(x), st.session_state.currency, st.session_state.locale))
        disp["spent"]  = disp["spent"].apply(lambda x: money(float(x), st.session_state.currency, st.session_state.locale))
        disp["pct"]    = (disp["pct"]*100).round(1)
        disp = disp.rename(columns={"category":"categoría","budget":"presupuesto","spent":"gastado","pct":"% usado","status":"estado"})
        st.dataframe(
            disp[["id","categoría","presupuesto","gastado","% usado","estado"]],
            use_container_width=True, hide_index=True
        )
        for _, r in usage.iterrows():
            pct_txt = f"{r.pct*100:,.1f}%"
            limite = money(float(r.amount), st.session_state.currency, st.session_state.locale)
            if r.pct >= 1.0:
                st.error(f"🔴 {r.category}: {pct_txt} del presupuesto gastado (límite {limite})")
            elif r.pct >= 0.8:
                st.warning(f"🟠 {r.category}: {pct_txt} del presupuesto gastado (límite {limite})")

        with st.expander("🗑️ Eliminar presupuesto"):
            bid_list = usage["id"].tolist()
            if bid_list:
                bid = st.selectbox("ID de presupuesto", bid_list)
                if st.button("Eliminar presupuesto"):
                    delete_budget(conn, int(bid))
                    st.success(f"Presupuesto {bid} eliminado. Recarga para ver cambios.")

    st.subheader("🧠 Recomendaciones")
    recs = recommend_articles(conn, s_month, s_year, k=5)
    if not recs:
        st.info("Aún no hay recomendaciones. Verifica `data/articles.json` y agrega transacciones/presupuestos.")
    else:
        for score, a, meta in recs:
            with st.container(border=True):
                st.write(f"**{a['title']}** — [{a['url']}]({a['url']})")
                st.caption(
                    f"tags: {', '.join(a['tags'])} · "
                    f"popularidad: {int(a['popularity'])} · "
                    f"score: {score:.2f} (match={meta['match_tags']:.2f}, recency={meta['recency']:.2f})"
                )

st.caption("RVA 1909 (dominio público). Monedas ISO-4217 con Babel/pycountry. Versículo con toggle. Campo ‘regular’ persistido.")
